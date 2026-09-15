"""CRUD for Computer connectors. Secrets stay encrypted and never leave this module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.core.crypto import decrypt_json, encrypt_json
from app.db.engine import SyncSessionLocal
from app.db.models import Connector

CONNECTOR_TYPES = ("gmail", "ssh", "http", "web")
MAX_CONNECTORS_PER_USER = 20

_REQUIRED_FIELDS = {
    "gmail": ("email", "app_password"),
    "ssh": ("host", "username"),
    "http": ("base_url",),
    "web": ("login_url", "username", "password"),
}


def _public_view(row: Connector) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "name": row.name,
        "hint": row.hint,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _validate_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind not in CONNECTOR_TYPES:
        raise ValueError("Неизвестный тип подключения")
    if not isinstance(payload, dict):
        raise ValueError("Данные подключения должны быть объектом")

    missing = [field for field in _REQUIRED_FIELDS[kind] if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError("Заполните обязательные поля: " + ", ".join(missing))

    if kind == "ssh" and not str(payload.get("password") or "").strip() and not str(payload.get("private_key") or "").strip():
        raise ValueError("Для SSH укажите пароль или приватный ключ")

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        cleaned[str(key)[:64]] = value
    return cleaned


def _hint_for(kind: str, payload: dict[str, Any]) -> str:
    if kind == "gmail":
        return str(payload.get("email", ""))[:120]
    if kind == "ssh":
        host = str(payload.get("host", ""))
        port = payload.get("port") or 22
        user = str(payload.get("username", ""))
        return f"{user}@{host}:{port}"[:120]
    if kind == "http":
        return str(payload.get("base_url", ""))[:120]
    if kind == "web":
        return str(payload.get("login_url", ""))[:120]
    return ""


def list_public(account_uid: int) -> list[dict[str, Any]]:
    with SyncSessionLocal() as session:
        rows = session.scalars(
            select(Connector).where(Connector.user_id == account_uid).order_by(Connector.id.desc())
        ).all()
        return [_public_view(row) for row in rows]


def _match_key(kind: str, payload: dict[str, Any]) -> str:
    if kind == "gmail":
        return str(payload.get("email") or "").strip().lower()
    if kind == "ssh":
        host = str(payload.get("host") or "").strip().lower()
        user = str(payload.get("username") or "").strip().lower()
        return f"{user}@{host}"
    if kind == "http":
        return str(payload.get("base_url") or "").strip().rstrip("/").lower()
    if kind == "web":
        from urllib.parse import urlparse

        host = (urlparse(str(payload.get("login_url") or "")).hostname or "").lower()
        user = str(payload.get("username") or "").strip().lower()
        return f"{user}@{host}"
    return ""


def upsert_connector(account_uid: int, kind: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update encrypted access from chat-provided credentials."""
    kind = (kind or "").strip().lower()
    cleaned = _validate_payload(kind, payload)
    key = _match_key(kind, cleaned)
    hint = _hint_for(kind, cleaned)
    label = (name or hint or kind).strip()[:80] or kind

    with SyncSessionLocal() as session:
        rows = session.scalars(
            select(Connector).where(Connector.user_id == account_uid, Connector.type == kind)
        ).all()
        row = None
        for existing in rows:
            try:
                existing_payload = decrypt_json(existing.payload_encrypted)
            except Exception:
                continue
            if key and _match_key(kind, existing_payload) == key:
                row = existing
                break
        if row is None:
            count = session.scalar(
                select(func.count()).select_from(Connector).where(Connector.user_id == account_uid)
            ) or 0
            if count >= MAX_CONNECTORS_PER_USER:
                raise ValueError(f"Можно сохранить не больше {MAX_CONNECTORS_PER_USER} доступов")
            row = Connector(
                user_id=account_uid,
                type=kind,
                name=label,
                hint=hint,
                payload_encrypted=encrypt_json(cleaned),
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
        else:
            row.name = label
            row.hint = hint
            row.payload_encrypted = encrypt_json(cleaned)
        session.commit()
        session.refresh(row)
        return _public_view(row)


def secret_values(account_uid: int) -> list[str]:
    keys = ("password", "app_password", "token", "private_key", "basic_password", "passphrase")
    found: list[str] = []
    with SyncSessionLocal() as session:
        rows = session.scalars(select(Connector).where(Connector.user_id == account_uid)).all()
        for row in rows:
            try:
                payload = decrypt_json(row.payload_encrypted)
            except Exception:
                continue
            for key in keys:
                value = str(payload.get(key) or "").strip()
                if len(value) >= 4:
                    found.append(value)
    return found


def create_connector(account_uid: int, kind: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    kind = (kind or "").strip().lower()
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажите название подключения")
    if len(name) > 80:
        raise ValueError("Название слишком длинное")
    cleaned = _validate_payload(kind, payload)

    with SyncSessionLocal() as session:
        count = session.scalar(
            select(func.count()).select_from(Connector).where(Connector.user_id == account_uid)
        ) or 0
        if count >= MAX_CONNECTORS_PER_USER:
            raise ValueError(f"Можно сохранить не больше {MAX_CONNECTORS_PER_USER} подключений")
        row = Connector(
            user_id=account_uid,
            type=kind,
            name=name,
            hint=_hint_for(kind, cleaned),
            payload_encrypted=encrypt_json(cleaned),
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _public_view(row)


def delete_connector(account_uid: int, connector_id: int) -> bool:
    with SyncSessionLocal() as session:
        row = session.get(Connector, connector_id)
        if not row or row.user_id != account_uid:
            return False
        session.delete(row)
        session.commit()
        return True


def get_secret(account_uid: int, connector_id: int) -> tuple[Connector, dict[str, Any]] | None:
    with SyncSessionLocal() as session:
        row = session.get(Connector, connector_id)
        if not row or row.user_id != account_uid:
            return None
        return row, decrypt_json(row.payload_encrypted)
