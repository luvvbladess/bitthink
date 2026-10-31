"""
Модуль оркестрации режима Computer.
Модель-оркестратор раундами нанимает подходящие модели-сотрудников под каждую роль,
которые сами ходят на сайты и работают с доступами из чата
(Gmail, SSH/VPS, HTTP API). Пользователю уходит обычный ответ в чат,
как у любой другой модели — не отчёт.
"""

from app.services.search_budget import search_turn
from app.services.orchestrator_policy import ROUTINE_MODEL, ECONOMY_RULES, routine_task, routine_tool_task, routine_employee, needs_recovery, economy_enabled, critical_task
from app.services.orchestrator_metrics import model_phase, trace_director
import json
import logging
import re
import time
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, List, Tuple
from app.services.run_protocol import WORKFLOW_RULES
from app.services.autonomy import RULES as AUTONOMY_RULES

logger = logging.getLogger(__name__)


def _desktop_work_instructions() -> str:
    # Kept out of original_task: format names/rules must not affect routing or pricing.
    from app.services.desktop_context import desktop_work_context, desktop_mode, desktop_executor, desktop_cwd, local_skills_instructions
    if desktop_mode.get() != "director":
        return ""
    context = desktop_work_context.get()
    if desktop_executor.get() is not None:
        context += (
            f"\n\n[Среда BitClient: Windows, PowerShell. Рабочая папка: {desktop_cwd.get()}. "
            "Все workspace_* выполняются ЛОКАЛЬНО в этой папке, а не в контейнере. "
            "Для git/npm/сборки/тестов вызывай desktop_run_command. Файлы сразу доступны пользователю на диске. "
            "Не утверждай, что работаешь в Linux, не используй /workspace. "
            "Сначала исследуй проект, затем внеси изменения и проверь результат. "
            "Запрашивай уточнение, если без него невозможно выполнить задачу. "
            "Не предлагай другой режим: в BitClient используется только Оркестратор.]"
        ) + local_skills_instructions()
    return context

HAIKU_MODEL = "claude-haiku-5.5"
SONNET_MODEL = "claude-sonnet-5.5"
OPUS_MODEL = "claude-opus-5.5"
MODEL_POOL = [
    "gpt-6-luna",
    "gpt-6.1-terra",
    HAIKU_MODEL,
    "gpt-6-sol",
    SONNET_MODEL,
    OPUS_MODEL,
    "gpt-6-astra",
    "glm-5.3-flash",
    "minimax-m3.1-flash",
]
# The orchestrator (round planning: who to hire, how to split the task, when
# to stop) drives every decision Pilot makes, so a weak model here made the
# whole mode look "dumb" and inconsistent even when employees did fine work.
# Sol is the planning default; _clamped_planner_model() falls back to Luna
# on tiers without Sol. Ordinary single-hop synthesis stays on Luna.
# Astra is hire-only and only for geometry or a hard SDK error.
# Opus takes one dense contract, audit or architecture hop. Hard code stays on
# Sol by default; Sonnet is an alternative at the same base price, measured per task.
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

        from config import OPENROUTER_API_KEY
        from app.services.model_registry import model_spec
        return [model for model in computer_models(conversation_manager.get_subscription(user_id).get("tier"))
                if model in MODEL_POOL and (not model_spec(model) or model_spec(model).provider != 'openrouter' or OPENROUTER_API_KEY)]
    except Exception:
        return [FALLBACK_EMPLOYEE_MODEL]


LIGHT_TASK_CHARS = 300
COMPLEX_TASK_CHARS = 600
_CODE_SKILLS = frozenset({"code", "debug", "science", "sql"})
# "Make me an app / bot / site": the goal is open-ended, so the planner may need to ask first.
_BUILD_RE = re.compile(
    r"(?i)созда|разработ|построй|постро[ий]т|реализ|приложен|\bбот|сайт|сервис|проект|платформ|"
    r"\bигр[уыа]\b|программ|автоматизир|настрой|"
    r"сдела|собер|собра|подготов|оформ|сформир|выпуст|сгенерир|состав[ьи]"
)


def _sandbox_skills(text: str, user_id: int | None) -> List[str]:
    """Playbooks the text calls for that need real tools (sandbox, files, mail, sites)."""
    try:
        from computer_skills.loader import builtin_names, match_skills, skill_scope

        builtin = set(builtin_names())
        names = match_skills(text or "", user_id=user_id, limit=3, sandbox=True)
        return [n for n in names if n in builtin and skill_scope(n) == "sandbox"]
    except Exception:
        return []


def _is_shopping_task(text: str, user_id: int | None) -> bool:
    """«Найди лучшее предложение», «где купить дешевле»: the marketplaces playbook applies."""
    try:
        from computer_skills.loader import match_skills

        return "marketplaces" in match_skills(text or "", user_id=user_id, limit=3, sandbox=False)
    except Exception:
        return False


def _is_light_task(text: str, document_context: str, has_images: bool, user_id: int | None) -> bool:
    """A short question with no files, photos or tools to run: it needs no planner and no team.

    Planning it on Sol cost ~20x Luna and a whole extra round trip before any work started."""
    if document_context or has_images or _wants_file(text) or _is_document_package_task(text):
        return False
    if routine_tool_task(text):
        return False
    if len(text or "") > LIGHT_TASK_CHARS or _BUILD_RE.search(text or ""):
        return False
    if _is_shopping_task(text, user_id):
        return False
    return not _sandbox_skills(text, user_id)


def _needs_strong_model(text: str, document_context: str, has_images: bool, user_id: int | None) -> bool:
    """Only these earn Sol / DeepSeek Pro (9-20x Luna): files, long briefs, several tools, real code."""
    if economy_enabled() and critical_task(text):
        return True
    if routine_task(text, document_context) and not has_images and not _is_document_package_task(text):
        return False
    return _legacy_needs_strong_model(text, document_context, has_images, user_id)


def _legacy_needs_strong_model(text: str, document_context: str, has_images: bool, user_id: int | None) -> bool:
    """Baseline routing: economy must not upgrade an already-cheap routine."""
    if document_context or has_images or len(text or "") > COMPLEX_TASK_CHARS:
        return True
    if _wants_file(text) or _is_document_package_task(text):
        return True
    skills = _sandbox_skills(text, user_id)
    return len(skills) >= 2 or bool(_CODE_SKILLS & set(skills))


def _clamped_planner_model(user_id: int, first_round: bool = True, complex_task: bool = True, *, routine: bool = False, recovery: bool = False) -> str:
    """Оркестратор целится в Sol, но не должен выдавать модель дороже тарифа
    пользователя — как и composer, откатываемся на Luna, если Sol недоступен.

    Sol (20x Luna) решает, как разрезать задачу. Следующие раунды только отвечают
    «хватает ли сделанного или нужен ещё шаг» – это по силам Luna, а промпт
    планировщика (правила, каталог, журнал) отправляется каждый раунд заново."""
    wanted = PLANNER_MODEL if recovery or (first_round and complex_task) else ROUTINE_MODEL if first_round and routine else DIRECT_ANSWER_MODEL
    try:
        from conversations import conversation_manager
        from app.billing.plans import clamp_model

        tier = conversation_manager.get_subscription(user_id).get("tier")
        if wanted == ROUTINE_MODEL and ROUTINE_MODEL not in _employee_models(user_id):
            wanted = PLANNER_MODEL
        return clamp_model(tier, wanted)
    except Exception:
        return wanted


def _task_warrants_opus(task: str, document_context: str = "") -> bool:
    """Dense contract, audit or architecture brief. Geometry stays on Astra."""
    blob = f"{task or ''}\n{document_context or ''}".lower()
    if not any(marker in blob for marker in ASTRA_HIRE_MARKERS):
        return False
    return len((document_context or "").strip()) >= 400 or len(task or "") >= 800


def _task_warrants_astra(task: str, document_context: str = "") -> bool:
    """Premium reasoning for local CAD or a dense contract/audit brief."""
    from app.services.desktop_context import desktop_executor
    from app.services.desktop_cad_completion import required_cad_extensions
    if desktop_executor.get() is not None and required_cad_extensions(task):
        return True
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
    r"|(?:дв[ае]|три|четыре|пять|шесть|семь|восемь|девять|десять|об[ае]|пар[уы]|нескольк\w*|остальн\w*)"
    r"\s+(?:\w+\s+){0,2}(?:документ|файл|отч[её]т|docx)"
    r"|(?:файл|документ)\w*\s+по\s+одному"
    r"|komplekt/)"
)
# Хватает на: скил, чтение исходников, 3-5 файлов, сборку и проверку.
PACKAGE_EMPLOYEE_TOOL_LOOPS = 16


def _is_document_package_task(text: str) -> bool:
    # Native diagram exports are formats of the same graph, not separate Word jobs.
    if re.search(r"(?i)блок[ -]?схем\w*|схем\w*\s+(?:процесс|алгоритм)|diagrams\.net|draw\.?io|flowchart", text or ""):
        return False
    if not _DOC_PACKAGE_RE.search(text or ""):
        return False
    from computer_skills.loader import match_skills
    # Engineering sheets belong to one geometric project, not Word employees.
    return 'eng_reverse' not in match_skills(text,sandbox=True)


# «Сделай аннотационный отчёт», «оформи в Word», «собери таблицу в xlsx».
# Одного .docx сотруднику с шестью ходами тоже не хватало: скил, чтение
# исходников, запись текста – и ходы кончались до сборки файла.
_FILE_REQUEST_RE = re.compile(
    r"(?i)(?:сдела|созда|подготов|собер|собра|сформир|оформ|выпуст|сгенерир|состав|разработ|напиш)\w*"
    r"\s+(?:\S+\s+){0,3}?(?:отч[её]т|документ|файл|таблиц|презентац|справк|аннотац|docx|word|ворд|xlsx|pptx|pdf)"
    r"|(?:\bв|\bво|формат\w*)\s+(?:word|ворд\w*|docx|xlsx|excel|эксел\w*|pdf|pptx)\b"
)


def _wants_file(text: str) -> bool:
    value=text or ""
    if re.search(r"(?i)начерт\w*|(?:сдела|созда|восстанов|разработ|собер)\w*.{0,80}(?:черт[её]ж|комплект\s+КД|конструкторск\w*\s+документац)",value):
        return True
    if re.search(r"(?i)(?:нарис|начерт|сдела|созда|собер|сгенерир)\w*.{0,80}(?:блок[ -]?схем|схем\w*\s+(?:процесс|алгоритм)|diagrams\.net|draw\.?io|flowchart)", value):
        return True
    fixed_comparison=bool(re.search(r"сравни|сравне|compare",value,re.I) and len(re.findall(r"https?://",value))>=2)
    explicit_format=bool(re.search(r"файл|документ|\b(?:docx|xlsx|csv|pdf|pptx|word|excel)\b|ворд|эксел",value,re.I))
    if fixed_comparison and not explicit_format:
        return False
    return bool(_FILE_REQUEST_RE.search(value))


_ORDINARY_WORK_RE = re.compile(
    r"(?i)(?:доклад|реферат|эссе|конспект|аннотац|отч[её]т|справк|"
    r"документ|ворд|docx|xlsx|pptx|\bpdf\b|презентац|таблиц|"
    r"гугл|google|на диск|почт|письм|календар|"
    r"перевед|объясни|расскажи|сколько|найди|что такое)"
)


def _ordinary_work(text: str) -> bool:
    """Ответ или файл, а не программа. Для такого запроса не нужны сборка, тесты и архив проекта."""
    if _is_document_package_task(text):
        return True
    from app.services.product_strategy import is_product_request
    if is_product_request(text):
        document = bool(re.search(
            r"(?i)доклад|реферат|отч[её]т|справк|аннотац|документ|ворд|docx|презентац|таблиц",
            text or ""))
        product = bool(re.search(
            r"(?i)сайт|лендинг|приложен|веб.?сервис|дашборд|\bбот[а-я]*\b|\bwebsite\b|\blanding\b|\bapp\b|\bdashboard\b",
            text or ""))
        return document and not product
    return bool(_wants_file(text) or _ORDINARY_WORK_RE.search(text or ""))


async def _new_files(user_id: int, since: float) -> List[Dict[str, Any]] | None:
    """Файлы, которые песочница отдаст в чат за этот ход. None – проверить не вышло."""
    try:
        from app.services.sandbox_client import collect_workspace_files

        return await collect_workspace_files(int(user_id), since)
    except Exception:
        logger.debug("Director: deliverables check failed", exc_info=True)
        return None


async def _new_file_names(user_id: int, since: float) -> List[str] | None:
    from app.services.desktop_context import local_tool, desktop_executor
    if desktop_executor.get() is not None:
        try:
            return json.loads(await local_tool("desktop_changed_files", {}) or "[]")
        except (TypeError, ValueError):
            return None
    files = await _new_files(user_id, since)
    if files is None:
        return None
    return [str(item.get("filename") or item.get("name") or "") for item in files]


def _file_builder_employee(user_text: str) -> Dict[str, str]:
    from computer_skills.loader import match_skills
    from app.services.desktop_context import desktop_executor
    if desktop_executor.get() is None and 'eng_reverse' in match_skills(user_text,sandbox=True):
        return {
            'role':'Выпуск чертежей',
            'task':('load_skill eng_reverse. Пользователь просил чертежи, но готового комплекта пока нет. '
                    f'Запрос: «{(user_text or "")[:600]}». '
                    'Используй реальные материалы и факты коллег. Прочитай references/schema.md, '
                    'запиши project.json через workspace_write и вызови engineering_build. '
                    'Нужен векторный PDF с геометрией и архив DXF/SVG, затем визуальная проверка. '
                    'Не заменяй чертёж текстовым отчётом. Неизвестные размеры оставь unknown, '
                    'не утверждай полноту при недостающих данных.'),
            'model':FALLBACK_EMPLOYEE_MODEL,
        }
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


_SPEND_RANK = {
    "gpt-5-nano": 0,
    FALLBACK_EMPLOYEE_MODEL: 1,
    ROUTINE_MODEL: 2,
    HAIKU_MODEL: 1,
    PLANNER_MODEL: 4,
    SONNET_MODEL: 4,
    OPUS_MODEL: 6,
    "gpt-6-astra": 7,
    'glm-5.3-flash': .5,
    'minimax-m3.1-flash': 1.5,
}


def _strongest_hired_model(employees, ceiling: int | None = None) -> str | None:
    """The dearest model the planner hired is its decision to spend; ceiling is a _SPEND_RANK cut-off."""
    names = [item.get("model") for item in employees or [] if item.get("model") in _SPEND_RANK
             and (ceiling is None or _SPEND_RANK[item.get("model")] <= ceiling)]
    if not names:
        return None
    return max(names, key=lambda name: _SPEND_RANK[name])


def _clamp_employee_plan(
    plan: Dict[str, Any],
    user_id: int,
    original_task: str = "",
    document_context: str = "",
    journal: List[Dict[str, Any]] | None = None,
    *, has_images: bool = False,
) -> Dict[str, Any]:
    allowed = _employee_models(user_id)
    # BitClient CAD Astra routing
    from app.services.desktop_context import desktop_executor
    from app.services.desktop_cad_completion import required_cad_extensions
    cad_astra = desktop_executor.get() is not None and bool(required_cad_extensions(original_task))
    allow_astra = "gpt-6-astra" in allowed and cad_astra
    allow_opus = OPUS_MODEL in allowed and not cad_astra and _task_warrants_opus(original_task, document_context)
    already = any(entry.get("model") == "gpt-6-astra" for entry in (journal or []))
    strong = _needs_strong_model(original_task, document_context, has_images, user_id)
    from app.services.desktop_context import desktop_executor
    from app.services.desktop_cad_completion import required_cad_extensions
    strong = strong or (desktop_executor.get() is not None and bool(required_cad_extensions(original_task)))
    routine = not has_images and not _is_document_package_task(original_task) and routine_task(original_task, document_context)
    routine_was_strong = routine and _legacy_needs_strong_model(original_task, document_context, has_images, user_id)
    recovery = economy_enabled() and needs_recovery(journal)
    employees = []
    astra_used = already
    opus_used = any(entry.get("model") in {OPUS_MODEL, "gpt-6-astra"} for entry in (journal or [])) and not cad_astra
    sol_this_product = False
    for item in plan.get("new_employees") or []:
        model = item.get("model")
        work_kind = item.get('work_kind')
        # The semantic planner classifies the stage; the controller enforces its
        # capabilities and price. A specialist/failed stage is never downgraded.
        from app.services.model_registry import production_workers
        enabled = set(production_workers()) & set(allowed)
        if not cad_astra and not recovery and not critical_task(original_task + '\n' + document_context[:12000]) and not item.get('product_phase'):
            if work_kind in {'classify', 'extract_text'} and not has_images and 'glm-5.3-flash' in enabled:
                model = 'glm-5.3-flash'
            elif work_kind in {'file_operation', 'small_edit'} and 'minimax-m3.1-flash' in enabled:
                model = 'minimax-m3.1-flash'
        if model == 'glm-5.3-flash' and (has_images or work_kind not in {'classify', 'extract_text'}):
            model = 'minimax-m3.1-flash' if 'minimax-m3.1-flash' in enabled else FALLBACK_EMPLOYEE_MODEL
        extra: Dict[str, Any] = {}
        # BitClient staged CAD specialists
        from app.services.desktop_cad_completion import cad_employee_phase, cad_phase_model, CAD_SPECIALIST_SCOPE
        phase = cad_employee_phase(item) if cad_astra else None
        stage_model = cad_phase_model(phase, allowed)
        if stage_model is not None:
            model = stage_model
            extra["cad_phase"] = phase
        elif cad_astra and model == "gpt-6-astra":
            model = _astra_fallback(allowed)
        if cad_astra and model == "gpt-6-astra":
            extra["task"] = CAD_SPECIALIST_SCOPE + str(item.get("task", ""))
        if item.get("product_phase") in {"brief", "build"} and not cad_astra:
            # Sonnet and Sol share the same price ceiling. Opus/Astra stay specialist-only.
            from config import OPENROUTER_API_KEY
            affordable = {FALLBACK_EMPLOYEE_MODEL, ROUTINE_MODEL, HAIKU_MODEL, PLANNER_MODEL, SONNET_MODEL}
            if item.get('work_kind') in {'file_operation', 'small_edit'} and 'minimax-m3.1-flash' in enabled:
                affordable.add('minimax-m3.1-flash')
            haiku_ok = bool(OPENROUTER_API_KEY) and HAIKU_MODEL in allowed
            chosen = model if model in affordable and model in allowed else None
            if chosen is None:
                if item.get("product_phase") == "brief":
                    chosen = HAIKU_MODEL if haiku_ok else (FALLBACK_EMPLOYEE_MODEL if FALLBACK_EMPLOYEE_MODEL in allowed else PLANNER_MODEL)
                else:
                    chosen = PLANNER_MODEL if PLANNER_MODEL in allowed else (HAIKU_MODEL if haiku_ok else FALLBACK_EMPLOYEE_MODEL)
            if chosen == HAIKU_MODEL and not haiku_ok:
                chosen = FALLBACK_EMPLOYEE_MODEL if FALLBACK_EMPLOYEE_MODEL in allowed else PLANNER_MODEL
            if chosen == SONNET_MODEL and not OPENROUTER_API_KEY:
                chosen = PLANNER_MODEL if PLANNER_MODEL in allowed else FALLBACK_EMPLOYEE_MODEL
            if chosen in {PLANNER_MODEL, SONNET_MODEL}:
                if sol_this_product:
                    chosen = HAIKU_MODEL if haiku_ok else FALLBACK_EMPLOYEE_MODEL
                else:
                    sol_this_product = True
            employees.append({**item, "model": chosen, **extra})
            continue
        if model == "kimi-k2.6":
            # The research worker uses the shared search/read tools. The selected
            # backend controls whether web_search is our metasearch or hosted.
            model, extra = FALLBACK_EMPLOYEE_MODEL, {"web": True}
        elif model in ("gpt-6-sol", SONNET_MODEL, "deepseek-v4-pro") and not strong and not recovery:
            if model == PLANNER_MODEL and routine_was_strong:
                if routine_employee(item, original_task, document_context) and ROUTINE_MODEL in allowed:
                    model = ROUTINE_MODEL
            else:
                model = FALLBACK_EMPLOYEE_MODEL
        if model == "gpt-6-astra" and allow_opus and not cad_astra:
            model = _astra_fallback(allowed) if opus_used else OPUS_MODEL
        if model == OPUS_MODEL and (cad_astra or not allow_opus or opus_used):
            model = _astra_fallback(allowed)
        elif model == OPUS_MODEL:
            opus_used = True
        if model == "gpt-6-astra" and (not allow_astra or (astra_used and not cad_astra) or (cad_astra and any(e.get("model") == "gpt-6-astra" for e in employees))):
            model = _astra_fallback(allowed)
        elif model not in allowed:
            model = FALLBACK_EMPLOYEE_MODEL if FALLBACK_EMPLOYEE_MODEL in allowed else (allowed[0] if allowed else FALLBACK_EMPLOYEE_MODEL)
        if model == "gpt-6-astra":
            astra_used = True
        if not cad_astra and routine_was_strong and routine_employee(item, original_task, document_context) and not recovery:
            if model == PLANNER_MODEL and ROUTINE_MODEL in allowed:
                model = ROUTINE_MODEL
        if routine and not routine_was_strong and model == ROUTINE_MODEL and not recovery and FALLBACK_EMPLOYEE_MODEL in allowed:
            model = FALLBACK_EMPLOYEE_MODEL
        if routine and critical_task(str(item.get('role') or '') + ' ' + str(item.get('task') or '')) and model in {ROUTINE_MODEL,FALLBACK_EMPLOYEE_MODEL} and PLANNER_MODEL in allowed:
            model = PLANNER_MODEL
        repair = bool(re.search(r'(?i)исправ|repair|fix|валид|тест|компиля', str(item.get('task') or '')))
        if recovery and (model == ROUTINE_MODEL or (model == FALLBACK_EMPLOYEE_MODEL and repair)) and PLANNER_MODEL in allowed:
            model = PLANNER_MODEL
        employees.append({**item, "model": model, **extra})
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
    в режиме Оркестратор собирали свои промпты с нуля и никогда не видели ни память
    пользователя, ни его активный кастомный промпт — отсюда жалобы, что Оркестратор
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
# «что нам делать», «где в договоре» – и Оркестратор искал по фото вместо работы.
PHOTO_RESEARCH_MARKERS = (
    "фото", "фотк", "снимк", "снимок", "картин", "изображ", "скрин", "где сня",
    "локац", "ориентир", "сделано данное", "это место", "за место",
)
_RESEARCH_MARKERS = PHOTO_RESEARCH_MARKERS + (
    "где ", "кто ", "когда", "актуаль", "сейчас", "на данный",
    "сравни", "обзор", "проверь", "источник", "рейтинг", "мета",
    "новост", "цен", "стоим", "адрес",
    "винрейт", "winrate", "win rate", "патч", "тариф", "подписк", "бюджет",
    "посоветуй", "порекомендуй", "лучше взять", "что лучше", "какой инструмент",
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
        "model": FALLBACK_EMPLOYEE_MODEL,
        "web": True,
    }]


def _light_research_employee(user_text: str) -> Dict[str, Any]:
    """One lean researcher with both search and selective page reading."""
    return {
        "role": "Поиск",
        "task": (
            "Ответь на вопрос по свежим данным из интернета: сделай веб-поиск и опирайся только на найденное. "
            "Страницу открывай (browse_page) только если в выдаче нет нужной цифры или даты. "
            "В ответе – факты с датой и источником, без вступлений.\n"
            f"Вопрос: {(user_text or '')[:1500]}"
        ),
        "model": FALLBACK_EMPLOYEE_MODEL,
        "web": True,
    }


def _has_sources(journal: List[Dict[str, Any]], minimum: int = 2) -> bool:
    links = {
        str(s.get("summary", "")).split("\n")[0]
        for entry in journal
        for s in entry.get("search", [])
        if str(s.get("summary", "")).startswith("http")
    }
    return len(links) >= minimum


def _research_needs_retry(journal: List[Dict[str, Any]]) -> bool:
    """A source list alone cannot turn a failed first attempt into completion."""
    if not journal or not _has_sources(journal, minimum=1):
        return True
    latest = journal[-1]
    if latest.get('status') == 'error':
        return True
    lead = str(latest.get('result') or '').strip().lstrip('*# ').lower()[:400]
    return not lead or bool(re.match(
        r'(?:к сожалению[,:]?\s*|честно[,:]?\s*)?(?:(?:сейчас|пока)\s+)?(?:'
        r'не (?:смог|смогла|удалось|могу|получилось)|'
        r'нет (?:достоверных|подтверждённых|актуальных) данных|'
        r'(?:i (?:could not|couldn.t|cannot|can.t)|unable to))', lead))


def _verify_employee(user_text: str) -> Dict[str, Any]:
    return {
        "role": "Сверка",
        "task": (
            "load_skill verify. Сначала проверь, относятся ли заметки и ссылки к нужному объекту и теме. "
            "При нерелевантной выдаче уточни запрос по исходному вопросу, сохрани название игры/продукта, "
            "используй оригинальное написание. Затем открой 1-2 подходящих URL через browse_page "
            "и подтверди или опровергни вывод. Не добавляй факты из памяти. "
            "Если был image_search – открой страницы из его выдачи.\n"
            f"Вопрос: {(user_text or '')[:1200]}"
        ),
        "model": "gpt-6-luna",
        "web": True,
    }


def _ensure_research_plan(
    round_num: int,
    plan: Dict[str, Any],
    user_text: str,
    journal: List[Dict[str, Any]],
    has_images: bool,
) -> Dict[str, Any]:
    """Оркестратор – исследователь: первый раунд не бывает пустым, второй – сверка.

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


def _parse_director_plan(response_text: str, *, strict: bool = False) -> Dict[str, Any]:
    """
    Разбирает JSON-ответ дирижёра в раунде. В режиме совместимости ошибка
    трактуется как "задача завершена"; strict вызывает ValueError для
    ограниченной повторной попытки планировщика. Это
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
        from app.services.conversation_context import workspaces
        selection = {}
        if workspaces.get() is not None:
            action = data.get('workspace_action')
            if action not in {'revise', 'create', 'none'}:
                raise ValueError('Planner must select how this request relates to the saved workspace')
            selection['workspace_action'] = action
            if action == 'revise':
                pid = data.get('workspace_id')
                if pid not in {item['product_id'] for item in workspaces.get()}:
                    raise ValueError('Workspace must belong to the current conversation')
                selection['workspace_id'] = pid
        if strict and status not in {"continue", "done", "clarify"}:
            raise ValueError('Unknown plan status')
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
            from app.services.desktop_cad_completion import CAD_PHASES
            phase = e.get("cad_phase")
            work_kind = e.get('work_kind')
            valid_employees.append({"role": role, "task": task, "model": model,
                **({'work_kind': work_kind} if work_kind in {'classify', 'extract_text', 'file_operation', 'small_edit', 'research', 'expert', 'build'} else {}),
                **({"cad_phase": phase} if isinstance(phase, str) and phase in CAD_PHASES else {})})

        if status == "clarify":
            from clarify import normalize_questions

            questions = normalize_questions(data.get("questions"))
            if questions:
                return {"status": "clarify", "new_employees": [], "questions": questions, **selection}
            if strict:
                raise ValueError('No valid clarification questions')
            status = "done"
        if strict and status == 'done' and valid_employees:
            raise ValueError('Completed plan cannot contain unfinished employees')

        if status not in ("continue", "done"):
            status = "continue" if valid_employees else "done"
        if status == "continue" and not valid_employees and selection.get('workspace_action') not in {'revise', 'create'}:
            if strict:
                raise ValueError('No valid employees in continuing plan')
            status = "done"

        return {"status": status, "new_employees": valid_employees, **selection}
    except Exception as e:
        if strict:
            raise ValueError('Invalid orchestrator plan') from None
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

    lines = ["**Оркестратор**:", ""]
    for round_num in sorted(rounds.keys()):
        lines.append(f"Раунд {round_num}:")
        for entry in rounds[round_num]:
            icon = STATUS_ICONS.get(entry["status"], "⏳")
            lines.append(f"{icon} {_escape_markdown(entry['role'])} — {entry['model']}")
        lines.append("")

    return "\n".join(lines).strip()


# Pilot hands the same files to the planner (every round), each employee (every tool hop
# resends it) and the composer. Whole files made one turn burn a Pro+ pool, so each stage gets
# the part of a file that matters to it; the rest is one read_chat_document call away.
PLANNER_DOC_CHARS = 14_000
COMPOSER_DOC_CHARS = 16_000
EMPLOYEE_DOC_CHARS = 48_000
PLANNER_HISTORY_CHARS = 16_000
EMPLOYEE_HISTORY_CHARS = 10_000
_DOC_HEADER = "Пользователь предоставил документ для контекста:"


def _trim_documents(document_context: str, query: str, budget: int) -> str:
    """Per file: the excerpt most relevant to `query`, within `budget` chars across all files."""
    if not document_context or len(document_context) <= budget:
        return document_context
    from db_conversations import _relevant_document_excerpt

    parts = [p for p in re.split(rf"(?m)(?=^{re.escape(_DOC_HEADER)})", document_context) if p.strip()]
    share = max(256, budget // max(1, len(parts)))
    out: List[str] = []
    for part in parts:
        if len(part) <= share:
            out.append(part)
            continue
        head, sep, body = part.partition("Содержание:\n")
        if not sep:
            head, body = "", part
        room = max(128, share - len(head) - 260)
        excerpt = _relevant_document_excerpt(body, query, room)
        out.append(
            f"{head}{sep}{excerpt}\n\n[Показана часть файла: {len(excerpt)} из {len(body)} знаков. "
            "Остальное – read_chat_document с точным именем и query.]"
        )
    combined = "\n\n".join(out)
    if len(combined) <= budget:
        return combined
    note = '\n[Контекст сокращён. Полный каталог — list_chat_files; нужный фрагмент — read_chat_document.]'
    return combined[:max(0, budget-len(note))] + note


def _tail(text: str, limit: int) -> str:
    from app.services.desktop_context import desktop_executor
    if desktop_executor.get() is not None and limit in {PLANNER_HISTORY_CHARS, EMPLOYEE_HISTORY_CHARS}:
        from app.services.desktop_policy import history_view_limit
        limit = history_view_limit(limit, PLANNER_HISTORY_CHARS)
    if len(text) <= limit:
        return text
    # History packing pins the initial requirements. Keeping only the tail undid
    # that packing and made short follow-ups forget the original constraints.
    if limit in {PLANNER_HISTORY_CHARS, EMPLOYEE_HISTORY_CHARS}:
        note = '\n[Часть промежуточной истории сокращена; при необходимости открой исходную беседу.]\n'
        room = max(0, limit-len(note))
        head = room // 3
        return text[:head] + note + text[-(room-head):]
    return '…' + text[-max(0, limit-1):]


def _extract_document_context(messages: List[Dict[str, Any]]) -> str:
    """Достаёт системные сообщения с текстом прикреплённых пользователем документов -
    тот же приём, что уже использует hybrid_router.py для авто-режима. Без этого
    Дирижёр получает только голый текст задачи и не видит загруженные документы."""
    doc_parts = []
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content", "")
            if ("документ для контекста" in content or "предоставил документ" in content
                or content.startswith(('Сохранённые материалы именно этой беседы', 'Правила пользователя для этого задания:'))):
                doc_parts.append(content)
    return "\n\n".join(doc_parts)


def _format_chat_history(messages: List[Dict[str, Any]]) -> str:
    """История для планировщика/сотрудников: ранние вопросы юзера + длинный хвост."""
    from model_context import format_chat_history_for_prompt

    from app.services.desktop_context import desktop_executor
    if desktop_executor.get() is not None:
        from app.services.desktop_policy import format_local_history
        return format_local_history(messages)
    return format_chat_history_for_prompt(messages)


async def _update_status(status_msg: Any, text: str, kind: str = 'work') -> None:
    """Безопасно обновляет статус. Если живая лента привязана — шаг в ней, иначе старый edit."""
    try:
        from status_feed import is_bound, push_status
        if is_bound():
            await push_status(kind, re.sub(r"\*\*(.+?)\*\*", r"\1", text))
            return
    except Exception:
        pass
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"Failed to edit director status message: {e}")


@model_phase('employee')
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
    # Orchestrator without Kimi: also handle stale checkpoint employees.
    legacy_search = employee["model"] == "kimi-k2.6"
    model = FALLBACK_EMPLOYEE_MODEL if legacy_search else employee["model"]
    try:
        from status_feed import push_status
        from orchestrator_activity import employee_activity
        await push_status(*employee_activity(employee))
    except Exception:
        pass

    context_lines = []
    for entry in journal:
        if entry["status"] == "ok" or entry.get("cad_errors"):
            context_lines.append(f"### {entry['role']} (раунд {entry['round']})\n{_clamp_result(entry['result'])}")
    context_block = "\n\n".join(context_lines)

    from computer_tools import skills_prompt

    date_note = _current_date_note()
    history_text = _tail(history_text, EMPLOYEE_HISTORY_CHARS)
    document_context = _trim_documents(document_context, task, EMPLOYEE_DOC_CHARS)
    history_block = f"\n\nИстория диалога:\n{history_text}" if history_text else ""
    doc_block = f"\n\nДокументы пользователя:\n{document_context}" if document_context else ""
    skills_block = f"\n\n{skills_prompt(user_id, compact=True)}"
    preferences_block = _preference_context(user_id)
    prefs_note = f"\n\n{preferences_block}" if preferences_block else ""

    base_prompt = (
        f"{date_note}{history_block}{doc_block}{skills_block}{prefs_note}\n\n{WORKFLOW_RULES}\n\n"
        f"{ECONOMY_RULES if economy_enabled() else ''}\n"
        f"Твоя роль: {role}.\nТвоя задача: {task}\n\n"
        "Ты сотрудник Оркестратора. Делай только свою задачу. "
        "Если выше есть память или правило «как отвечать» – соблюдай язык, тон и формат "
        "буквально, это важнее твоих привычек. "
        "Коллеги в этом раунде работают параллельно и не ждут тебя: не дублируй их работу "
        "и не откладывай шаг, пока не появятся чужие результаты. "
        "Ответь по существу, без отчёта, оглавления и нумерации разделов. "
        "Не рассказывай вслух, какой инструмент выберешь. Сначала вызови его. "
        "Если нужно зайти на сайт – browse_page или site_login с логином из чата. "
        "Дизайн, композицию и расположение заголовков смотри через browse_visual: он снимает десктоп и телефон. browse_page этого не показывает. "
        "Почта, VPS и API: сначала сохранённые подключения владельца; уже переданные доступы используй только по поручению. "
        "Перед кодом, файлом, таблицей, презентацией, письмом или входом на сайт – первым вызовом load_skill с точным именем из каталога. "
        "Не грузи все скилы. Если скил уже вложен ниже – не вызывай load_skill повторно. Если ни один не подходит, работай без скила. "
        "Песочница с pip и Python – чтобы экономить токены: сам решай, запускать скрипт или нет, пользователя не спрашивай. "
        "Цифру или цитату из поиска не считай проверенной, пока не откроешь страницу browse_page. "
        "Если в чате есть фото и вопрос про место, источник или «что на снимке» – первым вызовом image_search. "
        "Не называй адрес или площадку только по виду кадра. После выдачи поисковиков открой 2-4 страницы browse_page. "
        "Не пиши готовый ответ из памяти до инструментов: сначала поиск или страница, потом вывод. "
        "Если текста документа нет в блоке выше, сначала list_chat_files, затем read_chat_document по точному имени. "
        "Исходные аудио, видео, архивы и любые вложения получай через workspace_import_file: это оригинальные байты, не описание. "
        "Для встраивания в сайт копируй в assets именно папки проекта и используй относительную ссылку. "
        "Не заменяй приложенный звук/ролик заглушкой. Готовые файлы любых форматов отдавай через workspace_export_files. "
        "Не проси пользователя прислать файл снова: он уже в чате. "
        "Прошлые разговоры – search_chats или recent_chats, не интернет. Не проси открыть другой чат. "
        "Код только в workspace_* / pip_install / python_run. Сначала workspace_grep или workspace_glob, не читай все файлы. "
        "Если просят архив кода или проект-бота – запиши файлы и собери project.zip в песочнице. "
        "Блок-схема, схема процесса, алгоритм, diagrams.net/draw.io – diagram_create: создай полный несжатый mxfile XML с фигурами, координатами и стрелками, сохрани новый .drawio и заказанные PDF/PNG/SVG (по умолчанию PDF и PNG). PDF содержит все страницы, PNG/SVG – выбранную с 1. Исходный .drawio всегда приложи для редактирования. Для схем не заменяй готовые файлы инструкцией или Mermaid-кодом. "
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
    from app.services.run_protocol import current_run
    run = current_run.get()
    if run is not None and run.request_context:
        base_prompt = ('Текущая цель и материалы беседы, общие для всех исполнителей. '
            'Не теряй ограничения человека при выполнении своего этапа:\n'
            + json.dumps(run.request_context, ensure_ascii=False) + '\n\n' + base_prompt)
    if context_block:
        prompt = f"{base_prompt}\n\nРезультаты коллег из предыдущих раундов:\n{context_block}"
    else:
        prompt = base_prompt
    try:
        from computer_skills.loader import preload_skills_block

        # The task alone: matching on the whole chat history pulled in unrelated skills
        # (a 7 KB "documents" playbook because someone once said "договор").
        skill_block = preload_skills_block(
            task,
            has_images=has_images or "image_search" in (task or "").lower() or "фото" in (task or "").lower(),
            user_id=user_id,
            sandbox=True,
        )
        if skill_block:
            prompt = f"{prompt}\n\n{skill_block}"
    except Exception:
        pass

    employee_messages = [
        {"role": "system", "content": _OUTPUT_RULES + '\n\n' + AUTONOMY_RULES},
        {"role": "user", "content": prompt + _desktop_work_instructions()},
    ]
    try:
        from conversations import conversation_manager

        parts = conversation_manager.vision_parts_for_chat(int(user_id), task)
        if parts:
            conversation_manager._attach_images_to_last_user(employee_messages, parts)
    except Exception:
        logger.debug("Director employee image attach skipped", exc_info=True)

    # BitClient CAD compiler evidence
    from app.services.desktop_context import desktop_executor, desktop_cwd
    from app.services.desktop_cad_completion import CadToolEvidence
    cad_evidence = CadToolEvidence(desktop_cwd.get())
    from app.services.orchestrator_policy import validation, ValidationState
    validation_state = ValidationState()
    validation_token = validation.set(validation_state)
    cad_original_executor = desktop_executor.get()
    cad_executor_token = None
    if cad_original_executor is not None:
        async def cad_observed_executor(name, args):
            result = await cad_original_executor(name, args)
            cad_evidence.record(name, args, result)
            return result
        cad_executor_token = desktop_executor.set(cad_observed_executor)
    reasoning = ""
    search: List[Dict[str, str]] = []
    try:
        builds_file = _is_document_package_task(task) or _wants_file(task) or "docx" in (task or "").lower()
        from app.services.desktop_context import desktop_executor
        from app.services.desktop_cad_completion import required_cad_extensions
        cad_build = desktop_executor.get() is not None and bool(required_cad_extensions(task))
        from app.services.desktop_cad_completion import cad_employee_phase
        if employee.get("product_phase") == "brief":
            loops = 8
        elif employee.get("product_phase"):
            # Haiku on a 40-step build costs more than one Sol pass and still fails the checks.
            loops = 12 if model in {HAIKU_MODEL, "gpt-6-luna", "gpt-5-nano", ROUTINE_MODEL, 'minimax-m3.1-flash'} else 40
        else:
            loops = (60 if cad_employee_phase(employee)=="gui_geometry" else 30) if cad_build else PACKAGE_EMPLOYEE_TOOL_LOOPS if builds_file else None
        def product_accepted(name, result):
            from app.services.autonomy import product_evidence
            evidence = product_evidence.get() or {}
            return name == 'product_lifecycle' and evidence.get('product_id') == employee.get('product_id') and bool(evidence.get('ready'))
        stop_options = {'stop_after_tool': product_accepted} if employee.get('product_phase') == 'build' and employee.get('product_id') else {}
        from app.services.model_registry import openrouter_models
        response = None
        if model in openrouter_models(include_experimental=True):
            from openrouter_client import get_openrouter_response
            response = await get_openrouter_response(
                employee_messages, model=model, user_id=user_id, use_tools=True, max_tool_loops=loops,
                reasoning_effort='high' if model == OPUS_MODEL else None,
                **stop_options,
            )
            if getattr(response, 'retryable', False) and not response.actions_executed:
                # Only retry a provider failure before any tool action. Never replay a partial build.
                from openai_client import get_chat_response
                preferred = PLANNER_MODEL if model in {SONNET_MODEL, OPUS_MODEL} else FALLBACK_EMPLOYEE_MODEL
                allowed = _employee_models(user_id)
                fallback = preferred if preferred in allowed else FALLBACK_EMPLOYEE_MODEL
                response = await get_chat_response(employee_messages, model=fallback, user_id=user_id,
                    use_tools=True, max_tool_loops=loops, **stop_options)
                model = fallback
            answer, _, reasoning, search = response
        elif model == "deepseek-v4-pro":
            from deepseek_client import get_deepseek_response
            answer, _, reasoning, search = await get_deepseek_response(employee_messages, model=model, user_id=user_id, use_tools=True)
        else:
            from openai_client import get_chat_response
            if employee.get('web') and not cad_build and not builds_file:
                loops = 6  # Search, skill, selective read/retry, then synthesis.
            response = await get_chat_response(
                employee_messages, model=model, user_id=user_id, use_tools=True, max_tool_loops=loops,
                force_web_search=bool(employee.get("web", legacy_search)),
                reasoning_effort="high" if cad_build and model == "gpt-6-astra" else None,
                **stop_options,
            )
            answer, _, reasoning, search = response

        provider_failed = bool(getattr(response, 'error_kind', '')) or answer.startswith('❌') or not answer.strip() or answer == 'Нет ответа от модели'
        return {
            "round": round_num, "role": role, "task": task, "model": model, "cad_phase": employee.get("cad_phase"), "cad_errors": cad_evidence.errors, "cad_resolved": sorted(cad_evidence.resolved), "status": "error" if cad_evidence.errors else "ok", "result": answer + ("\nCAD compiler diagnostics:\n" + "\n".join(cad_evidence.errors) if cad_evidence.errors else ""),
            **({'product_phase': employee['product_phase']} if employee.get('product_phase') else {}),
            **({'status':'error'} if provider_failed else {}),
            **({'error_kind': response.error_kind, 'retryable': response.retryable} if getattr(response, 'error_kind', '') else {}),
            **({'validation_checks':dict(validation_state.checks)} if validation_state.checks else {}),
            **({'status':'error', 'validation_failed':True,
                'result':answer + '\nПроверка результата не пройдена: исправь ошибку теста/сборки и повтори только проверку, сначала проверь сохранённые изменения.'} if validation_state.failed else {}),
            "reasoning": reasoning, "search": search,
        }
    except Exception as e:
        logger.error(f"Director employee '{role}' ({model}) failed: {e}")
        return {
            "round": round_num, "role": role, "task": task, "model": model, "cad_phase": employee.get("cad_phase"), "cad_errors": cad_evidence.errors, "cad_resolved": sorted(cad_evidence.resolved), "status": "error",
            "result": f"[Ошибка при выполнении: {str(e)[:200]}]", "reasoning": "", "search": [],
        }

    finally:
        validation.reset(validation_token)
        if cad_executor_token is not None:
            desktop_executor.reset(cad_executor_token)


def _format_journal_for_prompt(journal: List[Dict[str, Any]]) -> str:
    if not journal:
        return "(пока никто не привлекался)"
    parts = []
    for entry in journal:
        status_label = "успешно" if entry["status"] == "ok" else "ошибка"
        result = entry["result"][:14500] if entry.get("live_verification") else _clamp_result(entry["result"])
        parts.append(f"- Раунд {entry['round']}, {entry['role']} ({entry['model']}, {status_label}): {result}")
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
    # A file alone no longer buys Sol (20x Luna): the employees already read it, and the
    # composer only merges their notes. Sol stays for contracts/audits and big result sets.
    needs_quality = (
        any(entry.get('model') in {SONNET_MODEL, OPUS_MODEL, 'gpt-6-astra'} for entry in ok_entries)
        or
        (bool(document_context) and any(marker in task for marker in hard_markers))
        or len(original_task) > 1200
        or result_chars > 15000
        or len(ok_entries) >= 6
        or (photo_task and len(ok_entries) >= 2)
        or (len(original_task) > 400 and any(marker in task for marker in hard_markers))
    )
    return QUALITY_COMPOSER_MODEL if needs_quality else ECONOMY_COMPOSER_MODEL


def _pool_description(user_id: int, original_task: str = "", document_context: str = "") -> str:
    lines = [
        ("gpt-6-luna", "дешёвая, простой анализ, черновики, короткие ответы; короткое чтение, извлечение и фильтрация файлов"),
        *([(ROUTINE_MODEL, "точные небольшие правки и ограниченные преобразования вместо Sol, когда Luna недостаточно; наличие файла само по себе не причина выбирать Terra")] if economy_enabled() else []),
        (HAIKU_MODEL, "короткие ограниченные операции, код и извлечение. Базовая цена как у Luna, но вход свыше 100 тысяч токенов повышает цену в пять раз. Для расчёта используй инструменты."),
        ("gpt-6-sol", "в 20 раз дороже. Сборка сайта, лендинга или приложения (один раз), починка после провала, плотный разбор. Не для поиска и снимков."),
        (SONNET_MODEL, "альтернатива Sol по той же базовой цене: сложный код, сборка и точечная починка. Не нанимай Sol и Sonnet для дублирующей работы."),
        ('glm-5.3-flash', 'дешёвое извлечение и классификация текста: work_kind extract_text/classify. Только текст, без изображений и создания продукта.'),
        ('minimax-m3.1-flash', 'основной экономный исполнитель ограниченных операций с файлами и небольших правок: work_kind file_operation/small_edit. Включая импорт аудио/видео в assets. Не большой проект и не экспертный вывод.'),
        (OPUS_MODEL, "договор, аудит, архитектура, расследование. Один такой сотрудник. Не геометрия и не SDK."),
        (
            "gpt-6-astra",
            "самая дорогая. Только сложная геометрия/сопряжения и трудные ошибки SDK. "
            "Типовые детали — Sol; чтение файлов и стандартные проверки — Luna. Не вся CAD-задача.",
        ),
    ]
    allowed = set(_employee_models(user_id))
    from app.services.desktop_context import desktop_executor
    from app.services.desktop_cad_completion import required_cad_extensions
    cad = desktop_executor.get() is not None and bool(required_cad_extensions(original_task))
    if cad:
        allowed.discard(OPUS_MODEL)
    elif _task_warrants_opus(original_task, document_context) and OPUS_MODEL in allowed:
        allowed.discard("gpt-6-astra")
    else:
        allowed.discard(OPUS_MODEL)
        allowed.discard("gpt-6-astra")
    return "\n".join(f"{mid} — {desc}" for mid, desc in lines if mid in allowed)


_clarify_only: ContextVar[bool] = ContextVar('director_clarify_only', default=False)


@model_phase('planner')
async def _plan_round(
    original_task: str,
    journal: List[Dict[str, Any]],
    user_id: int,
    document_context: str = "",
    history_text: str = "",
) -> Dict[str, Any]:
    """Один дешёвый вызов: решить, нанимать ли ещё сотрудников, и кого именно.

    In the preflight of a new product the build is Sol anyway, so this call only decides whether to ask first."""
    clarify_only = _clarify_only.get()
    from openai_client import get_chat_response

    pool_description = _pool_description(user_id, original_task, document_context)

    from computer_tools import connector_summary_for_prompt, skills_prompt

    history_text = _tail(history_text, PLANNER_HISTORY_CHARS)
    document_context_full = document_context
    document_context = _trim_documents(document_context, original_task, PLANNER_DOC_CHARS)
    history_block = f"\n\nИстория диалога:\n{history_text}\n" if history_text else ""
    doc_block = f"\n\nДокументы пользователя:\n{document_context}\n" if document_context else ""
    connectors_block = connector_summary_for_prompt(user_id)
    skills_block = skills_prompt(user_id, compact=True)
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
        "Ты Оркестратор, который выполняет задачу пользователя руками сотрудников. "
        "Сотрудники используют реальные сайты, файлы и подключения владельца. "
        "Если нужного подключения нет, сначала сделай доступную часть работы, затем укажи конкретный недостающий доступ. "
        "В задачи сотрудникам не копируй пароли: доступы уже в хранилище или в исходном сообщении.\n\n"
        f"Исходная задача пользователя:\n{original_task}\n"
        f"{history_block}"
        f"{doc_block}\n"
        f"{image_block}"
        f"{skills_block}\n\n{WORKFLOW_RULES}\n\n"
        "Если пользователь поручил работу позже или по расписанию, назначь ОДНОГО сотрудника с load_skill wf_automations. "
        "Он создаёт задачу через task_create и проверяет ответ. Не выдавай одно расписание нескольким сотрудникам. "
        "Обычную текущую задачу не превращай в фоновую без просьбы.\n"
        "Для обычной задачи не больше одного дорогого экспертного исполнителя; в BitClient CAD допускаются отдельные последовательные стадии по действующей политике.\n"
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
        "- Оркестратор – исследователь, не чат из памяти. Раунд 1 без сотрудников запрещён, "
        "кроме приветствия. status=done только после того, как сотрудники уже собрали и сверили источники.\n"
        "- Запрещено закрывать задачу в раунде 1, если нужно найти факт, место, источник, цену или разобрать фото.\n"
        "- Если цель двусмысленная (неясно что строить, для кого, какой стек, какой результат) "
        "– верни status=clarify и 1-3 коротких вопроса с вариантами. Не пиши вопросы текстом, только JSON. "
        "Не спрашивай очевидное и не спрашивай пароли. Если пользователь уже ответил на уточнения, "
        "но развилка осталась (идея, тип, стек, хостинг, доступы) – снова status=clarify. "
        "Запрещено писать опросник обычным текстом: никаких «выберите вариант» и нумерованных анкет в ответе.\n"
        "- Не заказывай финальный отчёт, оглавление или нумерованные разделы.\n"
        "- Не проси разрешение искать или открыть сайт: найми сотрудника сразу.\n"
        "Незнакомую тему не закрывай из памяти: ищи через server_search и не больше трёх browse_page. "
        "Если важен внешний вид предмета или страницы — один browse_visual, не серия. "
        "Чужие картинки в файлы не копируй: запиши композицию и факты. "
        "Подходящий скил из каталога — первая строка task.\n"
        "Модель выбираешь ты, по цене ошибки. Поиск, чтение, извлечение и черновик — gpt-6-luna. "
        "Короткий код и рассуждение — claude-haiku-5.5, ответ короткий. "
        "Сборка сайта, лендинга или приложения — один gpt-6-sol: длинная сборка на Haiku выходит дороже "
        "и не проходит приёмку. Поиск и снимки страниц Sol не отдавай. "
        "Один Sol на задачу; второй только если первый провалился.\n"
        + (
            "В локальной CAD-задаче разделяй работу на конкретные этапы с cad_phase: "
            "inspect (файлы, фото, SDK) — Luna; simple_geometry (типовые детали, выдавливания, "
            "цилиндры и обычные размерные правки) — Sol; complex_geometry (криволинейная "
            "геометрия, сложные сопряжения, топология) и sdk_repair (трудная ошибка SDK) — Astra; "
            "verify (проверки, сохранение, перечень результата) — Luna. Не отдавай Астре всё изделие "
            "одним заданием. Независимый анализ можно параллельно; изменения одного CAD-документа "
            "делай последовательно. Применяй уже готовые результаты коллег и передавай им "
            "конкретные пути/параметры. Астра — один сложный этап в раунде, не поиск и не финальный ответ. "
            if "gpt-6-astra" in pool_description
            else ""
        ) + (
            "Один сотрудник claude-opus-5.5 на плотный договор, аудит, архитектуру или расследование. "
            "Не нанимай его для геометрии, SDK и обычного анализа.\n"
            if "claude-opus-5.5" in pool_description
            else ""
        ) +
        "Если ищут наличие электронных компонентов или план закупки BOM/спецификации – всем поисковым сотрудникам первой строкой load_skill marketplaces. "
        "Раздели поиск: (ЧИП и ДИП, Терраэлектроника), (Промэлектроника, КОМПЭЛ, Платан), (Ozon, Wildberries, Яндекс Маркет и дополнительные магазины). "
        "Каждому передай точные MPN, корпуса, количества, город и конкретный диапазон строк спецификации. Требуй открыть карточки browse_page: статус склада, доступное количество, MOQ, упаковка, цена для нужного количества и срок поставки отдельно от доставки. "
        "Большую спецификацию разбирай партиями с сохранением CSV/XLSX; не теряй непроверенные строки. Обобщение: покрытие каждой позиции, дефицит и план по магазинам. Аналоги отдельно, не подменяют MPN. Реальные корзины и регистрацию не обещай.\n"
        "При сравнении конкретных ссылок нанимай одного сотрудника: открыть именно присланные ссылки, максимум 20 отзывов на товар; внешняя сверка первых пяти сайтов по точной модели без глубокого обхода. Не ищи альтернативы и не создавай файлы без явной просьбы. "
        "Для остальных задач найти товар, лучшее предложение или сравнить цены по магазинам – найми 3-4 поисковых сотрудников (model gpt-6-luna, поиск через server_search) ОДНОВРЕМЕННО, каждому первой строкой load_skill marketplaces и свою группу площадок: (Ozon, Wildberries), (Яндекс Маркет, Мегамаркет, DNS, Ситилинк), (отзывы и характеристики модели); для запроса «по миру» – ещё (Amazon, eBay, AliExpress). В task впиши товар, регион и цель человека. Второй раунд не нужен: таблицу соберёт сборщик ответа.\n"
        "Если нужны свежие данные с сайта - найми gpt-6-luna с server_search "
        "с задачей явно открыть URL через browse_page или войти через site_login. "
        "Если вопрос про фото (где снято, что на кадре, источник снимка) – в первом раунде "
        "обязательно gpt-6-luna с image_search по файлу из чата; "
        "по подписям и URL из image_search продолжай через server_search и browse_page. "
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
        '{"role": "Поиск A", "task": "...", "model": "gpt-6-luna"}, '
        '{"role": "Поиск B", "task": "...", "model": "gpt-6-luna"}]}\n'
        "или, если без ответа пользователя нельзя начать работу:\n"
        '{"status": "clarify", "questions": ['
        '{"prompt": "Какой тип приложения ты хочешь создать?", '
        '"options": ["Веб-приложение", "Telegram-бот", "Десктоп-приложение", "CLI / скрипт", "Другое"]}]}\n'
        "Terra назначай для чтения изображений/экранов и ограниченных точных правок; не заменяй ею дешёвые текстовые роли без необходимости. "
        "Поле model - строго один из id моделей выше. questions: 1-3 штуки, у каждого 2-6 коротких options."
    )
    prompt += ('\nКаждому сотруднику добавь work_kind: classify (классификация текста), extract_text (извлечение полей из текста), '
        'file_operation (копирование/преобразование/встраивание готовых файлов), small_edit (ограниченная небольшая правка), '
        'research, expert или build. Это смысл этапа, а не название инструмента. '
        'Для classify/extract_text используй glm-5.3-flash, если он доступен и не нужны изображения; '
        'для file_operation/small_edit — minimax-m3.1-flash. Сложные этапы оставляй сильной модели.\n')

    from app.services.conversation_context import workspaces
    if workspaces.get() is not None:
        prompt += ('\n\nСохранённые рабочие проекты ИМЕННО ЭТОЙ беседы (данные сервера):\n'
                   + json.dumps(workspaces.get(), ensure_ascii=False)
                   + '\nОпредели по смыслу текущего сообщения и всей истории, относится ли запрос к изменению '
                     'сохранённого проекта, созданию отдельного нового продукта или обычному ответу. '
                     'Фразы вроде «покрупнее», «всё ещё не нравится», «сделай как обсуждали» не требуют '
                     'повторять слово «сайт»: используй контекст. Вопрос или смена темы не разрешают править проект. '
                     'В JSON обязательно добавь workspace_action: revise / create / none. '
                     'create — только если человек просит программу: сайт, приложение, бота, сервис или дашборд. '
                     'Документ, доклад, отчёт, таблица, презентация, письмо, файл на Диск и обычный вопрос — это none: '
                     'без сборки, тестов, браузерной приёмки и архива проекта. '
                     'Для revise укажи workspace_id строго из списка выше. Для revise/create верни одного сотрудника: '
                     'его model — решение, нужен ли Sol на этот этап. Контроллер подставит задание и оставит модель. '
                     'Пустой new_employees значит, что ты не выбрал: разбор останется на Haiku, сборка на Sol. '
                     'Если нельзя выбрать между несколькими проектами, верни status=clarify. '
                     'Не отвечай, что файлы недоступны, без реальной проверки их доступности.')

    from app.services.run_protocol import current_run
    if current_run.get():
        prompt += current_run.get().evidence_prompt()
    if economy_enabled():
        prompt += '\n\n' + ECONOMY_RULES
    messages = [
        {"role": "system", "content": "Ты Computer - оркестратор команды моделей. Отвечаешь только валидным JSON.\n\n" + AUTONOMY_RULES},
        {"role": "user", "content": prompt + _desktop_work_instructions()},
    ]

    try:
        recovery = economy_enabled() and needs_recovery(journal)
        routine = not image_names and not _is_document_package_task(original_task) and routine_task(original_task, document_context_full) and _legacy_needs_strong_model(original_task, document_context_full, False, user_id)
        planner_model = _clamped_planner_model(user_id, first_round=not journal,
            complex_task=False if clarify_only else _needs_strong_model(original_task, document_context_full, bool(image_names), user_id), routine=routine, recovery=recovery)
        async def request_plan(selected):
            response_text, _, _, _ = await get_chat_response(messages, model=selected,
                user_id=user_id, use_tools=False, use_skills=False,
                reasoning_effort='medium' if selected == PLANNER_MODEL else 'low')
            return _parse_director_plan(response_text, strict=True)
        try:
            parsed = await request_plan(planner_model)
        except ValueError:
            fallback = _clamped_planner_model(user_id, recovery=True)
            if planner_model == fallback:
                raise
            # Planning has no tools: one stronger retry cannot replay an action.
            logger.info('orchestrator_planner_recovery from=%s to=%s', planner_model, fallback)
            parsed = await request_plan(fallback)
        return _clamp_employee_plan(
            parsed,
            user_id,
            original_task,
            document_context_full,
            journal,
            has_images=bool(image_names),
        )
    except Exception as e:
        from app.services.conversation_context import workspaces
        if workspaces.get() is not None:
            raise ValueError('Не удалось определить действие с рабочими файлами. Повторите запрос.') from e
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


@model_phase('composer')
async def _compose_answer(
    original_task: str,
    journal: List[Dict[str, Any]],
    user_id: int,
    history_text: str = "",
    document_context: str = "",
    built_files: List[str] | None = None,
) -> Tuple[str, str]:
    """Свести заметки сотрудников в обычный ответ чата — без отчёта и нумерации разделов."""
    from app.services.task_checkpoints import consume_steering
    original_task += await consume_steering()
    from openai_client import get_chat_response

    history_block = f"\n\nИстория диалога:\n{_tail(history_text, PLANNER_HISTORY_CHARS)}\n" if history_text else ""
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
    # The employees already worked through the files; the composer only needs enough to stay
    # consistent with them, not the whole text again.
    composer_docs = _trim_documents(document_context, original_task, COMPOSER_DOC_CHARS)
    doc_block = f"\n\nДокументы пользователя:\n{composer_docs}\n" if composer_docs else ""
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
        "Оценка соответствия запросу: reject исключи из выбора, unknown не называй лучшим, suitable оцени вместе с цитатами фактов. Не заполняй топ посторонними товарами или предложениями вне бюджета. "
        "Фактическая проверка карточки — главный источник подтверждения предложения. Только её status=ok доказывает чтение через домашний браузер; даже это не подтверждает поля, отсутствующие в тексте. "
        "Заметки поисковиков без такой проверки являются поисковыми подсказками. Не называй их проверенными и не говори что карточка не загрузилась, если попытки чтения не было. Рекомендуй только проверенные ссылки; остальные отдельно как кандидатов. "
        "URL копируй буквально из успешной фактической проверки карточки: не конструируй slug, артикул или короткую ссылку. При not_found, unavailable, invalid_content или timeout не ставь кликабельную магазинную ссылку. После редиректа используй проверенный конечный URL, не адрес подборки. "
        "Пиши только то, что сотрудники нашли и открыли. Не дополняй место, дату, имя или цифру из памяти модели. "
        "Если сверки нет или источники расходятся – скажи об этом, не выдавай догадку как факт.\n"
        "Закрой очевидный следующий шаг в том же ответе, чтобы не пришлось спрашивать «а как именно».\n"
        "Не нумеруй разделы (1., 1.1., 2.). Не пиши «Краткий вывод», «Итоги работы», "
        "«Результаты Computer». Пиши прямо по вопросу.\n"
        "Длина и тон — как у нормального ответа ассистента: коротко, если вопрос простой; "
        "подробнее, только если это нужно по сути.\n"
        "Если сотрудники собрали предложения на товар – дай одну сводную таблицу (Магазин | Товар и параметры | Цена | Рейтинг | Отзывы), ячейки до 6 слов, оговорки не в ячейки, а в «Проверь перед покупкой», лучшие строки сверху, затем «Лучший выбор» и «Проверь перед покупкой». "
        "Цены и рейтинги только из заметок сотрудников; чего нет – «н/д». Для рекомендованной строки дай Markdown-ссылку на проверенную конкретную карточку. "
        "Категории, поиск и подборки не выдавай за выбранный товар: сотрудник должен открыть конкретные предложения и сравнить цену, продавца, вариант, комплект и отзывы. "
        "Если карточку не удалось прочитать, показывай отдельно как непроверенную, а не лучший выбор; допускается меньше трёх проверенных вариантов. "
        "Не объявляй лучшим предложение без подтверждённой цены в бюджете, требуемого комплекта, продавца и данных рейтинга/отзывов, когда человек выбирает по отзывам. "
        "Не получил отзывы — не значит нет отзывов. Если условия не закрыты, скажи что проверенного лучшего варианта нет. Другие магазины при заданных Ozon/WB показывай только отдельной альтернативой. "
        "Для компонентов/BOM вместо потребительской таблицы используй покрытие позиций, наличие, MOQ и сроки, полный план в файле.\n"
        "Обычный разговор – проза. Списки и таблицы – только если без них хуже. Markdown можно, как в обычном чате.\n"
        "Не превращай ответ в анкету с вариантами. Не пиши «выберите 1/2/3». "
        "Не больше одного уточнения, и только если без него нельзя закончить.\n"
        "Ошибку сотрудников признай коротко и скажи, чего не хватает. Не выдумывай.\n"
        "Сначала дай найденный ответ на главный вопрос: число, объяснение или действие. "
        "Отсутствие заданного ранга/региона не причина скрывать найденную статистику: "
        "назови доступную выборку и период рядом с числом. Если соответствие текущему патчу "
        "не установлено, явно отдели этот пробел от полученного значения. "
        "Источники про одноимённые магазины вместо нужной игры не являются данными по вопросу.\n"
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

    from app.services.run_protocol import current_run
    if current_run.get():
        prompt += current_run.get().evidence_prompt()
    messages = [
        {
            "role": "system",
            "content": (
                "Ты тот же ассистент, что и в остальных режимах чата. "
                "Отвечаешь пользователю, а не пишешь документ.\n\n"
                f"{_OUTPUT_RULES}\n\n{AUTONOMY_RULES}"
            ),
        },
        {"role": "user", "content": prompt + _desktop_work_instructions()},
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
            "low"
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


@model_phase('direct')
async def _answer_directly(
    messages: List[Dict[str, Any]],
    user_id: int,
) -> Tuple[str, str, List[Dict[str, str]]]:
    """Простой вопрос без сотрудников: обычный ответ с теми же инструментами."""
    from openai_client import get_chat_response

    system = (
        f"{_current_date_note()}\n"
        "Ты Оркестратор в этом чате: отвечай как обычный ассистент. "
        "Если нужно зайти на сайт – browse_page или site_login с логином из чата. "
        "Дизайн, композицию и расположение заголовков смотри через browse_visual. "
        "Почта, VPS и API используют подключения владельца или уже переданный им доступ. "
        "Файлы этого чата – list_chat_files и read_chat_document. Прошлые чаты – search_chats. "
        "Фото – image_search в Яндексе, Google и Bing, затем browse_page по совпадениям. Не угадывай место по виду кадра. "
        "Под задачу вызови load_skill по каталогу. Не пиши отчёт и не нумеруй разделы. "
        "Не задавай пользователю вопросы с вариантами и не пиши «выберите 1/2/3». "
        "Если без выбора нельзя начать, это должен был сделать оркестратор через status=clarify. "
        "Действуй по уже сказанному.\n"
        f"{_OUTPUT_RULES}\n{WORKFLOW_RULES}\n\n{AUTONOMY_RULES}"
    )
    chat = [{"role": "system", "content": system + _desktop_work_instructions()}, *messages]
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


# Комплект делается строго по одному документу: параллельные сотрудники по
# 3-5 документов каждый сдавали один-два файла и теряли остальные.
MAX_PACKAGE_DOCUMENTS = 20


async def _plan_package_documents(
    user_text: str,
    user_id: int,
    history_text: str = "",
    document_context: str = "",
) -> List[Dict[str, str]]:
    """Какие файлы сделать в этом ответе и в каком порядке. [] – это не заказ на несколько файлов."""
    from openai_client import get_chat_response

    prompt = (
        f"{_current_date_note()}\n\n"
        f"Запрос пользователя:\n{user_text}\n"
        + (f"\nИстория диалога:\n{_tail(history_text, PLANNER_HISTORY_CHARS)}\n" if history_text else "")
        + (
            f"\nДокументы пользователя:\n{_trim_documents(document_context, user_text, PLANNER_DOC_CHARS)}\n"
            if document_context
            else ""
        )
        + "\nПользователь просит сделать несколько файлов (комплект, пакет, «три документа», «остальные документы»)? "
        "Составь список файлов, которые нужно сделать В ЭТОМ ответе, в порядке работы. "
        "Документы, уже сделанные раньше в этом чате, не включай, если их не просят переделать. "
        "Если просят только предложения, реестр, план, проверку или ответ текстом, а не сами файлы, "
        "или нужен всего один файл – верни пустой список.\n"
        "Для каждого файла: title – название документа; filename – короткое имя с номером и расширением, "
        "например 01_Отчет_2_6.docx (.docx, если формат не назван); brief – что в нём должно быть: "
        "исходный файл из чата, если документ переделывается, разделы, данные, требования к оформлению из задания. "
        "brief пиши так, чтобы исполнитель сделал документ целиком без переписки.\n"
        'Верни СТРОГО JSON: {"documents": [{"title": "...", "filename": "...", "brief": "..."}]}'
    )
    try:
        text, _, _, _ = await get_chat_response(
            [
                {"role": "system", "content": "Ты Computer - оркестратор. Отвечаешь только валидным JSON."},
                {"role": "user", "content": prompt + _desktop_work_instructions()},
            ],
            model=_clamped_planner_model(user_id),
            user_id=user_id,
            use_tools=False,
            reasoning_effort="low",
            use_skills=False,
        )
        items = json.loads(_clean_json_response(text)).get("documents") or []
    except Exception:
        logger.warning("Director: package planning failed", exc_info=True)
        return []
    docs: List[Dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        filename = re.split(r"[\\/]", str(item.get("filename") or "").strip())[-1]
        docs.append({
            "title": str(item["title"]).strip(),
            "filename": filename or f"{len(docs) + 1:02d}.docx",
            "brief": str(item.get("brief") or "").strip(),
        })
    return docs[:MAX_PACKAGE_DOCUMENTS]


def _package_document_employee(doc: Dict[str, str], index: int, total: int, user_text: str) -> Dict[str, str]:
    return {
        "role": f"Документ {index}/{total}: {doc['title']}"[:120],
        "task": (
            "load_skill documents. Сделай ОДИН документ полностью – только его, остальные сделают после тебя. "
            f"Документ: «{doc['title']}». Файл: komplekt/{doc['filename']}. "
            f"Что в нём: {doc['brief']} "
            f"Исходный запрос пользователя: «{(user_text or '')[:1500]}». "
            "Если документ переделывается из файла чата – сначала read_chat_document по точному имени. "
            "Напиши полный текст без заглушек и «[заполнить]», собери файл (.docx через bt_docx или формат из имени). "
            "Свой разбор markdown не пиши: bt_docx понимает #–######, списки и таблицы. Шрифт, поля и отступы "
            "по требованиям настраивай поверх готового файла python-docx, а не собирая абзацы вручную. "
            "Потом проверь собранный файл: разделы, полнота и оформление по требованиям из запроса и документов; "
            "не соответствует – исправь и пересобери. В конце workspace_glob: файл должен лежать. "
            "Ответ – 1-3 предложения: что в документе и что проверено."
        ),
        "model": FALLBACK_EMPLOYEE_MODEL,
    }


async def _run_package_one_by_one(
    docs: List[Dict[str, str]],
    user_text: str,
    user_id: int,
    status_msg: Any,
    document_context: str = "",
    history_text: str = "",
    has_images: bool = False,
) -> "Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]":
    """Документ за документом: сделал, проверил, выложил в чат – и только потом следующий."""
    import time
    from turn_scope import deliver_now

    total = len(docs)
    journal: List[Dict[str, Any]] = []
    sent: set[str] = set()
    done: List[str] = []
    failed: List[str] = []
    for index, doc in enumerate(docs, 1):
        await _update_status(status_msg, f"Готовлю документ {index} из {total} — {doc['title']}", 'file')
        employee = _clamp_employee_plan(
            {"new_employees": [_package_document_employee(doc, index, total, user_text)]}, user_id
        )["new_employees"][0]
        since = time.time()
        result: Dict[str, Any] = {}
        files: List[Dict[str, Any]] = []
        for attempt in range(2):
            result = await _execute_employee(
                employee, index, journal, user_id, document_context, history_text, has_images
            )
            files = [
                item for item in (await _new_files(user_id, since) or [])
                if str(item.get("filename") or "").casefold() not in sent
            ]
            if files:
                break
            employee = {**employee, "task": employee["task"] + " Прошлая попытка не оставила файла – собери его обязательно."}
        # Следующему сотруднику – короткая справка, а не весь текст документа.
        journal.append({**result, "result": _clamp_result(str(result.get("result") or ""))[:800]})
        if not files:
            failed.append(doc["title"])
            continue
        done.append(doc["title"])
        names = [str(item.get("filename") or "") for item in files]
        sent.update(name.casefold() for name in names)
        note = str(result.get("result") or "").strip()
        # Пустой финальный ответ клиент модели подменяет заглушкой – это не описание документа.
        if result.get("status") != "ok" or note.startswith(("Нет ответа от модели", "❌", "[Ошибка")):
            note = ""
        note = _sanitize_answer(note)[:700] if note else ""
        text = f"Готов документ {index} из {total}: «{doc['title']}»." + (f"\n\n{note}" if note else "")
        try:
            await deliver_now(text, files)
        except Exception:
            # Не выложился сейчас – уйдёт вместе с итоговым ответом.
            logger.exception("Director: failed to post package document %s", names)

    lines = [f"Готово документов: {len(done)} из {total}."]
    if failed:
        lines.append("Не получились: " + "; ".join(f"«{title}»" for title in failed) + ". Напишите «доделай» – продолжу с них.")
    reasoning = "\n\n".join(
        f"### {entry['role']}\n{entry['reasoning']}" for entry in journal if entry.get("reasoning")
    )
    search = [s for entry in journal for s in entry.get("search", [])]
    return "\n\n".join(lines), [], reasoning, search


@search_turn
@trace_director
async def get_director_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> "Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]":
    """Основная управляющая функция режима Computer."""
    from app.billing.quota import billing_pool
    from app.services.run_protocol import current_run, RunRecord

    from app.services.server_search import orchestrator_search
    search_token = orchestrator_search.set(True)
    token = billing_pool.set("computer")
    from app.services.autonomy import product_evidence
    product_token = product_evidence.set({})
    from app.services.conversation_context import workspaces
    record_token = current_run.set(RunRecord(requires_sources=_is_shopping_task(user_text, user_id),
        request_context={'current_request': user_text, 'workspaces': workspaces.get() or []}))
    try:
        answer, files, reasoning, sources = await _run_director(messages, user_text, user_id, status_msg)
        from app.services.engineering_io import guard_completion
        answer=guard_completion(answer,current_run.get())
        from app.services.orchestrator_metrics import mark_outcome
        mark_outcome(artifacts=len(files or []))
        current_run.get().link_excerpts(answer)
        logger.info('Run completed: elapsed_ms=%s reads=%s',
                    round((time.monotonic()-current_run.get().started)*1000),
                    current_run.get().timings)
        return answer, files, reasoning, current_run.get().enrich_sources(sources or [])
    finally:
        product_evidence.reset(product_token)
        current_run.reset(record_token)
        billing_pool.reset(token)
        orchestrator_search.reset(search_token)


async def _run_director(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> "Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]":
    import asyncio
    import time

    started = time.time()
    # BitClient explicit CAD intent and build opportunity
    from app.services.desktop_cad_completion import cad_task_from_history
    cad_user_task = cad_task_from_history(user_text, messages)
    from app.services.desktop_context import desktop_executor
    wants_file = _wants_file(user_text)
    forced_build = False
    # BitClient native CAD completion guard
    from app.services.desktop_cad_completion import required_cad_extensions, has_cad_deliverable, cad_builder_employee
    from app.services.desktop_context import desktop_capabilities, local_tool
    cad_extensions = required_cad_extensions(cad_user_task) if desktop_executor.get() is not None and "cad_native_results_v1" in desktop_capabilities.get() else ()
    cad_repairs = 0
    document_context = _extract_document_context(messages)
    history_text = _format_chat_history(messages)
    try:
        from app.services.chat_access import ingest_from_text

        ingest_from_text(user_id, user_text)
    except Exception:
        pass

    await _update_status(status_msg, "Разбираю задачу — Определяю нужный результат и порядок работы", 'plan')

    from app.services.task_checkpoints import resumed_journal, save as save_checkpoint
    journal: List[Dict[str, Any]] = list(resumed_journal.get() or [])
    from app.services.product_strategy import is_product_request
    from app.services.conversation_context import workspaces
    from app.services.autonomy import product_evidence, product_employee, verified_product
    initial_plan = None
    followup_id = None
    # Asked before a revision rewrites user_text with the old brief, which always looks like "build a site".
    asked_new_product = is_product_request(user_text) and not any(entry.get('product_id') for entry in journal)
    turn_has_images = packed_has_images(messages) or _turn_has_images(user_id)
    simple_without_project = not workspaces.get() and _is_light_task(user_text, document_context, turn_has_images, user_id)
    if desktop_executor.get() is None and workspaces.get() is not None and not journal and not simple_without_project:
        initial_plan = await _plan_round(user_text, journal, user_id, document_context, history_text)
        if initial_plan.get('status') == 'clarify' and initial_plan.get('questions'):
            from clarify import pack_search
            return initial_plan['questions'][0]['prompt'], [], '', pack_search(initial_plan['questions'])
        if initial_plan.get('workspace_action') == 'revise' and not _ordinary_work(user_text):
            followup_id = initial_plan.get('workspace_id')
            if followup_id not in {item['product_id'] for item in workspaces.get()}:
                raise ValueError('Выбранный проект не относится к этой беседе.')
    # create от планировщика само по себе не запускает приёмку: иначе доклад,
    # таблица или файл на Диск собираются как сайт, с тестами и архивом.
    product_build = desktop_executor.get() is None and not _ordinary_work(user_text) and (
        is_product_request(user_text) or bool(followup_id) or any(entry.get('product_id') for entry in journal))
    if (initial_plan is not None and not product_build
            and initial_plan.get('workspace_action') in {'revise', 'create'}
            and not initial_plan.get('new_employees')):
        initial_plan = {'status': 'done', 'new_employees': []}
    product_state = product_evidence.get()
    if product_state is None:
        product_state = {}
    if product_build:
        for entry in journal:
            if entry.get('product_id'):
                product_state['product_id'] = entry['product_id']
        if followup_id:
            # A new user turn must invalidate the old acceptance receipts before
            # the packaged-product fast path can decide there is nothing to do.
            await _update_status(status_msg, 'Открываю исходники созданного проекта', 'file')
            try:
                previous = await verified_product(user_id, followup_id, package=False)
                if previous.get('error') or not previous.get('path'):
                    raise ValueError('Исходники проекта недоступны')
                brief = str(previous.get('brief') or '')[:11000]
                revised_task = f'Доработай существующий проект.\nИсходные требования:\n{brief}\n\nНовые правки пользователя:\n{user_text[:4500]}'
                from app.services.sandbox_client import run_workspace_tool
                revision = json.loads(await run_workspace_tool('product_lifecycle', {
                    'action': 'revise', 'product_id': followup_id, 'brief': revised_task}, user_id))
                if revision.get('error') or revision.get('product_id') != followup_id:
                    raise ValueError('Не удалось открыть проект для правки')
                product_state.update(revision)
                user_text = revised_task
            except (ValueError, TypeError):
                return ('Не удалось открыть исходники ранее созданного проекта в облаке. '
                        'Прикрепите выданный ZIP-архив, чтобы продолжить работу с его файлами. '
                        'Новая версия пока не создана.'), [], '', []
    preflight = None
    phase_models: Dict[str, str] = {}
    round_num = 0
    turn_images = packed_has_images(messages) or _turn_has_images(user_id)
    has_images = wants_photo_research(user_text, turn_images)
    light = not product_build and not cad_extensions and _is_light_task(user_text, document_context, turn_images, user_id)
    from marketplace_verification import single_store_price_lookup
    price_lookup = not cad_extensions and not wants_file and single_store_price_lookup(user_text)
    light = light or price_lookup
    if _is_shopping_task(user_text, user_id):
        journal = []  # Fresh card/review/availability checks on each resumed shopping run.

    if _is_document_package_task(user_text):
        await _update_status(status_msg, "Составляю список документов — Определяю состав будущего комплекта", 'plan')
        docs = await _plan_package_documents(user_text, user_id, history_text, document_context)
        if len(docs) >= 2:
            return await _run_package_one_by_one(
                docs, user_text, user_id, status_msg, document_context, history_text, has_images
            )

    while round_num < MAX_ROUNDS and len(journal) < MAX_EMPLOYEES:
        from app.services.task_checkpoints import consume_steering
        steering = await consume_steering()
        user_text += steering
        if product_build and steering and product_state.get('product_id'):
            from app.services.sandbox_client import run_workspace_tool
            revision = json.loads(await run_workspace_tool('product_lifecycle', {
                'action': 'revise', 'product_id': product_state['product_id'], 'brief': user_text}, user_id))
            if revision.get('error'):
                raise ValueError('Не удалось применить уточнение к продукту: ' + revision['error'])
            product_state.update(revision)
        round_num += 1
        if product_build:
            if round_num == 1 and not journal and not product_state.get('product_id') and initial_plan is None:
                # Preserve essential clarification (e.g. an app with no purpose).
                # Stack selection and routine design choices stay autonomous.
                only_token = _clarify_only.set(True)
                try:
                    preflight = await _plan_round(user_text, journal, user_id, document_context, history_text)
                finally:
                    _clarify_only.reset(only_token)
                if preflight.get('status') == 'clarify' and preflight.get('questions'):
                    from clarify import pack_search
                    return preflight['questions'][0]['prompt'], [], '', pack_search(preflight['questions'])
            if product_state.get('product_id'):
                try:
                    fresh = await verified_product(user_id, product_state['product_id'], package=True)
                    if fresh.get('error'):
                        product_state.clear()
                    else:
                        product_state.update(fresh)
                except (ValueError, TypeError):
                    product_state.update(ready=False, packaged=False)
            employee = product_employee(user_text, product_state, journal)
            if employee is None:
                break
            phase_name = employee.get('product_phase') or 'build'
            cheap_build_failed = any(
                entry.get('product_phase') == 'build' and entry.get('model') not in {PLANNER_MODEL, SONNET_MODEL} for entry in journal
            )
            fresh_product = asked_new_product and not followup_id and (
                initial_plan is None or initial_plan.get('workspace_action') != 'revise')
            # A new product gets one strong builder, honoring Sol/Sonnet from the semantic plan.
            # A revision of an existing project stays the planner's call.
            if phase_name == 'build' and (fresh_product or cheap_build_failed) and PLANNER_MODEL in _employee_models(user_id):
                source = initial_plan if (initial_plan or {}).get('new_employees') else preflight
                picked = _strongest_hired_model((source or {}).get('new_employees'))
                builder = picked if picked in {PLANNER_MODEL, SONNET_MODEL} and picked in _employee_models(user_id) else PLANNER_MODEL
                employee['model'] = builder
                phase_models[phase_name] = builder
            elif phase_name in phase_models:
                employee['model'] = phase_models[phase_name]
            else:
                # The plan made for this turn already says what the work is worth: no second Sol planner call.
                source = initial_plan if (initial_plan or {}).get('new_employees') else preflight
                if not (source or {}).get('new_employees') and phase_name != 'brief':
                    source = await _plan_round(user_text, journal, user_id, document_context, history_text)
                # Research is not the dear step: the brief never inherits the build's Sol.
                ceiling = _SPEND_RANK[HAIKU_MODEL] if phase_name == 'brief' else None
                picked = _strongest_hired_model((source or {}).get('new_employees'), ceiling)
                if picked:
                    employee['model'] = picked
                    selected_stage = next((item for item in (source or {}).get('new_employees', []) if item.get('model') == picked), {})
                    if selected_stage.get('work_kind'):
                        employee['work_kind'] = selected_stage['work_kind']
                phase_models[phase_name] = employee['model']
            plan = _clamp_employee_plan({'status': 'continue', 'new_employees': [employee]}, user_id, user_text, document_context, journal)
        elif initial_plan is not None and round_num == 1:
            plan = initial_plan
        elif light and round_num == 1:
            # A short question with no files or tools: skip the Sol planner and its round trip.
            searching = needs_research(user_text, False) and not is_smalltalk(user_text)
            plan = {"status": "continue", "new_employees": [_light_research_employee(user_text)]} if searching else {
                "status": "done", "new_employees": [],
            }
        elif light and journal:
            if price_lookup or round_num >= 3 or not _research_needs_retry(journal):
                break
            # One bounded recovery pass, without another expensive planner call.
            plan = {"status": "continue", "new_employees": [_verify_employee(user_text)]}
        else:
            plan = await _plan_round(user_text, journal, user_id, document_context, history_text)
        plan = _enforce_caps(round_num, len(journal), plan)
        plan = _ensure_research_plan(round_num, plan, user_text, journal, has_images)
        plan = _enforce_caps(round_num, len(journal), plan)
        # BitClient CAD GUI execution
        from app.services.desktop_cad_completion import cad_gui_plan
        plan = cad_gui_plan(plan, cad_user_task)
        # BitClient reserved CAD build budget
        # Keep one employee slot for a native result check/build on the final round.
        if cad_extensions and round_num < MAX_ROUNDS:
            remaining_before_reserve = max(0, MAX_EMPLOYEES - len(journal) - 1)
            plan = {**plan, "new_employees": plan["new_employees"][:remaining_before_reserve]}

        if plan.get("status") == "clarify" and plan.get("questions"):
            from clarify import pack_search

            await _update_status(status_msg, "Подготавливаю уточняющие вопросы — Для продолжения нужен ваш выбор", 'plan')
            questions = plan["questions"]
            return questions[0]["prompt"], [], "", pack_search(questions)

        # Reserve the final opportunity for building instead of more probes/read-only work.
        from app.services.desktop_cad_completion import cad_employee_phase, unresolved_cad_errors
        cad_read_only_plan = bool(plan["new_employees"]) and all(
            cad_employee_phase(employee) in {"inspect", "verify"} for employee in plan["new_employees"]
        )
        if cad_extensions and (
            plan["status"] == "done" or not plan["new_employees"]
            or (unresolved_cad_errors(journal) and not any(
                cad_employee_phase(employee) in {"sdk_repair", "gui_geometry"} for employee in plan["new_employees"]
            ))
            or (cad_read_only_plan and (
                round_num >= 2 or round_num >= MAX_ROUNDS
                or len(journal) + len(plan["new_employees"]) >= MAX_EMPLOYEES
            ))
            or (round_num >= MAX_ROUNDS and not any(
                cad_employee_phase(employee) in {"simple_geometry", "complex_geometry", "sdk_repair", "gui_geometry"}
                for employee in plan["new_employees"]
            ))
        ):
            try:
                cad_files = json.loads(await local_tool("desktop_changed_files", {"native_cad_only": True}) or "[]")
            except (TypeError, ValueError):
                cad_files = None
            if not has_cad_deliverable(cad_files, cad_extensions) and cad_repairs < 2 and len(journal) < MAX_EMPLOYEES:
                cad_repairs += 1
                plan = _clamp_employee_plan(
                    {"status": "continue", "new_employees": [cad_builder_employee(cad_user_task, cad_extensions, journal=journal)]},
                    user_id, original_task=cad_user_task, journal=journal,
                )
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
            from orchestrator_activity import employee_activity
            kind, label = employee_activity(hired[0])
            await _update_status(status_msg, label, kind)
        else:
            await _update_status(status_msg, f"Работаю над {len(hired)} частями задачи параллельно — Затем объединю результаты", 'work')

        # BitClient live swarm collaboration
        from app.services.desktop_swarm import execute_swarm_batch
        results = await execute_swarm_batch(
            hired, round_num, journal, user_id, document_context, history_text, has_images, _execute_employee,
        )

        for employee, res in zip(plan["new_employees"], results):
            if isinstance(res, Exception):
                journal.append({
                    "round": round_num, "role": employee["role"], "task": employee["task"],
                    "model": employee["model"], "status": "error",
                    "result": f"[Ошибка при выполнении: {str(res)[:200]}]",
                })
            else:
                if product_build:
                    res['product_phase'] = employee.get('product_phase', 'build')
                    if product_state.get('product_id'):
                        res['product_id'] = product_state['product_id']
                journal.append(res)
        await asyncio.to_thread(save_checkpoint, journal, user_id)
        from app.services.orchestrator_budget import current_budget
        if current_budget.get() is not None and current_budget.get().exhausted:
            break

    if not journal:
        # This call can still search and browse. Writing belongs to the final,
        # tool-free synthesis after the observations have actually been collected.
        await _update_status(status_msg, "Разбираю вопрос и подбираю ответ", 'work')
        try:
            answer, reasoning, search = await _answer_directly(messages, user_id)
        except Exception as e:
            logger.error(f"Director direct answer failed: {e}", exc_info=True)
            answer, reasoning, search = f"Не удалось ответить: {str(e)[:200]}", "", []
        if not _is_shopping_task(user_text, user_id):
            return _sanitize_answer(answer), [], reasoning, search
        journal.append({"round": 0, "role": "Поисковые кандидаты", "model": DIRECT_ANSWER_MODEL, "status": "ok", "result": answer, "search": search, "reasoning": reasoning})

    if _is_shopping_task(user_text, user_id):
        await _update_status(status_msg, "Сверяю предложения на страницах магазинов — Проверяю доступные цены и условия", 'check')
        from marketplace_verification import verify_marketplace_cards
        journal.extend(await verify_marketplace_cards(user_text, journal, user_id=user_id))

    # Всегда, а не только когда просили файл: сотрудник мог собрать его по ходу дела.
    built_files = await _new_file_names(user_id, started)
    from app.services.orchestrator_metrics import mark_outcome
    mark_outcome(errors=sum(entry.get('status') == 'error' for entry in journal))
    await _update_status(status_msg, "Собираю итоговый ответ — Объединяю выводы и подготовленные файлы", 'work')
    from app.services.orchestrator_budget import current_budget
    budget_exhausted = current_budget.get() is not None and current_budget.get().exhausted
    if budget_exhausted and not product_build:
        mark_outcome(accepted=False)
        answer, compose_reasoning = ('Достигнут бюджет работы моделей. Выполненные действия и созданные файлы сохранены. '
            'Завершение всей задачи пока не подтверждено; продолжить можно с сохранённого состояния.'), ''
    elif product_build:
        # Completion is derived from receipts, never from a composer's claim.
        answer, compose_reasoning = '', ''
    else:
        answer, compose_reasoning = await _compose_answer(
            user_text, journal, user_id, history_text, document_context, built_files=built_files
        )
    if built_files and len(built_files) > 1:
        from turn_scope import choose_deliverables

        answer, chosen = _split_file_choice(answer, built_files)
        choose_deliverables(chosen)
    answer = _sanitize_answer(answer)
    if product_build:
        try:
            final_product = await verified_product(user_id, product_state.get('product_id', ''), package=True)
        except (ValueError, TypeError):
            final_product = {}
        if not final_product.get('packaged') or not final_product.get('ready'):
            from app.services.orchestrator_metrics import mark_outcome
            mark_outcome(accepted=False)
            gates = final_product.get('gates') or {'build': False, 'test': False}
            failed = [name for name, passed in gates.items() if not passed]
            if not failed:
                failed = ['упаковка проекта']
            answer = ('Продукт пока не прошёл приёмку: ' + ', '.join(failed) + '. Готовность не подтверждена. '
                      'Сохранённые исходники можно доработать в следующем запросе.\n\n' +
                      ('Папка проекта: ' + final_product['path'] if final_product.get('path') else 'Не удалось создать проверяемый проект.'))
        else:
            from app.services.orchestrator_metrics import mark_outcome
            mark_outcome(accepted=True)
            from app.services.autonomy import learn
            try:
                await asyncio.to_thread(learn, user_id, {
                    'problem': 'Сборка продукта на стеке ' + final_product['stack'],
                    'cause': 'Готовность подтверждается командами по текущей версии исходников.',
                    'standard': 'Для стека ' + final_product['stack'] + ' сохранять требования и запуск; выполнять build и test после правок, затем package.',
                }, final_product)
            except Exception:
                logger.warning('Product lesson could not be saved', exc_info=True)
            answer = ('Проект собран на стеке ' + final_product['stack'] + '. '
                      'Сборка и тесты текущей версии пройдены. Архив: ' + final_product['archive'] + '. '
                      'В README.md — команды запуска и размещения, в BRIEF.md — критерии приёмки.')
            if final_product['stack'] != 'python':
                answer += ' Браузерная проверка экранов 1440 и 390 px пройдена; снимки находятся в qa/ внутри архива.'
            from turn_scope import choose_deliverables
            choose_deliverables([final_product['archive']])

    if any(entry.get('live_verification') for entry in journal):
        from marketplace_verification import guard_answer_links
        answer=guard_answer_links(answer,journal)

    reasoning_sections = [
        f"### {entry['role']} (раунд {entry['round']})\n{entry['reasoning']}"
        for entry in journal
        if entry.get("reasoning")
    ]
    if compose_reasoning:
        reasoning_sections.append(compose_reasoning)
    search_results = [s for entry in journal for s in entry.get("search", [])]

    return answer, [], "\n\n".join(reasoning_sections), search_results
