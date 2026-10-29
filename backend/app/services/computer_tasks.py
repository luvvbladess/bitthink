"""Durable cloud work queue. Disconnects do not cancel; crashed runs need review.

Atomic claims and leases work across backend workers. Interrupted external actions
are never silently replayed. A recurring task starts a new conversation per run.
"""
import asyncio
import logging
import time
import uuid
import hashlib
import json

from sqlalchemy import select, update, or_
from app.db.engine import SyncSessionLocal
from app.db.models import ComputerTask, ComputerEvent, User, Conversation, Subscription
from app.services.computer_context import computer_task_id

log = logging.getLogger(__name__)
LEASE_SECONDS = 90


def public(row: ComputerTask) -> dict:
    return {key: getattr(row, key) for key in (
        "id", "title", "prompt", "status", "conversation_id", "interval_seconds", "enabled",
        "next_run_at", "run_number", "resume_history", "progress", "error", "created_at", "updated_at",
    )}


def list_tasks(user: str) -> list[dict]:
    with SyncSessionLocal() as session:
        return [public(row) for row in session.scalars(select(ComputerTask).where(
            ComputerTask.user_email == user, or_(ComputerTask.conversation_id.is_(None),
                ComputerTask.conversation_id.notin_(select(Conversation.id).where(Conversation.deleted_at.is_not(None))))).order_by(ComputerTask.updated_at.desc()).limit(100))]


def get_task(user: str, task_id: str) -> dict | None:
    with SyncSessionLocal() as session:
        row = session.get(ComputerTask, task_id)
        return public(row) if row and row.user_email == user else None


def create_task(user: str, prompt: str, title: str = "", interval: int = 0, start_at: int = 0, idempotency_key: str | None = None, conversation_id: str | None = None) -> dict:
    now = int(time.time())
    with SyncSessionLocal() as session:
        # Serialize enrollment per account across workers, including retries.
        owner = session.scalar(select(User).where(User.email == user).with_for_update())
        request_hash = hashlib.sha256(json.dumps([prompt, title, interval, start_at] + ([conversation_id] if conversation_id else [])).encode()).hexdigest()
        key = hashlib.sha256((user + ':' + idempotency_key).encode()).hexdigest() if idempotency_key else None
        if key:
            previous = session.scalar(select(ComputerEvent).join(ComputerTask, ComputerTask.id == ComputerEvent.task_id).where(ComputerTask.user_email == user, ComputerEvent.kind == 'enrollment', ComputerEvent.detail.like('%"key": "' + key + '"%')).limit(1))
            if previous:
                if json.loads(previous.detail)['request'] != request_hash:
                    raise ValueError('Ключ запроса уже использован для другой задачи.')
                return public(session.get(ComputerTask, previous.task_id))
        if conversation_id:
            from app.services.project_memory import _private_chat
            if not owner:raise ValueError('Беседа не найдена.')
            _private_chat(session, owner.bot_user_id, conversation_id)
            existing = session.scalar(select(ComputerTask.id).where(ComputerTask.conversation_id == conversation_id,
                ComputerTask.enabled.is_(True), ComputerTask.status.in_(['queued', 'running', 'scheduled'])).limit(1))
            if existing:raise ValueError('В этой беседе уже есть активная задача. Добавьте уточнение к ней.')
        count = len(session.scalars(select(ComputerTask.id).where(
            ComputerTask.user_email == user, ComputerTask.enabled.is_(True))).all())
        if count >= 20:
            raise ValueError("Доступно до 20 активных задач. Приостановите одну из текущих.")
        row = ComputerTask(id=uuid.uuid4().hex, user_email=user, title=title or prompt[:100], prompt=prompt,
            conversation_id=conversation_id,
            status="scheduled" if start_at > now else "queued", interval_seconds=interval, enabled=True,
            next_run_at=max(now, start_at), lease_until=0, run_number=0, progress="", error="",
            created_at=now, updated_at=now)
        session.add(row)
        sub = session.scalar(select(Subscription).where(Subscription.user_id == owner.bot_user_id)) if owner else None
        session.add(ComputerEvent(task_id=row.id, run_number=0, kind='preferences',
            detail=json.dumps({'selected_model': 'director', 'reasoning_effort': sub.reasoning_effort if sub else None,
                'image_quality': sub.image_quality if sub and sub.image_quality else 'high'}), created_at=now))
        if key:
            session.add(ComputerEvent(task_id=row.id, run_number=0, kind='enrollment', detail=json.dumps({'key': key, 'request': request_hash}), created_at=now))
        session.commit()
        return public(row)


def task_preferences(task_id: str, user_id: int) -> dict:
    with SyncSessionLocal() as session:
        saved = session.scalar(select(ComputerEvent.detail).where(ComputerEvent.task_id == task_id,
            ComputerEvent.kind == 'preferences').order_by(ComputerEvent.id).limit(1))
        preferences = json.loads(saved) if saved else {}
        # This endpoint enrolls an Orchestrator task, independently of whatever
        # mode the account chooses in another chat before the worker starts.
        return {**preferences, 'user_id': user_id, 'selected_model': 'director'}


def event(task_id: str, kind: str, detail: str = "") -> None:
    with SyncSessionLocal() as session:
        row = session.get(ComputerTask, task_id)
        if row:
            session.add(ComputerEvent(task_id=task_id, run_number=row.run_number, kind=kind,
                                     detail=detail[:4000], created_at=int(time.time())))
            session.commit()


def events(user: str, task_id: str) -> list[dict]:
    if get_task(user, task_id) is None:
        raise ValueError("Задача не найдена.")
    with SyncSessionLocal() as session:
        rows = session.scalars(select(ComputerEvent).where(ComputerEvent.task_id == task_id, ComputerEvent.kind.not_in(['checkpoint', 'action_receipt', 'enrollment', 'run_scope', 'preferences']))
                               .order_by(ComputerEvent.id.desc()).limit(200)).all()
        return [{"id": r.id, "run": r.run_number, "kind": r.kind, "detail": r.detail,
                 "created_at": r.created_at} for r in reversed(rows)]


def claim() -> dict | None:
    now = int(time.time())
    with SyncSessionLocal() as session:
        session.execute(update(ComputerTask).where(ComputerTask.status == "running", ComputerTask.lease_until < now)
                        .values(status="interrupted", enabled=False, updated_at=now,
                                error="Сервер перезапустился во время работы. Проверьте шаги и продолжите вручную."))
        session.commit()
        rows = session.scalars(select(ComputerTask).where(
            ComputerTask.enabled.is_(True), ComputerTask.status.in_(["queued", "scheduled"]),
            ComputerTask.next_run_at <= now).order_by(ComputerTask.next_run_at).limit(20)).all()
        for row in rows:
            active = session.scalar(select(ComputerTask.id).where(
                ComputerTask.user_email == row.user_email, ComputerTask.status == "running").limit(1))
            if active:
                continue
            changed = session.execute(update(ComputerTask).where(
                ComputerTask.id == row.id, ComputerTask.status.in_(["queued", "scheduled"]),
                ComputerTask.enabled.is_(True),
            ).values(status="running", lease_until=now + LEASE_SECONDS, run_number=row.run_number + 1,
                     updated_at=now, error="", progress="Начинаю задачу"))
            session.commit()
            if changed.rowcount:
                session.refresh(row)
                return {**public(row), "user_email": row.user_email}
    return None


def heartbeat(task_id: str, run_number: int | None = None) -> bool:
    with SyncSessionLocal() as session:
        row = session.get(ComputerTask, task_id)
        if not row or row.status != "running" or not row.enabled or (run_number is not None and row.run_number != run_number):
            return False
        row.lease_until = int(time.time()) + LEASE_SECONDS
        session.commit()
        return True


def progress(task_id: str, run_number: int | None = None, **fields):
    with SyncSessionLocal() as session:
        row = session.get(ComputerTask, task_id)
        if row and row.status == "running" and (run_number is None or row.run_number == run_number):
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = int(time.time())
            session.commit()


def finish(task_id: str, status="completed", error="", run_number: int | None = None):
    now = int(time.time())
    with SyncSessionLocal() as session:
        row = session.get(ComputerTask, task_id)
        if not row or row.status != "running" or (run_number is not None and row.run_number != run_number):
            return
        row.error = error[:1000]
        if status == "completed":
            row.resume_history = False
        row.status = status
        row.lease_until = 0
        if status == "completed" and row.interval_seconds and row.enabled:
            row.status = "scheduled"
            row.next_run_at = now + row.interval_seconds
        else:
            row.enabled = False
        row.updated_at = now
        session.commit()


def control(user: str, task_id: str, action: str) -> dict:
    with SyncSessionLocal() as session:
        row = session.get(ComputerTask, task_id)
        if not row or row.user_email != user:
            raise ValueError("Задача не найдена.")
        if action == "resume":
            if row.conversation_id and session.scalar(select(Conversation.id).where(Conversation.id == row.conversation_id, Conversation.deleted_at.is_not(None))):
                raise ValueError('Сначала восстановите беседу из корзины.')
            if row.status == "running":
                raise ValueError("Задача уже выполняется.")
            row.resume_history = row.status not in {"completed", "scheduled"}
            row.status, row.enabled, row.next_run_at = "queued", True, int(time.time())
            row.error = ""
        elif action in {"pause", "cancel"}:
            row.status, row.enabled = ("paused" if action == "pause" else "cancelled"), False
        else:
            raise ValueError("Неизвестное действие.")
        row.updated_at = int(time.time())
        session.commit()
        return public(row)


def steer(user, task_id, text):
    with SyncSessionLocal() as session:
        row = session.scalar(select(ComputerTask).where(ComputerTask.id == task_id,
            ComputerTask.user_email == user).with_for_update())
        if not row:raise ValueError('Задача не найдена.')
        if row.status not in {'queued', 'running', 'paused', 'interrupted', 'failed', 'blocked'}:
            raise ValueError('Эта задача уже завершена. Отправьте новый запрос в беседу.')
        text = text.strip()
        if not text or len(text) > 2000:raise ValueError('Уточнение: от 1 до 2000 символов.')
        if len(row.prompt) + len(text) > 48000:raise ValueError('Слишком много уточнений для одной задачи.')
        row.prompt += '\n\nУточнение пользователя:\n' + text
        row.updated_at = int(time.time())
        session.add(ComputerEvent(task_id=task_id, run_number=row.run_number, kind='steering', detail=text,
            created_at=row.updated_at))
        session.commit()
        return public(row)


class ComputerWorker:
    def __init__(self):
        self.loop_task = None
        self.running: dict[str, asyncio.Task] = {}

    async def start(self):
        self.loop_task = asyncio.create_task(self.loop())

    async def stop(self):
        pending = ([self.loop_task] if self.loop_task else []) + list(self.running.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def loop(self):
        while True:
            try:
                if len(self.running) < 4:
                    row = await asyncio.to_thread(claim)
                    if row:
                        task = asyncio.create_task(self.run(row))
                        self.running[row["id"]] = task
                        def done(finished, key=row["id"]):
                            if self.running.get(key) is finished:
                                self.running.pop(key, None)
                        task.add_done_callback(done)
            except Exception:
                log.exception("Computer queue iteration failed")
            await asyncio.sleep(2)

    async def run(self, row: dict):
        from app.core.repository import repo
        from app.services.chat_service import run_chat
        from app.services.computer_hooks import task_instructions
        from app.services.generation_hub import hub
        from app.billing.plans import allowed_models
        from app.billing.quota import QuotaError, effective_tier

        task_id, user = row["id"], row["user_email"]
        token = computer_task_id.set(task_id)
        from app.services import task_checkpoints
        run_token = task_checkpoints.task_run_number.set(row['run_number'])
        group_token = journal_token = None
        beat = None
        cid = None
        busy = False
        preference_token = None
        try:
            uid = await repo.ensure_user(user)
            group, journal = await asyncio.to_thread(task_checkpoints.begin, task_id, row['run_number'], row['resume_history'])
            group_token = task_checkpoints.logical_run.set(group)
            journal_token = task_checkpoints.resumed_journal.set(journal)
            sub = await asyncio.to_thread(repo.billing.get_subscription, uid)
            if "director" not in allowed_models(effective_tier(sub)):
                raise QuotaError("Режим Оркестратора доступен с тарифа Pro.", "plan")
            from app.core.request_context import generation_preferences
            preference_token = generation_preferences.set(await asyncio.to_thread(task_preferences, task_id, uid))
            cid = row["conversation_id"]
            # A new recurring run gets a clean context. A user-resumed run uses its transcript.
            if not cid or (not row['resume_history'] and row['run_number'] > 1):
                cid = (await repo.create_conversation(user, title=row["title"]))["id"]
            hub.mark_busy(user, cid)
            busy = True
            hub.upsert_job(user, cid, user_text=row["prompt"])
            await asyncio.to_thread(progress, task_id, run_number=row["run_number"], conversation_id=cid)
            senders = hub.bind(user, cid)

            async def status(text):
                await asyncio.to_thread(progress, task_id, run_number=row["run_number"], progress=text[-4000:])
                if text:
                    await asyncio.to_thread(event, task_id, "progress", text[-4000:])
                await senders.send_status(text)

            async def watch():
                while True:
                    await asyncio.sleep(15)
                    if not await asyncio.to_thread(heartbeat, task_id, row["run_number"]):
                        current = self.running.get(task_id)
                        if current:
                            current.cancel()
                        return

            beat = asyncio.create_task(watch())
            await asyncio.to_thread(event, task_id, "before_task", "Начало выполнения")
            instructions = await asyncio.to_thread(task_instructions, uid)
            prompt = row["prompt"] + ("\n\nПравила рабочего процесса:\n" + instructions if instructions else "")
            if row["conversation_id"] and row["resume_history"]:
                prompt = "Продолжи задачу по истории. Проверь уже выполненные действия; не повторяй отправки и изменения без необходимости.\n" + prompt
            await run_chat(user, prompt, cid, status, senders.send_chunk, senders.send_file,
                           send_meta=senders.send_meta, send_extras=senders.send_extras,
                           send_reasoning_delta=senders.send_reasoning_delta)
            await asyncio.to_thread(event, task_id, "after_task", "Задача завершена")
            await asyncio.to_thread(finish, task_id, run_number=row["run_number"])
            await hub.broadcast(user, {"type": "done", "conversation_id": cid})
        except asyncio.CancelledError:
            await asyncio.to_thread(finish, task_id, "interrupted", "Работа остановлена; можно продолжить по истории.", row["run_number"])
            raise
        except Exception as exc:
            from app.services.improvement_journal import capture_error
            await asyncio.to_thread(capture_error, 'background', type(exc).__name__, account=user,
                                    event_key='background:' + task_id + ':' + str(row['run_number']))
            await asyncio.to_thread(finish, task_id, "blocked" if isinstance(exc, QuotaError) else "failed",
                                    str(exc) if isinstance(exc, (QuotaError, ValueError)) else "Не удалось выполнить задачу. Проверьте журнал и повторите.", row["run_number"])
            await asyncio.to_thread(event, task_id, "error", type(exc).__name__)
            log.warning("Computer task failed: %s", type(exc).__name__)
        finally:
            if busy and cid:
                hub.clear_busy(user, cid)
                hub.finish_job(user, cid)
            if beat:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)
            computer_task_id.reset(token)
            task_checkpoints.task_run_number.reset(run_token)
            if group_token is not None: task_checkpoints.logical_run.reset(group_token)
            if journal_token is not None: task_checkpoints.resumed_journal.reset(journal_token)
            if preference_token is not None: generation_preferences.reset(preference_token)


worker = ComputerWorker()
