import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, WebSocketException, status

from app.auth import decode_token, get_current_user
from app.services.chat_service import regenerate_chat, run_chat
from app.services.generation_hub import MAX_JOBS_PER_USER, hub

router = APIRouter()
logger = logging.getLogger(__name__)


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
        logger.warning(f"WS invalid auth message: {raw[:200]}")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid auth message") from e
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
    return {"jobs": hub.snapshots(user_id)}


async def _run_job(user_id: str, initial_id: str, coro, senders) -> None:
    cid = initial_id
    try:
        await coro
    except asyncio.CancelledError:
        cid = senders.conversation_id or initial_id
        try:
            await hub.broadcast(user_id, {"type": "stopped", "payload": {"conversation_id": cid}})
        except Exception:
            pass
        raise
    except Exception as exc:
        cid = senders.conversation_id or initial_id
        logger.exception("Chat job error")
        try:
            await hub.broadcast(
                user_id,
                {"type": "error", "payload": {"message": str(exc) or "Internal error", "conversation_id": cid}},
            )
        except Exception:
            logger.warning("Failed to deliver job error; no live sockets")
    finally:
        cid = senders.conversation_id or initial_id
        try:
            await hub.broadcast(user_id, {"type": "done", "payload": {"conversation_id": cid}})
        except Exception:
            pass
        hub.finish_job(user_id, cid)
        if initial_id != cid:
            hub.finish_job(user_id, initial_id)


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        user_id = await _authenticate_ws(websocket)
    except WebSocketException as e:
        # Auth helper already raised; avoid double-close which crashes ASGI.
        try:
            await websocket.close(code=e.code, reason=e.reason)
        except Exception:
            pass
        return
    except Exception:
        logger.exception("WS auth failed")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass
        return

    jobs = await hub.subscribe(user_id, websocket)
    try:
        await websocket.send_json({"type": "jobs", "payload": {"jobs": jobs}})
    except Exception:
        await hub.unsubscribe(user_id, websocket)
        return

    # Incoming WS frames are pumped into a queue by a background receiver so the
    # main loop can keep listening for a "stop" message *while* generation jobs
    # run in the background.
    queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()

    async def receiver():
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    await queue.put(raw)
                    continue
                msg_type = parsed.get("type")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "payload": {}})
                    continue
                if msg_type == "stop":
                    conv_id = (parsed.get("payload") or {}).get("conversation_id")
                    hub.cancel(user_id, conv_id)
                    continue
                await queue.put(raw)
        except WebSocketDisconnect:
            await queue.put(None)
        except Exception as e:
            logger.warning(f"WS receiver error: {e}")
            await queue.put(None)

    receiver_task = asyncio.create_task(receiver())

    try:
        while True:
            raw = await queue.get()
            if raw is None:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "payload": {"message": "Invalid JSON"}})
                continue

            msg_type = msg.get("type")
            payload = msg.get("payload", {})

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "payload": {}})
                continue

            if msg_type == "stop":
                hub.cancel(user_id, payload.get("conversation_id"))
                continue

            if msg_type == "message":
                content = payload.get("content", "").strip()
                conversation_id = payload.get("conversation_id")
                if not content:
                    await websocket.send_json({"type": "error", "payload": {"message": "Empty message"}})
                    continue
                job_key = conversation_id or f"pending:{uuid.uuid4().hex}"
                if hub.is_running(user_id, conversation_id):
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": "Этот чат ещё отвечает. Дождитесь окончания или остановите ответ.", "conversation_id": conversation_id},
                    })
                    continue
                if hub.running_count(user_id) >= MAX_JOBS_PER_USER:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": "Слишком много ответов сразу. Дождитесь одного из них.", "conversation_id": conversation_id},
                    })
                    continue
                senders = hub.bind(user_id, conversation_id, job_key=job_key)
                if conversation_id:
                    hub.upsert_job(user_id, conversation_id, user_text=content, thinking=True, status_text="Думаю", text="")
                coro = run_chat(
                    user_id,
                    content,
                    conversation_id,
                    send_status=senders.send_status,
                    send_chunk=senders.send_chunk,
                    send_file=senders.send_file,
                    send_meta=senders.send_meta,
                    send_extras=senders.send_extras,
                    send_reasoning_delta=senders.send_reasoning_delta,
                )
                try:
                    # Claim the job before any await so a second new-chat message
                    # cannot start another pending stream on this event loop.
                    hub.start_task(user_id, job_key, _run_job(user_id, job_key, coro, senders))
                except RuntimeError:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": "Этот чат ещё отвечает. Дождитесь окончания или остановите ответ.", "conversation_id": conversation_id},
                    })
                    continue
                await senders.send_thinking()
            elif msg_type == "regenerate":
                conversation_id = payload.get("conversation_id")
                if not conversation_id:
                    await websocket.send_json({"type": "error", "payload": {"message": "Missing conversation_id"}})
                    continue
                if hub.is_running(user_id, conversation_id):
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": "Этот чат ещё отвечает. Дождитесь окончания или остановите ответ.", "conversation_id": conversation_id},
                    })
                    continue
                if hub.running_count(user_id) >= MAX_JOBS_PER_USER:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": "Слишком много ответов сразу. Дождитесь одного из них.", "conversation_id": conversation_id},
                    })
                    continue
                senders = hub.bind(user_id, conversation_id)
                hub.upsert_job(user_id, conversation_id, thinking=True, status_text="Думаю", text="")
                await senders.send_thinking()
                coro = regenerate_chat(
                    user_id,
                    conversation_id,
                    send_status=senders.send_status,
                    send_chunk=senders.send_chunk,
                    send_file=senders.send_file,
                    send_meta=senders.send_meta,
                    send_extras=senders.send_extras,
                    send_reasoning_delta=senders.send_reasoning_delta,
                )
                hub.start_task(user_id, conversation_id, _run_job(user_id, conversation_id, coro, senders))
            else:
                await websocket.send_json({"type": "error", "payload": {"message": "Unknown message type"}})
                continue

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {user_id}")
    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(e)[:120])
        except Exception:
            pass
    finally:
        receiver_task.cancel()
        await hub.unsubscribe(user_id, websocket)
