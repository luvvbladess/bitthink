"""
Модуль оркестрации режима Computer.
Модель-оркестратор раундами нанимает более дешёвые модели-сотрудников,
которые сами ходят на сайты и работают с доступами из чата
(Gmail, SSH/VPS, HTTP API). Пользователю уходит обычный ответ в чат,
как у любой другой модели — не отчёт.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

MODEL_POOL = [
    "gpt-5-nano",
    "gpt-6-luna",
    "deepseek-v4-pro",
    "kimi-k2.6",
    "gpt-6-sol",
    "gpt-6-astra",
]
# The orchestrator (round planning: who to hire, how to split the task, when
# to stop) drives every decision Pilot makes, so a weak model here made the
# whole mode look "dumb" and inconsistent even when employees did fine work.
# Sol is the planning default; _clamped_planner_model() falls back to Luna
# on tiers without Sol. Ordinary single-hop synthesis stays on Luna.
# Astra is hire-only, never the composer: one hop, and only when a contract/audit
# brief is heavy enough that Sol would not pay for itself.
PLANNER_MODEL = "gpt-6-sol"
DIRECT_ANSWER_MODEL = "gpt-6-luna"
ECONOMY_COMPOSER_MODEL = "gpt-6-luna"
QUALITY_COMPOSER_MODEL = "gpt-6-sol"
FALLBACK_EMPLOYEE_MODEL = "gpt-6-luna"
ASTRA_HIRE_MARKERS = ("юрид", "договор", "контракт", "архитектур", "аудит", "расслед")


def _employee_models(user_id: int) -> list[str]:
    try:
        from conversations import conversation_manager
        from app.billing.plans import computer_models

        return computer_models(conversation_manager.get_subscription(user_id).get("tier"))
    except Exception:
        return list(MODEL_POOL)


def _clamped_planner_model(user_id: int) -> str:
    """Оркестратор целится в Sol, но не должен выдавать модель дороже тарифа
    пользователя — как и composer, откатываемся на Luna, если Sol недоступен."""
    try:
        from conversations import conversation_manager
        from app.billing.plans import clamp_model

        return clamp_model(conversation_manager.get_subscription(user_id).get("tier"), PLANNER_MODEL)
    except Exception:
        return PLANNER_MODEL


def _task_warrants_astra(task: str, document_context: str = "") -> bool:
    """Astra costs about 5× Sol. Only a dense contract/audit brief is worth that."""
    blob = f"{task or ''}\n{document_context or ''}".lower()
    if not any(marker in blob for marker in ASTRA_HIRE_MARKERS):
        return False
    return len((document_context or "").strip()) >= 400 or len(task or "") >= 800


# Комплект документов: «подготовь комплект», «18 документов», «пакет
# документов», «переработай документы». Такой заказ — это много файлов, и
# сотруднику с шестью ходами инструментов хватало ровно на один .docx.
_DOC_PACKAGE_RE = re.compile(
    r"(?i)(?:комплект\w*\s+(?:документ|документац|файл)"
    r"|(?:пакет|набор|перечень|реестр)\w*\s+документ"
    r"|\b\d{1,3}\s+(?:документ|файл)\w*"
    r"|недостающ\w*\s+документ"
    r"|переработ\w*\s+(?:\w+\s+){0,2}документ"
    r"|komplekt/)"
)
# Хватает на: скил, чтение исходников, 3-5 файлов, сборку и проверку.
PACKAGE_EMPLOYEE_TOOL_LOOPS = 16


def _is_document_package_task(text: str) -> bool:
    return bool(_DOC_PACKAGE_RE.search(text or ""))


# «Сделай аннотационный отчёт», «оформи в Word», «собери таблицу в xlsx».
# Одного .docx сотруднику с шестью ходами тоже не хватало: скил, чтение
# исходников, запись текста – и ходы кончались до сборки файла.
_FILE_REQUEST_RE = re.compile(
    r"(?i)(?:сдела|созда|подготов|собер|собра|сформир|оформ|выпуст|сгенерир|состав|разработ|напиш)\w*"
    r"\s+(?:\S+\s+){0,3}?(?:отч[её]т|документ|файл|таблиц|презентац|справк|аннотац|docx|word|ворд|xlsx|pptx|pdf)"
    r"|(?:\bв|\bво|формат\w*)\s+(?:word|ворд\w*|docx|xlsx|excel|эксел\w*|pdf|pptx)\b"
)


def _wants_file(text: str) -> bool:
    return bool(_FILE_REQUEST_RE.search(text or ""))


async def _new_file_names(user_id: int, since: float) -> List[str] | None:
    """Файлы, которые песочница отдаст в чат за этот ход. None – проверить не вышло."""
    try:
        from app.services.sandbox_client import collect_workspace_files

        files = await collect_workspace_files(int(user_id), since)
    except Exception:
        logger.debug("Director: deliverables check failed", exc_info=True)
        return None
    return [str(item.get("filename") or item.get("name") or "") for item in files]


def _file_builder_employee(user_text: str) -> Dict[str, str]:
    return {
        "role": "Сборка файла",
        "task": (
            "load_skill documents. Пользователь просил файл, но в песочнице его пока нет. "
            f"Запрос: «{(user_text or '')[:600]}». "
            "Возьми текст и данные из результатов коллег и из песочницы (workspace_glob), допиши недостающее, "
            "собери файл: .docx через bt_docx, либо .xlsx/.pdf/.pptx, если просили этот формат. "
            "В конце workspace_glob: файл должен лежать. Не пиши, что нет доступа к созданию DOCX."
        ),
        "model": FALLBACK_EMPLOYEE_MODEL,
    }


def _astra_fallback(allowed: list[str]) -> str:
    for model in ("gpt-6-sol", FALLBACK_EMPLOYEE_MODEL):
        if model in allowed:
            return model
    return allowed[0] if allowed else FALLBACK_EMPLOYEE_MODEL


def _clamp_employee_plan(
    plan: Dict[str, Any],
    user_id: int,
    original_task: str = "",
    document_context: str = "",
    journal: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    allowed = _employee_models(user_id)
    allow_astra = "gpt-6-astra" in allowed and _task_warrants_astra(original_task, document_context)
    already = any(entry.get("model") == "gpt-6-astra" for entry in (journal or []))
    employees = []
    astra_used = already
    for item in plan.get("new_employees") or []:
        model = item.get("model")
        if model == "gpt-6-astra" and (not allow_astra or astra_used):
            model = _astra_fallback(allowed)
        elif model not in allowed:
            model = FALLBACK_EMPLOYEE_MODEL if FALLBACK_EMPLOYEE_MODEL in allowed else (allowed[0] if allowed else FALLBACK_EMPLOYEE_MODEL)
        if model == "gpt-6-astra":
            astra_used = True
        employees.append({**item, "model": model})
    return {**plan, "new_employees": employees}


MAX_ROUNDS = 5
MAX_EMPLOYEES = 12
MAX_PARALLEL_PER_ROUND = 4
MAX_RESULT_CHARS_IN_PROMPT = 3000

STATUS_ICONS = {"pending": "⏳", "ok": "✅", "error": "❌"}

# Единые правила оформления для всех ответов Дирижёра (из SYSTEM_PROMPT)
_OUTPUT_RULES = (
    "Важно: не используй длинное тире «—», только среднее «–»; "
    "не используй HTML-теги и LaTeX (\\textbf{}, \\textit{}, \\texttt{}); "
    "формулы – обычный текст с Unicode: ×, ÷, ±, √, ², ³, ≈, ≤, ≥ (пример: S = a × b), "
    "запрещена LaTeX-нотация формул (доллары, скобки после обратного слэша вроде \\[ \\] или \\( \\), "
    "\\frac{}{}, \\cdot, \\text{} и другие команды с обратным слэшем); "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО оборачивать что-либо в угловые скобки << >> или использовать их как плейсхолдер — "
    "такая запись ломается в документе. Если значение неизвестно — напиши об этом словами."
)

_RU_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _preference_context(user_id: int) -> str:
    """Память и правило «как отвечать» — то же самое, что подмешивается в обычный чат
    через get_messages_for_api. Раньше планировщик, сотрудники и сборщик ответа
    в режиме Пилот собирали свои промпты с нуля и никогда не видели ни память
    пользователя, ни его активный кастомный промпт — отсюда жалобы, что Пилот
    «не помнит», «не слушается» и отвечает мимо инструкции, даже когда сотрудники
    честно нашли нужные данные."""
    parts: List[str] = []
    try:
        from conversations import conversation_manager
        from app.memory import memory_system_message

        mem_msg = memory_system_message(conversation_manager.get_user_memory(int(user_id)))
        if mem_msg:
            parts.append(mem_msg["content"])
    except Exception:
        pass
    try:
        from conversations import conversation_manager

        active_prompt = conversation_manager.get_active_custom_prompt(int(user_id))
        if active_prompt:
            parts.append(
                "Правило человека для всех ответов в этом чате (обязательно к исполнению, "
                "важнее твоих привычек форматирования):\n" + active_prompt
            )
    except Exception:
        pass
    return "\n\n".join(parts)


def _current_date_note() -> str:
    """Модели считают "сегодня" датой окончания своего обучения, если не сказать иначе -
    без этого они принимают реальные текущие даты за футуристичные и им не доверяют."""
    now = datetime.now()
    return (
        f"Актуальная дата на момент выполнения задачи: {now.day} {_RU_MONTHS_GENITIVE[now.month - 1]} "
        f"{now.year} года ({now.strftime('%d.%m.%Y')}). Это и есть реальное «сегодня» - "
        "не считай даты 2025-2026 годов и позже футуристичными, аномальными или подозрительными."
    )


# Только слова про сам снимок. «найд», «что на», «где в» ловили «найди ошибку»,
# «что нам делать», «где в договоре» – и Пилот искал по фото вместо работы.
PHOTO_RESEARCH_MARKERS = (
    "фото", "фотк", "снимк", "снимок", "картин", "изображ", "скрин", "где сня",
    "локац", "ориентир", "сделано данное", "это место", "за место",
)
_RESEARCH_MARKERS = PHOTO_RESEARCH_MARKERS + (
    "где ", "кто ", "когда", "актуаль", "сейчас", "на данный",
    "сравни", "обзор", "проверь", "источник", "рейтинг", "мета",
    "новост", "цен", "стоим", "адрес",
)
_SMALLTALK_RE = re.compile(
    r"^(?:привет|здравствуй(?:те)?|добр(?:ый|ое)\s+(?:день|утро|вечер)|хай|ку|йоу|"
    r"спасибо|благодарю|пока|ок|окей|понял[ао]?|ясно)(?:\s*[!?.]*)*$",
    re.I,
)


def is_smalltalk(user_text: str) -> bool:
    text = " ".join((user_text or "").strip().lower().split())
    if not text or len(text) > 48:
        return False
    return bool(_SMALLTALK_RE.match(text))


def wants_photo_research(user_text: str, has_images: bool) -> bool:
    if not has_images:
        return False
    text = (user_text or "").lower()
    return any(marker in text for marker in PHOTO_RESEARCH_MARKERS)


def needs_research(user_text: str, has_images: bool) -> bool:
    if has_images:
        return True
    if is_smalltalk(user_text):
        return False
    text = (user_text or "").lower()
    return any(marker in text for marker in _RESEARCH_MARKERS)


def packed_has_images(messages: List[Dict[str, Any]] | None) -> bool:
    for message in messages or []:
        attachment = {}
        content = None
        if isinstance(message, dict):
            attachment = message.get("attachment") or {}
            content = message.get("content")
        else:
            attachment = getattr(message, "attachment", None) or {}
            content = getattr(message, "content", None)
        kind = str(attachment.get("type") or "")
        mime = str(attachment.get("mime_type") or "")
        if kind == "image" or mime.startswith("image/"):
            return True
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}:
                    return True
    return False


def _hires_image_search(employees: List[Dict[str, Any]]) -> bool:
    for item in employees or []:
        blob = f"{item.get('role', '')} {item.get('task', '')}".lower()
        if "image_search" in blob or "поиск по фото" in blob:
            return True
    return False


def _photo_search_employee() -> Dict[str, str]:
    return {
        "role": "Поиск по фото",
        "task": (
            "load_skill images. Вызови image_search по фото из этого чата "
            "(filename из list_chat_files, если имя неясно – без filename, возьмётся последнее). "
            "Затем browse_page по 2-4 лучшим совпадениям. Не угадывай место по памяти. "
            "В ответе: место или источник, какие страницы это подтверждают, и где сомнение."
        ),
        "model": "gpt-6-luna",
    }


def _web_research_employees(user_text: str) -> List[Dict[str, str]]:
    return [{
        "role": "Исследование",
        "task": (
            "load_skill research. Разбей вопрос на узкие поисковые запросы. "
            "Собери источники, затем открой лучшие URL через browse_page. "
            "Не пиши итог из памяти модели.\n"
            f"Запрос: {(user_text or '')[:1500]}"
        ),
        "model": "kimi-k2.6",
    }]


def _verify_employee(user_text: str) -> Dict[str, str]:
    return {
        "role": "Сверка",
        "task": (
            "load_skill verify. По заметкам коллег открой 2-4 конкретных URL через browse_page "
            "и подтверди или опровергни вывод. Не добавляй факты из памяти. "
            "Если был image_search – открой страницы из его выдачи.\n"
            f"Вопрос: {(user_text or '')[:1200]}"
        ),
        "model": "gpt-6-luna",
    }


def _ensure_research_plan(
    round_num: int,
    plan: Dict[str, Any],
    user_text: str,
    journal: List[Dict[str, Any]],
    has_images: bool,
) -> Dict[str, Any]:
    """Пилот – исследователь: первый раунд не бывает пустым, второй – сверка.

    has_images – вопрос про фото из чата (wants_photo_research), а не просто
    «в чате когда-то была картинка»: иначе любой запрос превращался в поиск по фото.
    """
    if plan.get("status") == "clarify" and plan.get("questions"):
        return plan
    employees = list(plan.get("new_employees") or [])
    if is_smalltalk(user_text) and not has_images:
        return plan
    if round_num == 1:
        if has_images:
            # Сотрудник по фото добавляется к команде планировщика, а не заменяет её.
            if not _hires_image_search(employees):
                employees = [_photo_search_employee(), *employees]
            return {"status": "continue", "new_employees": employees}
        if not employees and needs_research(user_text, False):
            return {"status": "continue", "new_employees": _web_research_employees(user_text)}
        if employees:
            return {"status": "continue", "new_employees": employees}
        return plan
    if round_num == 2 and needs_research(user_text, has_images) and journal:
        if not employees:
            return {"status": "continue", "new_employees": [_verify_employee(user_text)]}
    return plan


def _chat_image_names(user_id: int) -> List[str]:
    try:
        from conversations import conversation_manager

        return [item["name"] for item in conversation_manager.list_chat_image_files(int(user_id))]
    except Exception:
        return []


def _turn_has_images(user_id: int) -> bool:
    try:
        from conversations import conversation_manager
        from routing import current_turn_has_files

        conv = conversation_manager.conversation_for_turn(int(user_id))
        _, has_images = current_turn_has_files(conv.messages if conv else [])
        return bool(has_images)
    except Exception:
        return False


def _clean_json_response(text: str) -> str:
    """Очищает ответ модели от markdown-разметки кода, оставляя только сырой JSON"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\n', '', cleaned)
        cleaned = re.sub(r'\n```$', '', cleaned)
    return cleaned.strip()


def _clamp_result(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS_IN_PROMPT:
        return text
    return text[:MAX_RESULT_CHARS_IN_PROMPT] + "... [обрезано]"


def _parse_director_plan(response_text: str) -> Dict[str, Any]:
    """
    Разбирает JSON-ответ дирижёра в раунде. Никогда не бросает исключение:
    любая проблема с разбором трактуется как "задача завершена" — это
    безопасный дефолт, который просто отдаёт накопленное в обычный ответ.
    """
    try:
        cleaned = _clean_json_response(response_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if not match:
                raise
            data = json.loads(match.group(0))

        status = data.get("status")
        raw_employees = data.get("new_employees", [])

        valid_employees = []
        for e in raw_employees:
            if not isinstance(e, dict):
                continue
            role = e.get("role")
            task = e.get("task")
            if not role or not task:
                continue
            model = e.get("model")
            if model not in MODEL_POOL:
                model = FALLBACK_EMPLOYEE_MODEL
            valid_employees.append({"role": role, "task": task, "model": model})

        if status == "clarify":
            from clarify import normalize_questions

            questions = normalize_questions(data.get("questions"))
            if questions:
                return {"status": "clarify", "new_employees": [], "questions": questions}
            status = "done"

        if status not in ("continue", "done"):
            status = "continue" if valid_employees else "done"
        if status == "continue" and not valid_employees:
            status = "done"

        return {"status": status, "new_employees": valid_employees}
    except Exception as e:
        logger.error(f"Director plan parsing failed: {e}. Treating as done.")
        return {"status": "done", "new_employees": []}


def _enforce_caps(round_num: int, total_employees_so_far: int, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Жёстко ограничивает раунды и суммарное число сотрудников, независимо от того, что попросил дирижёр."""
    if plan.get("status") == "clarify":
        if round_num > 1 or total_employees_so_far:
            return {"status": "done", "new_employees": []}
        questions = plan.get("questions") or []
        if not questions:
            return {"status": "done", "new_employees": []}
        return {"status": "clarify", "new_employees": [], "questions": questions}
    if round_num > MAX_ROUNDS:
        return {"status": "done", "new_employees": []}

    remaining = MAX_EMPLOYEES - total_employees_so_far
    if remaining <= 0:
        return {"status": "done", "new_employees": []}

    employees = plan["new_employees"]
    cap = min(remaining, MAX_PARALLEL_PER_ROUND)
    if len(employees) > cap:
        employees = employees[:cap]

    return {"status": plan["status"], "new_employees": employees}


def _escape_markdown(text: str) -> str:
    """Экранирует спецсимволы легаси-Markdown Telegram (_ * ` [), чтобы свободный
    текст роли от LLM не превращался в непреднамеренный курсив/форматирование."""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def _build_roster_text(journal_view: List[Dict[str, Any]]) -> str:
    """Рендерит накопительный чек-лист сотрудников по раундам для статусного сообщения."""
    rounds: Dict[int, List[Dict[str, Any]]] = {}
    for entry in journal_view:
        rounds.setdefault(entry["round"], []).append(entry)

    lines = ["**Пилот**:", ""]
    for round_num in sorted(rounds.keys()):
        lines.append(f"Раунд {round_num}:")
        for entry in rounds[round_num]:
            icon = STATUS_ICONS.get(entry["status"], "⏳")
            lines.append(f"{icon} {_escape_markdown(entry['role'])} — {entry['model']}")
        lines.append("")

    return "\n".join(lines).strip()


def _extract_document_context(messages: List[Dict[str, Any]]) -> str:
    """Достаёт системные сообщения с текстом прикреплённых пользователем документов -
    тот же приём, что уже использует hybrid_router.py для авто-режима. Без этого
    Дирижёр получает только голый текст задачи и не видит загруженные документы."""
    doc_parts = []
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content", "")
            if "документ для контекста" in content or "предоставил документ" in content:
                doc_parts.append(content)
    return "\n\n".join(doc_parts)


def _format_chat_history(messages: List[Dict[str, Any]]) -> str:
    """История для планировщика/сотрудников: ранние вопросы юзера + длинный хвост."""
    from model_context import format_chat_history_for_prompt

    return format_chat_history_for_prompt(messages)


async def _update_status(status_msg: Any, text: str) -> None:
    """Безопасно обновляет статус. Если живая лента привязана — шаг в ней, иначе старый edit."""
    try:
        from status_feed import is_bound, push_status
        if is_bound():
            await push_status("think", re.sub(r"\*\*(.+?)\*\*", r"\1", text))
            return
    except Exception:
        pass
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"Failed to edit director status message: {e}")


async def _execute_employee(
    employee: Dict[str, Any],
    round_num: int,
    journal: List[Dict[str, Any]],
    user_id: int,
    document_context: str = "",
    history_text: str = "",
    has_images: bool = False,
) -> Dict[str, Any]:
    """
    Выполняет задачу одного сотрудника указанной моделью. Контекст — задача
    сотрудника плюс история диалога, прикреплённые документы и результаты всех
    предыдущих раундов, чтобы новый сотрудник мог опираться на уже готовые данные.
    """
    role = employee["role"]
    task = employee["task"]
    model = employee["model"]
    try:
        from status_feed import push_status
        await push_status("think", (task or role)[:120])
    except Exception:
        pass

    context_lines = []
    for entry in journal:
        if entry["status"] == "ok":
            context_lines.append(f"### {entry['role']} (раунд {entry['round']})\n{_clamp_result(entry['result'])}")
    context_block = "\n\n".join(context_lines)

    from computer_tools import skills_prompt

    date_note = _current_date_note()
    history_block = f"\n\nИстория диалога:\n{history_text}" if history_text else ""
    doc_block = f"\n\nДокументы пользователя:\n{document_context}" if document_context else ""
    skills_block = f"\n\n{skills_prompt(user_id)}"
    preferences_block = _preference_context(user_id)
    prefs_note = f"\n\n{preferences_block}" if preferences_block else ""

    base_prompt = (
        f"{date_note}{history_block}{doc_block}{skills_block}{prefs_note}\n\n"
        f"Твоя роль: {role}.\nТвоя задача: {task}\n\n"
        "Ты сотрудник режима Computer. Делай только свою задачу. "
        "Если выше есть память или правило «как отвечать» – соблюдай язык, тон и формат "
        "буквально, это важнее твоих привычек. "
        "Коллеги в этом раунде работают параллельно и не ждут тебя: не дублируй их работу "
        "и не откладывай шаг, пока не появятся чужие результаты. "
        "Ответь по существу, без отчёта, оглавления и нумерации разделов. "
        "Не рассказывай вслух, какой инструмент выберешь. Сначала вызови его. "
        "Если нужно зайти на сайт – browse_page или site_login с логином из чата. "
        "Почта, VPS и API: данные из сообщения пользователя, не из настроек. "
        "Перед кодом, файлом, таблицей, презентацией, письмом или входом на сайт – первым вызовом load_skill с точным именем из каталога. "
        "Не грузи все скилы. Если скил уже вложен ниже – не вызывай load_skill повторно. Если ни один не подходит, работай без скила. "
        "Песочница с pip и Python – чтобы экономить токены: сам решай, запускать скрипт или нет, пользователя не спрашивай. "
        "Цифру или цитату из поиска не считай проверенной, пока не откроешь страницу browse_page. "
        "Если в чате есть фото и вопрос про место, источник или «что на снимке» – первым вызовом image_search. "
        "Не называй адрес или площадку только по виду кадра. После выдачи поисковиков открой 2-4 страницы browse_page. "
        "Не пиши готовый ответ из памяти до инструментов: сначала поиск или страница, потом вывод. "
        "Если текста документа нет в блоке выше, сначала list_chat_files, затем read_chat_document по точному имени. "
        "Не проси пользователя прислать файл снова: он уже в чате. "
        "Прошлые разговоры – search_chats или recent_chats, не интернет. Не проси открыть другой чат. "
        "Код только в workspace_* / pip_install / python_run. Сначала workspace_grep или workspace_glob, не читай все файлы. "
        "Если просят архив кода или проект-бота – запиши файлы и собери project.zip в песочнице. "
        "Схема процесса, блок-схема, swimlane – studio_build (infographic) или PNG шрифтом DejaVuSans. "
        "Запрещён PDF через reportlab/fpdf с Helvetica/WinAnsi: кириллица станет палками IIIII. "
        "Договор, ТЗ, смета, таблица, расчёт – это .docx/.xlsx/.pdf или текст в чате, НИКОГДА не .py скрипт. "
        "Расчёт, калькуляция, стоимость – пиши результат текстом прямо в сообщении или создай .xlsx таблицу. Не создавай .py файлы для простых вычислений. "
        "Файл из песочницы (xlsx, csv, docx, pdf, zip) пользователь скачает кнопкой в чате: не выдумывай ссылку. "
        "python-docx и bt_docx (markdown → .docx) уже стоят в песочнице: не пиши, что нет доступа к созданию "
        "или прикреплению DOCX. Если тебе поручено несколько документов – сделай каждый отдельным .docx, "
        "не останавливайся на первом, в конце проверь workspace_glob, что все файлы на месте. "
        "Пароли в ответ не пиши. "
        "Не проси пользователя скопировать страницу или выполнить команду за тебя. "
        "Не спрашивай пользователя и не давай нумерованный опросник: делай работу сам."
    )
    if context_block:
        prompt = f"{base_prompt}\n\nРезультаты коллег из предыдущих раундов:\n{context_block}"
    else:
        prompt = base_prompt
    try:
        from computer_skills.loader import preload_skills_block

        skill_block = preload_skills_block(
            f"{task}\n{history_text}",
            has_images=has_images or "image_search" in (task or "").lower() or "фото" in (task or "").lower(),
            user_id=user_id,
            sandbox=True,
        )
        if skill_block:
            prompt = f"{prompt}\n\n{skill_block}"
    except Exception:
        pass

    employee_messages = [
        {"role": "system", "content": _OUTPUT_RULES},
        {"role": "user", "content": prompt},
    ]
    if model != "kimi-k2.6":
        try:
            from conversations import conversation_manager

            parts = conversation_manager.vision_parts_for_chat(int(user_id), task)
            if parts:
                conversation_manager._attach_images_to_last_user(employee_messages, parts)
        except Exception:
            logger.debug("Director employee image attach skipped", exc_info=True)

    reasoning = ""
    search: List[Dict[str, str]] = []
    try:
        if model == "deepseek-v4-pro":
            from deepseek_client import get_deepseek_response
            answer, _, reasoning, search = await get_deepseek_response(employee_messages, model=model, user_id=user_id, use_tools=True)
        elif model == "kimi-k2.6":
            from kimi_client import get_kimi_search_brief
            answer = await get_kimi_search_brief(employee_messages, task, user_id=user_id)
            # Kimi builtin search hides raw sites, but we can at least surface the task and brief.
            search = [{"query": task, "summary": answer[:600]}] if answer else []
        else:
            from openai_client import get_chat_response
            builds_file = _is_document_package_task(task) or _wants_file(task) or "docx" in (task or "").lower()
            loops = PACKAGE_EMPLOYEE_TOOL_LOOPS if builds_file else None
            answer, _, reasoning, search = await get_chat_response(
                employee_messages, model=model, user_id=user_id, use_tools=True, max_tool_loops=loops,
            )

        return {
            "round": round_num, "role": role, "task": task, "model": model, "status": "ok", "result": answer,
            "reasoning": reasoning, "search": search,
        }
    except Exception as e:
        logger.error(f"Director employee '{role}' ({model}) failed: {e}")
        return {
            "round": round_num, "role": role, "task": task, "model": model, "status": "error",
            "result": f"[Ошибка при выполнении: {str(e)[:200]}]", "reasoning": "", "search": [],
        }


def _format_journal_for_prompt(journal: List[Dict[str, Any]]) -> str:
    if not journal:
        return "(пока никто не привлекался)"
    parts = []
    for entry in journal:
        status_label = "успешно" if entry["status"] == "ok" else "ошибка"
        parts.append(f"- Раунд {entry['round']}, {entry['role']} ({entry['model']}, {status_label}): {_clamp_result(entry['result'])}")
    return "\n".join(parts)


def _select_composer_model(
    original_task: str,
    journal: List[Dict[str, Any]],
    document_context: str = "",
) -> str:
    """Use Sol only when synthesis itself is genuinely demanding.

    Employee calls already do the specialist work. Repeating every result through
    Sol is the expensive Computer-mode path, especially across several planning
    rounds. Astra stays off the composer: wrap-up is not where its extra cost
    shows up.
    """
    ok_entries = [entry for entry in journal if entry.get("status") == "ok"]
    result_chars = sum(len(entry.get("result", "")) for entry in ok_entries)
    task = original_task.lower()
    hard_markers = (
        "архитектур", "аудит", "юрид", "договор", "безопасност",
        "миграц", "стратег", "расслед", "доказ", "противореч",
    )
    photo_task = any(marker in task for marker in ("фото", "где сня", "локац", "картин"))
    needs_quality = (
        bool(document_context)
        or len(original_task) > 1200
        or result_chars > 15000
        or len(ok_entries) >= 6
        or (photo_task and len(ok_entries) >= 2)
        or (len(original_task) > 400 and any(marker in task for marker in hard_markers))
    )
    return QUALITY_COMPOSER_MODEL if needs_quality else ECONOMY_COMPOSER_MODEL


def _pool_description(user_id: int, original_task: str = "", document_context: str = "") -> str:
    lines = [
        ("gpt-5-nano", "самая дешёвая, тривиальные микро-задачи и форматирование"),
        ("gpt-6-luna", "дешёвая, простой анализ, черновики, короткие ответы"),
        ("kimi-k2.6", "дешёвая, веб-поиск и актуальные факты"),
        ("deepseek-v4-pro", "средняя-выше, сложные рассуждения и код"),
        ("gpt-6-sol", "дорогая, сложный код и анализ, только если Luna заметно недостаточно"),
        (
            "gpt-6-astra",
            "самая дорогая. Не больше одного сотрудника, только разбор договора или аудита "
            "по тексту документа, когда Sol недостаточно. Не для поиска, почты и сайтов",
        ),
    ]
    allowed = set(_employee_models(user_id))
    if not _task_warrants_astra(original_task, document_context):
        allowed.discard("gpt-6-astra")
    return "\n".join(f"{mid} — {desc}" for mid, desc in lines if mid in allowed)


async def _plan_round(
    original_task: str,
    journal: List[Dict[str, Any]],
    user_id: int,
    document_context: str = "",
    history_text: str = "",
) -> Dict[str, Any]:
    """Один дешёвый вызов: решить, нанимать ли ещё сотрудников, и кого именно."""
    from openai_client import get_chat_response

    pool_description = _pool_description(user_id, original_task, document_context)

    from computer_tools import connector_summary_for_prompt, skills_prompt

    history_block = f"\n\nИстория диалога:\n{history_text}\n" if history_text else ""
    doc_block = f"\n\nДокументы пользователя:\n{document_context}\n" if document_context else ""
    connectors_block = connector_summary_for_prompt(user_id)
    skills_block = skills_prompt(user_id)
    preferences_block = _preference_context(user_id)
    image_names = _chat_image_names(user_id)
    image_block = ""
    if image_names:
        listed = ", ".join(image_names[-6:])
        image_block = (
            f"В этом чате есть фото: {listed}. "
            "Если вопрос про место, источник или содержимое кадра – найми gpt-6-luna с image_search. "
            "Не угадывай локацию по памяти и не ставь status=done до сверки страниц.\n"
        )

    prompt = (
        f"{_current_date_note()}\n\n"
        "Ты Computer: оркестратор, который выполняет задачу пользователя руками сотрудников. "
        "Сотрудники сами открывают сайты, входят по логину из чата, читают почту и ходят по SSH. "
        "Не проси пользователя открыть настройки или сделать это вручную. "
        "В задачи сотрудникам не копируй пароли: доступы уже в хранилище или в исходном сообщении.\n\n"
        f"Исходная задача пользователя:\n{original_task}\n"
        f"{history_block}"
        f"{doc_block}\n"
        f"{image_block}"
        f"{skills_block}\n\n"
        f"{connectors_block}\n\n"
        + (f"{preferences_block}\n\n" if preferences_block else "")
        + "Учитывай память и правило «как отвечать» выше при найме: если там задан язык, тон, "
        "формат (Word/таблица/кратко) или обращение – впиши это требование в task каждому "
        "сотруднику и в финальную сверку, а не только рассчитывай на сборщика ответа.\n\n"
        f"Доступные модели:\n{pool_description}\n\n"
        f"Уже сделано другими сотрудниками:\n{_format_journal_for_prompt(journal)}\n\n"
        "Как нанимать команду:\n"
        "- Все new_employees в одном JSON запускаются ОДНОВРЕМЕННО, параллельно.\n"
        "- Независимые части задачи (сравнить несколько объектов, обойти несколько сайтов, "
        "почта и сервер сразу, поиск плюс разбор документа) ОБЯЗАНЫ попасть в один раунд, "
        f"2-{MAX_PARALLEL_PER_ROUND} сотрудника. Не режь их по раундам.\n"
        "- Следующий раунд только для шагов, которым реально нужны результаты предыдущих.\n"
        "- Не нанимай одного универсального сотрудника на всю задачу, если её можно разрезать.\n"
        "- Пилот – исследователь, не чат из памяти. Раунд 1 без сотрудников запрещён, "
        "кроме приветствия. status=done только после того, как сотрудники уже собрали и сверили источники.\n"
        "- Запрещено закрывать задачу в раунде 1, если нужно найти факт, место, источник, цену или разобрать фото.\n"
        "- Если цель двусмысленная (неясно что строить, для кого, какой стек, какой результат) "
        "– верни status=clarify и 1-3 коротких вопроса с вариантами. Не пиши вопросы текстом, только JSON. "
        "Не спрашивай очевидное и не спрашивай пароли. Если пользователь уже ответил на уточнения, "
        "но развилка осталась (идея, тип, стек, хостинг, доступы) – снова status=clarify. "
        "Запрещено писать опросник обычным текстом: никаких «выберите вариант» и нумерованных анкет в ответе.\n"
        "- Не заказывай финальный отчёт, оглавление или нумерованные разделы.\n"
        "- Не проси разрешение искать или открыть сайт: найми сотрудника сразу.\n"
        "Экономь токены без потери результата: по умолчанию gpt-6-luna; "
        "для актуальных фактов и поиска - kimi-k2.6; для сложного кода и рассуждений - deepseek-v4-pro. "
        "gpt-6-sol только если Luna заметно недостаточно.\n"
        + (
            "gpt-6-astra - не больше одного сотрудника и только на разбор договора или аудита по документу; "
            "не нанимай её на поиск, почту, сайты и сборку ответа.\n"
            if "gpt-6-astra" in pool_description
            else ""
        ) +
        "Если нужны свежие данные с сайта - найми kimi-k2.6 для поиска или gpt-6-luna "
        "с задачей явно открыть URL через browse_page или войти через site_login. "
        "Если вопрос про фото (где снято, что на кадре, источник снимка) – в первом раунде "
        "обязательно gpt-6-luna с image_search по файлу из чата. kimi-k2.6 не умеет поиск по картинке: "
        "его нанимай во втором раунде, уже по подписям и URL из image_search. "
        "Не закрывай задачу после первого правдоподобного названия места: открой страницы-совпадения "
        "browse_page и сверь ориентиры на независимых сайтах. "
        "Не угадывай локацию по памяти модели. "
        "Для обзора, сравнения или «найди где» держи 2-4 сотрудника в первом раунде и второй раунд на сверку. "
        "В task сотруднику первой строкой укажи load_skill и точное имя из каталога скилов выше, "
        "если задача про код, файл, таблицу, презентацию, почту, сайт, фото или сверку факта. "
        "Не назначай скил, которого нет в каталоге. "
        "В task пиши, какой готовый вывод нужен: как применить, ограничение, что проверить. "
        "Не оставляй полуфабрикат, из-за которого пользователь спросит «а как именно».\n"
        "Если просят файл (отчёт, документ, Word, таблицу) – текст и сборку файла поручай одному сотруднику. "
        "Текст и «параметры оформления» без собранного файла – не результат: status=done только после workspace_glob с файлом.\n"
        "Если счёт, разбор файла или повторные вычисления дешевле скриптом – найми сотрудника с python_run/pip_install, не жуй сырьё токенами.\n"
        "Если просят комплект документов (переработать имеющиеся и разработать недостающие, «18 документов» и т. п.) – "
        "это много отдельных .docx, а не один файл и не только структура. Раунд 1: один сотрудник с load_skill documents "
        "читает задание, требования к оформлению, данные и каждый исходный документ и пишет реестр комплекта "
        "komplekt/00_Реестр.md (№, название, «переработать» + исходный файл или «разработать», что изменить). "
        "Если человек просил сначала предложения – после реестра status=done, ответ – реестр. "
        "Иначе следующие раунды: 2-4 сотрудника параллельно, каждому 3-5 документов из реестра по номерам; "
        "каждый пишет текст своих документов в komplekt/src/NN_Название.md и собирает их в .docx через bt_docx. "
        "Последний сотрудник запускает сборку всех src/*.md и сверяет workspace_glob komplekt/*.docx с реестром, "
        "дописывает пропущенные. status=done только когда число .docx равно числу строк реестра. "
        "В task каждому пиши номера и названия его документов и путь к реестру.\n"
        "Если просят схему, блок-схему, процессную карту или swimlane – найми сотрудника с load_skill infographic и studio_build. "
        "Не заказывай PDF reportlab/fpdf/Helvetica: подписи на русском превратятся в палки.\n"
        "Если в разделе 'Документы пользователя' выше только каталог без текста – "
        "найми сотрудника с list_chat_files или read_chat_document и точным именем файла. "
        "Не требуй повторно предоставить файл.\n"
        "Если спрашивают, о чём говорили раньше – найми сотрудника с search_chats или recent_chats, не с web_search.\n"
        f"{_OUTPUT_RULES}\n\n"
        "Верни СТРОГО JSON без markdown-обёрток в одном из трёх форматов:\n"
        '{"status": "done"}\n'
        "или\n"
        '{"status": "continue", "new_employees": ['
        '{"role": "Поиск A", "task": "...", "model": "kimi-k2.6"}, '
        '{"role": "Поиск B", "task": "...", "model": "gpt-6-luna"}]}\n'
        "или, если без ответа пользователя нельзя начать работу:\n"
        '{"status": "clarify", "questions": ['
        '{"prompt": "Какой тип приложения ты хочешь создать?", '
        '"options": ["Веб-приложение", "Telegram-бот", "Десктоп-приложение", "CLI / скрипт", "Другое"]}]}\n'
        "Поле model - строго один из id моделей выше. questions: 1-3 штуки, у каждого 2-6 коротких options."
    )

    messages = [
        {"role": "system", "content": "Ты Computer - оркестратор команды моделей. Отвечаешь только валидным JSON."},
        {"role": "user", "content": prompt},
    ]

    try:
        response_text, _, _, _ = await get_chat_response(
            messages,
            model=_clamped_planner_model(user_id),
            user_id=user_id,
            use_tools=False,
            reasoning_effort="none",
            use_skills=False,
        )
        return _clamp_employee_plan(
            _parse_director_plan(response_text),
            user_id,
            original_task,
            document_context,
            journal,
        )
    except Exception as e:
        logger.error(f"Director round planning failed: {e}. Treating as done.")
        return {"status": "done", "new_employees": []}


FILE_CHOICE_LABEL = "Файлы для пользователя"
_FILE_CHOICE_RE = re.compile(rf"(?im)^[\s*_>`-]*{FILE_CHOICE_LABEL}[\s*_`]*[:：]\s*(.*?)[\s*_`]*$")


def _split_file_choice(answer: str, candidates: List[str] | None) -> Tuple[str, List[str] | None]:
    """Вырезать строку «Файлы для пользователя: …» и вернуть выбранные имена из списка кандидатов.

    None – выбора нет или он не совпал ни с одним файлом: тогда уходит всё, как раньше.
    """
    matches = list(_FILE_CHOICE_RE.finditer(answer or ""))
    if not matches:
        return answer, None
    cleaned = _FILE_CHOICE_RE.sub("", answer).rstrip()
    known = {name.casefold(): name for name in (candidates or [])}
    chosen = []
    for raw in re.split(r"[;,\n]", matches[-1].group(1)):
        name = raw.strip(" \t«»\"'`*_")
        if name.casefold() in known and known[name.casefold()] not in chosen:
            chosen.append(known[name.casefold()])
    return cleaned, (chosen or None)


async def _compose_answer(
    original_task: str,
    journal: List[Dict[str, Any]],
    user_id: int,
    history_text: str = "",
    document_context: str = "",
    built_files: List[str] | None = None,
) -> Tuple[str, str]:
    """Свести заметки сотрудников в обычный ответ чата — без отчёта и нумерации разделов."""
    from openai_client import get_chat_response

    history_block = f"\n\nИстория диалога:\n{history_text}\n" if history_text else ""
    # Факт из песочницы, а не пересказ сотрудника: без него сборщик писал
    # «файл не выпущен», когда файл уже лежал и уходил кнопкой в чат.
    if built_files and len(built_files) > 1:
        # Сотрудники оставляют черновики и дубли; в чат уходит только то, что выберет сборщик.
        files_block = (
            "За этот ответ в песочнице появились файлы: " + "; ".join(built_files) + ".\n"
            "Реши, какие отдать пользователю: только итоговые версии того, что он просил. "
            "Без черновиков, дублей одного документа под разными именами, промежуточных и служебных файлов. "
            "Выбранные придут кнопками скачивания, не пиши, что они не созданы. "
            f"Последней строкой ответа напиши ровно: «{FILE_CHOICE_LABEL}: имя1; имя2» – точными именами из списка.\n\n"
        )
    elif built_files:
        files_block = (
            "Собраны и придут кнопкой скачивания в этом ответе: " + ", ".join(built_files) + ". "
            "Не пиши, что эти файлы не созданы.\n\n"
        )
    else:
        files_block = ""
    doc_block = f"\n\nДокументы пользователя:\n{document_context}\n" if document_context else ""
    preferences_block = _preference_context(user_id)
    prefs_block = f"{preferences_block}\n\n" if preferences_block else ""

    prompt = (
        f"{_current_date_note()}\n\n"
        f"{prefs_block}"
        "Ответь пользователю так, как ответила бы обычная модель в этом чате.\n"
        "Если выше есть память или правило «как отвечать» – выполни его буквально: язык, тон, "
        "обращение, формат вывода. Это важнее твоих привычек форматирования.\n"
        "Ниже – внутренние заметки сотрудников. Пользователь их не видит: не ссылайся на раунды, "
        "роли, «команду», «отчёт» и не делай оглавление.\n"
        "Пиши только то, что сотрудники нашли и открыли. Не дополняй место, дату, имя или цифру из памяти модели. "
        "Если сверки нет или источники расходятся – скажи об этом, не выдавай догадку как факт.\n"
        "Закрой очевидный следующий шаг в том же ответе, чтобы не пришлось спрашивать «а как именно».\n"
        "Не нумеруй разделы (1., 1.1., 2.). Не пиши «Краткий вывод», «Итоги работы», "
        "«Результаты Computer». Пиши прямо по вопросу.\n"
        "Длина и тон — как у нормального ответа ассистента: коротко, если вопрос простой; "
        "подробнее, только если это нужно по сути.\n"
        "Обычный разговор – проза. Списки и таблицы – только если без них хуже. Markdown можно, как в обычном чате.\n"
        "Не превращай ответ в анкету с вариантами. Не пиши «выберите 1/2/3». "
        "Не больше одного уточнения, и только если без него нельзя закончить.\n"
        "Ошибку сотрудников признай коротко и скажи, чего не хватает. Не выдумывай.\n"
        "Если сотрудники собрали xlsx/csv/docx/pdf в песочнице, не ставь markdown-ссылку «скачать». "
        "Напиши, что файл придёт кнопкой скачивания в чате. "
        "Если собран комплект документов – дай реестр: какие документы переработаны, какие разработаны заново, "
        "и чего не хватило в исходных данных. Больше восьми файлов придут одним архивом «Комплект документов.zip». "
        "Не пиши, что нет доступа к созданию DOCX, если сотрудники файлы собрали.\n\n"
        f"{history_block}"
        f"Вопрос пользователя:\n{original_task}\n\n"
        f"{files_block}"
        f"{doc_block}"
        f"Заметки сотрудников:\n{_format_journal_for_prompt(journal)}\n\n"
        "Убери повторы. Если каких-то данных нет из-за ошибки — скажи об этом коротко, не выдумывай."
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Ты тот же ассистент, что и в остальных режимах чата. "
                "Отвечаешь пользователю, а не пишешь документ.\n\n"
                f"{_OUTPUT_RULES}"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        composer_model = _select_composer_model(original_task, journal, document_context)
        try:
            from conversations import conversation_manager
            from app.billing.plans import clamp_model

            composer_model = clamp_model(conversation_manager.get_subscription(user_id).get("tier"), composer_model)
        except Exception:
            pass
        composer_effort = "medium" if composer_model == QUALITY_COMPOSER_MODEL and document_context else (
            "low" if composer_model == QUALITY_COMPOSER_MODEL else "none"
        )
        answer, _, reasoning, _ = await get_chat_response(
            messages,
            model=composer_model,
            user_id=user_id,
            use_tools=False,
            reasoning_effort=composer_effort,
            use_skills=False,
        )
        return answer, reasoning
    except Exception as e:
        logger.error(f"Director compose failed: {e}", exc_info=True)
        ok = [e for e in journal if e.get("status") == "ok" and e.get("result")]
        if len(ok) == 1:
            return ok[0]["result"], ""
        return "\n\n".join(e["result"] for e in ok) or "Не удалось собрать ответ.", ""


async def _answer_directly(
    messages: List[Dict[str, Any]],
    user_id: int,
) -> Tuple[str, str, List[Dict[str, str]]]:
    """Простой вопрос без сотрудников: обычный ответ с теми же инструментами."""
    from openai_client import get_chat_response

    system = (
        f"{_current_date_note()}\n"
        "Ты Computer в этом чате: отвечай как обычный ассистент. "
        "Если нужно зайти на сайт – browse_page или site_login с логином из чата. "
        "Почта, VPS и API берутся из сообщения, не из настроек. "
        "Файлы этого чата – list_chat_files и read_chat_document. Прошлые чаты – search_chats. "
        "Фото – image_search в Яндексе, Google и Bing, затем browse_page по совпадениям. Не угадывай место по виду кадра. "
        "Под задачу вызови load_skill по каталогу. Не пиши отчёт и не нумеруй разделы. "
        "Не задавай пользователю вопросы с вариантами и не пиши «выберите 1/2/3». "
        "Если без выбора нельзя начать, это должен был сделать оркестратор через status=clarify. "
        "Действуй по уже сказанному.\n"
        f"{_OUTPUT_RULES}"
    )
    chat = [{"role": "system", "content": system}, *messages]
    answer, _, reasoning, search = await get_chat_response(
        chat,
        model=DIRECT_ANSWER_MODEL,
        user_id=user_id,
        use_tools=True,
        reasoning_effort="low",
    )
    return answer, reasoning, search or []


def _sanitize_answer(text: str) -> str:
    from handlers.core import sanitize_response_text
    return sanitize_response_text(text)


async def get_director_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> "Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]":
    """Основная управляющая функция режима Computer."""
    from app.billing.quota import billing_pool

    token = billing_pool.set("computer")
    try:
        return await _run_director(messages, user_text, user_id, status_msg)
    finally:
        billing_pool.reset(token)


async def _run_director(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> "Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]":
    import asyncio
    import time

    started = time.time()
    wants_file = _wants_file(user_text)
    forced_build = False
    document_context = _extract_document_context(messages)
    history_text = _format_chat_history(messages)
    try:
        from app.services.chat_access import ingest_from_text

        ingest_from_text(user_id, user_text)
    except Exception:
        pass

    await _update_status(status_msg, "Исследую задачу")

    journal: List[Dict[str, Any]] = []
    round_num = 0
    has_images = wants_photo_research(user_text, packed_has_images(messages) or _turn_has_images(user_id))

    while round_num < MAX_ROUNDS and len(journal) < MAX_EMPLOYEES:
        round_num += 1
        plan = await _plan_round(user_text, journal, user_id, document_context, history_text)
        plan = _enforce_caps(round_num, len(journal), plan)
        plan = _ensure_research_plan(round_num, plan, user_text, journal, has_images)
        plan = _enforce_caps(round_num, len(journal), plan)

        if plan.get("status") == "clarify" and plan.get("questions"):
            from clarify import pack_search

            await _update_status(status_msg, "Уточняю задачу")
            questions = plan["questions"]
            return questions[0]["prompt"], [], "", pack_search(questions)

        if plan["status"] == "done" or not plan["new_employees"]:
            # Просили файл, а в песочнице пусто: планировщик закрывал задачу на
            # «текст и параметры оформления готовы». Один раз досылаем сборщика.
            if not wants_file or forced_build or len(journal) >= MAX_EMPLOYEES:
                break
            if await _new_file_names(user_id, started) != []:
                break
            forced_build = True
            plan = _clamp_employee_plan(
                {"status": "continue", "new_employees": [_file_builder_employee(user_text)]}, user_id
            )

        hired = plan["new_employees"]
        if len(hired) == 1:
            await _update_status(status_msg, f"Делаю: {hired[0]['role']}")
        else:
            roles = ", ".join(item["role"] for item in hired)
            await _update_status(status_msg, f"Запускаю {len(hired)} сотрудников параллельно: {roles}")

        jobs = [
            _execute_employee(e, round_num, journal, user_id, document_context, history_text, has_images)
            for e in hired
        ]
        results = await asyncio.gather(*jobs, return_exceptions=True)

        for employee, res in zip(plan["new_employees"], results):
            if isinstance(res, Exception):
                journal.append({
                    "round": round_num, "role": employee["role"], "task": employee["task"],
                    "model": employee["model"], "status": "error",
                    "result": f"[Ошибка при выполнении: {str(res)[:200]}]",
                })
            else:
                journal.append(res)

    if not journal:
        await _update_status(status_msg, "Пишу ответ")
        try:
            answer, reasoning, search = await _answer_directly(messages, user_id)
        except Exception as e:
            logger.error(f"Director direct answer failed: {e}", exc_info=True)
            answer, reasoning, search = f"Не удалось ответить: {str(e)[:200]}", "", []
        return _sanitize_answer(answer), [], reasoning, search

    await _update_status(status_msg, "Пишу ответ")
    # Всегда, а не только когда просили файл: сотрудник мог собрать его по ходу дела.
    built_files = await _new_file_names(user_id, started)
    answer, compose_reasoning = await _compose_answer(
        user_text, journal, user_id, history_text, document_context, built_files=built_files
    )
    if built_files and len(built_files) > 1:
        from turn_scope import choose_deliverables

        answer, chosen = _split_file_choice(answer, built_files)
        choose_deliverables(chosen)
    answer = _sanitize_answer(answer)

    reasoning_sections = [
        f"### {entry['role']} (раунд {entry['round']})\n{entry['reasoning']}"
        for entry in journal
        if entry.get("reasoning")
    ]
    if compose_reasoning:
        reasoning_sections.append(compose_reasoning)
    search_results = [s for entry in journal for s in entry.get("search", [])]

    return answer, [], "\n\n".join(reasoning_sections), search_results
