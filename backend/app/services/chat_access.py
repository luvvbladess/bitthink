"""Chat-provided Computer access: parse, encrypt, resolve, redact."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.security.redact import labeled_secret_spans, redact_text
from app.services import connectors as store

_LOGIN_PASS = re.compile(r"(?i)логин\s+(\S+)\s+пароль\s+(\S+)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s]+", re.I)
_LABELED = re.compile(
    r"(?i)\b(пароль(?:\s+приложения)?|app\s*password|password|token|логин|login|username|email|host|url|base_url)\s*[:=]\s*(\S+)"
)

_MISSING = "Нет доступа. Передай в инструмент логин и пароль из сообщения пользователя."


def _labeled_map(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, value in _LABELED.findall(text or ""):
        mapping[key.lower()] = value.strip().strip(".,;\"'")
    return mapping


def ingest_from_text(user_id: int, text: str) -> None:
    """Best-effort stash of clearly labeled credentials from the current message."""
    labeled = _labeled_map(text)
    urls = _URL.findall(text or "")
    emails = _EMAIL.findall(text or "")
    login_pass = _LOGIN_PASS.search(text or "")

    email = labeled.get("email") or (emails[0] if emails else "")
    app_password = (
        labeled.get("пароль приложения")
        or labeled.get("app password")
        or labeled.get("app_password")
    )
    if email and app_password and len(app_password) >= 8:
        try:
            store.upsert_connector(user_id, "gmail", email, {"email": email, "app_password": app_password})
        except Exception:
            pass

    if login_pass:
        username, password = login_pass.group(1), login_pass.group(2)
        url = labeled.get("url") or (urls[0] if urls else "")
        if url and password:
            try:
                store.upsert_connector(
                    user_id,
                    "web",
                    urlparse(url).hostname or "сайт",
                    {"login_url": url, "username": username, "password": password},
                )
            except Exception:
                pass

    host = labeled.get("host")
    ssh_user = labeled.get("username") or labeled.get("логин") or labeled.get("login")
    ssh_password = labeled.get("пароль") or labeled.get("password")
    if host and ssh_user and ssh_password and "пароль приложения" not in labeled:
        try:
            store.upsert_connector(
                user_id,
                "ssh",
                f"{ssh_user}@{host}",
                {"host": host, "username": ssh_user, "password": ssh_password},
            )
        except Exception:
            pass

    token = labeled.get("token")
    base = labeled.get("base_url") or labeled.get("url")
    if token and base and base.startswith("http"):
        try:
            store.upsert_connector(user_id, "http", base, {"base_url": base, "token": token})
        except Exception:
            pass


def redact_for_user(user_id: int, text: str) -> str:
    secrets = store.secret_values(user_id) + labeled_secret_spans(text)
    return redact_text(text, secrets)


def scrub_recent(user_id: int, conv_id: str | None = None) -> None:
    from conversations import conversation_manager

    conversation_manager.redact_recent_messages(user_id, store.secret_values(user_id), conv_id=conv_id)


def public_summary(user_id: int) -> str:
    items = store.list_public(user_id)
    if not items:
        return (
            "Сохранённых доступов пока нет. Пользователь кидает логин и пароль прямо в чат. "
            "Сотрудники сами вызывают site_login / gmail_* / ssh_exec / http_request с этими данными. "
            "Не проси открыть настройки."
        )
    lines = []
    for item in items:
        hint = f" ({item['hint']})" if item.get("hint") else ""
        lines.append(f"- id={item['id']}, type={item['type']}, name={item['name']}{hint}")
    return (
        "Уже сохранённые доступы (секреты скрыты). Можно вызывать инструменты без пароля:\n"
        + "\n".join(lines)
        + "\nНовые логины пользователь даёт в чате, не через настройки."
    )


def _inline_payload(kind: str, args: dict[str, Any]) -> dict[str, Any] | None:
    if kind == "gmail":
        email = str(args.get("email") or "").strip()
        password = str(args.get("app_password") or args.get("password") or "").strip()
        if email and password:
            return {"email": email, "app_password": password}
        return None
    if kind == "ssh":
        host = str(args.get("host") or "").strip()
        username = str(args.get("username") or "").strip()
        password = str(args.get("password") or "").strip()
        private_key = str(args.get("private_key") or "").strip()
        if host and username and (password or private_key):
            payload = {"host": host, "username": username, "port": args.get("port") or 22}
            if password:
                payload["password"] = password
            if private_key:
                payload["private_key"] = private_key
            return payload
        return None
    if kind == "http":
        base_url = str(args.get("base_url") or "").strip()
        if not base_url:
            return None
        payload = {"base_url": base_url}
        if args.get("token"):
            payload["token"] = str(args.get("token"))
        if args.get("basic_user"):
            payload["basic_user"] = str(args.get("basic_user"))
            payload["basic_password"] = str(args.get("basic_password") or "")
        return payload
    if kind == "web":
        username = str(args.get("username") or args.get("login") or "").strip()
        password = str(args.get("password") or "").strip()
        login_url = str(args.get("login_url") or args.get("url") or "").strip()
        if username and password and login_url:
            payload = {
                "login_url": login_url,
                "username": username,
                "password": password,
                "username_field": str(args.get("username_field") or "username"),
                "password_field": str(args.get("password_field") or "password"),
            }
            extra = args.get("extra_fields")
            if isinstance(extra, dict):
                payload["extra_fields"] = extra
            return payload
        return None
    return None


def resolve(user_id: int, kind: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    inline = _inline_payload(kind, args)
    if inline:
        try:
            hint = inline.get("email") or inline.get("host") or inline.get("base_url") or inline.get("login_url") or kind
            store.upsert_connector(user_id, kind, str(hint)[:80], inline)
        except Exception:
            pass
        return inline, None

    connector_id = args.get("connector_id") or args.get("access_id")
    if connector_id is not None:
        try:
            loaded = store.get_secret(user_id, int(connector_id))
        except (TypeError, ValueError):
            loaded = None
        if not loaded:
            return None, "Доступ не найден."
        row, payload = loaded
        if row.type != kind:
            return None, f"Это доступ типа {row.type}, нужен {kind}."
        return payload, None

    matches = [item for item in store.list_public(user_id) if item["type"] == kind]
    email = str(args.get("email") or "").strip().lower()
    host = str(args.get("host") or "").strip().lower()
    if email or host:
        for item in matches:
            hint = (item.get("hint") or "").lower()
            if email and email in hint:
                loaded = store.get_secret(user_id, item["id"])
                return (loaded[1], None) if loaded else (None, _MISSING)
            if host and host in hint:
                loaded = store.get_secret(user_id, item["id"])
                return (loaded[1], None) if loaded else (None, _MISSING)
    if len(matches) == 1:
        loaded = store.get_secret(user_id, matches[0]["id"])
        return (loaded[1], None) if loaded else (None, _MISSING)
    if len(matches) > 1:
        names = ", ".join(f"id={item['id']} {item.get('hint') or item['name']}" for item in matches)
        return None, f"Несколько доступов ({names}). Укажи connector_id или передай логин из чата."
    return None, _MISSING
