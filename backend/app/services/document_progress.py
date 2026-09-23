"""Stream honest parse progress for a document upload.

Events are units the parser actually finished (pages, files, slides, sheets),
not a timer. A one-step job emits nothing until the final result.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import HTTPException

ProgressReport = Callable[[int, int, str], None]
Work = Callable[[ProgressReport], Awaitable[dict]]


def progress_label(done: int, total: int, unit: str) -> str:
    from app.bot_core.document_parser import progress_label as label

    return label(int(done), int(total), unit)


def encode_event(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


async def iter_work_events(work: Work) -> AsyncIterator[dict]:
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def report(done: int, total: int, unit: str) -> None:
        payload = {
            "type": "progress",
            "done": int(done),
            "total": int(total),
            "unit": str(unit or ""),
            "label": progress_label(done, total, unit),
        }
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    async def runner() -> None:
        try:
            result = await work(report)
            if not isinstance(result, dict):
                result = {"ok": True}
            await queue.put({"type": "result", **result})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Не удалось прочитать документ"
            await queue.put({"type": "error", "detail": detail, "status": exc.status_code})
        except MemoryError:
            await queue.put({
                "type": "error",
                "detail": "Файл слишком тяжёлый для разбора. Пришлите часть документа или меньше страниц.",
                "status": 400,
            })
        except Exception as exc:
            await queue.put({
                "type": "error",
                "detail": str(exc) or "Не удалось прочитать документ",
                "status": 400,
            })
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            item: Any = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
