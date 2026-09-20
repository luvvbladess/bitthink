"""Live activity feed for the chat UI (Perplexity-style step list)."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Awaitable, Callable, List, Optional, Tuple
from urllib.parse import urlparse

Emit = Callable[[str], Awaitable[None]]

_emit: ContextVar[Optional[Emit]] = ContextVar("status_emit", default=None)
_steps: ContextVar[Optional[List[Tuple[str, str]]]] = ContextVar("status_steps", default=None)

MAX_STEPS = 20
MAX_DETAIL = 140


def bind_status(emit: Emit) -> None:
    _emit.set(emit)
    _steps.set([])


def is_bound() -> bool:
    return _emit.get() is not None and _steps.get() is not None


def host_from_url(url: str) -> str:
    try:
        host = (urlparse(url).netloc or url).strip()
    except Exception:
        host = (url or "").strip()
    if host.lower().startswith("www."):
        host = host[4:]
    return host[:80]


async def push_status(kind: str, detail: str) -> None:
    steps = _steps.get()
    emit = _emit.get()
    if steps is None or emit is None:
        return
    kind = (kind or "think").strip().lower()[:16]
    detail = " ".join((detail or "").split())[:MAX_DETAIL]
    if not detail:
        return
    # Generic search lifecycle pings collapse to one step. Distinct queries from
    # parallel Computer employees must still appear separately.
    generic_search = detail.lower() in {"ищу в интернете", "search"}
    if kind == "search" and generic_search and any(existing_kind == "search" for existing_kind, _ in steps):
        return
    if (kind, detail) in steps:
        return
    if steps and steps[-1] == (kind, detail):
        return
    steps.append((kind, detail))
    if len(steps) > MAX_STEPS:
        del steps[: len(steps) - MAX_STEPS]
    text = "\n".join(f"[{k}] {d}" for k, d in steps)
    await emit(text)


async def announce_tool(name: str, args: Optional[dict] = None) -> None:
    args = args or {}
    if name in ("web_search", "$web_search"):
        q = str(args.get("query") or args.get("q") or args.get("text_query") or "").strip()
        await push_status("search", q or "Ищу в интернете")
    elif name == "image_search":
        filename = str(args.get("filename") or "").strip()
        await push_status("search", f"Ищу фото {filename}" if filename else "Ищу фото в Яндексе и Google")
    elif name == "read_chat_document":
        filename = str(args.get("filename") or "").strip()
        await push_status("think", f"Читаю {filename}" if filename else "Читаю файл")
    elif name == "list_chat_files":
        await push_status("think", "Смотрю файлы чата")
    elif name == "search_chats":
        q = str(args.get("query") or "").strip()
        await push_status("think", f"Ищу в чатах: {q}" if q else "Ищу в прошлых чатах")
    elif name == "recent_chats":
        await push_status("think", "Смотрю недавние чаты")
    elif name in ("browse_page", "connector_browse", "site_login"):
        url = str(args.get("url") or args.get("login_url") or "").strip()
        await push_status("browse", host_from_url(url) or url or "страницу")
    elif name == "gmail_list":
        await push_status("mail", "Смотрю почту")
    elif name == "gmail_read":
        await push_status("mail", "Читаю письмо")
    elif name == "gmail_send":
        to = str(args.get("to") or "").strip()
        await push_status("mail", f"Отправляю письмо{(' на ' + to) if to else ''}")
    elif name == "ssh_exec":
        cmd = str(args.get("command") or "").strip()[:70]
        await push_status("ssh", cmd or "Команда на сервере")
    elif name == "http_request":
        method = str(args.get("method") or "GET").upper()
        path = str(args.get("path") or "/")
        await push_status("api", f"{method} {path}")
    elif name == "list_connectors":
        await push_status("think", "Смотрю доступы")
    elif name == "list_skills":
        await push_status("think", "Смотрю скилы")
    elif name == "load_skill":
        skill = str(args.get("name") or "").strip()
        await push_status("think", f"Скил {skill}" if skill else "Загружаю скил")
    elif name == "save_skill":
        skill = str(args.get("name") or "").strip()
        await push_status("think", f"Сохраняю скил {skill}" if skill else "Сохраняю скил")
    elif name == "delete_skill":
        skill = str(args.get("name") or "").strip()
        await push_status("think", f"Удаляю скил {skill}" if skill else "Удаляю скил")
    elif name == "forget_access":
        await push_status("think", "Забываю доступ")
    elif name == "workspace_ls":
        await push_status("think", "Смотрю файлы в песочнице")
    elif name == "workspace_read":
        await push_status("think", str(args.get("path") or "файл")[:80])
    elif name == "workspace_write":
        await push_status("think", f"Пишу {str(args.get('path') or 'файл')[:60]}")
    elif name == "workspace_edit":
        await push_status("think", f"Правлю {str(args.get('path') or 'файл')[:60]}")
    elif name == "workspace_delete":
        await push_status("think", f"Удаляю {str(args.get('path') or 'файл')[:60]}")
    elif name == "workspace_grep":
        await push_status("think", f"Ищу в песочнице {str(args.get('pattern') or '')[:50]}".strip() or "Ищу в песочнице")
    elif name == "workspace_glob":
        await push_status("think", f"Файлы {str(args.get('pattern') or '')[:50]}".strip() or "Ищу файлы")
    elif name == "python_run":
        await push_status("think", f"Python {str(args.get('path') or '')[:50]}".strip() or "Запускаю скрипт")
    elif name == "pip_install":
        pkgs = args.get("packages") or []
        label = ", ".join(str(item) for item in pkgs[:4]) if isinstance(pkgs, list) else ""
        await push_status("think", f"pip {label}".strip() or "Ставлю пакеты")
    elif name == "visualize_data":
        await push_status("chart", str(args.get("title") or "Строю график"))
    else:
        await push_status("think", name)
