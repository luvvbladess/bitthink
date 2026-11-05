"""Presence channel for a signed-in Bit Client.

The open app pushes its Orchestrator sessions and executes commands that the
website relays. The browser never talks to the computer directly. One API
process owns the sockets; production runs Uvicorn with a single worker.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_MODES = {"ask", "auto", "readonly"}
_STATUS = {"idle", "running", "needs_approval"}
_ROLES = {"user", "assistant"}
_TOOL_STATUS = {"pending", "running", "needs_approval", "done", "error", "denied"}
MAX_SESSIONS = 20
MAX_MESSAGES = 16
MAX_TEXT = 2500
MAX_PROJECTS = 40


class LinkError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _identifier(value: object) -> str:
    return value if isinstance(value, str) and _ID.fullmatch(value) else ""


def valid_id(value: object) -> bool:
    return bool(_identifier(value))


def _items(value):
    return value if isinstance(value, list) else []


def normalize_state(payload: object) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    projects = []
    seen_projects: set[str] = set()
    for item in _items(raw.get("projects")):
        if not isinstance(item, dict):
            continue
        project_id = _identifier(item.get("id"))
        name = _clean(item.get("name"), 120)
        if not project_id or not name or project_id in seen_projects:
            continue
        seen_projects.add(project_id)
        projects.append({"id": project_id, "name": name})
        if len(projects) >= MAX_PROJECTS:
            break
    sessions = []
    seen: set[str] = set()
    for item in _items(raw.get("sessions")):
        if not isinstance(item, dict):
            continue
        session_id = _identifier(item.get("id"))
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        status = item.get("status") if item.get("status") in _STATUS else "idle"
        project_id = _identifier(item.get("project_id"))
        if project_id and project_id not in seen_projects:
            project_id = ""
        messages = []
        for message in _items(item.get("messages")):
            if not isinstance(message, dict) or message.get("role") not in _ROLES:
                continue
            tools = []
            for tool in _items(message.get("tools")):
                if not isinstance(tool, dict):
                    continue
                name = _clean(tool.get("name"), 80)
                if not name:
                    continue
                tools.append({"name": name, "status": tool.get("status") if tool.get("status") in _TOOL_STATUS else "done"})
                if len(tools) >= 12:
                    break
            messages.append({
                "id": _identifier(message.get("id")) or f"m{len(messages)}",
                "role": message.get("role"),
                "content": _clean(message.get("content"), MAX_TEXT),
                "error": _clean(message.get("error"), 500),
                "tools": tools,
            })
        messages = messages[-MAX_MESSAGES:]
        approval = item.get("pending_approval") if isinstance(item.get("pending_approval"), dict) else None
        pending = None
        if status == "needs_approval" and approval:
            tool_id = _identifier(approval.get("tool_id"))
            if tool_id:
                pending = {"tool_id": tool_id, "name": _clean(approval.get("name"), 80) or "Действие", "summary": _clean(approval.get("summary"), 180)}
        if status == "needs_approval" and pending is None:
            status = "running"
        updated = item.get("updated_at")
        updated_at = int(updated) if isinstance(updated, (int, float)) and 0 <= updated <= 10_000_000_000_000 else 0
        sessions.append({
            "id": session_id,
            "title": _clean(item.get("title"), 120) or "Чат Оркестратора",
            "project_id": project_id,
            "project_name": _clean(item.get("project_name"), 120),
            "status": status,
            "updated_at": updated_at,
            "pending_approval": pending,
            "messages": messages,
        })
        if len(sessions) >= MAX_SESSIONS:
            break
    mode = raw.get("approval_mode")
    return {
        "device_name": _clean(raw.get("device_name"), 64) or "Компьютер",
        "client_version": _clean(raw.get("client_version"), 32),
        "approval_mode": mode if mode in _MODES else "ask",
        "projects": projects,
        "sessions": sessions,
    }


def summary(session: dict) -> dict:
    return {key: session[key] for key in ("id", "title", "project_id", "project_name", "status", "updated_at", "pending_approval")}


@dataclass
class _Link:
    generation: int
    send: object
    online: bool = True
    device_name: str = "Компьютер"
    version: str = ""
    approval_mode: str = "ask"
    projects: list = field(default_factory=list)
    sessions: dict = field(default_factory=dict)
    updated_at: float = 0
    inflight: asyncio.Future | None = None
    pending_id: str = ""


class DesktopLinkHub:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._links: dict[str, _Link] = {}
        self._token = 0

    def reset(self) -> None:
        self._links.clear()
        self._token = 0

    async def attach(self, user_id: str, send) -> int:
        async with self._lock:
            self._token += 1
            generation = self._token
            previous = self._links.get(user_id)
            link = _Link(generation=generation, send=send, updated_at=time.time())
            old_send = None
            inflight = None
            if previous:
                link.device_name = previous.device_name
                link.version = previous.version
                link.approval_mode = previous.approval_mode
                link.projects = previous.projects
                link.sessions = previous.sessions
                link.updated_at = previous.updated_at
                old_send = previous.send
                previous.online = False
                previous.send = None
                previous.generation = -1
                inflight = previous.inflight
                previous.inflight = None
                previous.pending_id = ""
            self._links[user_id] = link
        if old_send is not None:
            try:
                await old_send("replaced")
            except Exception:
                pass
        if inflight is not None and not inflight.done():
            inflight.set_result({"ok": False, "message": "Подключение компьютера сменилось."})
        return generation

    async def detach(self, user_id: str, generation: int) -> None:
        inflight = None
        async with self._lock:
            link = self._links.get(user_id)
            if link is None or link.generation != generation:
                return
            link.online = False
            link.send = None
            for session in link.sessions.values():
                session["status"] = "offline"
                session["pending_approval"] = None
            inflight = link.inflight
            link.inflight = None
            link.pending_id = ""
        if inflight is not None and not inflight.done():
            inflight.set_result({"ok": False, "message": "Связь с компьютером прервалась."})

    async def apply_state(self, user_id: str, generation: int, payload: object) -> None:
        state = normalize_state(payload)
        async with self._lock:
            link = self._links.get(user_id)
            if link is None or link.generation != generation or not link.online:
                return
            link.device_name = state["device_name"]
            link.version = state["client_version"]
            link.approval_mode = state["approval_mode"]
            link.projects = state["projects"]
            link.sessions = {item["id"]: item for item in state["sessions"]}
            link.updated_at = time.time()

    async def ack(self, user_id: str, generation: int, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        async with self._lock:
            link = self._links.get(user_id)
            if link is None or link.generation != generation:
                return
            if str(payload.get("id") or "") != link.pending_id or link.inflight is None or link.inflight.done():
                return
            link.inflight.set_result({"ok": payload.get("ok") is True, "message": _clean(payload.get("message"), 300)})

    async def request(self, user_id: str, command: dict, timeout: float = 20) -> dict:
        async with self._lock:
            link = self._links.get(user_id)
            if link is None or not link.online or link.send is None:
                raise LinkError(409, "Bit Client не открыт на компьютере. Откройте приложение и войдите в этот аккаунт.")
            if link.inflight is not None and not link.inflight.done():
                raise LinkError(409, "Компьютер ещё принимает предыдущую команду.")
            future = asyncio.get_running_loop().create_future()
            link.inflight = future
            link.pending_id = command["id"]
            send = link.send
        try:
            await send("command", **command)
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise LinkError(504, "Bit Client не ответил. Проверьте, что окно приложения открыто.") from None
        finally:
            async with self._lock:
                current = self._links.get(user_id)
                if current is not None and current.pending_id == command["id"]:
                    current.inflight = None
                    current.pending_id = ""

    def view(self, user_id: str) -> dict:
        link = self._links.get(user_id)
        if link is None:
            return {"online": False, "device_name": "", "client_version": "", "approval_mode": "ask", "projects": [], "sessions": []}
        sessions = sorted(link.sessions.values(), key=lambda item: item.get("updated_at") or 0, reverse=True)
        return {
            "online": link.online,
            "device_name": link.device_name,
            "client_version": link.version,
            "approval_mode": link.approval_mode,
            "projects": list(link.projects),
            "sessions": [summary(item) for item in sessions],
        }

    def session(self, user_id: str, session_id: str) -> dict | None:
        link = self._links.get(user_id)
        if link is None:
            return None
        return link.sessions.get(session_id)


link_hub = DesktopLinkHub()
