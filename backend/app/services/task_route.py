"""Route a turn the way ChatGPT and Claude do: name the requested result, then act.

OpenAI function calling leaves tool_choice on auto: the model calls a tool only when
the reply cannot be completed without it. Anthropic's routing workflow classifies the
input and sends it to one specialized path. Their prompting guide says not to start
an implementation when the request is ambiguous: answer instead.
"""
import json
import re

from app.services.product_strategy import expected_deliverable

ACTIONS = frozenset({'reply', 'file', 'product', 'revise', 'research'})

ROUTE_INSTRUCTIONS = """Ты определяешь, какой результат человек хочет получить в этом сообщении. Ты ничего не создаёшь и не вызываешь инструменты.

Сборка, правка проекта, файл и поиск — это инструменты. Их выбирают только если без них просьбу нельзя выполнить. Ответ в чате инструментом не является.

Смысл бери из того, что нужно вернуть человеку, а не из соседних слов. «Сайт», «лендинг», «приложение» и «бот» часто называют тему текста, а не продукт, который надо собрать. Если внутри запрошенного промпта или ТЗ написано «создай сайт», результатом остаётся промпт или ТЗ.

action:
- reply — текст в чате: промпт, ТЗ, план, название, объяснение, идея, письмо, кусок кода.
- file — отдельный файл, который прямо попросили: документ, таблица, презентация, отчёт.
- product — нужно собрать работающий сайт, приложение, бота, сервис или дашборд.
- revise — нужно изменить проект из <projects>, а не написать текст о нём.
- research — нужно найти или проверить факт, цену, место или источник.

Если непонятно, собирать продукт или ответить текстом, выбирай reply.
revise допустим только для id из <projects>. Если проекта нет, не ставь revise.
workspace_id заполняй только для revise, иначе пустая строка.
goal — одна короткая фраза: что именно человек получит.

<examples>
<example><message>сделай промпт для сайта кофейни</message><route>{"action":"reply","goal":"промпт для сайта кофейни","workspace_id":""}</route></example>
<example><message>напиши промпт. Текст промпта: создай современный лендинг</message><route>{"action":"reply","goal":"промпт, который описывает лендинг","workspace_id":""}</route></example>
<example><message>сделай сайт по этому промпту: тёмная тема и форма заявки</message><route>{"action":"product","goal":"сайт по присланному промпту","workspace_id":""}</route></example>
<example><message>напиши промпт и собери по нему лендинг</message><route>{"action":"product","goal":"лендинг, собранный по промпту","workspace_id":""}</route></example>
<example><message>шрифты бы покрупнее</message><projects>[{"product_id":"p1"}]</projects><route>{"action":"revise","goal":"более крупные шрифты в текущем проекте","workspace_id":"p1"}</route></example>
<example><message>оформи доклад в ворд</message><route>{"action":"file","goal":"доклад в документе Word","workspace_id":""}</route></example>
<example><message>найди актуальную цену подписки</message><route>{"action":"research","goal":"проверенная цена подписки","workspace_id":""}</route></example>
</examples>

Верни только JSON: {"action":"reply|file|product|revise|research","goal":"...","workspace_id":""}"""


def route_user_prompt(user_text, projects, history):
    listed = []
    for item in projects or []:
        if isinstance(item, dict) and item.get('product_id'):
            listed.append({'product_id': item.get('product_id'), 'artifact': item.get('artifact') or ''})
    return (
        f'<projects>{json.dumps(listed, ensure_ascii=False)}</projects>\n'
        f'<history>{(history or "")[-2500:]}</history>\n'
        f'<message>{(user_text or "")[:6000]}</message>'
    )


def rule_route(text):
    """Used when the classifier is unavailable. A product word is not enough."""
    kind = expected_deliverable(text)
    if kind == 'text':
        return {'action': 'reply', 'goal': '', 'workspace_id': ''}
    if kind == 'product':
        return {'action': 'product', 'goal': '', 'workspace_id': ''}
    return {'action': 'defer', 'goal': '', 'workspace_id': ''}


def parse_route(raw, projects):
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    blob = fenced.group(1) if fenced else ''
    if not blob:
        found = re.search(r'\{.*\}', text, re.S)
        blob = found.group(0) if found else ''
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    action = str(data.get('action') or '').strip().lower()
    if action not in ACTIONS:
        return None
    goal = str(data.get('goal') or '').strip()[:240]
    ids = [str(item.get('product_id')) for item in (projects or []) if isinstance(item, dict) and item.get('product_id')]
    workspace_id = str(data.get('workspace_id') or '').strip()
    if action == 'revise':
        if workspace_id not in ids:
            workspace_id = ids[0] if len(ids) == 1 else ''
        if not workspace_id:
            return {'action': 'reply', 'goal': goal, 'workspace_id': ''}
    else:
        workspace_id = ''
    return {'action': action, 'goal': goal, 'workspace_id': workspace_id}
