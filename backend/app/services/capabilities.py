"""Truthful capability contracts, separate from instructional skill availability."""
GROUPS = {
    'web': ('Поиск и чтение сайтов', ['server_search', 'browse_page'], 'Поиск с сервера без платного API; фрагмент выдачи не равен странице. Домашний читатель только для российских магазинов, обычные страницы читаются точечно.'),
    'history': ('История и вложения', ['recent_chats', 'search_chats', 'list_chat_files', 'read_chat_document'], 'Только доступные этому пользователю беседы; не полноценная общая wiki.'),
    'projects': ('Рабочая область проекта', ['project_search', 'project_read', 'project_file_open', 'project_result', 'project_result_read', 'project_result_patch', 'project_purchase_plan', 'project_purchase_offer'], 'Проекты в боковом списке: личные беседы, постоянные оригиналы материалов, память и редактируемые таблицы/отчёты/слайды с версиями и экспортом XLSX/DOCX/PPTX. Пилот закупки 1–20 позиций; предложения сохраняются с цитатами о цене/наличии из прочитанной карточки. Создание плана не подтверждает наличие и не собирает корзины. Общих проектов с участниками пока нет.'),
    'files': ('Файлы песочницы', ['workspace_ls', 'workspace_read', 'workspace_write', 'python_run'], 'Оркестратор/Astra, рабочая среда пользователя; чтение файла не доказывает визуальную проверку.'),
    'data': ('Вычисления', ['python_run', 'workspace_read'], 'Оркестратор/Astra; база данных требует отдельного подключения.'),
    'connections': ('Внешние сервисы и MCP', ['list_connectors', 'mcp_discover', 'mcp_call', 'http_request'], 'Нужен доступ владельца. Подключение и разрешённые инструменты проверяются отдельно.'),
    'skills': ('Личные инструкции', ['list_skills', 'load_skill', 'save_skill', 'read_skill_resource'], 'До 20 личных навыков; пакет 10 МБ и 100 файлов. Общие навыки можно выключать.'),
    'tasks': ('Фоновые задачи', ['task_list', 'task_create', 'task_control'], 'Pro и личная беседа. Повтор по интервалу от 5 минут до 30 дней, календарного cron и event-триггеров нет.'),
    'studio': ('Холст и презентации', ['studio_build'], 'Поддерживаемый JSON-spec и штатная Студия; не универсальный хостинг произвольного приложения.'),
    'engineering': ('Чертежи и реконструкция', ['engineering_import','engineering_read_page','engineering_build'], 'Облачный Оркестратор: предварительная 2D-КД PDF/SVG/DXF и проверка размеров/комплектности. Источники и допущения разделены. Не заменяет изготовление, испытания или параметрическую 3D CAD-модель.'),
    'device': ('Локальное устройство', ['desktop_skill_list', 'desktop_skill_read', 'desktop_run_command'], 'Только подключённый BitClient. Домашний читатель маркетплейсов не даёт доступ к локальным файлам.'),
    'media': ('Медиа', [], 'Используйте штатную Студию для поддерживаемых изображений; произвольные аудио/видео-генераторы не подключены автоматически.'),
    'voice': ('Исходящие звонки', [], 'Штатного исполнителя звонков нет; возможен сценарий или отдельно подключённый MCP.'),
    'health': ('Медицинские источники', [], 'Штатных HealthKit/EHR-коннекторов нет; возможны пользовательские выгрузки или отдельно подключённый MCP.'),
    'databricks': ('Databricks', [], 'Штатного CLI и авторизованного workspace нет; требуется отдельное подключение.'),
}


def dependency_note(groups: list[str]) -> str:
    return 'Зависимости навыка:\n' + '\n'.join(f'- {GROUPS[g][0]}: {GROUPS[g][2]}' for g in groups if g in GROUPS)


def capability_catalog() -> dict:
    from computer_tools import COMPUTER_TOOL_NAMES
    return {
        'contract': 'Это реестр поддерживаемых функций, не подтверждение подключений или успешного выполнения. Учитывай инструменты текущего вызова и ограничения тарифа/среды.',
        'model_selection': 'automatic',
        'modes': ['Экспресс', 'Оркестратор', 'Студия', 'Поиск', 'Исследование', 'Astra', 'Документы'],
        'groups': [{'id': name, 'title': title, 'tools': [tool for tool in names if tool in COMPUTER_TOOL_NAMES],
                    'status': 'supported_with_conditions' if names or name == 'projects' else 'requires_adapter', 'constraint': constraint}
                   for name, (title, names, constraint) in GROUPS.items()],
        'native_features': ['Российские маркетплейсы и домашний читатель', 'План закупки BOM', 'ГОСТ/ЕСКД и CAD', 'Редактируемые документы', 'Оплата по российским тарифам'],
    }
