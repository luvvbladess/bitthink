"""Choose an artifact task without changing the user's selected chat mode."""
import re
from contextvars import ContextVar

canvas_creation = ContextVar('canvas_creation', default=False)


def text_response_requested(text):
    """Read directives outside source quotations, including multiline quotations."""
    scope = re.sub(r'```[\s\S]*?```|«[^»]*»|“[^”]*”|"[^"]*"', ' ', text or '')
    if re.search(r'(?i)не\s+(?:(?:надо|нужно|делай|создавай|создавать)\s+){0,2}(?:делать\s+)?холст|без\s+холста|(?:результат\w*|ответ\w*)[^.!?\n]{0,45}(?:текстом|в\s+чате)', scope):
        return True
    analysis = re.search(r'(?i)\b(?:проанализируй|проанализируйте|скорректируй|переформулируй|разбери|оцени|проверь|analyze|analyse|review)\b', scope)
    build = re.search(r'(?i)\b(?:создай|собери|сделай|подготовь|нарисуй|create|build|make)\s+(?:[\w-]+\s+){0,3}(?:холст\w*|дашборд\w*|инфографик\w*|презентаци\w*|сайт\w*|лендинг\w*|картинк\w*|изображени\w*|dashboard|website|slides|image)\b', scope)
    edit_canvas = (re.search(r'(?i)текущ\w*\s+(?:макет\w*|холст\w*)', scope)
                   and re.search(r'(?i)\b(?:исправь|измени|поправь|обнови)\b', scope))
    return bool(analysis and not build and not edit_canvas)

_CREATE = re.compile(r'(?i)\b(?:собери(?:те)?|собрать|создай(?:те)?|создать|сделай(?:те)?|сделать|сверстай(?:те)?|подготовь(?:те)?|составь(?:те)?|разработай(?:те)?|построй(?:те)?|нарисуй(?:те)?|нарисовать|сгенерируй(?:те)?|нужен|нужна|нужно|хочу|build|create|make|design|draw|generate)\b')
_EDIT = re.compile(r'(?i)\b(?:измени\w*|изменить|поправ\w*|исправ\w*|обнов\w*|замени\w*|добав\w*|убери\w*|удали\w*|перенеси\w*|сделай|увелич\w*|уменьш\w*|перекрас\w*|edit|change|update|remove|add)\b')
_VISUAL = re.compile(r'(?i)заголов|шрифт|цвет|кнопк|блок|макет|холст|слайд|презентац|стил|фон|отступ|подзагол|меню|секци|контраст|ширин|высот|крупнее|мельче|темнее|светлее|короче|heading|font|button|layout')
_READ = re.compile(r'(?i)^\s*(?:как\b|что\b|почему\b|зачем\b|объясни\w*|расскажи\w*|проанализиру\w*|оцени\w*|сравни\w*|перескажи\w*|проверь\w*|explain\b|why\b|how\b|review\b)')
_TEXT = re.compile(r'(?i)^\s*(?:напиши|составь|создай|подготовь|сделай|write|create)\s+(?:(?:мне|пожалуйста|краткий|подробный|короткий)\s+){0,3}(?:план\b|промпт\b|описани|текст\b|идеи\b|идею\b|техзадани|техническое\s+задание|brief\b|prompt\b)')
_FULL_APP = re.compile(r'(?i)авторизац|аутентификац|регистраци|баз[аыуе]\s+данных|postgres|backend|back.end|full.stack|серверн\w*\s+(?:част|api)|исходн\w*\s+(?:проект|код)|\b(?:react|next\.js|django|fastapi)\b')

_TEXT_JOB = re.compile(r'(?i)^\s*(?:(?:пожалуйста|please)[,\s]+)?(?:'
    r'переведи|перефразируй|перескажи|кратко\s+перескажи|объясни|расскажи|опиши|ответь|найди|поищи|'
    r'дай\s+(?:разбор|анализ|совет|объяснение|описание)|'
    r'хочу\s+(?:узнать|понять)|я\s+не\s+прошу|можно\s+ли\b|'
    r'(?:нужен|нужна|нужно)\s+(?:(?:мне|нам|только|лишь|короткий|краткий|подробный|небольшой)\s+){0,4}'
    r'(?:текст|описание|консультаци|помощь|совет|план|промпт)|'
    r'translate\b|paraphrase\b|summarize\b|explain\b|describe\b|how\b|why\b|find\b|search\b)')
_NO_ARTIFACT = re.compile(r'(?i)\b(?:без\s+(?:генерации|создания\s+файлов)|'
    r'ничего\s+не\s+(?:создавай|меняй|генерируй)|(?:текущий\s+)?(?:холст|макет)\s+не\s+меняй)\b')
_NEGATED = re.compile(r'(?i)(?:\bне|не\s+надо|не\s+нужно|не\s+стоит|do\s+not|don[’\']t)\s*$')


def artifact_brief(text):
    """Return a positive artifact directive, never instructions inside requested text.

    The original brief still goes to the writer/provider. This bounded view only
    decides whether a generation action may start. Ambiguous asks stay in chat.
    """
    from app.services.product_strategy import expected_deliverable
    text = (text or '').strip()
    if not text or text_response_requested(text) or _TEXT_JOB.search(text) or _NO_ARTIFACT.search(text):
        return None
    canvas_edit = bool(re.search(r'(?i)^\s*(?:в\s+текущем\s+макете\s+измени|измени\s+текущий\s+макет|'
                                r'сделай\s+(?:заголовок|шрифт|кнопк\w*)\b.*(?:крупнее|мельче|шире|выше|ниже))', text))
    if expected_deliverable(text) == 'text' and not canvas_edit:
        return None
    # Quoted examples and fenced code do not authorise generating their content.
    directive = re.sub(r'```[\s\S]*?```|«[^»]*»|“[^”]*”|"[^"]*"', ' ', text)
    directive = re.sub(r'(?i)\bне\s+(?:(?:надо|нужно|стоит)\s+)?'
        r'(?:созда\w*|собира\w*|собрать|рис\w*|нарис\w*|генерир\w*|дела\w*|стро\w*)'
        r'[^,.;\n]*?(?=[,.;\n]|\s+\b(?:а|но|затем)\b|$)', ' ', directive)
    if not directive.strip(' ,.;\n'):
        return None
    if _TEXT_JOB.search(directive.lstrip(' ,.;\n')):
        return None
    matches = list(_CREATE.finditer(directive))
    positive = [m for m in matches if not _NEGATED.search(directive[max(0, m.start()-40):m.start()])]
    if matches and not positive:
        return None
    # Mentioning a picture inside a conversational question is not a request
    # to generate it. Preserve explicit creation and leading editing commands.
    if (not positive and not _EDIT.match(directive.lstrip())
            and re.search(r'(?i)(?:^|[.!?]\s*)\s*(?:как|почему|зачем|что|можно\s+ли|how|why)\b', directive)):
        return None
    if not positive and re.search(r'(?i)\b(?:объясни|расскажи|опиши|explain|describe)\b', directive):
        return None
    # After a writing request, only a distinct positive build action can win.
    if _TEXT.search(text) and not expected_deliverable(text) == 'product':
        return None
    return directive


def target_for_turn(user_id):
    from app.core.request_context import preference
    bound, target = preference(user_id, 'canvas_target')
    return target if bound and isinstance(target, str) and target else None


def canvas_attachments(user_id):
    """Only results of this bound conversation, never an arbitrary supplied URL."""
    from conversations import conversation_manager
    conv = conversation_manager.conversation_for_turn(user_id)
    results = []
    for message in getattr(conv, 'messages', []) if conv else []:
        role = message.get('role') if isinstance(message, dict) else getattr(message, 'role', None)
        if role != 'assistant':
            continue
        attachment = message.get('attachment') if isinstance(message, dict) else getattr(message, 'attachment', None)
        if not isinstance(attachment, dict):
            continue
        extra = attachment.get('files')
        for item in [attachment, *(extra if isinstance(extra, list) else [])]:
            if not isinstance(item, dict):
                continue
            if item.get('url') and (item.get('canvas') or str(item.get('name', '')).lower().endswith(('.html', '.htm'))):
                results.append(item)
    return results


def canvas_request(user_id, text):
    """Return create/edit/ambiguous, or None for ordinary chat and plain images."""
    from studio.html_canvas import detect_kind_explicit, HTML_KINDS, load_previous_html, is_image_canvas
    text = artifact_brief(text)
    if text is None:
        return None
    fixing = re.search(r'(?i)\b(?:исправь|поправь|измени|обнови|замени|добавь|убери)\b', text)
    if not text or (_READ.search(text) and not fixing):
        return None
    kind = detect_kind_explicit(text)
    modifying = bool(re.search(r'(?i)крупнее|мельче|темнее|светлее|короче|шире|выше|ниже', text))
    if _CREATE.search(text) and not modifying and (kind in HTML_KINDS or (kind == 'image' and re.search(r'(?i)на\s+холст', text))):
        requirements = re.sub(r'(?i)\b(?:без|without|не\s+нуж(?:ен|на|ны))\b[^,.;\n]*', '', text)
        if kind in {'landing', 'app', 'dashboard'} and _FULL_APP.search(requirements):
            return 'project'
        return 'create'
    if not _EDIT.search(text) or not _VISUAL.search(text):
        return None
    attachments = canvas_attachments(user_id)
    if not attachments:
        return None
    target = target_for_turn(user_id)
    if target and not any(item['url'] == target for item in attachments):
        return 'missing'
    # Different saved outputs may be versions or independent works, even when
    # their filenames match. Never guess without an explicit card selection.
    if not target and len({item['url'] for item in attachments}) > 1:
        return 'ambiguous'
    previous = load_previous_html(user_id)
    if previous and not is_image_canvas(previous):
        return 'edit'
    return None
