"""Choose an artifact task without changing the user's selected chat mode."""
import re
from contextvars import ContextVar

canvas_creation = ContextVar('canvas_creation', default=False)


def _directive(text):
    return re.sub(r'```[\s\S]*?```|«[^»]*»|“[^”]*”|"[^"]*"', ' ', text or '')


def explicitly_text_only(text):
    return bool(re.search(r'(?i)не\s+(?:(?:надо|нужно|делай|создавай|создавать)\s+){0,2}(?:делать\s+)?холст|без\s+холста|(?:результат\w*|ответ\w*)[^.!?\n]{0,45}(?:текстом|в\s+чате)', _directive(text)))


def text_response_requested(text):
    """Read directives outside source quotations, including multiline quotations."""
    if explicitly_text_only(text):
        return True
    scope = _directive(text)
    analysis = re.search(r'(?i)\b(?:проанализируй|проанализируйте|скорректируй|переформулируй|разбери|оцени|проверь|analyze|analyse|review)\b', scope)
    build = re.search(r'(?i)\b(?:создай|собери|сделай|подготовь|нарисуй|create|build|make)\s+(?:[\w-]+\s+){0,3}(?:холст\w*|дашборд\w*|инфографик\w*|презентаци\w*|сайт\w*|лендинг\w*|картинк\w*|изображени\w*|dashboard|website|slides|image)\b', scope)
    edit_canvas = (re.search(r'(?i)текущ\w*\s+(?:макет\w*|холст\w*)', scope)
                   and re.search(r'(?i)\b(?:исправь|измени|поправь|обнови)\b', scope))
    return bool(analysis and not build and not edit_canvas)

_CREATE = re.compile(r'(?i)\b(?:собери(?:те)?|собрать|создай(?:те)?|создать|сделай(?:те)?|сделать|сверстай(?:те)?|подготовь(?:те)?|составь(?:те)?|разработай(?:те)?|построй(?:те)?|нарисуй(?:те)?|нарисовать|сгенерируй(?:те)?|нужен|нужна|нужно|хочу|build|create|make|design|draw|generate)\b')
# An action belongs to its clause and to the object it actually governs.
_ACTION_CLAUSE = re.compile(r'(?<=[!?])\s+|(?<!\d)\.\s+|[;\n]+|,\s+(?:а|но|затем|потом)\s+|\s+(?:и|затем|потом|and then)\s+(?=(?:создай|собери|подготовь|сделай|build|create)\b)', re.I)
_REQUEST_PREFIX = re.compile(r'^(?:пожалуйста[, ]+|(?:затем|потом|давай(?:те)?|можешь|можете|сможешь|мне нужно|хочу|please|can you|could you|i want to)\s+)', re.I)
_BUILD = re.compile(
    r'(?i)^(?:собери(?:те)?|собрать|созда(?:й(?:те)?|ть|дим)|сдела(?:й(?:те)?|ть|ем)|'
    r'сверстай(?:те)?|сверстать|подготов(?:ь(?:те)?|ить)|состав(?:ь(?:те)?|ить)|'
    r'разработа(?:й(?:те)?|ть)|постро(?:й(?:те)?|ить)|нарисова(?:й(?:те)?|ть)|'
    r'сгенериру(?:й(?:те)?|ем)|нуж(?:ен|на|но|ны)|хочу|build|create|make|design|draw|generate)\s+'
)
_BUILD_OBJECT = re.compile(
    r'(?i)^(?:по\s+(?:нему|ней|этому\s+(?:брифу|промпту))\s+)?'
    r'(?:(?:мне|нам|пожалуйста|готов\w*|[\w-]{4,}(?:ый|ий|ой|ую|ая|ое|ый|ые|ный)|'
    r'new|modern|responsive|simple|working|a|an|the)\s+){0,4}?'
    r'(?P<object>сайт\w*|лендинг\w*|страниц\w*|дашборд\w*|инфографик\w*|'
    r'презентаци\w*|слайд\w*|приложени\w*|веб-приложени\w*|прототип\w*|'
    r'интерфейс\w*|макет\w*|холст\w*|pptx|powerpoint|website\w*|web\s+page\w*|'
    r'landing\w*|dashboard\w*|infographic\w*|slides?|presentation\w*|(?:web\s+)?apps?|'
    r'prototype\w*|картинк\w*|изображени\w*|image\w*)\b'
)
_CANVAS_REFERENCE = re.compile(r'(?i)\b(?:холст\w*|(?:этом|текущ\w*|открыт\w*|выбран\w*)\s+макет\w*)\b')
_EDIT_CLAUSE = re.compile(
    r'(?i)^(?:(?:а\s+)?(?:теперь|ещ[её]|тогда)\s+)?'
    r'(?:(?:в|на)\s+(?:[\w-]+\s+){0,2}(?:холст\w*|макет\w*|слайд\w*)\s+)?'
    r'(?:измени(?:те|ть)?|поправ(?:ь(?:те)?|ить)|исправ(?:ь(?:те)?|ить)|'
    r'обнови(?:те|ть)?|замени(?:те|ть)?|добав(?:ь(?:те)?|ить)|убер(?:и(?:те)?|ём|ем)|убрать|'
    r'удали(?:те|ть)?|перенеси(?:те)?|сдела(?:й(?:те)?|ть)|увелич(?:ь(?:те)?|ить)|'
    r'уменьш(?:ь(?:те)?|ить)|перекрас(?:ь(?:те)?|ить)|edit|change|update|remove|add)\b'
)
_VISUAL_OBJECT = re.compile(
    r'(?i)^(?:(?:[\w-]+(?:ый|ий|ой|ую|ая|ое|ые)|мне|нам|размер\w*|ширин\w*|высот\w*)\s+){0,2}?(?:заголов\w*|подзагол\w*|шрифт\w*|кнопк\w*|макет\w*|холст\w*|'
    r'слайд\w*|презентац\w*|отступ\w*|меню|heading|font|button|layout|'
    r'цвет\w*|фон\w*|контраст\w*)\b'
    r'|^(?:[\w-]+\s+){0,2}?(?:секци\w*|блок\w*)\s+(?:с\s+)?(?:контакт\w*|цен\w*|отзыв\w*|услуг\w*|тариф\w*)\b'
)
_SHORT_EDIT = re.compile(r'(?i)(?:сделай\s+)?(?:крупнее|мельче|темнее|светлее|шире|выше|ниже)[.!\s]*')
_ADVICE = re.compile(
    r'(?i)^(?:а\s+)?(?:как\b|почему\b|зачем\b|что\b|можно\s+ли\b|'
    r'(?:можно|стоит|надо|нужно|лучше)\s+(?:ли\s+)?(?:сделать|убрать|добавить|создать|изменить|обновить|собрать|поменять)\b|'
    r'(?:(?:мне|нам)\s+)?(?:нужно|хочу|хотелось\s+бы)\s+(?:понять|узнать|разобраться|обсудить|решить)\b|'
    r'предложи\w*|подскажи\w*|посоветуй\w*|обсудим\b|what\b|should\b|would\b|how\b|why\b|suggest\b)'
)
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
    if not text or explicitly_text_only(text) or _NO_ARTIFACT.search(_directive(text)):
        return None
    if _ADVICE.match(text) or _TEXT_JOB.match(text):
        # Only a separately requested action can override the leading advice or text task.
        followup = re.search(r'(?is)[.!?;\n]\s*(?:а\s+)?(?:затем|потом|then)\s+(.+)', _directive(text))
        if not followup:
            return None
        text = followup[1].strip()
    if text_response_requested(text):
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
    if (not positive and not _EDIT_CLAUSE.match(directive.lstrip())
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


def is_canvas_attachment(item):
    """Recognize a result card that the chat UI can open as a canvas."""
    return (
        isinstance(item, dict)
        and bool(item.get('url'))
        and item.get('type') != 'image'
        and item.get('status', 'done') == 'done'
        and (bool(item.get('canvas')) or (
            item.get('type') in {None, 'generated'}
            and str(item.get('name', '')).lower().endswith(('.html', '.htm'))
        ))
    )


def _assistant_attachments(user_id):
    from conversations import conversation_manager

    conv = conversation_manager.conversation_for_turn(user_id)
    for message in reversed(getattr(conv, 'messages', ()) or ()):
        role = message.get('role') if isinstance(message, dict) else getattr(message, 'role', None)
        if role != 'assistant':
            continue
        attachment = message.get('attachment') if isinstance(message, dict) else getattr(message, 'attachment', None)
        extra = attachment.get('files') if isinstance(attachment, dict) else None
        items = extra if isinstance(extra, list) and extra else [attachment]
        yield [item for item in items if is_canvas_attachment(item)]


def canvas_attachments(user_id):
    """Only results of this bound conversation, newest first."""
    return [item for reply in _assistant_attachments(user_id) for item in reply]


def action_clauses(text):
    for clause in _ACTION_CLAUSE.split(text):
        clause = clause.strip(' ,.!')
        while prefix := _REQUEST_PREFIX.match(clause):
            build = _BUILD.match(clause)
            if build and _BUILD_OBJECT.match(clause[build.end():]):
                break
            clause = clause[prefix.end():]
        if clause:
            yield clause


def canvas_request(user_id, text):
    """Route by the requested action, then resolve its target in this chat."""
    from studio.html_canvas import detect_kind_explicit, load_previous_html, is_image_canvas

    text = artifact_brief(text)
    if text is None:
        return None
    clauses = list(action_clauses(text))
    for clause in clauses:
        build = _BUILD.match(clause)
        obj = _BUILD_OBJECT.match(clause[build.end():]) if build else None
        if not obj:
            continue
        after_object = clause[build.end() + obj.end():].strip()
        if _SHORT_EDIT.fullmatch(after_object) or after_object.casefold() == 'короче':
            continue
        kind = detect_kind_explicit(obj['object'])
        if kind == 'image' and not re.search(r'(?i)\bна\s+холст\w*\b', clause):
            continue
        if not kind and obj['object'].lower().startswith('холст'):
            kind = 'landing'
        if kind is None:
            continue
        requirements = re.sub(r'(?i)\b(?:без|without|не\s+нуж(?:ен|на|ны))\b[^,.;\n]*', '', text)
        if kind in {'landing', 'app', 'dashboard'} and _FULL_APP.search(requirements):
            return 'project'
        return 'create'

    edit = explicit = False
    for clause in clauses:
        action = _EDIT_CLAUSE.match(clause)
        references_canvas = bool(_CANVAS_REFERENCE.search(clause))
        if action and (references_canvas or _VISUAL_OBJECT.match(clause[action.end():].lstrip())):
            edit = True
            explicit |= references_canvas
        elif references_canvas and re.match(r'(?i)^(?:проверь|оцени)\b', clause):
            if re.search(r'(?i)\bи\s+(?:исправь|поправь|измени|обнови)\b', clause):
                edit = explicit = True
    short_edit = len(clauses) == 1 and _SHORT_EDIT.fullmatch(clauses[0])
    if not (edit or short_edit):
        return None

    target = target_for_turn(user_id)
    replies = _assistant_attachments(user_id)
    recent = next(replies, [])
    if target or explicit:
        candidates = {item['url']: item for reply in [recent, *replies] for item in reply}
    else:
        candidates = {item['url']: item for item in recent}
    if not candidates:
        return None
    if target and target not in candidates:
        return 'missing' if explicit or recent else None
    if not target and len(candidates) > 1:
        return 'ambiguous'
    previous = load_previous_html(user_id, target or next(iter(candidates)))
    if previous and not is_image_canvas(previous):
        return 'edit'
    return None
