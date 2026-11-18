"""Internal MCP endpoint for a bounded FreeCAD operation."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field


cad = FastMCP('Bit Think FreeCAD', host='0.0.0.0', port=8091, stateless_http=True, json_response=True)
slots = asyncio.Semaphore(1)
Dimension = Annotated[float, Field(strict=True, ge=0.1, le=1000, allow_inf_nan=False)]
FILES = ('mounting-plate.FCStd', 'mounting-plate.step', 'mounting-plate.html')


def generate(dimensions):
    with tempfile.TemporaryDirectory(prefix='cad-') as directory:
        path = Path(directory)
        process = subprocess.run(
            ['/usr/bin/python3', '-I', str(Path(__file__).with_name('plate.py')), json.dumps(dimensions)],
            cwd=path, env={'HOME': directory, 'TMPDIR': directory, 'QT_QPA_PLATFORM': 'offscreen'},
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False,
        )
        if process.returncode == 2:
            raise ValueError(process.stderr.strip()[-300:])
        if process.returncode:
            raise RuntimeError('FreeCAD не завершил построение детали.')
        result = json.loads(process.stdout.splitlines()[-1])
        result['files'] = {}
        for name in FILES:
            artifact = path / name
            if not 0 < artifact.stat().st_size <= 1024 * 1024:
                raise RuntimeError('Файл модели превысил лимит пилота.')
            result['files'][name] = base64.b64encode(artifact.read_bytes()).decode('ascii')
        return result


@cad.tool()
async def create_mounting_plate(
    length_mm: Dimension, width_mm: Dimension, thickness_mm: Dimension,
    hole_diameter_mm: Dimension, edge_inset_mm: Dimension,
) -> CallToolResult:
    """Rectangular plate, four equal through holes with equal center-to-edge inset."""
    dimensions = dict(length_mm=length_mm, width_mm=width_mm, thickness_mm=thickness_mm,
                      hole_diameter_mm=hole_diameter_mm, edge_inset_mm=edge_inset_mm)
    async with asyncio.timeout(25), slots:
        result = await asyncio.to_thread(generate, dimensions)
    return CallToolResult(
        content=[TextContent(type='text', text='Пластина построена. Геометрия STEP проверена.')],
        structuredContent=result,
    )


if __name__ == '__main__':
    cad.run(transport='streamable-http')
