"""Conversational access to the same persistent queue as the inline UI."""
import asyncio
import json
import hashlib
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from app.db.engine import SyncSessionLocal
from app.db.models import User


def owner_email(user_id: int) -> str | None:
    with SyncSessionLocal() as session:
        return session.scalar(select(User.email).where(User.bot_user_id == user_id))


async def run_task_tool(name: str, args: dict, user_id: int | None) -> str:
    from computer_skills.loader import turn_is_shared
    from app.api.computer import TaskCreate, create_task, list_tasks, control, get_task
    from app.services.computer_context import computer_task_id
    if not user_id or turn_is_shared(user_id):
        return "Задачи аккаунта доступны в вашей личной беседе."
    owner = await asyncio.to_thread(owner_email, user_id)
    if not owner:
        return "Для фоновых задач нужен аккаунт БитСинк."
    try:
        if name == "task_list":
            rows = await list_tasks(owner)
            result = [{key: row.get(key) for key in ("id", "title", "status", "enabled", "interval_seconds", "next_run_at", "conversation_id")} for row in rows]
        elif name == "task_create":
            if computer_task_id.get():
                return "Фоновая задача не создаёт вложенные расписания. Измените расписание в личной беседе."
            payload = TaskCreate.model_validate(args)
            from app.services.run_protocol import current_run
            record = current_run.get()
            if record:
                fingerprint = hashlib.sha256((owner + json.dumps(payload.model_dump(), sort_keys=True)).encode()).hexdigest()
                # Parallel workers/retries in this turn must not enroll duplicate jobs.
                async with record.task_lock:
                    result = record.task_results.get(fingerprint)
                    if result is None:
                        result = await create_task(payload, owner)
                        record.task_results[fingerprint] = result
                    result = await get_task(result['id'], owner)
            else:
                result = await create_task(payload, owner)
                result = await get_task(result['id'], owner)
        else:
            action = args.get("action")
            if action not in {"pause", "resume", "cancel"}:
                return "Допустимые действия: pause, resume, cancel."
            if computer_task_id.get() == args.get("task_id"):
                return "Запущенная задача не может изменять собственное расписание."
            result = await control(str(args.get("task_id") or ""), action, owner)
        return json.dumps(result, ensure_ascii=False)
    except ValidationError:
        return "Проверьте текст, дату начала и интервал фоновой задачи."
    except (HTTPException, ValueError) as exc:
        return "Не удалось изменить задачу: " + str(exc.detail if isinstance(exc, HTTPException) else exc)
