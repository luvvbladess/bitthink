"""User-facing intent labels. These describe work starting, never proof of success."""
from pathlib import PurePosixPath


def filename(value) -> str:
    return PurePosixPath(str(value or '').replace('\\', '/')).name[:80]


def employee_activity(employee: dict) -> tuple[str, str]:
    phase = employee.get('product_phase')
    if phase in {'brief', 'research', 'discover'}:
        return 'plan', 'Изучаю примеры и требования к результату'
    if phase == 'build':
        return 'file', 'Собираю рабочую версию проекта'
    if phase in {'verify', 'test', 'review'}:
        return 'check', 'Проверяю рабочую версию проекта'
    role = str(employee.get('role') or '').lower()
    if any(word in role for word in ('провер', 'вериф', 'ревью', 'тест')):
        return 'check', 'Проверяю материалы и ищу возможные ошибки'
    if any(word in role for word in ('документ', 'docx', 'редактор')):
        return 'file', 'Подготавливаю документ по заданию'
    if any(word in role for word in ('поиск', 'исслед', 'источник')):
        return 'search', 'Подбираю информацию для задачи'
    if any(word in role for word in ('сравн', 'аналит')):
        return 'work', 'Сопоставляю данные и готовлю выводы'
    return 'work', 'Разбираю материалы и готовлю решение'


def tool_activity(name: str, args: dict) -> tuple[str, str] | None:
    if name == 'product_lifecycle':
        return {
            'start': ('plan', 'Сохраняю требования к проекту'),
            'install': ('prepare', 'Подготавливаю инструменты для сборки проекта'),
            'build': ('file', 'Собираю рабочую версию проекта'),
            'test': ('check', 'Запускаю проверки проекта'),
            'smoke': ('check', 'Проверяю запуск и отображение проекта'),
            'package': ('file', 'Упаковываю проект для скачивания'),
        }.get(str(args.get('action')), ('work', 'Проверяю состояние проекта'))
    short = filename(args.get('path') or args.get('filename'))
    detail = f' — {short}' if short else ''
    if name == 'workspace_write':
        ext = PurePosixPath(short).suffix.lower()
        title = {'.docx': 'Собираю документ', '.pdf': 'Подготавливаю PDF', '.xlsx': 'Создаю таблицу',
                 '.pptx': 'Собираю презентацию', '.html': 'Собираю страницу', '.zip': 'Упаковываю файлы',
                 '.py': 'Подготавливаю обработку данных', '.js': 'Подготавливаю код проекта'}.get(ext, 'Сохраняю рабочий файл')
        return 'file', title + detail
    actions = {
        'swarm_read': ('work', 'Сверяю промежуточные результаты'),
        'swarm_publish': ('work', 'Передаю результаты для дальнейшей работы'),
        'swarm_send': ('work', 'Согласовываю детали выполнения задачи'),
        'workspace_ls': ('file', 'Смотрю доступные файлы задачи'),
        'workspace_read': ('file', 'Читаю материалы задачи' + detail),
        'workspace_edit': ('file', 'Вношу изменения в файл' + detail),
        'workspace_delete': ('file', 'Удаляю рабочий файл' + detail),
        'workspace_grep': ('file', 'Ищу нужные сведения в файлах'),
        'workspace_glob': ('file', 'Ищу файлы по заданию'),
        'workspace_import_file': ('file', 'Переношу вложение в проект'),
        'workspace_export_files': ('file', 'Подготавливаю файлы для скачивания'),
        'python_run': ('work', 'Обрабатываю данные для задачи — Выполняю подготовленный сценарий'),
        'pip_install': ('prepare', 'Подготавливаю инструменты — Они нужны для обработки данных и сборки файлов'),
        'list_skills': ('prepare', 'Подбираю инструкции для задачи'),
        'load_skill': ('prepare', 'Изучаю инструкции по выполнению задачи'),
        'skill_resource': ('prepare', 'Читаю дополнительные инструкции'),
        'save_skill': ('file', 'Сохраняю инструкцию для следующих задач'),
        'delete_skill': ('file', 'Удаляю сохранённую инструкцию'),
        'list_connectors': ('prepare', 'Проверяю доступные подключения'),
        'mcp_discover': ('prepare', 'Проверяю возможности подключённого сервиса'),
        'mcp_call': ('work', 'Выполняю действие в подключённом сервисе'),
        'ssh_exec': ('ssh', 'Выполняю действие на подключённом сервере'),
        'http_request': ('api', 'Обращаюсь к подключённому сервису'),
        'engineering_build': ('file', 'Создаю комплект чертежей'),
    }
    return actions.get(name)
