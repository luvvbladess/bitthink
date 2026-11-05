"""Website window onto Orchestrator tasks running in an open Bit Client."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.websockets import WebSocketState

from app.api.chat import _authenticate_ws
from app.auth import get_current_user
from app.db.engine import AsyncSessionLocal
from app.db.models import User
from app.services.desktop_link import LinkError, link_hub, valid_id

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_FRAME = 1_000_000
MAX_PROMPT = 20_000
OFFLINE = "Bit Client не открыт на компьютере. Откройте приложение и войдите в этот аккаунт."


def _fail(exc: LinkError) -> NoReturn:
    raise HTTPException(exc.status, exc.message)


def _no_store(body: dict) -> JSONResponse:
    response = JSONResponse(body)
    response.headers["Cache-Control"] = "no-store"
    return response


def _online(user_id: str) -> None:
    if not link_hub.view(user_id)["online"]:
        raise HTTPException(409, OFFLINE)


async def _account_exists(user_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(User.id).where(User.email == user_id)) is not None


@router.get("")
async def desktop_link(user_id: str = Depends(get_current_user)):
    return _no_store(link_hub.view(user_id))


@router.get("/sessions/{session_id}")
async def desktop_link_session(session_id: str, user_id: str = Depends(get_current_user)):
    if not valid_id(session_id):
        raise HTTPException(404, "Задача на компьютере не найдена.")
    found = link_hub.session(user_id, session_id)
    if found is None:
        raise HTTPException(404, "Задача на компьютере не найдена.")
    body = dict(found)
    body["online"] = link_hub.view(user_id)["online"]
    return _no_store(body)


@router.post("/sessions")
async def desktop_link_create(body: dict | None, user_id: str = Depends(get_current_user)):
    _online(user_id)
    content = str((body or {}).get("content") or "").strip()
    project_id = str((body or {}).get("project_id") or "")
    if not content or len(content) > MAX_PROMPT:
        raise HTTPException(422, "Введите задачу до 20 000 символов.")
    if not valid_id(project_id):
        raise HTTPException(422, "Выберите проект, открытый в Bit Client.")
    if not any(item["id"] == project_id for item in link_hub.view(user_id)["projects"]):
        raise HTTPException(409, "Такого проекта нет в открытом Bit Client.")
    session_id = uuid.uuid4().hex
    try:
        result = await link_hub.request(user_id, {"id": uuid.uuid4().hex, "action": "create", "session_id": session_id, "project_id": project_id, "content": content})
    except LinkError as exc:
        _fail(exc)
    if not result.get("ok"):
        raise HTTPException(409, result.get("message") or "Bit Client не начал задачу.")
    return {"ok": True, "session_id": session_id, "message": result.get("message") or ""}


@router.post("/sessions/{session_id}/message")
async def desktop_link_message(session_id: str, body: dict | None, user_id: str = Depends(get_current_user)):
    _online(user_id)
    if not valid_id(session_id) or link_hub.session(user_id, session_id) is None:
        raise HTTPException(404, "Задача на компьютере не найдена.")
    content = str((body or {}).get("content") or "").strip()
    if not content or len(content) > MAX_PROMPT:
        raise HTTPException(422, "Введите сообщение до 20 000 символов.")
    try:
        result = await link_hub.request(user_id, {"id": uuid.uuid4().hex, "action": "prompt", "session_id": session_id, "content": content})
    except LinkError as exc:
        _fail(exc)
    if not result.get("ok"):
        raise HTTPException(409, result.get("message") or "Bit Client не принял сообщение.")
    return {"ok": True, "session_id": session_id, "message": result.get("message") or ""}


@router.post("/sessions/{session_id}/stop")
async def desktop_link_stop(session_id: str, user_id: str = Depends(get_current_user)):
    _online(user_id)
    session = link_hub.session(user_id, session_id) if valid_id(session_id) else None
    if session is None:
        raise HTTPException(404, "Задача на компьютере не найдена.")
    if session.get("status") not in {"running", "needs_approval"}:
        raise HTTPException(409, "Задача сейчас не выполняется.")
    try:
        result = await link_hub.request(user_id, {"id": uuid.uuid4().hex, "action": "stop", "session_id": session_id})
    except LinkError as exc:
        _fail(exc)
    if not result.get("ok"):
        raise HTTPException(409, result.get("message") or "Не удалось остановить задачу.")
    return {"ok": True}


@router.post("/sessions/{session_id}/approval")
async def desktop_link_approval(session_id: str, body: dict | None, user_id: str = Depends(get_current_user)):
    _online(user_id)
    session = link_hub.session(user_id, session_id) if valid_id(session_id) else None
    if session is None:
        raise HTTPException(404, "Задача на компьютере не найдена.")
    pending = session.get("pending_approval") or {}
    tool_id = str((body or {}).get("tool_id") or "")
    if session.get("status") != "needs_approval" or pending.get("tool_id") != tool_id or not valid_id(tool_id):
        raise HTTPException(409, "Это подтверждение уже не актуально.")
    try:
        result = await link_hub.request(user_id, {
            "id": uuid.uuid4().hex, "action": "approve", "session_id": session_id, "tool_id": tool_id, "allow": (body or {}).get("allow") is True,
        })
    except LinkError as exc:
        _fail(exc)
    if not result.get("ok"):
        raise HTTPException(409, result.get("message") or "Bit Client не принял решение.")
    return {"ok": True}


@router.websocket("/ws")
async def desktop_link_socket(ws: WebSocket):
    await ws.accept()
    lock = asyncio.Lock()
    user_id = ""
    generation = 0

    async def send(kind: str, **payload):
        async with lock:
            if ws.application_state != WebSocketState.CONNECTED:
                raise WebSocketDisconnect()
            await ws.send_json({"type": kind, "payload": payload})

    try:
        user_id = await _authenticate_ws(ws)
        if not await _account_exists(user_id):
            raise WebSocketException(code=1008, reason="Account unavailable")
        generation = await link_hub.attach(user_id, send)
        await send("ready", protocol=1)
        while ws.application_state == WebSocketState.CONNECTED:
            raw = await ws.receive_text()
            if len(raw) > MAX_FRAME:
                await send("error", code="protocol", message="Снимок Bit Client слишком большой.")
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                await send("error", code="protocol", message="Некорректное сообщение Bit Client.")
                continue
            if not isinstance(msg, dict):
                continue
            payload = msg.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            kind = msg.get("type")
            if kind == "ping":
                await send("pong")
            elif kind == "state":
                await link_hub.apply_state(user_id, generation, payload)
            elif kind == "ack":
                await link_hub.ack(user_id, generation, payload)
    except WebSocketException:
        try:
            await send("error", code="auth", message="Сессия Bit-Think истекла или доступ к аккаунту ограничен. Войдите заново.")
            await ws.close(code=1008)
        except Exception:
            pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.info("Desktop link closed after an unexpected error")
    finally:
        if user_id and generation:
            await link_hub.detach(user_id, generation)
        try:
            await ws.close()
        except Exception:
            pass
