"""Pilot tools over the Google account the user connected by button (Gmail, Drive, Calendar)."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import secrets
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from app.services.google_oauth import GoogleAuthError, api

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3/files"
CALENDAR = "https://www.googleapis.com/calendar/v3"
MAX_LIST = 20
DRIVE_MAX_BYTES = 30 * 1024 * 1024
MAX_OUTPUT = 12000

# Google Docs formats have no bytes of their own: export them to something we parse.
_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
}


def _clamp(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n\n[...обрезано...]"


def _limit(value: Any, default: int = 10) -> int:
    try:
        return max(1, min(int(value or default), MAX_LIST))
    except (TypeError, ValueError):
        return default


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}


def _mail_body(part: dict[str, Any]) -> tuple[str, str, list[str]]:
    """(plain, html, attachment names) collected from a MIME tree."""
    plain, html, files = "", "", []
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if part.get("filename"):
        files.append(part["filename"])
    elif data and mime == "text/plain":
        plain = _b64(data).decode("utf-8", errors="replace")
    elif data and mime == "text/html":
        html = _b64(data).decode("utf-8", errors="replace")
    for child in part.get("parts", []) or []:
        p, h, f = _mail_body(child)
        plain, html = plain or p, html or h
        files += f
    return plain, html, files


async def _mail_search(payload: dict, args: dict) -> str:
    params = {"maxResults": _limit(args.get("limit")), "q": str(args.get("query") or "").strip()}
    listed = await api(payload, "GET", f"{GMAIL}/messages", params=params)
    ids = [item["id"] for item in listed.get("messages", [])]
    if not ids:
        return "Писем не найдено."
    meta = [("format", "metadata")] + [("metadataHeaders", h) for h in ("From", "Subject", "Date")]
    messages = await asyncio.gather(*(api(payload, "GET", f"{GMAIL}/messages/{i}", params=meta) for i in ids))
    lines = []
    for msg in messages:
        head = _headers(msg)
        unread = " (не прочитано)" if "UNREAD" in msg.get("labelIds", []) else ""
        lines.append(
            f"id {msg['id']}{unread}\nFrom: {head.get('from', '')}\nSubject: {head.get('subject', '')}\n"
            f"Date: {head.get('date', '')}\nSnippet: {msg.get('snippet', '')}"
        )
    return _clamp("\n\n".join(lines))


async def _mail_read(payload: dict, args: dict) -> str:
    message_id = str(args.get("message_id") or "").strip()
    if not message_id.isalnum():
        return "Нужен message_id из google_mail_search."
    msg = await api(payload, "GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"})
    head = _headers(msg)
    plain, html, files = _mail_body(msg.get("payload", {}))
    if not plain and html:
        from bs4 import BeautifulSoup

        plain = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    attached = f"\nВложения: {', '.join(files)}" if files else ""
    return _clamp(
        f"From: {head.get('from', '')}\nTo: {head.get('to', '')}\nSubject: {head.get('subject', '')}\n"
        f"Date: {head.get('date', '')}{attached}\n\n{plain or msg.get('snippet', '')}"
    )


def _drive_query(text: str) -> str:
    text = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"(name contains '{text}' or fullText contains '{text}') and trashed = false"


async def _drive_search(payload: dict, args: dict) -> str:
    text = str(args.get("query") or "").strip()
    params = {
        "pageSize": _limit(args.get("limit")),
        "fields": "files(id,name,mimeType,modifiedTime)",
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
    }
    if text:
        params["q"] = _drive_query(text)  # Drive refuses orderBy together with fullText.
    else:
        params["q"] = "trashed = false"
        params["orderBy"] = "modifiedTime desc"
    listed = await api(payload, "GET", DRIVE, params=params)
    files = listed.get("files", [])
    if not files:
        return "Файлов не найдено."
    return _clamp("\n\n".join(
        f"id {f['id']}\n{f['name']}\n{f['mimeType']}, изменён {f.get('modifiedTime', '')}" for f in files
    ))


async def _drive_read(payload: dict, args: dict, user_id: int) -> str:
    file_id = str(args.get("file_id") or "").strip()
    if not file_id or not file_id.replace("-", "").replace("_", "").isalnum():
        return "Нужен file_id из google_drive_search."
    meta = await api(
        payload, "GET", f"{DRIVE}/{file_id}", params={"fields": "id,name,mimeType", "supportsAllDrives": "true"}
    )
    name, mime = str(meta.get("name") or "file"), str(meta.get("mimeType") or "")
    if mime in _EXPORTS:
        export_mime, ext = _EXPORTS[mime]
        data = await api(
            payload, "GET", f"{DRIVE}/{file_id}/export",
            params={"mimeType": export_mime}, raw=True, max_bytes=DRIVE_MAX_BYTES,
        )
        name += ext
    elif mime.startswith("application/vnd.google-apps."):
        return f"{name}: этот тип Google ({mime}) не читается как текст."
    else:
        data = await api(
            payload, "GET", f"{DRIVE}/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"}, raw=True, max_bytes=DRIVE_MAX_BYTES,
        )
    from db_conversations import _relevant_document_excerpt
    from document_parser import extract_text_from_file

    text = await extract_text_from_file(data, name, user_id=user_id)
    if not text:
        return f"{name}: формат не читается как текст."
    excerpt = _relevant_document_excerpt(text, str(args.get("query") or name), MAX_OUTPUT)
    return f"Файл: {name}\n\n{excerpt}"


async def _calendar_zone(payload: dict) -> ZoneInfo:
    try:
        setting = await api(payload, "GET", f"{CALENDAR}/users/me/settings/timezone")
        return ZoneInfo(str(setting.get("value") or "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def _rfc3339(value: str, zone: ZoneInfo, fallback: datetime) -> str:
    """Model-supplied date or datetime → RFC3339 in the calendar's zone."""
    value = (value or "").strip()
    if not value:
        return fallback.isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.isoformat()


async def _calendar_events(payload: dict, args: dict) -> str:
    zone = await _calendar_zone(payload)
    now = datetime.now(zone)
    params = {
        "timeMin": _rfc3339(str(args.get("time_min") or ""), zone, now),
        "timeMax": _rfc3339(str(args.get("time_max") or ""), zone, now + timedelta(days=7)),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
    }
    if args.get("query"):
        params["q"] = str(args["query"])
    listed = await api(payload, "GET", f"{CALENDAR}/calendars/primary/events", params=params)
    events = listed.get("items", [])
    if not events:
        return f"Событий нет ({params['timeMin']} – {params['timeMax']})."
    lines = [f"Часовой пояс календаря: {zone.key}"]
    for ev in events:
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
        end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
        place = f"\nГде: {ev['location']}" if ev.get("location") else ""
        people = len(ev.get("attendees", []))
        lines.append(
            f"{start} – {end}: {ev.get('summary', '(без названия)')}{place}"
            + (f"\nУчастников: {people}" if people else "")
        )
    return _clamp("\n\n".join(lines))


def _event_time(value: str, zone: str) -> dict[str, str]:
    value = value.strip()
    if len(value) == 10:
        return {"date": date.fromisoformat(value).isoformat()}
    datetime.fromisoformat(value.replace("Z", "+00:00"))  # reject garbage before Google does
    return {"dateTime": value, "timeZone": zone}


async def _calendar_create(payload: dict, args: dict) -> str:
    summary = str(args.get("summary") or "").strip()
    start = str(args.get("start") or "").strip()
    if not summary or not start:
        return "Нужны summary и start."
    zone = (await _calendar_zone(payload)).key
    end = str(args.get("end") or "").strip()
    if not end:
        if len(start) == 10:
            end = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
        else:
            end = (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=1)).isoformat()
    body = {"summary": summary, "start": _event_time(start, zone), "end": _event_time(end, zone)}
    for key in ("description", "location"):
        if args.get(key):
            body[key] = str(args[key])
    # ponytail: no attendees, so Pilot never mails invitations to other people.
    created = await api(payload, "POST", f"{CALENDAR}/calendars/primary/events", json_body=body)
    return f"Событие создано: {created.get('summary')} ({start} – {end}), {created.get('htmlLink', '')}"


SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"
# drive.file came first (only files the app made); an account connected then can still save.
DRIVE_WRITE_SCOPES = (DRIVE_FULL_SCOPE, "https://www.googleapis.com/auth/drive.file")
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
MAX_RECIPIENTS = 10
MAIL_MAX_BYTES = 18 * 1024 * 1024  # Gmail caps a message at 25 MB after base64.
_EMAIL_RE = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")


def _missing_scope(payload: dict, scopes: str | tuple[str, ...], what: str) -> str:
    """Accounts connected before this permission existed have to grant it once."""
    wanted = (scopes,) if isinstance(scopes, str) else scopes
    if set(wanted) & set(payload.get("scopes") or []):
        return ""
    return (
        f"Google подключён без права {what}. Пусть человек в Настройках → Google нажмёт "
        "«Подключить заново» и на экране Google отметит все галочки."
    )


def _recipients(value: Any) -> list[str] | None:
    items = value if isinstance(value, list) else str(value or "").replace(";", ",").split(",")
    emails = [str(item).strip() for item in items if str(item).strip()]
    if not emails or len(emails) > MAX_RECIPIENTS or not all(_EMAIL_RE.match(e) for e in emails):
        return None
    return emails


def _load_file(user_id: int, ref: str) -> tuple[str, bytes] | str:
    """A file from this person's sandbox (path) or from the current chat (file name)."""
    ref = str(ref or "").strip()
    if not ref:
        return "Нужен путь в песочнице или имя файла из чата."
    try:
        from app.services.workspace_fs import resolve_in_jail

        target = resolve_in_jail(int(user_id), ref)
        if target.is_file() and not target.is_symlink():
            if target.stat().st_size > DRIVE_MAX_BYTES:
                return f"{target.name}: больше {DRIVE_MAX_BYTES // (1024 * 1024)} МБ."
            return target.name, target.read_bytes()
    except Exception:
        pass
    from turn_scope import turn_conversation_id

    conv_id = turn_conversation_id()
    if conv_id:
        from app.api.editor import file_bytes
        from conversations import conversation_manager

        conv = conversation_manager.conversation_view(int(user_id), conv_id)
        data = file_bytes(conv, ref) if conv else None
        if data:
            return ref, data
    return f"Файл «{ref}» не найден ни в песочнице, ни в этом чате."


async def _mail_send(payload: dict, args: dict, user_id: int) -> str:
    missing = _missing_scope(payload, SEND_SCOPE, "отправлять письма")
    if missing:
        return missing
    to = _recipients(args.get("to"))
    cc = _recipients(args.get("cc")) if args.get("cc") else []
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").strip()
    if to is None or cc is None:
        return f"Нужны корректные адреса получателей, не больше {MAX_RECIPIENTS}."
    if not subject or not body:
        return "Нужны тема и текст письма."
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(body)
    total = 0
    for ref in args.get("attachments") or []:
        loaded = _load_file(user_id, ref)
        if isinstance(loaded, str):
            return loaded + " Письмо не отправлено."
        name, data = loaded
        total += len(data)
        if total > MAIL_MAX_BYTES:
            return "Вложения больше 18 МБ: положи файл на Диск (google_drive_upload) и пришли ссылку. Письмо не отправлено."
        maintype, _, subtype = (mimetypes.guess_type(name)[0] or "application/octet-stream").partition("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = await api(payload, "POST", f"{GMAIL}/messages/send", json_body={"raw": raw})
    copies = f", копия: {', '.join(cc)}" if cc else ""
    return f"Письмо отправлено: {', '.join(to)}{copies}. Тема «{subject}». id {sent.get('id', '')}"


async def _drive_upload(payload: dict, args: dict, user_id: int) -> str:
    missing = _missing_scope(payload, DRIVE_WRITE_SCOPES, "сохранять файлы на Диск")
    if missing:
        return missing
    name = str(args.get("name") or "").strip()
    if args.get("file"):
        loaded = _load_file(user_id, str(args["file"]))
        if isinstance(loaded, str):
            return loaded
        source_name, data = loaded
        name = name or source_name
    elif args.get("content"):
        data = str(args["content"]).encode("utf-8")
        name = name or "Заметка.txt"
    else:
        return "Нужен file (путь в песочнице или имя файла из чата) или content (текст)."
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    meta: dict[str, Any] = {"name": name}
    folder = str(args.get("folder_id") or "").strip()
    if folder:
        meta["parents"] = [folder]
    boundary = secrets.token_hex(16)
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta, ensure_ascii=False)}\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--".encode("ascii")
    created = await api(
        payload, "POST", UPLOAD,
        params={"uploadType": "multipart", "fields": "id,name,webViewLink", "supportsAllDrives": "true"},
        data=body, content_type=f"multipart/related; boundary={boundary}",
    )
    return (
        f"Сохранено на Google Диск: {created.get('name', name)} — {created.get('webViewLink', '')} "
        f"(id {created.get('id', '')})"
    )


async def _drive_trash(payload: dict, args: dict) -> str:
    """By default into the Drive trash, restorable for 30 days. permanent=true deletes
    outright, only when the person said so. drive.file accounts reach only app-made files."""
    missing = _missing_scope(payload, DRIVE_WRITE_SCOPES, "удалять файлы на Диске")
    if missing:
        return missing
    file_id = str(args.get("file_id") or "").strip()
    if not file_id or not file_id.replace("-", "").replace("_", "").isalnum():
        return "Нужен file_id из google_drive_search или из ответа google_drive_upload."
    permanent = args.get("permanent") in (True, "true", "True", 1)
    params = {"fields": "id,name", "supportsAllDrives": "true"}
    try:
        meta = await api(payload, "GET", f"{DRIVE}/{file_id}", params=params)
        name = meta.get("name", file_id)
        if permanent:
            await api(payload, "DELETE", f"{DRIVE}/{file_id}", params={"supportsAllDrives": "true"}, raw=True)
        else:
            await api(payload, "PATCH", f"{DRIVE}/{file_id}", params=params, json_body={"trashed": True})
    except GoogleAuthError as exc:
        if " 403" in str(exc) or " 404" in str(exc):
            if DRIVE_FULL_SCOPE not in (payload.get("scopes") or []):
                return _missing_scope(payload, DRIVE_FULL_SCOPE, "удалять любые файлы на Диске")
            return "Google не дал удалить файл: нет прав на него (например, это чужой общий файл) или его уже нет."
        raise
    if permanent:
        return f"Файл «{name}» удалён с Google Диска навсегда."
    return f"Файл «{name}» перемещён в корзину Google Диска. Восстановить можно из корзины в течение 30 дней."


async def run_google_tool(name: str, args: dict[str, Any], payload: dict[str, Any], user_id: int) -> str:
    if name == "google_drive_trash":
        return await _drive_trash(payload, args)
    if name == "google_mail_send":
        return await _mail_send(payload, args, user_id)
    if name == "google_drive_upload":
        return await _drive_upload(payload, args, user_id)
    if name == "google_mail_search":
        return await _mail_search(payload, args)
    if name == "google_mail_read":
        return await _mail_read(payload, args)
    if name == "google_drive_search":
        return await _drive_search(payload, args)
    if name == "google_drive_read":
        return await _drive_read(payload, args, user_id)
    if name == "google_calendar_events":
        return await _calendar_events(payload, args)
    if name == "google_calendar_create":
        return await _calendar_create(payload, args)
    return f"Инструмент {name} не найден."
