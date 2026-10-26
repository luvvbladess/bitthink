import asyncio
import json
import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, WebSocketException, status
from app.auth import decode_token, get_current_user
from app.services import generation_store as store
from app.services.generation_hub import hub
from app.core.repository import repo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/activity')
async def activity(user: str = Depends(get_current_user)):
    from app.domains.execution import activity
    return await asyncio.to_thread(activity, user)


@router.post('/activity/{generation_id}/stop')
async def stop_activity(generation_id: str, user: str = Depends(get_current_user)):
    from fastapi import HTTPException
    from app.domains.execution import stop
    if not await asyncio.to_thread(stop, user, generation_id):raise HTTPException(404, 'Задача уже завершена или недоступна')
    return {'ok': True}

async def _authenticate_ws(websocket: WebSocket) -> str:
    # Token travels in the first WS message instead of the URL query string so
    # it doesn't end up in proxy/access logs (nginx, browser history, etc).
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=20)
    except Exception as e:
        logger.warning(f"WS auth timeout: {e}")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Auth timeout") from e
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("WS invalid auth message")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid auth message") from e
    if not isinstance(msg, dict) or not isinstance(msg.get('payload') or {}, dict):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason='Invalid auth message')
    token = (msg.get("payload") or {}).get("token") if msg.get("type") == "auth" else None
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
    try:
        payload = decode_token(token, expected_type="access")
        return payload["sub"]
    except Exception as e:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token") from e



@router.get("/jobs")
async def list_jobs(user_id: str = Depends(get_current_user)):
    return {"jobs": await asyncio.to_thread(hub.snapshots, user_id)}


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        user_id = await _authenticate_ws(websocket)
    except WebSocketException as exc:
        await websocket.close(code=exc.code, reason=exc.reason)
        return
    try:
        jobs = await hub.subscribe(user_id, websocket)
        await websocket.send_json({"type": "jobs", "payload": {"jobs": jobs}})
        while True:
            try:
                message = json.loads(await websocket.receive_text())
                if not isinstance(message, dict):
                    raise ValueError()
                payload = message.get('payload') or {}
                if not isinstance(payload, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                await websocket.send_json({'type': 'error', 'payload': {'message': 'Invalid JSON'}})
                continue
            kind = message.get('type')
            if kind == 'ping':
                await websocket.send_json({'type': 'pong', 'payload': {}})
                continue
            cid = payload.get('conversation_id')
            if cid is not None and (not isinstance(cid, str) or not cid or len(cid) > 64):
                await websocket.send_json({'type': 'error', 'payload': {'message': 'Invalid conversation'}})
                continue
            if kind == 'stop':
                await asyncio.to_thread(hub.cancel, user_id, cid)
                continue
            if kind not in ('message', 'regenerate'):
                await websocket.send_json({'type': 'error', 'payload': {'message': 'Unknown message type'}})
                continue
            request_id = payload.get('request_id')
            if request_id is not None and (not isinstance(request_id, str) or not 8 <= len(request_id) <= 64 or not all(c.isalnum() or c in '-_' for c in request_id)):
                await websocket.send_json({'type': 'error', 'payload': {'message': 'Некорректный идентификатор отправки', 'conversation_id': cid}})
                continue
            content = payload.get('content', '')
            if kind == 'message' and (not isinstance(content, str) or not content.strip() or len(content) > 120000):
                await websocket.send_json({'type': 'error', 'payload': {'message': 'Введите сообщение до 120 000 символов.', 'conversation_id': cid}})
                continue
            if kind == 'regenerate' and not cid:
                await websocket.send_json({'type': 'error', 'payload': {'message': 'Missing conversation_id'}})
                continue
            try:
                preferences = await repo.capture_generation_preferences(user_id)
                generation_id = await asyncio.to_thread(store.reserve, user_id, cid, kind,
                    {'preferences': preferences, **({'content': content.strip()} if kind == 'message' else {})}, request_id=request_id)
            except RuntimeError as exc:
                await websocket.send_json({'type': 'error', 'payload': {'message': str(exc), 'conversation_id': cid, 'request_id': request_id}})
                continue
            if request_id:
                delivery_status = await asyncio.to_thread(store.delivery_status, user_id, generation_id)
                await websocket.send_json({'type': 'accepted', 'payload': {'request_id': request_id, 'generation_id': generation_id, 'conversation_id': cid, 'status': delivery_status}})
                continue
            # Acknowledgement only. The independent worker owns execution and
            # publishes ordered events; closing this socket cannot cancel it.
            await websocket.send_json({'type': 'thinking', 'payload': {'started': True, 'conversation_id': cid}})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception('Chat transport failed')
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason='Connection error')
        except Exception:
            pass
    finally:
        await hub.unsubscribe(user_id, websocket)
