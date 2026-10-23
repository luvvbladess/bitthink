import asyncio
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.auth import get_current_user
from app.core.repository import repo
from app.db.engine import SyncSessionLocal
from app.db.models import ComputerHook
from app.services import computer_tasks

router = APIRouter()


class TaskCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=50000)
    title: str = Field(default="", max_length=160)
    interval_seconds: int = Field(default=0, ge=0, le=2592000)
    start_at: int = Field(default=0, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class Steering(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class HookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    event: str = Field(pattern="^(before_task|before_tool|after_tool)$")
    action: str = Field(pattern="^(instruction|deny|limit)$")
    value: str = Field(min_length=1, max_length=4000)


async def require_computer(user: str):
    from app.billing.plans import allowed_models
    from app.billing.quota import effective_tier
    sub = await repo.get_subscription(user)
    if "director" not in allowed_models(effective_tier(sub)):
        raise HTTPException(403, "Оркестратор доступен с тарифа Pro.")


@router.get("/tasks")
async def list_tasks(user: str = Depends(get_current_user)):
    return await asyncio.to_thread(computer_tasks.list_tasks, user)


@router.post("/tasks")
async def create_task(data: TaskCreate, user: str = Depends(get_current_user)):
    await require_computer(user)
    if data.interval_seconds and data.interval_seconds < 300:
        raise HTTPException(400, "Интервал должен быть не меньше пяти минут.")
    if not data.prompt.strip() or data.start_at > int(time.time()) + 366 * 86400:
        raise HTTPException(400, "Проверьте текст задачи и дату начала.")
    from app.services.chat_access import redact_for_user
    uid = await repo.ensure_user(user)
    prompt = await asyncio.to_thread(redact_for_user, uid, data.prompt.strip())
    try:
        return await asyncio.to_thread(computer_tasks.create_task, user, prompt, data.title,
                                       data.interval_seconds, data.start_at, data.idempotency_key, data.conversation_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: str = Depends(get_current_user)):
    row = await asyncio.to_thread(computer_tasks.get_task, user, task_id)
    if row is None:
        raise HTTPException(404, "Задача не найдена.")
    return row


@router.get("/tasks/{task_id}/events")
async def events(task_id: str, user: str = Depends(get_current_user)):
    try:
        return await asyncio.to_thread(computer_tasks.events, user, task_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/tasks/{task_id}/steer')
async def steer_task(task_id: str, data: Steering, user: str = Depends(get_current_user)):
    from app.services.chat_access import redact_for_user
    text = await asyncio.to_thread(redact_for_user, await repo.ensure_user(user), data.text)
    try:return await asyncio.to_thread(computer_tasks.steer, user, task_id, text)
    except ValueError as exc:raise HTTPException(400, str(exc)) from exc


@router.post("/tasks/{task_id}/{action}")
async def control(task_id: str, action: str, user: str = Depends(get_current_user)):
    if action == "resume":
        await require_computer(user)
        existing = computer_tasks.worker.running.get(task_id)
        if existing and not existing.done():
            raise HTTPException(409, "Дождитесь остановки текущего запуска.")
    try:
        row = await asyncio.to_thread(computer_tasks.control, user, task_id, action)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if action in {"pause", "cancel"}:
        task = computer_tasks.worker.running.get(task_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return row


def hook_view(row):
    return {k: getattr(row, k) for k in ("id", "name", "event", "action", "value", "enabled")}


def list_hooks(uid):
    with SyncSessionLocal() as session:
        return [hook_view(r) for r in session.scalars(select(ComputerHook).where(ComputerHook.user_id == uid))]


@router.get("/hooks")
async def hooks(user: str = Depends(get_current_user)):
    return await asyncio.to_thread(list_hooks, await repo.ensure_user(user))


@router.post("/hooks")
async def add_hook(data: HookCreate, user: str = Depends(get_current_user)):
    valid = {("before_task", "instruction"), ("before_tool", "deny"), ("after_tool", "limit")}
    if (data.event, data.action) not in valid:
        raise HTTPException(400, "Недопустимое действие для этого события.")
    if data.action == "limit" and (not data.value.isdigit() or not 200 <= int(data.value) <= 12000):
        raise HTTPException(400, "Лимит результата — от 200 до 12000 символов.")
    if data.action == "deny":
        data.value = ",".join(t.strip() for t in data.value.split(",") if t.strip())
        from computer_tools import COMPUTER_TOOL_NAMES
        if any(n not in COMPUTER_TOOL_NAMES for n in data.value.split(",")):
            raise HTTPException(400, "Указан неизвестный инструмент.")
    uid = await repo.ensure_user(user)
    from app.services.chat_access import redact_for_user
    data.value = await asyncio.to_thread(redact_for_user, uid, data.value)
    def save():
        with SyncSessionLocal() as session:
            if len(session.scalars(select(ComputerHook.id).where(ComputerHook.user_id == uid)).all()) >= 20:
                raise ValueError("Доступно до 20 правил.")
            row = ComputerHook(user_id=uid, **data.model_dump(), enabled=True)
            session.add(row)
            session.commit()
            return hook_view(row)
    try:
        return await asyncio.to_thread(save)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/hooks/{hook_id}")
async def delete_hook(hook_id: int, user: str = Depends(get_current_user)):
    uid = await repo.ensure_user(user)
    def remove():
        with SyncSessionLocal() as session:
            row = session.get(ComputerHook, hook_id)
            if not row or row.user_id != uid:
                return False
            session.delete(row)
            session.commit()
            return True
    if not await asyncio.to_thread(remove):
        raise HTTPException(404, "Правило не найдено.")
    return {"ok": True}
