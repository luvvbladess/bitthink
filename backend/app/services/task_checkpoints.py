"""Fenced checkpoints and conservative external-action receipts for cloud jobs.

An uncertain action is never replayed automatically. This is not a claim of
exactly-once execution in an external service; a crash requires readback there.
"""
import hashlib
import json
import time
from contextvars import ContextVar
from sqlalchemy import select
from app.db.models import ComputerTask, ComputerEvent
from app.db.engine import SyncSessionLocal
from app.services.computer_context import computer_task_id

task_run_number: ContextVar[int] = ContextVar("task_run_number", default=0)
logical_run: ContextVar[int] = ContextVar("logical_run", default=0)
resumed_journal: ContextVar[list | None] = ContextVar("resumed_journal", default=None)


def _task(session):
    tid = computer_task_id.get()
    row = session.scalar(select(ComputerTask).where(ComputerTask.id == tid).with_for_update()) if tid else None
    if not row or row.status != "running" or not row.enabled or row.run_number != task_run_number.get():
        raise ValueError("Запуск задачи уже остановлен. Действие не выполнено.")
    return row


def begin(task_id, run_number, resume):
    with SyncSessionLocal() as session:
        previous = session.scalar(select(ComputerEvent).where(ComputerEvent.task_id == task_id, ComputerEvent.kind == "run_scope").order_by(ComputerEvent.id.desc()).limit(1)) if resume else None
        group = json.loads(previous.detail)["logical_run"] if previous else run_number
        checkpoint = session.scalar(select(ComputerEvent).where(ComputerEvent.task_id == task_id, ComputerEvent.kind == "checkpoint").order_by(ComputerEvent.id.desc()).limit(1)) if resume else None
        data = json.loads(checkpoint.detail) if checkpoint else {}
        journal = data.get("journal", []) if data.get("logical_run") == group else []
        session.add(ComputerEvent(task_id=task_id, run_number=run_number, kind="run_scope", detail=json.dumps({"logical_run": group}), created_at=int(time.time())))
        session.commit()
        return group, journal


def save(journal, uid):
    if not computer_task_id.get(): return
    from app.services.chat_access import redact_for_user
    clean = []
    for entry in journal[-12:]:
        # Prices, reviews and search observations must be fetched anew on resume.
        if entry.get("status") != "ok" or entry.get("search") or entry.get("live_verification"): continue
        item = {key: entry.get(key) for key in ("round", "role", "task", "model", "status", "result")}
        item["result"] = redact_for_user(uid, str(item.get("result") or ""))[:6000]
        clean.append(item)
    payload = json.dumps({"logical_run": logical_run.get(), "journal": clean}, ensure_ascii=False)
    with SyncSessionLocal() as session:
        row = _task(session)
        session.add(ComputerEvent(task_id=row.id, run_number=row.run_number, kind="checkpoint", detail=payload, created_at=int(time.time())))
        session.commit()


def external_action(name, args):
    if name == "http_request": return str(args.get("method", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
    # Unknown MCP calls and arbitrary commands may mutate state.
    return name in {"project_result", "project_result_patch", "project_purchase_plan", "project_purchase_offer", "gmail_send", "google_mail_send", "mcp_call", "ssh_exec", "desktop_run_command", "site_login", "google_calendar_create", "google_drive_upload", "google_drive_folder", "google_docs_create", "google_sheets_create", "google_sheets_update"}


def reserve(name, args):
    fingerprint = hashlib.sha256(json.dumps([logical_run.get(), name, args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with SyncSessionLocal() as session:
        row = _task(session)
        receipt = session.scalar(select(ComputerEvent).where(ComputerEvent.task_id == row.id, ComputerEvent.kind == "action_receipt", ComputerEvent.detail.like('%"key": "' + fingerprint + '"%')).order_by(ComputerEvent.id.desc()).limit(1))
        if receipt:
            data = json.loads(receipt.detail)
            if data["state"] == "done": return fingerprint, "Действие уже выполнено в этом запуске задачи; повтор не отправлялся. Сохранённый результат:\n" + data.get("result", "Проверьте результат в сервисе.")
            return fingerprint, "Действие уже запускалось, но его результат не подтверждён. Повтор заблокирован: сначала проверьте состояние во внешнем сервисе и попросите пользователя решить, нужен ли повтор."
        session.add(ComputerEvent(task_id=row.id, run_number=row.run_number, kind="action_receipt", detail=json.dumps({"key": fingerprint, "state": "pending", "tool": name}), created_at=int(time.time())))
        session.commit()
        return fingerprint, None


def complete(key, name, result, uid):
    from app.services.chat_access import redact_for_user
    result = redact_for_user(uid, str(result))[:8000]
    with SyncSessionLocal() as session:
        row = _task(session)
        session.add(ComputerEvent(task_id=row.id, run_number=row.run_number, kind="action_receipt", detail=json.dumps({"key": key, "state": "done", "tool": name, "result": result}, ensure_ascii=False), created_at=int(time.time())))
        session.commit()
