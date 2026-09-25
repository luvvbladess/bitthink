"""In-memory live generation jobs.

Jobs keep running after a WebSocket disconnect so a user can switch chats,
close the tab, come back, and still see intermediate status. Events are
broadcast to every socket the user currently has open.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

MAX_JOBS_PER_USER = 4
MAX_STATUS = 4000
MAX_TEXT = 120_000
MAX_REASONING = 20_000


@dataclass
class LiveJob:
    conversation_id: str
    user_text: str = ""
    status_text: str = ""
    text: str = ""
    reasoning: str = ""
    search: list = field(default_factory=list)
    thinking: bool = True
    error: Optional[str] = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "user_text": self.user_text,
            "status_text": self.status_text,
            "text": self.text,
            "reasoning": self.reasoning,
            "search": self.search,
            "thinking": self.thinking,
            "error": self.error,
        }


class GenerationHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}
        self._jobs: dict[tuple[str, str], LiveJob] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def snapshots(self, user_id: str) -> list[dict[str, Any]]:
        return [job.snapshot() for (uid, _), job in self._jobs.items() if uid == user_id]

    def running_count(self, user_id: str) -> int:
        return sum(1 for (uid, _), task in self._tasks.items() if uid == user_id and not task.done())

    def has_pending(self, user_id: str) -> bool:
        return any(
            uid == user_id and str(cid).startswith("pending:") and task and not task.done()
            for (uid, cid), task in self._tasks.items()
        )

    def is_running(self, user_id: str, conversation_id: Optional[str]) -> bool:
        if not conversation_id:
            return self.has_pending(user_id)
        task = self._tasks.get((user_id, conversation_id))
        return bool(task and not task.done())

    def get_job(self, user_id: str, conversation_id: str) -> Optional[LiveJob]:
        return self._jobs.get((user_id, conversation_id))

    async def subscribe(self, user_id: str, websocket: WebSocket) -> list[dict[str, Any]]:
        async with self._lock:
            self._sockets.setdefault(user_id, set()).add(websocket)
            return self.snapshots(user_id)

    async def unsubscribe(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._sockets.get(user_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._sockets.pop(user_id, None)

    async def broadcast(self, user_id: str, message: dict[str, Any]) -> None:
        sockets = list(self._sockets.get(user_id) or ())
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        if not stale:
            return
        async with self._lock:
            current = self._sockets.get(user_id)
            if not current:
                return
            for websocket in stale:
                current.discard(websocket)
            if not current:
                self._sockets.pop(user_id, None)

    def upsert_job(self, user_id: str, conversation_id: str, **fields: Any) -> LiveJob:
        key = (user_id, conversation_id)
        job = self._jobs.get(key)
        if job is None:
            job = LiveJob(conversation_id=conversation_id)
            self._jobs[key] = job
        for name, value in fields.items():
            if hasattr(job, name):
                setattr(job, name, value)
        if job.status_text and len(job.status_text) > MAX_STATUS:
            job.status_text = job.status_text[-MAX_STATUS:]
        if job.text and len(job.text) > MAX_TEXT:
            job.text = job.text[-MAX_TEXT:]
        if job.reasoning and len(job.reasoning) > MAX_REASONING:
            job.reasoning = job.reasoning[-MAX_REASONING:]
        return job

    def rekey(self, user_id: str, old_id: str, new_id: str) -> None:
        if not old_id or old_id == new_id:
            return
        old_key, new_key = (user_id, old_id), (user_id, new_id)
        job = self._jobs.pop(old_key, None)
        if job is not None:
            job.conversation_id = new_id
            self._jobs[new_key] = job
        task = self._tasks.pop(old_key, None)
        if task is not None:
            self._tasks[new_key] = task

    def finish_job(self, user_id: str, conversation_id: str) -> None:
        self._jobs.pop((user_id, conversation_id), None)
        self._tasks.pop((user_id, conversation_id), None)

    def start_task(self, user_id: str, conversation_id: str, coro) -> asyncio.Task:
        if str(conversation_id).startswith("pending:") and self.has_pending(user_id):
            raise RuntimeError("already running")
        key = (user_id, conversation_id)
        existing = self._tasks.get(key)
        if existing and not existing.done():
            raise RuntimeError("already running")
        task = asyncio.create_task(coro)
        self._tasks[key] = task
        return task

    def cancel(self, user_id: str, conversation_id: Optional[str]) -> bool:
        if not conversation_id:
            return self.cancel_pending(user_id)
        task = self._tasks.get((user_id, conversation_id))
        if task and not task.done():
            task.cancel()
            return True
        return False

    def cancel_pending(self, user_id: str) -> bool:
        cancelled = False
        for (uid, cid), task in list(self._tasks.items()):
            if uid == user_id and str(cid).startswith("pending:") and task and not task.done():
                task.cancel()
                cancelled = True
        return cancelled

    def bind(self, user_id: str, conversation_id: Optional[str], job_key: Optional[str] = None) -> "BoundSenders":
        return BoundSenders(self, user_id, conversation_id, job_key or conversation_id)


class BoundSenders:
    def __init__(
        self,
        hub: GenerationHub,
        user_id: str,
        conversation_id: Optional[str],
        job_key: Optional[str] = None,
    ) -> None:
        self.hub = hub
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.job_key = job_key or conversation_id

    def _cid(self) -> Optional[str]:
        return self.conversation_id

    async def _emit(self, msg_type: str, payload: dict[str, Any]) -> None:
        if self.conversation_id:
            payload = {**payload, "conversation_id": self.conversation_id}
        await self.hub.broadcast(self.user_id, {"type": msg_type, "payload": payload})

    async def send_thinking(self) -> None:
        if self.conversation_id:
            self.hub.upsert_job(self.user_id, self.conversation_id, thinking=True)
        await self._emit("thinking", {"started": True})

    async def send_status(self, text: str) -> None:
        if self.conversation_id:
            self.hub.upsert_job(self.user_id, self.conversation_id, status_text=text or "")
        await self._emit("status", {"text": text})

    async def send_chunk(self, text: str) -> None:
        chunk_size = 800
        if self.conversation_id:
            job = self.hub.get_job(self.user_id, self.conversation_id)
            current = (job.text if job else "") + (text or "")
            self.hub.upsert_job(self.user_id, self.conversation_id, text=current, thinking=False)
        for index in range(0, len(text or ""), chunk_size):
            piece = text[index:index + chunk_size]
            await self._emit("chunk", {"text": piece, "done": index + chunk_size >= len(text)})
            await asyncio.sleep(0.01)

    async def send_file(self, filename: str, data: bytes, url: str = "") -> None:
        encoded = base64.b64encode(data or b"").decode("utf-8")
        payload: dict[str, Any] = {"filename": filename, "data": encoded}
        if url:
            payload["url"] = url
        if url or str(filename).lower().endswith((".html", ".htm")):
            payload["canvas"] = True
        await self._emit("file", payload)

    async def send_meta(self, conv_id: str, replaces: Optional[str] = None) -> None:
        previous = self.job_key
        if previous and previous != conv_id:
            self.hub.rekey(self.user_id, previous, conv_id)
        self.job_key = conv_id
        self.conversation_id = conv_id
        self.hub.upsert_job(self.user_id, conv_id, thinking=True)
        # replaces: the deleted chat this reply moved out of, so the tab follows it.
        await self._emit("meta", {"conversation_id": conv_id, **({"replaces": replaces} if replaces else {})})

    async def send_extras(self, reasoning: str, search_results: list) -> None:
        if self.conversation_id:
            self.hub.upsert_job(
                self.user_id,
                self.conversation_id,
                reasoning=reasoning or "",
                search=search_results or [],
            )
        await self._emit("extras", {"reasoning": reasoning, "search": search_results})

    async def send_reasoning_delta(self, text: str) -> None:
        if self.conversation_id:
            job = self.hub.get_job(self.user_id, self.conversation_id)
            current = (job.reasoning if job else "") + (text or "")
            self.hub.upsert_job(self.user_id, self.conversation_id, reasoning=current)
        await self._emit("reasoning_delta", {"text": text})


hub = GenerationHub()
