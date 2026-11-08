"""Bound execution scope, not intelligence: small edits keep a capable coder."""
import re

CODE_EDIT_TOOLS = frozenset({
    'workspace_ls', 'workspace_glob', 'workspace_grep', 'workspace_read',
    'workspace_edit', 'workspace_write', 'workspace_run', 'python_run',
    'workspace_export_files', 'list_chat_files', 'read_chat_document', 'workspace_import_file',
    'load_skill', 'read_skill_resource', 'desktop_run_command', 'desktop_changed_files',
    'desktop_skill_list', 'desktop_skill_read',
})


CODE_CHANGE_RULES = (
    'Для правки существующего кода сначала найди конкретное место и выбери минимальное '
    'законченное исправление. Сохрани текущие API, стиль, стек и зависимости. '
    'Не вводи интерфейсы, фабрики, универсальные обёртки, новые слои, зависимости или '
    'реорганизацию файлов ради SOLID/DRY/«на будущее»: только если это нужно по задаче '
    'или для устранения подтверждённой причины ошибки. Явно заказанный рефакторинг выполняй. '
    'Одну связанную правку поручай одному исполнителю; не дели чтение, патч и проверку '
    'одного файла между коллегами. Если путь известен, сразу прочитай его, иначе используй '
    'один подходящий поиск. Независимые чтения целевых файлов и тестов запрашивай в одном '
    'пакете вызовов. Затем исправь и запусти подходящую проверку. '
    'Для точечной правки оставь соседние файлы и тесты нетронутыми: отдельные обходы '
    'каталогов, контрольные суммы и проверка всех соседних файлов для этого не нужны. '
    'Для локальной правки сначала целевой тест/сборка; расширяй проверки при изменении '
    'общего контракта, затронутых зависимостях или конкретной ошибке. Обязательные проверки '
    'репозитория сохраняются. После успешной проверки не повторяй её и не начинай новый '
    'рефакторинг без новых изменений. При провале исправляй причину, не ослабляй тесты. '
    'Если обнаружены риски безопасности, гонки или затронуты несколько подсистем, '
    'расширь анализ по фактам. Кратко сообщи результат и реально выполненную проверку. '
    'Проблему, замеченную попутно и не являющуюся причиной текущей просьбы, назови в ответе '
    'и не меняй из-за неё код. Ответ workspace_edit показывает ровно заменённый фрагмент: '
    'проверь его вместо повторного чтения файла, если замена подтверждена. '
    'Если правка задевает поведение, о котором не просили, верни лишнее. '
    'Когда просьба выполнена и проверка прошла, остановись.'
)

_EDIT = re.compile(r'(?i)^\s*(?:пожалуйста[, ]+)?(?:исправь|поправь|замени|поменяй|измени|добавь|убери|fix|change|replace|add|remove)\b')
_FILE = re.compile(r'(?i)(?<![\w])(?:[\w./\\-]+\.(?:py|cpp|cc|cxx|hpp|h|rs|cs|ts|tsx|js|jsx|c|go|java|vue|css|scss|html|json|toml|yaml|yml))(?![\w])')
_TARGET = re.compile(r'(?i)\b(?:опечатк\w*|подпис\w*\s+кнопк\w*|текст\w*\s+кнопк\w*|цвет\w*\s+кнопк\w*|typo|label)\b')
_RISK = re.compile(r'(?i)архитектур|рефактор|миграц|авторизац|аутентификац|безопасност|уязвим|гонк[аиу]|deadlock|race.condition|security|authenticat|authoriz|oauth|refactor|migration|плат[её]ж|криптограф|encrypt|payment|перепиши|переработай|во\s+вс[её]м|вс[её]\s+приложени|across\s+(?:all|the)|deploy|деплой|опублику|баз[ауы]\s+данных|database|удали\s+файл|delete\s+file|с\s+нуля|from\s+scratch|сохрани\s+на\s+диск|google|гугл|docx|pdf|xlsx|https?://')


_PROJECT_CHANGE = re.compile(
    r'(?i)(?:исправ|поправ|почини|доработ|\bfix\b|\bbug\b|баг|регресс|сломал|'
    r'(?:^|\s)(?:измени|замени|добавь|убери)\b)'
)
_NOT_PROJECT = re.compile(r'(?i)договор|письм|почт|календар|docx|ворд|презентац|\bxlsx\b|реферат|доклад|таблиц')
_QUESTION_ONLY = re.compile(r'(?i)^\s*(?:как|почему|объясни|расскажи|что\s+такое)\b')
_ASKS_CHANGE = re.compile(r'(?i)\b(?:исправь|поправь|почини|fix|добавь|убери|замени|измени)\b')


def show_change(path: str, old: str, new: str) -> str:
    def clip(value: str) -> str:
        value = value or ''
        return value if len(value) <= 1500 else value[:1500] + '\n…'

    return (
        f'Изменённый фрагмент {path}:\n'
        f'Было:\n{clip(old) or "(пусто)"}\n'
        f'Стало:\n{clip(new) or "(пусто)"}\n'
        'Это вся замена. Если она меняет поведение, о котором не просили, верни лишнее. '
        'Чужую проблему в этом фрагменте не исправляй: назови её в ответе.'
    )


def with_edit_preview(name: str, args: dict, result: str) -> str:
    """Show the coder the exact replacement, the same way an editor shows a diff."""
    if name != 'workspace_edit' or not isinstance(result, str):
        return result
    if not (result.startswith('Записал ') or result.startswith('Сохранён ')):
        return result
    if 'Изменённый фрагмент ' in result[:4000]:
        return result
    source = args or {}
    return result.rstrip() + '\n' + show_change(
        str(source.get('path') or ''), str(source.get('old_string') or ''), str(source.get('new_string') or ''))


def local_project_change(task: str) -> bool:
    """A fix in the open project belongs to one coding agent, not a hiring round."""
    text = (task or '').strip()
    if not text or len(text) > 8000:
        return False
    directive = text.split('```', 1)[0]
    if not _PROJECT_CHANGE.search(directive):
        return False
    if _QUESTION_ONLY.search(directive) and not _ASKS_CHANGE.search(directive):
        return False
    if _NOT_PROJECT.search(directive):
        return False
    from app.services.orchestrator_policy import critical_task
    return not critical_task(directive)


def code_change_rules(task: str) -> str:
    from app.services.subject_guidance import subject_for_query
    return CODE_CHANGE_RULES if _FILE.search(task or '') or subject_for_query(task) == 'code' else ''


def bounded_code_change(task: str) -> bool:
    """Opt in only to a concrete local edit. 'Simple' alone is never evidence."""
    text = (task or '').strip()
    if not text or len(text) > 4000 or not _EDIT.search(text):
        return False
    # Code is data; inspect the directive, not keywords inside a fenced example.
    directive = text.split('```', 1)[0]
    directive = re.sub(r'(?i)\b(?:без\s+(?:постороннего\s+)?рефакторинга|no\s+refactor(?:ing)?)\b', '', directive)
    from app.services.orchestrator_policy import critical_task
    if critical_task(directive) or _RISK.search(directive) or re.search(r'(?i)отправ|\bsend\b|upload|скачай|загрузи|\bssh\b|publish|install|установи|browser|браузер|почт|шифров|\bjwt\b|architect|rewrite|\b(?:whole|entire)\b|весь\s+(?:api|код|проект)|полностью|нов\w*\s+(?:подсистем\w*|сервис\w*|api\b)', directive):
        return False
    targets = re.sub(r'(?i)\b(?:не\s+меняй|не\s+трогай|do\s+not\s+change)\b[^\n]*', '', directive)
    files = {m.group(0).lower() for m in _FILE.finditer(targets)}
    if len(files) > 2:
        return False
    return bool(files or _TARGET.search(directive))
