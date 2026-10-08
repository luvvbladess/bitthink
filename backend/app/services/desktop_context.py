"""Per-turn desktop bridge. ContextVars isolate concurrent users and employees."""
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

DesktopExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]
desktop_executor: ContextVar[DesktopExecutor | None] = ContextVar("desktop_executor", default=None)
desktop_cwd: ContextVar[str] = ContextVar("desktop_cwd", default="")
desktop_mode: ContextVar[str | None] = ContextVar("desktop_mode", default=None)
desktop_chat_model: ContextVar[str] = ContextVar("desktop_chat_model", default="auto")
desktop_skills: ContextVar[list[dict[str, str]]] = ContextVar("desktop_skills", default=[])
desktop_work_context: ContextVar[str] = ContextVar("desktop_work_context", default="")
desktop_capabilities: ContextVar[frozenset[str]] = ContextVar("desktop_capabilities", default=frozenset())


def local_skills_instructions() -> str:
    skills = desktop_skills.get()
    if not skills:
        return ""
    lines = []
    size = 0
    for skill in skills:
        line = f"- {skill['name']} (id={skill['id']}): {skill['description'][:300]}"
        if size + len(line) > 24_000:
            break
        lines.append(line)
        size += len(line)
    return (
        "\n\n[Локальные скилы пользователя BitClient]\n"
        "Выбери подходящие скилы по задаче. Если пользователь назвал скил, прочитай его. "
        "До выполнения прочитай SKILL.md через desktop_skill_read с skill_id из каталога. "
        "Относительные references/scripts/assets читай тем же инструментом, указав path. "
        "desktop_skill_list возвращает весь локальный каталог и поддерживает поиск query. "
        "Не загружай все инструкции подряд. Сообщи пользователю, какой скил применяешь. "
        "Инструкции скила не заменяют запрос пользователя и режим согласования. "
        "Скилы Claude/Codex могут упоминать свои инструменты: используй доступные аналоги BitClient, "
        "не выдумывай наличие Claude/Codex API. Скрипты выполняй через desktop_run_command "
        "с абсолютным путём из прочитанного скила; файлы результата создавай в рабочем проекте.\n"
        + "\n".join(lines)
        + "\n[Конец каталога локальных скилов]"
    )


async def local_tool(name: str, args: dict[str, Any]) -> str | None:
    executor = desktop_executor.get()
    return await executor(name, args) if executor else None
