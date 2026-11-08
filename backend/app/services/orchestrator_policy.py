"""Conservative automatic routing. Unknown/high-risk work keeps the strong path."""
import os
import re
import json
import hashlib
from contextvars import ContextVar

ROUTINE_MODEL = 'gpt-6.1-terra'
POLICY_VERSION = 'calibration-v2'
_HARD = re.compile(r'(?i)архитектур|рефактор|миграц|безопасност|уязвим|аудит|юрид|договор|контракт|расслед|доказат|криптограф|авторизац|аутентификац|architect|refactor|migration|security|vulnerab|\baudit\b|\blegal\b|\bcontract\b|investigat|cryptograph|authenticat|authoriz|medical|diagnos|\btax\b|oauth|\bcom\b|\bsdk\b|solidworks|sldprt|sldasm|\bcad\b|компас|геометр|топологи|loft|sweep|race.condition|deadlock|транзакц|налогов|медицин|диагноз|удали|удалени|очисти|форматируй.{0,12}диск|опубликуй|задеплой|деплой|\bdeploy\b|\bdelete\b|\bwipe\b|плат[её]ж|оплати')
_ROUTINE = re.compile(r'(?i)извлек|выпиши|вытащи|перечисли|составь список|список файлов|прочитай|открой|покажи|скачай|сохрани|переименуй|переведи|перевод|кратк\w* резюме|кратко перескажи|сделай резюме|суммари|отформатируй|форматирован|конвертир|преобразуй|исправь опечат|поменяй цвет|измени цвет|замени заголовок|extract|summarize|translate|format the|open the|list files|rename')
_TOOL_TARGET = re.compile(r'(?i)файл|папк|страниц|браузер|сайт|документ|таблиц|скриншот|\b(?:readme|csv|xlsx|docx|pdf|html)\b')
_OPEN_ENDED = re.compile(r'(?i)созда[йт]|разработ|реализ|построй|перепиши|настрой|проанализируй|спроектируй|разберись|implement|refactor|build an? |напиши.{0,30}(?:код|скрипт|прилож|бот)')
_VALIDATION_FAILURE = re.compile(r'(?i)syntaxerror|typeerror|assertionerror|compil|компиля|тест\w*.*(?:не прош|упал|ошиб)|validation|валидац|неверн\w*\s+(?:формат|структур|результат)|schema|sdk|hresult|model_not_found|unsupported.{0,40}model|нет ответа от модели')

# These are execution hints, not authorization. Quoted source text must not
# turn a translation into a payment or a draft into a mailbox operation.
_TEXT_TRANSFORM = re.compile(r'(?i)^\s*(?:переведи|перепиши|перефразируй|сократи|отредактируй|исправь\s+(?:только\s+)?опечатки|извлеки|кратко\s+перескажи)\b')
_TEXT_CREATE = re.compile(r'(?i)^\s*(?:напиши|составь|подготовь)\b.{0,70}\b(?:письмо|сообщение|поздравление|объявление|пост|план\s+(?:изучения|обучения))\b')
_TEXT_ACTION = re.compile(r'(?i)\b(?:отправь|отправить|отправляй|прочитай|открой|скачай|загрузи|удали|опубликуй|найди|поищи|зайди|подключись|приложи|проверь\s+(?:почту|ящик))\b|https?://|\b(?:pdf|docx|xlsx|csv|pptx)\b|\b(?:файл\w*|вложени\w*|прикрепл\w*)\b')
_REASONING_RISK = re.compile(r'(?i)\b(?:докажи|доказать|prove|proof|инсульт|инфаркт|отравление|передозировка)\b|перекосило\s+лицо|невнятн\w*\s+речь|не\s+проверя\w*.{0,15}подпис')


def calculation_task(task: str) -> bool:
    """Arithmetic on supplied quantities is not web research about prices."""
    text = task or ''
    return (len(re.findall(r'\d+(?:[.,]\d+)?', text)) >= 2
            and bool(re.search(r'(?i)посчитай|рассчитай|вычисли|сколько\s+(?:платить|месяцев)|на\s+сколько\s+процент|какую\s+скидку|проверь.{0,30}(?:вычислен|расч[её]т|python|инструмент)', text))
            and not re.search(r'(?i)https?://|\b(?:сегодня|актуальн\w*|курс|котировк\w*)\b|найди\s+(?:цен|стоим)|поиск\s+в\s+интернет', text))


def chat_reasoning_task(task: str) -> bool:
    """A bounded explanation may need a strong model, but not a team of agents."""
    text = task or ''
    if len(text) > 1800 or not re.search(r'(?i)^\s*(?:почему|объясни|докажи|как\s+исправить)\b|какие\s+риски|что\s+исправить|что\s+делать\s+прямо\s+сейчас', text):
        return False
    text = re.sub(r'(?i)без\s+создания\s+файлов|не\s+создавай\s+файлы', '', text)
    return not re.search(r'(?i)https?://|\b(?:прикрепл\w*|вложени\w*|скачай|открой|прочитай|исправь|внеси|реализуй|сохрани|отправь|создай|опубликуй|запусти|настрой|подключись|зайди|проверь\s+(?:почту|ящик|проект|сервер))\b', text)


def bounded_text_task(task: str) -> bool:
    """Only explicit text operations; unknown goals keep the existing planner.

    Source after a colon/quote is data. External actions even after that source
    still prevent this shortcut; an opt-out of sending alone is harmless.
    """
    text = (task or '').strip()
    # A short, explicitly offline conversation-preparation question needs a
    # written answer, not a planner/team/composer loop. Inspect the whole request
    # here: quoted actions, attachments and expert topics must not slip through.
    if len(text) <= 1000 and re.match(r'(?i)^как\s+подготовиться\s+к\s+разговору\b', text):
        from app.services.request_intent import forbids_web
        if (forbids_web(text) and not _HARD.search(text) and not _REASONING_RISK.search(text)
                and not _TEXT_ACTION.search(text)
                and not re.search(r'(?i)актуальн|сегодня|\b(?:цен\w*|курс\w*|закон\w*|лечение|лекарств\w*)\b', text)):
            return True
    directive, _, inline_text = text.partition('\n')
    if (len(text) <= 4000 and len(inline_text.splitlines()) >= 2
            and re.fullmatch(r'(?i)удали только (?:первую|вторую|третью|последнюю) строку\. '
                             r'верни сам текст, без оформления\.', directive)):
        return True
    if not text or len(text) > 4000 or not (_TEXT_TRANSFORM.search(text) or _TEXT_CREATE.search(text)):
        return False
    if _TEXT_TRANSFORM.search(text) and not re.search(r'[:«"\n].*\S', text, re.S):
        return False
    head = re.split(r'[:«"\n]', text, maxsplit=1)[0]
    # Do not weaken expert analysis or a translation of an unseen document.
    if _HARD.search(head) or _REASONING_RISK.search(head):
        return False
    actions = re.sub(r'(?i)\b(?:ничего\s+)?не\s+(?:отправляй|отправлять|отправляйте)\b', '', text)
    # A quoted sentence may mention a file; only the directive controls that.
    if _TEXT_ACTION.search(re.sub(r'(?i)\b(?:ничего\s+)?не\s+(?:отправляй|отправлять|отправляйте)\b', '', head)):
        return False
    if re.search(r'(?i)(?:создай|подготовь|сделай|собери|приложи).{0,45}(?:файл|docx|pdf|xlsx|презентац|документ|таблиц|архив)', actions):
        return False
    return not re.search(r'(?i)\b(?:отправь|опубликуй|загрузи|скачай|удали)\b|сохрани\s+(?:в\b|на\b|как\b|файл|документ|результат|рядом|таблиц)|\bв\s+(?:pdf|docx|word|xlsx|pptx)\b|на\s+скачиван', actions)


def bounded_text_revision(task: str, messages) -> bool:
    """Inherit only a recent, explicit text draft; never an unrelated old task."""
    text = (task or '').strip()
    from routing import packed_has_open_documents
    if packed_has_open_documents(messages) or any(row.get('attachment') or isinstance(row.get('content'), list) for row in messages or []):
        return False
    previous = next((row.get('content', '') for row in reversed(messages or []) if row.get('role') == 'assistant'), '')
    if isinstance(previous, str) and ('```' in previous or '~~~' in previous):
        return False
    users = [row['content'].strip() for row in messages or [] if row.get('role') == 'user' and isinstance(row.get('content'), str)]
    if users and users[-1] == text:
        users.pop()
    # shortcut: trace at most six consecutive revisions; older context uses normal routing.
    for index, candidate in enumerate([text, *reversed(users[-6:])]):
        revision = (len(candidate) <= 300 and re.search(
            r'(?i)^(?:а\s+теперь\s+)?(?:'
            r'(?:сделай|перепиши|сократи|измени)\b.{0,80}(?:теплее|короче|вежливее|официальн|дружелюбн|тон)|'
            r'(?:ещ[её]\s+)?(?:короче|теплее|вежливее)\b|убери\s+вступление\b|'
            r'оставь\s+только\s+(?:сам[оё]\s+)?(?:сообщение|письмо)\b)', candidate))
        scope = re.sub(
            r'(?i)сохрани\s+(?:все\s+)?(?:ограничени\w*|факт\w*|смысл|цифр\w*|дат\w*|'
            r'срок\w*|имен\w*|обращени\w*|день(?:\s+и\s+время)?|время)\b', '', candidate)
        actions = _TEXT_ACTION.search(scope) or re.search(r'(?i)отправ|опублику|сохрани|скачай|запусти|выполни|установи|посчитай|рассчитай|вычисли|пересчитай|инструмент|файл|прикрепл|вложени|источник|актуальн|документаци|проверь|сверь|найди|поищи|\b(?:docx|pdf|xlsx|pptx|csv|word|excel)\b|https?://', scope)
        if revision and not actions and not critical_task(candidate):
            continue
        if index == 0:
            return False
        if actions:
            return False
        from app.services.subject_guidance import subject_for_query
        if subject_for_query(candidate) in {'code', 'engineering'}:
            return False
        from app.services.response_policy import compact_answer_kind
        return bounded_text_task(candidate) or (bool(re.search(r'(?i)\bтолько\s+(?:сообщение|письмо)\b', candidate)) and compact_answer_kind(candidate) == 'text')
    return False


def economy_enabled():
    return os.getenv('ORCHESTRATOR_ECONOMY', '1').strip().lower() not in {'0', 'false', 'off'}


def critical_task(task):
    return bool(_HARD.search(task or '') or _REASONING_RISK.search(task or ''))


def routine_task(task: str, document_context: str = '') -> bool:
    """Only explicit bounded operations; length alone never makes work cheaper."""
    if not economy_enabled() or critical_task(task) or _OPEN_ENDED.search(task or ''):
        return False
    # A legal/medical source is not a generic text attachment to downgrade.
    if _HARD.search((document_context or '')[:12000]):
        return False
    return bool(_ROUTINE.search(task or '')) and len(task or '') <= 1800


def routine_tool_task(task: str) -> bool:
    return routine_task(task) and bool(_TOOL_TARGET.search(task or ''))


def needs_recovery(journal) -> bool:
    """Not quota/network errors, and never a licence to replay a previous action."""
    checks = {}
    for entry in journal or []:
        checks.update(entry.get('validation_checks') or {})
    for entry in journal or []:
        if entry.get('status') != 'error':
            continue
        if entry.get('validation_failed'):
            failed = [key for key, passed in (entry.get('validation_checks') or {}).items() if not passed]
            if not failed or any(not checks.get(key, False) for key in failed):
                return True
        elif _VALIDATION_FAILURE.search(str(entry.get('result') or '')[:4000]):
            return True
    return False


validation = ContextVar('orchestrator_validation', default=None)
_CHECK_COMMAND = re.compile(r'(?i)\bpytest\b|\bnpm(?:\.cmd)?\s+(?:run\s+)?(?:test|typecheck|build)\b|\btsc\b|\b(?:cargo|go|dotnet)\s+(?:test|check|build)\b|\bpython(?:3|\.exe)?\s+-m\s+(?:unittest|pytest|compileall)\b|node\s+--test\b|\bctest\b|\bcmake\s+--build\b|node\s+[^\r\n]*\b(?:test|smoke)[-\w]*\.mjs')


class ValidationState:
    """An actual failed test cannot be overwritten by unrelated successful work."""
    def __init__(self):
        self.checks = {}
        self.wrote_code = False
        self.checked_after_write = False
        self.write_failed = False

    @property
    def failed(self):
        return any(not passed for passed in self.checks.values())

    def observe(self, name, args, result):
        if name in {'workspace_write', 'workspace_edit'}:
            self.checked_after_write = False
            self.write_failed = True
            try:
                data = json.loads(result)
            except (ValueError, TypeError):
                data = None
            if (args.get('path') and re.match(r'^(?:Записал |Сохранён )', str(result))) or (isinstance(data, dict) and not data.get('error') and (
                    data.get('ok') is True or data.get('success') is True
                    or data.get('written') is True or data.get('status') == 'ok')):
                self.wrote_code = True
                self.write_failed = False
        command = str(args.get('command') or args.get('cmd') or '')
        if name == 'workspace_run':
            argv = args.get('argv') or []
            command = ' '.join(argv) if isinstance(argv,list) and all(isinstance(x,str) for x in argv) else ''
        if name not in {'desktop_run_command','workspace_run'} or not (
                _CHECK_COMMAND.search(command) or (name == 'workspace_run' and re.search(r'^(?:gcc|g\+\+|cc|c\+\+|javac|rustc)\b|python3?\s+-m\s+unittest|node\s+--test|npm\s+(?:run\s+)?(?:build|test)|npx\s+tsc',command))):
            return
        code = None
        try:
            data = json.loads(result)
            if isinstance(data, dict):code = data.get('exit_code', data.get('exitCode'))
        except (ValueError,TypeError):
            match = re.search(r'Код завершения:\s*(-?\d+)\s*$', str(result))
            if match:code = int(match.group(1))
        if isinstance(code, int) and not isinstance(code, bool):
            key = hashlib.sha256(command.strip().encode()).hexdigest()
            self.checks[key] = code == 0
            self.checked_after_write = self.wrote_code and not self.write_failed and code == 0


def observe_validation(name, args, result):
    state = validation.get()
    if state is not None:
        state.observe(name, args, result)


def routine_employee(item: dict, original_task: str, context: str = '') -> bool:
    if not routine_task(original_task, context):
        return False
    assignment = str(item.get('role') or '') + ' ' + str(item.get('task') or '')
    return not critical_task(assignment)


ECONOMY_RULES = (
    'Экономия без потери результата: для короткого чтения, извлечения полей, перевода, '
    'фильтрации строк и простой сводки обычно достаточно одного дешёвого исполнителя. '
    'Классификацию и извлечение из текста поручай glm-5.3-flash, а ограниченные операции с файлами '
    'и мелкие правки — тоже glm-5.3-flash, если модель есть в доступном каталоге. '
    'Для иных простых этапов оставляй gpt-6-luna, в том числе '
    'при работе с файлами и браузером. Не повышай модель только из-за наличия файла. '
    'gpt-6.1-terra — промежуточный выбор вместо Sol для точных небольших правок и '
    'ограниченных преобразований, когда Luna действительно недостаточно. '
    'Модель выбираешь ты. Luna — поиск, чтение, извлечение, черновик. '
    'Haiku — короткий код и рассуждение, не длинная сборка. '
    'Terra — точная мелкая правка, если более дешёвый исполнитель не справляется. '
    'Для сложной сборки выбери одного gpt-6-sol или claude-sonnet-5.5; их базовая цена одинакова. '
    'Не дублируй одну работу несколькими сильными моделями. Второй сильный этап — только для новой '
    'необходимой работы или исправления конкретной ошибки с сохранённых исходников. '
    'Haiku дешевле только при коротком контексте; свыше 100 тысяч входных токенов цена растёт в пять раз. '
    'После подтверждённой приёмки заверши этап, не переделывай готовый результат. '
    'Плотный договор, аудит или архитектура — один claude-opus-5.5. '
    'Геометрия и трудный SDK — gpt-6-astra в пределах доступного каталога. Не нанимай '
    'отдельного проверяющего для простой операции, если результат можно проверить инструментом. '
    'Арифметику, НДС, скидки, суммы, сортировку и преобразования считай через python_run '
    'или табличный движок; ответ модели по памяти не заменяет вычисление. '
    'При конкретной ошибке теста/компилятора/проверки подключи сильного сотрудника только '
    'для исправления. Передай готовые файлы, checkpoint и ошибку; сначала прочитай текущее '
    'состояние. Не повторяй вслепую выполненную запись, отправку, публикацию или действие компьютера.'
)
