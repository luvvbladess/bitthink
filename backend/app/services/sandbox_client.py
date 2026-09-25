"""HTTP facade to the Computer sandbox. Local fs is used only in tests."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import aiohttp

DEFAULT_SANDBOX_URL = "http://sandbox:8090"
TOOL_OPS = {
    "workspace_ls": "ls",
    "workspace_read": "read",
    "workspace_write": "write",
    "workspace_edit": "edit",
    "workspace_delete": "delete",
    "python_run": "run",
    "pip_install": "pip",
    "workspace_grep": "grep",
    "workspace_glob": "glob",
}


def sandbox_url() -> str:
    if os.environ.get("WORKSPACE_ALLOW_LOCAL_RUN") == "1" and not os.environ.get("SANDBOX_URL"):
        return ""
    return (os.environ.get("SANDBOX_URL") or "http://sandbox:8090").strip()


async def run_workspace_tool(name: str, args: dict[str, Any], user_id: int) -> str:
    op = TOOL_OPS.get(name)
    if not op:
        return f"Инструмент {name} не найден."
    extra = dict(args or {})
    extra.pop("user_id", None)
    extra.pop("op", None)
    payload = {**extra, "user_id": int(user_id), "op": op}
    url = sandbox_url()
    if url:
        return await _remote(url, payload)
    if os.environ.get("WORKSPACE_ALLOW_LOCAL_RUN") == "1":
        from app.services.workspace_fs import dispatch

        return dispatch(int(user_id), op, payload)
    if name in ("python_run", "pip_install"):
        return "Песочница сейчас недоступна. Python и pip запускаются только в изолированном контейнере."
    from app.services.workspace_fs import dispatch

    return dispatch(int(user_id), op, payload)


def _sandbox_headers() -> dict[str, str]:
    token = (os.environ.get("SANDBOX_TOKEN") or "").strip()
    if not token:
        return {}
    return {"X-Sandbox-Token": token}


async def _remote(base: str, payload: dict[str, Any]) -> str:
    timeout = aiohttp.ClientTimeout(total=200)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base.rstrip('/')}/v1/op", json=payload, headers=_sandbox_headers(),
            ) as resp:
                raw = await resp.text()
                if resp.status >= 400:
                    return f"Песочница ответила HTTP {resp.status}: {raw[:300]}"
                data = json.loads(raw)
    except Exception as exc:
        return f"Песочница недоступна: {str(exc)[:200]}"
    if not isinstance(data, dict):
        return "Песочница вернула странный ответ."
    if data.get("error"):
        return str(data["error"])[:500]
    return str(data.get("text") or "")


async def collect_workspace_files(user_id: int, since: float) -> list[dict[str, Any]]:
    """Binary files the Computer job just wrote, ready to attach to the chat."""
    payload = {"user_id": int(user_id), "op": "deliverables", "since": float(since or 0)}
    raw = ""
    if os.environ.get("WORKSPACES_DIR"):
        try:
            from app.services.workspace_fs import collect_deliverables

            raw = collect_deliverables(int(user_id), float(since or 0))
        except Exception:
            raw = ""
        parsed = _parse_deliverables(raw)
        if parsed or raw.strip() == "[]":
            return parsed
    url = sandbox_url()
    if url:
        raw = await _remote(url, payload)
    elif os.environ.get("WORKSPACE_ALLOW_LOCAL_RUN") == "1":
        from app.services.workspace_fs import dispatch

        raw = dispatch(int(user_id), "deliverables", payload)
    return _parse_deliverables(raw)


def _parse_deliverables(raw: str) -> list[dict[str, Any]]:
    if not raw or raw.startswith("Песочница") or raw.startswith("Неизвестная"):
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    files: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        encoded = str(item.get("data_b64") or "")
        name = str(item.get("name") or Path(str(item.get("path") or "")).name or "file")
        if not encoded:
            continue
        try:
            data = base64.b64decode(encoded, validate=False)
        except Exception:
            continue
        if not data:
            continue
        if name.lower().endswith(".docx"):
            from app.bot_core.docx_generator import scrub_markdown_marks

            data = scrub_markdown_marks(data)
        files.append({"filename": Path(name).name, "bytes": data})
    return files
