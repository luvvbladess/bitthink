"""Conservative automatic routing. Unknown/high-risk work keeps the strong path."""
import os
import re
import json
import hashlib
from contextvars import ContextVar

ROUTINE_MODEL = 'gpt-6.1-terra'
POLICY_VERSION = 'economy-v1'
_HARD = re.compile(r'(?i)архитектур|рефактор|миграц|безопасност|уязвим|аудит|юрид|договор|контракт|расслед|доказат|криптограф|авторизац|аутентификац|architect|refactor|migration|security|vulnerab|\baudit\b|\blegal\b|\bcontract\b|investigat|cryptograph|authenticat|authoriz|medical|diagnos|\btax\b|oauth|\bcom\b|\bsdk\b|solidworks|sldprt|sldasm|\bcad\b|компас|геометр|топологи|loft|sweep|race.condition|deadlock|транзакц|налогов|медицин|диагноз|удали|удалени|очисти|форматируй.{0,12}диск|опубликуй|задеплой|деплой|\bdeploy\b|\bdelete\b|\bwipe\b|плат[её]ж|оплати')
_ROUTINE = re.compile(r'(?i)извлек|выпиши|вытащи|перечисли|составь список|список файлов|прочитай|открой|покажи|скачай|сохрани|переименуй|переведи|перевод|кратк\w* резюме|кратко перескажи|сделай резюме|суммари|отформатируй|форматирован|конвертир|преобразуй|исправь опечат|поменяй цвет|измени цвет|замени заголовок|extract|summarize|translate|format the|open the|list files|rename')
_TOOL_TARGET = re.compile(r'(?i)файл|папк|страниц|браузер|сайт|документ|таблиц|скриншот|\b(?:readme|csv|xlsx|docx|pdf|html)\b')
_OPEN_ENDED = re.compile(r'(?i)созда[йт]|разработ|реализ|построй|перепиши|настрой|проанализируй|спроектируй|разберись|implement|refactor|build an? |напиши.{0,30}(?:код|скрипт|прилож|бот)')
_VALIDATION_FAILURE = re.compile(r'(?i)syntaxerror|typeerror|assertionerror|compil|компиля|тест\w*.*(?:не прош|упал|ошиб)|validation|валидац|неверн\w*\s+(?:формат|структур|результат)|schema|sdk|hresult|model_not_found|unsupported.{0,40}model|нет ответа от модели')


def economy_enabled():
    return os.getenv('ORCHESTRATOR_ECONOMY', '1').strip().lower() not in {'0', 'false', 'off'}


def critical_task(task):
    return bool(_HARD.search(task or ''))


def routine_task(task: str, document_context: str = '') -> bool:
    """Only explicit bounded operations; length alone never makes work cheaper."""
    if not economy_enabled() or _HARD.search(task or '') or _OPEN_ENDED.search(task or ''):
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
_CHECK_COMMAND = re.compile(r'(?i)\bpytest\b|\bnpm(?:\.cmd)?\s+(?:run\s+)?(?:test|typecheck|build)\b|\btsc\b|\b(?:cargo|go|dotnet)\s+test\b|node\s+[^\r\n]*\b(?:test|smoke)[-\w]*\.mjs')


class ValidationState:
    """An actual failed test cannot be overwritten by unrelated successful work."""
    def __init__(self):
        self.checks = {}

    @property
    def failed(self):
        return any(not passed for passed in self.checks.values())

    def observe(self, name, args, result):
        command = str(args.get('command') or args.get('cmd') or '')
        if name != 'desktop_run_command' or not _CHECK_COMMAND.search(command):
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


def observe_validation(name, args, result):
    state = validation.get()
    if state is not None:
        state.observe(name, args, result)


def routine_employee(item: dict, original_task: str, context: str = '') -> bool:
    if not routine_task(original_task, context):
        return False
    assignment = str(item.get('role') or '') + ' ' + str(item.get('task') or '')
    return not _HARD.search(assignment)


ECONOMY_RULES = (
    'Экономия без потери результата: для короткого чтения, извлечения полей, перевода, '
    'фильтрации строк и простой сводки обычно достаточно одного gpt-6-luna, в том числе '
    'при работе с файлами и браузером. Не повышай модель только из-за наличия файла. '
    'gpt-6.1-terra — промежуточный выбор вместо Sol для точных небольших правок и '
    'ограниченных преобразований, когда Luna действительно недостаточно. '
    'Код и рассуждения — claude-haiku-5.5, коротко. Починка кода и сложный анализ — gpt-6-sol. '
    'Плотный договор, аудит или архитектура — один claude-opus-5.5. '
    'Геометрия и трудный SDK — gpt-6-astra в пределах доступного каталога. Не нанимай '
    'отдельного проверяющего для простой операции, если результат можно проверить инструментом. '
    'Арифметику, НДС, скидки, суммы, сортировку и преобразования считай через python_run '
    'или табличный движок; ответ модели по памяти не заменяет вычисление. '
    'При конкретной ошибке теста/компилятора/проверки подключи сильного сотрудника только '
    'для исправления. Передай готовые файлы, checkpoint и ошибку; сначала прочитай текущее '
    'состояние. Не повторяй вслепую выполненную запись, отправку, публикацию или действие компьютера.'
)
