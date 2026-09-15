"""Computer tools: visit pages, and use the user's own Gmail / SSH / HTTP / site logins."""

from __future__ import annotations

import asyncio
import email
import imaplib
import io
import ipaddress
import json
import logging
import re
import smtplib
import socket
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT = 12000
SSH_TIMEOUT_SECONDS = 30
SSH_MAX_OUTPUT = 50000
HTTP_TIMEOUT_SECONDS = 20
IMAP_MAX_MESSAGES = 20

_SAFE_IMAP_SEARCH = re.compile(
    r'^(ALL|UNSEEN|SEEN|FROM\s+"[^"]{1,80}"|SUBJECT\s+"[^"]{1,80}")$',
    re.IGNORECASE,
)

_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "169.254.169.254",
    "metadata.google.internal",
}


def _responses_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


def _chat_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_BROWSE_PROPS = {
    "url": {"type": "string", "description": "Полный URL страницы (https://...)"},
    "query": {"type": "string", "description": "Что вытащить со страницы. Без этого вернётся начало."},
}
_IMAGE_SEARCH_PROPS = {
    "filename": {
        "type": "string",
        "description": "Точное имя фото из чата. Без имени берётся последнее загруженное.",
    },
}
_CHAT_DOC_PROPS = {
    "filename": {"type": "string", "description": "Точное имя файла из чата, например report.pdf"},
    "query": {"type": "string", "description": "Что искать в файле. Без этого вернётся начало документа."},
}
_LIST_PROPS: dict = {}
_GMAIL_LIST_PROPS = {
    "email": {"type": "string", "description": "Gmail из сообщения пользователя"},
    "app_password": {"type": "string", "description": "Пароль приложения из чата. Не пиши его в ответ."},
    "connector_id": {"type": "integer", "description": "ID уже сохранённого доступа, если пароль уже передавали"},
    "folder": {"type": "string", "description": "Папка IMAP, по умолчанию INBOX"},
    "limit": {"type": "integer", "description": "Сколько писем показать, максимум 20"},
    "query": {"type": "string", "description": "IMAP SEARCH: ALL, UNSEEN, SEEN, FROM \"addr\", SUBJECT \"text\""},
}
_GMAIL_READ_PROPS = {
    "email": {"type": "string"},
    "app_password": {"type": "string"},
    "connector_id": {"type": "integer"},
    "uid": {"type": "string", "description": "UID письма из gmail_list"},
}
_GMAIL_SEND_PROPS = {
    "email": {"type": "string"},
    "app_password": {"type": "string"},
    "connector_id": {"type": "integer"},
    "to": {"type": "string"},
    "subject": {"type": "string"},
    "body": {"type": "string"},
}
_SSH_PROPS = {
    "host": {"type": "string", "description": "Хост VPS из сообщения пользователя"},
    "username": {"type": "string"},
    "password": {"type": "string"},
    "private_key": {"type": "string"},
    "port": {"type": "integer"},
    "connector_id": {"type": "integer"},
    "command": {"type": "string", "description": "Команда для выполнения на сервере пользователя"},
}
_HTTP_PROPS = {
    "base_url": {"type": "string", "description": "Базовый URL API из чата"},
    "token": {"type": "string"},
    "connector_id": {"type": "integer"},
    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
    "path": {"type": "string", "description": "Путь относительно base_url, например /v1/me"},
    "json_body": {"type": "string", "description": "JSON-тело для POST/PUT/PATCH, строкой"},
}
_WEB_BROWSE_PROPS = {
    "url": {"type": "string", "description": "Страница после входа"},
    "username": {"type": "string", "description": "Логин из чата"},
    "password": {"type": "string", "description": "Пароль из чата. Не пиши его в ответ."},
    "login_url": {"type": "string", "description": "URL формы входа, если он не совпадает с url"},
    "username_field": {"type": "string"},
    "password_field": {"type": "string"},
    "connector_id": {"type": "integer"},
}
_SKILL_PROPS = {
    "name": {"type": "string", "description": "Точное имя из list_skills, латиницей: api, browser, code, compare, prices, workspace, deck, infographic, visual_system, studio_render и т.д."},
}
_SAVE_SKILL_PROPS = {
    "name": {"type": "string", "description": "Короткое имя латиницей, с буквы. Например bitship_tone. Не общие имена вроде code или deck."},
    "title": {"type": "string", "description": "Человеческое название, если имя техническое"},
    "description": {"type": "string", "description": "Когда включать этот скил, одно-два предложения"},
    "body": {"type": "string", "description": "Правила работы: что делать и чего не делать"},
    "triggers": {"type": "string", "description": "Слова через запятую, по которым скил сам подхватится. Необязательно."},
}
_STUDIO_BUILD_PROPS = {
    "spec": {
        "type": "string",
        "description": (
            "JSON-строка DeckSpec или BoardSpec (kind: deck|infographic). "
            "Поддерживает visual/split_visual/composed и image_prompt – движок сам сгенерирует картинки."
        ),
    },
}
_FORGET_PROPS = {
    "connector_id": {"type": "integer", "description": "ID доступа из list_connectors, который нужно забыть"},
}
_WS_PATH = {"path": {"type": "string", "description": "Относительный путь внутри песочницы, например scripts/job.py"}}
_WS_READ_PROPS = {
    **_WS_PATH,
    "start_line": {"type": "integer", "description": "Первая строка с 1. Без неё – файл целиком до лимита."},
    "end_line": {"type": "integer", "description": "Последняя строка включительно."},
}
_WS_WRITE_PROPS = {
    **_WS_PATH,
    "content": {"type": "string", "description": "Полный текст файла"},
}
_WS_EDIT_PROPS = {
    **_WS_PATH,
    "old_string": {"type": "string", "description": "Уникальный фрагмент, который заменить"},
    "new_string": {"type": "string", "description": "На что заменить"},
}
_WS_RUN_PROPS = {
    **_WS_PATH,
    "argv": {"type": "array", "items": {"type": "string"}, "description": "Аргументы скрипта, без дефиса в начале"},
}
_PIP_PROPS = {
    "packages": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Пакеты PyPI, например [\"requests\", \"pandas\"]. Без URL и локальных путей.",
    },
}
_SEARCH_CHATS_PROPS = {
    "query": {"type": "string", "description": "Короткий запрос: тема, имя, цифра. Не целое предложение."},
    "limit": {"type": "integer", "description": "Сколько чатов вернуть, 1–10"},
}
_RECENT_CHATS_PROPS = {
    "limit": {"type": "integer", "description": "Сколько чатов показать, по умолчанию 8, максимум 20"},
}
_WS_GREP_PROPS = {
    "pattern": {"type": "string", "description": "Подстрока, без регулярок"},
    "path": {"type": "string", "description": "Папка или файл внутри песочницы, по умолчанию корень"},
    "glob": {"type": "string", "description": "Фильтр имён, например *.py"},
}
_WS_GLOB_PROPS = {
    "pattern": {"type": "string", "description": "Glob: **/*.py, scripts/*.json"},
    "path": {"type": "string", "description": "Относительная папка, по умолчанию корень"},
}

_TOOL_SPECS = [
    (
        "browse_page",
        "Прочитать публичную страницу. query – что вытащить; без него начало. После поиска, когда сниппета мало. Не localhost и не замена read_chat_document.",
        _BROWSE_PROPS,
        ["url"],
    ),
    (
        "image_search",
        "Поиск по фото из ЭТОГО чата в Яндекс.Картинках, Google Картинках/Lens и Bing. Для места, источника, «где снято». Не угадывай локацию по памяти. Не для генерации картинок.",
        _IMAGE_SEARCH_PROPS,
        [],
    ),
    (
        "read_chat_document",
        "Открыть уже загруженный в этот чат файл по точному имени. Не проси прислать его снова. query – что искать; без него вернётся начало.",
        _CHAT_DOC_PROPS,
        ["filename"],
    ),
    (
        "list_chat_files",
        "Имена файлов и фото этого чата. Документ – read_chat_document, фото – image_search. Не проси прислать снова.",
        _LIST_PROPS,
        [],
    ),
    (
        "search_chats",
        "Поиск по прошлым чатам этого человека, не интернет. Короткий запрос фактами. Не переключает чат. Не для новостей.",
        _SEARCH_CHATS_PROPS,
        ["query"],
    ),
    (
        "recent_chats",
        "Последние чаты с заголовками. Когда нужно вспомнить недавнюю тему без точного слова. Не интернет.",
        _RECENT_CHATS_PROPS,
        [],
    ),
    (
        "list_skills",
        "Каталог общих и ваших скилов. Когда человек спрашивает «какие скилы» / «покажи скилы» – верни имена и короткие описания. Текст общего скила человеку не читай вслух. Затем load_skill для себя. Не грузи все подряд.",
        _LIST_PROPS,
        [],
    ),
    (
        "load_skill",
        "Прочитать скил до кода, файла, таблицы, презентации, письма или входа на сайт. Скил знает ограничения среды, которых нет в памяти модели. Имя латиницей из list_skills. Если скил уже вложен в этот ход – не вызывай повторно.",
        _SKILL_PROPS,
        ["name"],
    ),
    (
        "save_skill",
        "Сохранить скил только для этого человека. Когда говорит «запомни как скил», «добавь скил», «сохрани скил». Имя латиницей, описание когда применять, правила. Не клади пароли. Не замена памяти предпочтений. Общие скилы не перезаписывай.",
        _SAVE_SKILL_PROPS,
        ["name", "description", "body"],
    ),
    (
        "delete_skill",
        "Удалить свой скил человека. Общие из каталога не удаляй.",
        _SKILL_PROPS,
        ["name"],
    ),
    (
        "list_connectors",
        "Уже сохранённые доступы из чата, без секретов. Вызови, если неясно, какой логин использовать.",
        _LIST_PROPS,
        [],
    ),
    (
        "site_login",
        "Войти на сайт логином и паролем из этого чата и открыть страницу. Настройки не нужны. Не проси человека копировать страницу.",
        _WEB_BROWSE_PROPS,
        ["url"],
    ),
    (
        "gmail_list",
        "Список писем. Email и пароль приложения из чата либо connector_id. Не ходи в настройки аккаунта Bit-Think.",
        _GMAIL_LIST_PROPS,
        [],
    ),
    (
        "gmail_read",
        "Прочитать одно письмо по UID из gmail_list. Сниппет темы – не содержимое.",
        _GMAIL_READ_PROPS,
        ["uid"],
    ),
    (
        "gmail_send",
        "Отправить письмо через Gmail человека. Пароль приложения из чата. Тело – готовый текст, не черновик «проверьте».",
        _GMAIL_SEND_PROPS,
        ["to", "subject", "body"],
    ),
    (
        "ssh_exec",
        "Команда на VPS человека. Host, логин, пароль или ключ – из чата. Не ходи на localhost и metadata.",
        _SSH_PROPS,
        ["command"],
    ),
    (
        "http_request",
        "Запрос к API человека. base_url и token из чата. Для публичной страницы лучше browse_page.",
        _HTTP_PROPS,
        ["method", "path"],
    ),
    (
        "connector_browse",
        "То же, что site_login: логин из чата или connector_id, затем страница.",
        _WEB_BROWSE_PROPS,
        ["url"],
    ),
    (
        "forget_access",
        "Удалить сохранённый доступ, только если человек просит забыть пароль.",
        _FORGET_PROPS,
        ["connector_id"],
    ),
    (
        "workspace_ls",
        "Список файлов личной песочницы (до 3 ГБ). Вызови до записи, чтобы не плодить дубли.",
        _WS_PATH,
        [],
    ),
    (
        "workspace_read",
        "Прочитать файл из песочницы. start_line/end_line – кусок большого файла. Для вложения чата – read_chat_document.",
        _WS_READ_PROPS,
        ["path"],
    ),
    (
        "workspace_write",
        "Создать или перезаписать файл в песочнице целиком. Правка куска – workspace_edit. Готовый артефакт человек скачает кнопкой.",
        _WS_WRITE_PROPS,
        ["path", "content"],
    ),
    (
        "workspace_edit",
        "Точечная замена уникального фрагмента. Не переписывай файл из-за опечатки.",
        _WS_EDIT_PROPS,
        ["path", "old_string"],
    ),
    (
        "workspace_delete",
        "Удалить файл или папку в песочнице. Только мусор, не чужие данные.",
        _WS_PATH,
        ["path"],
    ),
    (
        "workspace_grep",
        "Найти подстроку в файлах песочницы, без регулярок. Сначала это, не читай все файлы. Сложный разбор – python_run.",
        _WS_GREP_PROPS,
        ["pattern"],
    ),
    (
        "workspace_glob",
        "Найти файлы в песочнице по имени, например **/*.py или data/*.csv. Не выдумывай пути.",
        _WS_GLOB_PROPS,
        ["pattern"],
    ),
    (
        "python_run",
        "Запустить .py из песочницы. Если скрипт экономит токены или время – запускай, не спрашивай. Правка после падения – workspace_edit, потом снова run.",
        _WS_RUN_PROPS,
        ["path"],
    ),
    (
        "pip_install",
        "Пакеты PyPI в личный venv. Без URL, git+ и локальных путей. Затем python_run.",
        _PIP_PROPS,
        ["packages"],
    ),
    (
        "studio_build",
        "Собрать PPTX или PNG по JSON-spec Студии. Схема процесса, блок-схема, swimlane – infographic, не PDF. Для слайдов сначала load_skill deck. Результат – кнопка скачивания, не выдуманная ссылка.",
        _STUDIO_BUILD_PROPS,
        ["spec"],
    ),
]

COMPUTER_TOOLS_RESPONSES = [_responses_tool(*spec) for spec in _TOOL_SPECS]
COMPUTER_TOOLS_CHAT = [_chat_tool(*spec) for spec in _TOOL_SPECS]
COMPUTER_TOOL_NAMES = {spec[0] for spec in _TOOL_SPECS}


def _clamp(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...обрезано...]"


def _is_blocked_host(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS:
        return True
    if host.endswith(".localhost") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except ValueError:
        return False


def _assert_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Нужен обычный http(s) URL")
    host = parsed.hostname or ""
    if _is_blocked_host(host):
        raise ValueError("Этот адрес недоступен для Пилота")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Не удалось разрешить хост {host}") from exc
    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0]
        if _is_blocked_host(ip):
            raise ValueError("Этот адрес недоступен для Пилота")
    return url


async def _browse_public(url: str, query: str = "") -> str:
    from web_scraper import fetch_url_content

    _assert_public_http_url(url)
    fetched_url, text = await fetch_url_content(url)
    if (query or "").strip():
        from db_conversations import _relevant_document_excerpt

        excerpt = _relevant_document_excerpt(text or "", query.strip(), min(MAX_TOOL_OUTPUT - 80, 8_000))
        return _clamp(f"URL: {fetched_url}\nЗапрос: {query.strip()}\n\n{excerpt}")
    return _clamp(f"URL: {fetched_url}\n\n{text}")


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return " ".join(parts).strip()


def _message_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                html = payload.decode(charset, errors="replace")
                from bs4 import BeautifulSoup
                return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _imap_connect(payload: dict[str, Any]) -> imaplib.IMAP4_SSL:
    host = payload.get("imap_host") or "imap.gmail.com"
    port = int(payload.get("imap_port") or 993)
    mailbox = imaplib.IMAP4_SSL(host, port, timeout=20)
    mailbox.login(payload["email"], payload["app_password"])
    return mailbox


def _gmail_list_sync(payload: dict[str, Any], folder: str, limit: int, query: str) -> str:
    folder = folder or "INBOX"
    limit = max(1, min(int(limit or 10), IMAP_MAX_MESSAGES))
    search = (query or "UNSEEN").strip() or "UNSEEN"
    if not _SAFE_IMAP_SEARCH.match(search):
        return "Недопустимый IMAP-запрос. Разрешены: ALL, UNSEEN, SEEN, FROM \"addr\", SUBJECT \"text\"."
    mailbox = _imap_connect(payload)
    try:
        mailbox.select(folder, readonly=True)
        status, data = mailbox.uid("SEARCH", None, search)
        if status != "OK":
            return f"IMAP SEARCH не удался: {status}"
        uids = (data[0] or b"").decode().split()
        uids = uids[-limit:]
        if not uids:
            return "Писем не найдено."
        lines = []
        for uid in reversed(uids):
            status, fetched = mailbox.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK" or not fetched or fetched[0] is None:
                continue
            raw = fetched[0][1] if isinstance(fetched[0], tuple) else fetched[0]
            msg = email.message_from_bytes(raw)
            date_raw = msg.get("Date", "")
            try:
                date_s = parsedate_to_datetime(date_raw).isoformat()
            except Exception:
                date_s = date_raw
            lines.append(
                f"UID {uid.decode() if isinstance(uid, bytes) else uid}\n"
                f"From: {_decode_header_value(msg.get('From'))}\n"
                f"Subject: {_decode_header_value(msg.get('Subject'))}\n"
                f"Date: {date_s}"
            )
        return _clamp("\n\n".join(lines) or "Писем не найдено.")
    finally:
        try:
            mailbox.logout()
        except Exception:
            pass


def _gmail_read_sync(payload: dict[str, Any], uid: str, folder: str = "INBOX") -> str:
    uid = str(uid).strip()
    if not uid.isdigit():
        return "UID должен быть числом."
    mailbox = _imap_connect(payload)
    try:
        mailbox.select(folder or "INBOX", readonly=True)
        status, fetched = mailbox.uid("FETCH", uid, "(RFC822)")
        if status != "OK" or not fetched or fetched[0] is None:
            return "Письмо не найдено."
        raw = fetched[0][1] if isinstance(fetched[0], tuple) else fetched[0]
        msg = email.message_from_bytes(raw)
        body = _message_body(msg)
        return _clamp(
            f"From: {_decode_header_value(msg.get('From'))}\n"
            f"To: {_decode_header_value(msg.get('To'))}\n"
            f"Subject: {_decode_header_value(msg.get('Subject'))}\n"
            f"Date: {msg.get('Date', '')}\n\n{body}"
        )
    finally:
        try:
            mailbox.logout()
        except Exception:
            pass


def _gmail_send_sync(payload: dict[str, Any], to: str, subject: str, body: str) -> str:
    to = (to or "").strip()
    if "@" not in to or len(to) > 320:
        return "Некорректный адрес получателя."
    host = payload.get("smtp_host") or "smtp.gmail.com"
    port = int(payload.get("smtp_port") or 587)
    msg = MIMEText(body or "", "plain", "utf-8")
    msg["From"] = payload["email"]
    msg["To"] = to
    msg["Subject"] = subject or "(без темы)"
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(payload["email"], payload["app_password"])
        smtp.sendmail(payload["email"], [to], msg.as_string())
    return f"Письмо отправлено на {to}."


def _load_ssh_key(private_key: str, passphrase: str | None):
    import paramiko

    buf = io.StringIO(private_key)
    errors = []
    for loader in (paramiko.Ed25519Key.from_private_key, paramiko.RSAKey.from_private_key, paramiko.ECDSAKey.from_private_key):
        buf.seek(0)
        try:
            return loader(buf, password=passphrase or None)
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError("Не удалось прочитать SSH-ключ")


def _ssh_exec_sync(payload: dict[str, Any], command: str) -> str:
    import paramiko

    command = (command or "").strip()
    if not command:
        return "Пустая команда."
    if len(command) > 4000:
        return "Команда слишком длинная."
    host = payload["host"]
    if _is_blocked_host(host):
        return "Этот хост недоступен для Пилота."
    port = int(payload.get("port") or 22)
    username = payload["username"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    if payload.get("private_key"):
        pkey = _load_ssh_key(payload["private_key"], payload.get("passphrase"))
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=payload.get("password") or None,
            pkey=pkey,
            timeout=SSH_TIMEOUT_SECONDS,
            auth_timeout=SSH_TIMEOUT_SECONDS,
            allow_agent=False,
            look_for_keys=False,
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=SSH_TIMEOUT_SECONDS)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        text = f"exit={code}\n{out}"
        if err.strip():
            text += f"\nSTDERR:\n{err}"
        return _clamp(text, SSH_MAX_OUTPUT)
    finally:
        client.close()


def _same_host(base: str, target: str) -> bool:
    a = urlparse(base)
    b = urlparse(target)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


async def _http_request(payload: dict[str, Any], method: str, path: str, json_body: str | None) -> str:
    base = payload["base_url"].rstrip("/") + "/"
    _assert_public_http_url(base)
    url = urljoin(base, path.lstrip("/") if path else "")
    if not _same_host(base, url):
        return "Запрос разрешён только к хосту из подключения."
    headers = {}
    if payload.get("token"):
        scheme = payload.get("auth_scheme") or "Bearer"
        headers["Authorization"] = f"{scheme} {payload['token']}"
    extra = payload.get("headers")
    if isinstance(extra, dict):
        for key, value in extra.items():
            headers[str(key)] = str(value)
    auth = None
    if payload.get("basic_user"):
        auth = aiohttp.BasicAuth(payload["basic_user"], payload.get("basic_password") or "")
    body = None
    if json_body:
        try:
            body = json.loads(json_body)
        except json.JSONDecodeError:
            return "json_body должен быть валидным JSON."
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method.upper(), url, json=body, headers=headers, auth=auth, ssl=False) as resp:
            text = await resp.text(errors="replace")
            return _clamp(f"HTTP {resp.status} {url}\n\n{text}")


async def _connector_browse(payload: dict[str, Any], url: str) -> str:
    from web_scraper import HEADERS, _clean_html

    _assert_public_http_url(url)
    login_url = payload.get("login_url") or url
    _assert_public_http_url(login_url)
    user_field = payload.get("username_field") or "username"
    pass_field = payload.get("password_field") or "password"
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        form = {user_field: payload["username"], pass_field: payload["password"]}
        extra = payload.get("extra_fields")
        if isinstance(extra, dict):
            form.update({str(k): str(v) for k, v in extra.items()})
        async with session.post(login_url, data=form, allow_redirects=True, ssl=False) as login_resp:
            if login_resp.status >= 400:
                return f"Вход не удался: HTTP {login_resp.status}"
        async with session.get(url, allow_redirects=True, ssl=False) as resp:
            if resp.status != 200:
                return f"Не удалось открыть страницу: HTTP {resp.status}"
            html = await resp.text(errors="replace")
    text = _clean_html(html)
    return _clamp(f"URL: {url}\n\n{text}")


def connector_summary_for_prompt(account_uid: int) -> str:
    from app.services.chat_access import public_summary

    return public_summary(account_uid)


def skills_prompt(user_id: int | None = None) -> str:
    from computer_skills.loader import catalog_for_prompt

    return catalog_for_prompt(user_id)


async def _studio_build(user_id: int, args: dict[str, Any]) -> str:
    raw = args.get("spec")
    if isinstance(raw, dict):
        spec_obj = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return "Нужен spec (JSON DeckSpec или BoardSpec)."
        try:
            spec_obj = json.loads(text)
        except json.JSONDecodeError:
            return "spec должен быть валидным JSON."
        if not isinstance(spec_obj, dict):
            return "spec должен быть JSON-объектом."
    try:
        from studio.build import build_studio_artifact_async
        from studio.schema import StudioSpecError
    except Exception as exc:
        return f"Движок Студии недоступен: {exc}"
    try:
        files = await build_studio_artifact_async(
            spec_obj,
            user_id=int(user_id),
            with_previews=True,
            generate_images=True,
        )
    except StudioSpecError as exc:
        return f"Ошибка схемы Студии: {exc}"
    except Exception as exc:
        logger.exception("studio_build failed")
        return f"Не удалось собрать файл: {str(exc)[:240]}"
    if not files:
        return "Рендер не вернул файлов."

    written = []
    for item in files:
        name = str(item.get("filename") or "studio.bin")
        data = item.get("bytes") or b""
        if not data:
            continue
        try:
            from app.services.workspace_fs import user_root

            root = user_root(int(user_id))
            target = root / "studio"
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(data)
            written.append(name)
        except Exception:
            logger.exception("Failed to persist studio file %s", name)
    if not written:
        return "Файлы собраны, но не удалось записать в песочницу. Используйте режим Студия."
    return "Студия готова: " + ", ".join(written) + ". Файлы появятся кнопкой скачивания в чате."


async def run_computer_tool(name: str, args: dict[str, Any], user_id: int | None) -> str:
    try:
        from status_feed import announce_tool
        from app.security.redact import strip_secret_args

        await announce_tool(name, strip_secret_args(args))
    except Exception:
        pass
    try:
        if name == "browse_page":
            url = str(args.get("url") or "").strip()
            if not url:
                return "Нужен url."
            return await _browse_public(url, str(args.get("query") or ""))

        if name == "image_search":
            if not user_id:
                return "Нет пользователя для доступа."
            from conversations import conversation_manager
            from image_search import reverse_image_search

            loaded = conversation_manager.load_chat_image(int(user_id), str(args.get("filename") or ""))
            if not loaded:
                return "В этом чате нет фото. Нужно изображение вложением, не ссылкой в тексте."
            if loaded.get("error"):
                return str(loaded["error"])
            return await reverse_image_search(loaded["bytes"], str(loaded["name"]), str(loaded.get("mime") or "image/jpeg"))

        if name == "read_chat_document":
            if not user_id:
                return "Нет пользователя для доступа."
            filename = str(args.get("filename") or "").strip()
            if not filename:
                return "Нужно имя файла из чата."
            from conversations import conversation_manager
            from db_conversations import _relevant_document_excerpt

            docs = conversation_manager.get_documents(int(user_id))
            match = next((item for item in docs if str(item.get("filename") or "") == filename), None)
            if match is None:
                names = ", ".join(str(item.get("filename") or "") for item in docs) or "нет файлов"
                return f"Файл {filename} не найден. В чате: {names}."
            excerpt = _relevant_document_excerpt(
                match.get("content") or "",
                str(args.get("query") or filename),
                min(MAX_TOOL_OUTPUT, 12_000),
            )
            return excerpt or "Файл пустой."

        if name == "list_chat_files":
            if not user_id:
                return "Нет пользователя для доступа."
            from conversations import conversation_manager

            return await asyncio.to_thread(conversation_manager.list_chat_files, int(user_id))

        if name == "search_chats":
            if not user_id:
                return "Нет пользователя для доступа."
            query = str(args.get("query") or "").strip()
            if not query:
                return "Нужен query."
            from conversations import conversation_manager

            return await asyncio.to_thread(
                conversation_manager.search_user_chats,
                int(user_id),
                query,
                args.get("limit") or 5,
            )

        if name == "recent_chats":
            if not user_id:
                return "Нет пользователя для доступа."
            from conversations import conversation_manager

            return await asyncio.to_thread(
                conversation_manager.recent_user_chats,
                int(user_id),
                args.get("limit") or 8,
            )

        if name == "list_skills":
            from computer_skills.loader import catalog

            return json.dumps(list(catalog(user_id)), ensure_ascii=False)

        if name == "load_skill":
            from computer_skills.loader import load_skill

            return load_skill(str(args.get("name") or ""), user_id=user_id)

        if not user_id:
            return "Нет пользователя для доступа."

        if name == "save_skill":
            from conversations import conversation_manager

            try:
                row = conversation_manager.save_user_skill(
                    int(user_id),
                    name=str(args.get("name") or ""),
                    title=str(args.get("title") or ""),
                    description=str(args.get("description") or ""),
                    body=str(args.get("body") or ""),
                    triggers=str(args.get("triggers") or ""),
                )
            except ValueError as exc:
                return str(exc)
            except Exception:
                logger.exception("save_skill failed")
                return "Не удалось сохранить скил. Попробуйте ещё раз или добавьте его в Настройках."
            return (
                f"Скил «{row['name']}» сохранён только для вас. "
                "Он появится в Настройках и подхватится, когда задача совпадёт с описанием."
            )

        if name == "delete_skill":
            from conversations import conversation_manager

            try:
                ok = conversation_manager.delete_user_skill(int(user_id), str(args.get("name") or ""))
            except ValueError as exc:
                return str(exc)
            except Exception:
                logger.exception("delete_skill failed")
                return "Не удалось удалить скил."
            if not ok:
                return "Такого своего скила нет. Общие удалить нельзя."
            return f"Скил «{str(args.get('name') or '').strip().lower()}» удалён."

        from app.services import chat_access
        from app.services.connectors import delete_connector, list_public

        if name == "list_connectors":
            items = list_public(user_id)
            if not items:
                return "Сохранённых доступов пока нет. Возьми логин и пароль из сообщения пользователя и вызови site_login / gmail_* / ssh_exec."
            return json.dumps(items, ensure_ascii=False)

        if name == "forget_access":
            try:
                connector_id = int(args.get("connector_id"))
            except (TypeError, ValueError):
                return "Нужен connector_id."
            if delete_connector(user_id, connector_id):
                return "Доступ забыт."
            return "Такой доступ не найден."

        from app.services.sandbox_client import TOOL_OPS, run_workspace_tool

        if name == "studio_build":
            return await _studio_build(user_id, args)

        if name in TOOL_OPS:
            return await run_workspace_tool(name, args, user_id)

        kind = None
        if name.startswith("gmail_"):
            kind = "gmail"
        elif name == "ssh_exec":
            kind = "ssh"
        elif name == "http_request":
            kind = "http"
        elif name in ("connector_browse", "site_login"):
            kind = "web"

        if kind:
            payload, error = chat_access.resolve(user_id, kind, args)
            if error:
                return error
            assert payload is not None
            if name == "gmail_list":
                return await asyncio.to_thread(
                    _gmail_list_sync,
                    payload,
                    str(args.get("folder") or "INBOX"),
                    args.get("limit") or 10,
                    str(args.get("query") or "UNSEEN"),
                )
            if name == "gmail_read":
                return await asyncio.to_thread(_gmail_read_sync, payload, str(args.get("uid") or ""))
            if name == "gmail_send":
                return await asyncio.to_thread(
                    _gmail_send_sync,
                    payload,
                    str(args.get("to") or ""),
                    str(args.get("subject") or ""),
                    str(args.get("body") or ""),
                )
            if name == "ssh_exec":
                return await asyncio.to_thread(_ssh_exec_sync, payload, str(args.get("command") or ""))
            if name == "http_request":
                return await _http_request(
                    payload,
                    str(args.get("method") or "GET"),
                    str(args.get("path") or "/"),
                    args.get("json_body"),
                )
            url = str(args.get("url") or "").strip()
            if not url:
                return "Нужен url."
            return await _connector_browse(payload, url)

        return f"Инструмент {name} не найден."
    except Exception as exc:
        logger.exception("Computer tool %s failed", name)
        return f"Ошибка инструмента {name}: {str(exc)[:300]}"
