"""BitClient transport: the existing Orchestrator and billing, with local tools."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from starlette.websockets import WebSocketState
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, WebSocketException
from app.auth import get_current_user
from app.api.chat import _authenticate_ws
from app.api.billing import subscription_payload
from app.core.repository import repo
from app.services.desktop_context import desktop_executor, desktop_cwd, desktop_mode, desktop_chat_model, desktop_skills, desktop_work_context, desktop_capabilities
from app.services.chat_service import run_chat
from app.services.desktop_local_chat import run_local_chat
from app.services.generation_hub import hub, MAX_JOBS_PER_USER
from app.services.chat_modes import normalize_chat_mode, public_chat_modes
from app.core.request_context import generation_preferences

router = APIRouter()
logger = logging.getLogger(__name__)
from app.services.desktop_policy import context_policy
PROTOCOL = 1
MAX_CLIENT_FRAME = 4_000_000
LOCAL_TOOLS = frozenset({
    "workspace_ls", "workspace_read", "workspace_write", "workspace_edit",
    "workspace_delete", "workspace_grep", "workspace_glob", "python_run",
    "pip_install", "desktop_run_command", "desktop_changed_files", "desktop_register_result",
    "desktop_skill_read", "desktop_skill_list",
    "desktop_browser_inspect", "desktop_browser_action",
    "desktop_image_read", "desktop_apps", "desktop_inspect", "desktop_capture", "desktop_pointer", "desktop_cad_saved_file", "desktop_control", "desktop_cad_inspect",
    "desktop_solidworks", "desktop_kompas", "desktop_cad_action", "desktop_presentation", "desktop_save_artifact", "desktop_ocr", "desktop_pdf_to_text", "diagram_create",
})
_active_users: set[str] = set()


@router.get("/status")
async def desktop_status(user_id: str = Depends(get_current_user)):
    subscription = await subscription_payload(user_id)
    choices = public_chat_modes(subscription.get('tier'))
    models = [item['id'] for item in choices if item['available']]
    return {"protocol": PROTOCOL, "mode": "director", "modes": ["director", "chat"], "local_history": True, "work_context": True, "context_compaction": True, "context_policy": context_policy(), "chat_models": sorted(models), "chat_modes": choices, "canvas": True, "remote_link": True, "subscription": subscription}


@router.get("/chats")
async def desktop_chats(user_id: str = Depends(get_current_user)):
    chats = await repo.get_conversations(user_id)
    return [{**chat, "running": hub.is_running(user_id, chat["id"])} for chat in chats]


@router.websocket("/ws")
async def desktop_socket(ws: WebSocket):
    await ws.accept()
    task: asyncio.Task | None = None
    pending: dict[str, asyncio.Future] = {}
    lock = asyncio.Lock()
    user_id = ""

    async def send(kind: str, **payload):
        async with lock:
            await ws.send_json({"type": kind, "payload": payload})

    async def execute(name: str, args: dict) -> str:
        if name not in LOCAL_TOOLS:
            return "Неизвестный локальный инструмент."
        call_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        pending[call_id] = future
        try:
            # BitClient per-agent local read evidence
            from app.services.desktop_swarm import active_agent, active_swarm
            owner = active_agent.get()
            board = active_swarm.get()
            role = board.agents.get(owner, {}).get('role', '') if board else ''
            await send("tool_call", id=call_id, name=name, arguments=args, agent_id=owner, agent_role=role)
            result = await asyncio.wait_for(future, timeout=600)
            return str(result.get("output") or "")[:1_100_000 if name == "desktop_image_read" else 80_000]
        except asyncio.TimeoutError:
            return "Истекло ожидание локального действия. Результат неизвестен: команда могла уже сохранить файл или изменить документ. Сначала проверь готовые файлы/окно, не повторяй действие автоматически."
        finally:
            pending.pop(call_id, None)

    async def run(payload: dict):
        cid = None
        marked = False
        preferences_token = None
        mode = str(payload.get("mode") or "director")
        context = desktop_executor.set(execute if mode == "director" else None)
        folder = desktop_cwd.set(str(payload.get("cwd") or "")[:4096] if mode == "director" else "")
        mode_context = desktop_mode.set(mode)
        model_context = desktop_chat_model.set(str(payload.get("chat_model") or "auto"))
        catalog = payload.get("skills") or []
        catalog = [
            {"id": str(s.get("id") or "")[:100], "name": str(s.get("name") or "")[:160], "description": str(s.get("description") or "")[:1200]}
            for s in catalog[:600] if isinstance(s, dict) and s.get("id") and s.get("name")
        ] if isinstance(catalog, list) and mode == "director" else []
        skills_context = desktop_skills.set(catalog)
        caps = payload.get("capabilities") or []
        capabilities_context = desktop_capabilities.set(frozenset(c for c in caps[:64] if isinstance(c, str)) if isinstance(caps, list) and mode == "director" else frozenset())
        raw_work_context = payload.get("work_context") or ""
        work_context = desktop_work_context.set(raw_work_context if mode == "director" and isinstance(raw_work_context, str) and len(raw_work_context) <= 100_000 else "")
        try:
            if mode not in {"director", "chat"}:
                raise ValueError("Неизвестный режим беседы.")
            if mode == "director" and (not isinstance(raw_work_context, str) or len(raw_work_context) > 100_000):
                raise ValueError("Контекст проекта должен быть текстом до 100 000 символов.")
            content = str(payload.get("content") or "").strip()
            if not content or len(content) > 100_000:
                raise ValueError("Введите задачу до 100 000 символов.")
            bot_id = await repo.ensure_user(user_id)
            if mode == 'chat':
                target = payload.get('canvas_target')
                if target is not None and (not isinstance(target, str) or len(target) > 2048):
                    raise ValueError('Некорректная ссылка на холст.')
                selected = normalize_chat_mode(str(payload.get('chat_model') or 'auto'))
                desktop_chat_model.set(selected)
                preferences = await repo.capture_generation_preferences(user_id)
                preferences.update({'user_id': bot_id, 'selected_model': selected, 'canvas_target': target})
                preferences_token = generation_preferences.set(preferences)
            cid = payload.get("conversation_id") if mode == "chat" else None
            if cid:
                owner = await asyncio.to_thread(repo.conversations.owner, str(cid))
                if owner != bot_id:
                    roles = await asyncio.to_thread(repo.conversations.roles, bot_id, [str(cid)])
                    if roles.get(str(cid)) != "member":
                        raise ValueError("Нет доступа к этой беседе. Создайте новую.")
            elif mode == "chat":
                created = await repo.create_conversation(user_id, title=content[:60])
                cid = created["id"]
            if hub.running_count(user_id) >= MAX_JOBS_PER_USER:
                raise ValueError("Дождитесь завершения одной из текущих задач.")
            hub.mark_busy(user_id, cid or "desktop-local")
            marked = True
            if mode == "chat":
                await send("conversation", conversation_id=cid)

            async def status(text):
                await send("status", text=text)

            async def chunk(text):
                await send("text", text=text)

            async def file(name, data, url=""):
                import base64
                if mode == 'chat' and not data and url:
                    path = repo._manager._attachment_disk_path({'url': url})
                    if not path or not path.is_file() or path.stat().st_size > 100 * 1024 * 1024:
                        raise ValueError('Не удалось прочитать готовый файл. Откройте его в истории беседы.')
                    data = await asyncio.to_thread(path.read_bytes)
                await send("file", name=name, url=url, data=base64.b64encode(data).decode() if data else "")

            async def extras(reasoning, search):
                await send("extras", reasoning=reasoning, search=search)

            async def reasoning_delta(text):
                await send("reasoning_delta", text=text)

            if mode == "director" and payload.get("compact"):
                from app.services.desktop_compact import compact_history
                await status("Сжимаю контекст, сохраняю решения и незавершённые шаги…")
                summary = await compact_history(user_id, payload.get("history"), payload.get("compact_focus"))
                await send("context_compacted", summary=summary)
            elif mode == "director":
                await run_local_chat(user_id, content, None, status, chunk, file, history=payload.get("history") or [], send_extras=extras, send_reasoning_delta=reasoning_delta)
            else:
                await run_chat(user_id, content, cid, status, chunk, file, send_extras=extras, send_reasoning_delta=reasoning_delta)
        except asyncio.CancelledError:
            await send("stopped")
            raise
        except Exception as exc:
            from app.billing.quota import QuotaError
            logger.info("Desktop task failed: %s", type(exc).__name__)
            message = str(exc) if isinstance(exc, (ValueError, QuotaError)) else "Не удалось выполнить задачу. Попробуйте ещё раз."
            await send("error", message=message, code=getattr(exc, "code", "task"))
        finally:
            if marked:
                hub.clear_busy(user_id, cid or "desktop-local")
            _active_users.discard(user_id)
            desktop_cwd.reset(folder)
            desktop_executor.reset(context)
            desktop_mode.reset(mode_context)
            desktop_chat_model.reset(model_context)
            desktop_skills.reset(skills_context)
            desktop_work_context.reset(work_context)
            desktop_capabilities.reset(capabilities_context)
            if preferences_token is not None:
                generation_preferences.reset(preferences_token)
            subscription = None
            try:
                subscription = await subscription_payload(user_id)
            except Exception:
                logger.warning("Desktop subscription refresh failed at completion")
            try:
                await send("done", subscription=subscription)
            except (WebSocketDisconnect, RuntimeError):
                pass

    try:
        user_id = await _authenticate_ws(ws)
        # A valid signature alone is insufficient after an account is removed.
        from sqlalchemy import select
        from app.db.engine import AsyncSessionLocal
        from app.db.models import User
        async with AsyncSessionLocal() as session:
            exists = await session.scalar(select(User.id).where(User.email == user_id))
            if exists is None:
                raise WebSocketException(code=1008, reason="Account unavailable")
        await send("ready", protocol=PROTOCOL, mode="director", modes=["director", "chat"], local_history=True, work_context=True, context_compaction=True, context_policy=context_policy())
        while ws.application_state == WebSocketState.CONNECTED:
            raw = await ws.receive_text()
            if len(raw) > MAX_CLIENT_FRAME:
                await send("error", code="protocol", message="Сообщение BitClient слишком большое. Сократите историю или вложение и повторите.")
                continue
            msg = json.loads(raw)
            payload = msg.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if msg.get("type") == "ping":
                await send("pong")
            elif msg.get("type") == "tool_result":
                future = pending.get(str(payload.get("id") or ""))
                if future and not future.done():
                    future.set_result(payload)
            elif msg.get("type") == "stop":
                if task and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            elif msg.get("type") == "run":
                if user_id in _active_users or (task and not task.done()):
                    await send("error", message="Оркестратор уже выполняет задачу.", code="busy")
                    continue
                _active_users.add(user_id)
                task = asyncio.create_task(run(payload))
    # BitClient explicit connection failure
    except WebSocketException:
        try:
            await send("error", code="auth", message="Сессия Bit-Think истекла или доступ к аккаунту ограничен. Войдите заново.")
            await ws.close(code=1008)
        except Exception:
            pass
    except WebSocketDisconnect:
        pass
    except ValueError:
        try:
            await send("error", code="protocol", message="Некорректное сообщение BitClient. Обновите приложение.")
            await ws.close(code=1003)
        except Exception:
            pass
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for future in pending.values():
            if not future.done():
                future.cancel()
        try:
            await ws.close()
        except Exception:
            pass
