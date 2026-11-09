"""Bounded chat answers do not need a planner, a team and a composer."""
import re


def supplied_analysis_task(text):
    """Recognize self-contained inference, never permission to fetch or act."""
    from app.services.subject_guidance import subject_for_query
    from app.services.orchestrator_policy import critical_task
    text = text or ''
    if len(text) > 4000 or subject_for_query(text) in {'code', 'engineering'}:
        return False
    if (re.match(r'(?i)^\s*что\s+такое\b', text)
            and not re.search(r'(?i)\b(?:разбери|докажи|сравни|проверь)\b|следует\s+ли', text)):
        return False
    # Proof vocabulary alone is not an external or hazardous action.
    scope = re.sub(r'(?i)\b(?:докажи|доказать|доказательство\w*)\b', '', text)
    if (re.search(r'(?i)без\s+возвращ\w*', text)
            and re.search(r'(?i)\b(?:шар\w*|жетон\w*|фишк\w*)\b', text)):
        scope = re.sub(r'(?i)\bудалени\w*\b', '', scope)
    if critical_task(scope) or re.search(r'(?i)https?://|источник\w*|документаци\w*|'
            r'актуальн\w*|новост\w*|закон\w*|\bлечени\w*|\bлекарств\w*|'
            r'\b(?:файл\w*|вложени\w*|прикрепл\w*|сервер\w*|репозитори\w*|'
            r'отправ\w*|опублику\w*|запусти|выполни|скачай|найди|поищи|открой|'
            r'прочитай|создай|собери|сохрани|удали|инструмент\w*)\b', text):
        return False
    return bool((subject_for_query(text) in {'history', 'humanities'}
                 and re.search(r'(?i)\b(?:докажи|разбери|сравни|трактовк\w*|объясни)\b|'
                               r'как\s+форм[аы]|можно\s+ли|обязательно\s+ли', text)) or re.search(
        r'(?i)следует\s+ли|что\s+следует\s+из|равносильн\w*|контрпример\w*|вероятност\w*|без\s+возвращ\w*|'
        r'\b(?:посылк\w*|квантор\w*|импликаци\w*|аргумент\w*|рассказчик\w*)\b|'
        r'допустим\w*\s+порядок|минимальн\w*\s+(?:общ\w*\s+)?врем\w*|'
        r'причинн\w*\s+(?:схем\w*|связ\w*)|'
        r'доказывает\s+ли|какой\s+вывод\s+нужно\s+пересмотреть', text))


def inline_code_task(text):
    """An explicit self-contained code/JSON answer grants no tool actions."""
    from app.services.subject_guidance import subject_for_query
    from app.services.orchestrator_policy import critical_task
    if not text or len(text) > 6000 or subject_for_query(text) != 'code':
        return False
    explicit_format = re.search(r'(?i)(?:только|only)\s+(?:(?:один|one)\s+)?(?:блок\s+(?:кода|sql)|код\b|json\b|code\b)', text)
    standalone_snippet = re.fullmatch(
        r'(?i)(?:напиши|покажи|приведи) код [^\n.!?]{1,140} на (?:python|javascript|typescript|rust|go|c\+\+|c#)[.!?]?',
        text.strip(),
    )
    if not standalone_snippet:
        standalone_snippet = re.fullmatch(
            r'(?i)(?:короч[, ]+)?(?:(?:подскажи|покажи)(?:\s+пж|,?\s+пожалуйста)?[, ]+)?'
            r'как\s+(?:выглядит\s+(?:алгоритм|функция)\s+[^\n.!?]{1,90}|'
            r'(?:алгоритм|функция)\s+[^\n.!?]{1,90}\s+выглядит)\s+(?:в|на)\s+питоне[.!?]?',
            text.strip(),
        )
    if not (explicit_format or standalone_snippet):
        return False
    scope = re.sub(r'(?i)не\s+создавай\s+(?:вложения|файлы)|без\s+создания\s+файлов', '', text)
    scope = re.sub(r'(?i)источник\w*\s+отмен\w*', '', scope)
    # Removing duplicates describes the function's behavior, not an external action.
    scope = re.sub(r'(?i)\bудал(?:и|ить)\s+(?:(?:только\s+)?(?:соседние\s+)?(?:повторы|дубликаты)|'
                   r'(?:все\s+)?неч[её]тные)\b', '', scope)
    if re.search(r'(?i)https?://|документаци|источник|актуальн|текущ\w*\s+верс|'
                 r'\b(?:файл\w*|папк\w*|проект\w*|репозитори\w*|вложени\w*|прикрепл\w*|сервер\w*|'
                 r'сохрани|запусти|протестируй|выполни|отправь|опубликуй|открой|прочитай|установи|скачай)\b', scope):
        return False
    return not critical_task(scope)


def everyday_answer(text):
    """Personal circumstances and supplied pantry are not current web facts."""
    from app.services.orchestrator_policy import critical_task
    from app.services.subject_guidance import subject_for_query
    from app.services.request_intent import classify_request
    scope = re.sub(r'(?i)\bбез\s+диагнозов\b', '', text or '')
    if len(text or '') > 1800 or critical_task(scope) or subject_for_query(text):
        return False
    if classify_request(text).topic != 'general':
        return False
    if re.search(r'(?i)https?://|источник|документаци|новост|актуальн|'
                 r'лекарств|лечени|болит|симптом|суицид|самоубий|насили|угроз|'
                 r'не\s+хочу\s+жить|себе\s+вред|самоповрежден|'
                 r'закон\w*|увольн\w*|налог\w*|политик\w*|выбор\w*|президент\w*|'
                 r'\b(?:файл\w*|вложени\w*|прикрепл\w*|сервер\w*|почт\w*|проект\w*|'
                 r'отправь|отправить|открой|найди|поищи|сохрани|опубликуй|запусти|проверь)\b', text or ''):
        return False
    personal = bool(re.search(r'(?i)голова\s+забита|сил\s+мало|\bустал\w*\b', text or '')
                    and re.search(r'(?i)дел\w*|посуд\w*|стирк\w*|одежд\w*|гости|дома|приглаш\w*|сообщени\w*', text or ''))
    return personal or bool(re.search(r'(?i)'
        r'\b(?:рубашк\w*|одежд\w*|уборк\w*|посуд\w*|стирк\w*|завтрак\w*|ужин\w*)\b|'
        r'просто\s+поговори|поговори\s+со\s+мной|помоги\s+ответить|'
        r'\b(?:поддержи|поддержать|поздравь)\s+меня\b|'
        r'\b(?:мне\s+одиноко|мне\s+грустно|я\s+растерян\w*|меня\s+не\s+слышат)\b|'
        r'(?:выслушай|побудь\s+собеседником|без\s+советов|не\s+хочу\s+советов)|'
        r'(?:боюсь|волнуюсь|переживаю).{0,90}(?:разговор|собеседован|выступлен|экзамен)|'
        r'^нет[, ]+.{0,100}(?:не\s+могу|не\s+подходит)|'
        r'(?:человек|коллега|друг)\b.{0,100}(?:не\s+отвечает|не\s+поздоровался)|'
        r'(?:коллега|друг|собеседник)\b.{0,100}(?:перебил|обидел|не\s+понял)|'
        r'(?:суббот\w*|воскресень\w*|завтра).{0,150}(?:встреч\w*|друз\w*|дома).{0,150}(?:только|обязательн\w*|не\s+могу)|'
        r'(?:ужин|завтрак|рецепт)\b.{0,160}(?:этих\s+продукт|перечислен|без\s+покупок)|'
        r'^(?:сделай|сократи)\s+сообщение\s+короче\b', text or '', re.S))


def _clock_snapshot_question(text):
    from app.services.orchestrator_policy import critical_task

    scope = re.sub(r'(?i)\bбез\s+рефакторинга\b', '', text)
    return (len(text) <= 1500 and not critical_task(scope)
            and bool(re.search(r'(?i)\bstm32[a-z]\d{3}\w*\b', text))
            and bool(re.search(r'(?i)\b(?:HSERDY|HSIRDY|PLLRDY|HSEBYP|SWS)\s*=\s*(?:[01]|HSI|HSE|PLL)\b', text))
            and bool(re.search(r'(?i)какой\s+этап|что\s+проверить|почему\s+не', text))
            and not re.search(r'(?i)https?://|источник|документаци|проект|файл|прошивк|вложени', text))


def compact_answer_kind(text, *, web_required=False, messages=None):
    from app.services.orchestrator_policy import bounded_text_task, calculation_task, critical_task
    from app.services.request_intent import classify_request
    from app.services.subject_guidance import subject_for_query
    text = text or ''
    if not text.strip() or len(text) > 6000:
        return ''
    if messages and not web_required:
        from app.services.orchestrator_policy import bounded_text_revision
        if bounded_text_revision(text, messages):
            return 'text'
    if inline_code_task(text):
        return 'text'
    if bounded_text_task(text):
        return 'text'
    # A recipient before the colon need not contain the word "message".
    # Require an explicit result format and reject actions anywhere in the ask.
    if (not web_required and len(text) <= 1500 and subject_for_query(text) is None
            and re.match(r'(?i)^\s*(?:напиши|составь|подготовь)\b', text)
            and re.search(r'(?i)\bтолько\s+(?:сообщение|письмо|реплик[ау])\b', text)
            and not critical_task(text)
            and not re.search(r'(?i)https?://|источник\w*|актуальн\w*|'
                r'\b(?:файл\w*|вложени\w*|прикрепл\w*|сервер\w*|почт\w*|'
                r'pdf|docx|xlsx|pptx|csv|отправ\w*|опублику\w*|сохрани|удали|'
                r'открой|прочитай|найди|поищи|запусти|выполни|инструмент\w*)\b', text)):
        return 'text'
    # An answer shortcut never inherits permission to act on files/accounts.
    action_scope = re.sub(r'(?i)\bпроверь\s+(?:аргумент|вывод|рассуждени[ея]|посылки)\b', '', text)
    if re.search(r'(?i)прикрепл|вложени|\b(?:pdf|docx|xlsx|pptx|csv)\b|'
                 r'\b(?:файл\w*|репозитори\w*|проект\w*|сервер\w*|почт\w*|отч[её]т\w*|таблиц\w*)\b|'
                 r'\bдокумент(?:ы|ов|а|е|у|ом|ами|ах)?\b|'
                 r'\b(?:отправ\w*|опублику\w*|скачай|сохрани|удали|запусти|установи|подключись|'
                 r'внеси|реализуй|создай|собери|сгенерируй|исправь|измени|протестируй|открой|прочитай|'
                 r'выполни|посчитай|вычисли|рассчитай|проверь|инструмент\w*|мой|мои|мою|моих|наши)\b', action_scope):
        return ''
    # Personal circumstances can contain "today" without requiring current web facts.
    if everyday_answer(text):
        return 'text'
    if not web_required and _clock_snapshot_question(text):
        return 'text'
    if re.search(r'(?i)\bлечени\w*|\bлекарств\w*|\bдоз\w*', text):
        return ''
    if supplied_analysis_task(text) and not web_required:
        return 'text'
    if (not web_required and re.search(r'(?i)enfusion|enforce\s+script|arma\s+reforger', text)
            and re.search(r'(?i)\bScriptComponent\b', text)
            and re.search(r'(?i)\b(?:E?OnDelete|EOnInit|EOnFrame)\b', text)
            and re.search(r'(?i)сигнатур|\bcallback\b', text)
            and not critical_task(re.sub(r'(?i)\bcallback\s+удаления\b', '', text))):
        return 'text'
    if (subject_for_query(text) == 'engineering' and len(text) <= 1800
            and re.search(r'(?i)других\s+данных\s+нет|больше\s+ничего\s+не\s+известно', text)
            and not re.search(r'(?i)https?://|источник|документаци', text)):
        return 'text'  # Explain missing inputs; there is no numerical calculation to run.
    head = text.split('\n', 1)[0].split(':', 1)[0]
    code_explanation = (subject_for_query(text) == 'code'
                        and bool(re.match(r'(?i)^\s*(?:объясни|почему)\b', head))
                        and bool(re.search(r'```|:\s*(?:async\s+)?def\s|:\s*\n', text)))
    if code_explanation and not critical_task(head) and not re.search(r'(?i)источник|документаци|ссылк', head):
        return 'text'
    if calculation_task(text) or critical_task(text) or subject_for_query(text) == 'engineering':
        return ''
    intent = classify_request(text)
    if intent.topic in {'shopping', 'places'} or intent.task in {'recommendation', 'overview'}:
        return ''
    source_lookup = (not intent.web_forbidden and bool(re.search(
        r'(?i)по\s+официальн\w*\s+(?:источник\w*|документаци\w*)|'
        r'текущ\w*.{0,35}(?:верс|релиз)|на\s+официальн\w*\s+сайт', head)))
    if web_required or intent.needs_web or source_lookup:
        return 'web' if len(text) <= 1800 and intent.task in {'fact', 'explanation', 'comparison'} else ''
    if re.search(r'(?i)\b(?:сайт\w*|страниц\w*|сервис\w*|приложени\w*)\b', head):
        return ''  # Comparing external objects is not an inline text operation.
    if re.search(r'(?i)https?://|источник|точн\w*\s+цитат|номер\w*\s+страниц', text) and not intent.web_forbidden:
        return ''
    if re.match(r'(?i)^\s*(?:что такое|объясни|почему|расскажи|сравни|разбери|верни\s+только\s+json)\b', text):
        return 'text'
    return ''


def compact_model(task, available, *, context_chars=0):
    """Spend saved planning/tool context on reasoning, within the existing tier."""
    from app.services.subject_guidance import needs_subject_reasoning
    if (context_chars <= 60000 and 'gpt-6-sol' in available and supplied_analysis_task(task)
            and (re.search(r'(?i)\b(?:аргумент\w*|посылк\w*|равносильн\w*)\b|следует\s+ли', task)
                 or (re.search(r'(?i)вероятност\w*|без\s+возвращ\w*', task)
                     and re.search(r'(?i)больше|меньше|измен\w*|без\s+возвращ\w*|неизвест\w*', task)))):
        return 'gpt-6-sol'
    if needs_subject_reasoning(task) and context_chars <= 60000:
        if 'gpt-6-sol' in available:
            return 'gpt-6-sol'
    from app.services.subject_guidance import subject_for_query
    if (subject_for_query(task) == 'code' and context_chars <= 60000
            and re.search(r'(?i)async|await|асинхрон', task)
            and re.search(r'(?i)отмен|cancellation', task)
            and ('gpt-6-sol' in available or 'gpt-6.1-terra' in available)):
        return 'gpt-6-sol' if 'gpt-6-sol' in available else 'gpt-6.1-terra'
    if (subject_for_query(task) == 'code' and context_chars <= 60000
            and re.search(r'(?i)O\s*\(\s*n\s*\)', task)
            and re.search(r'(?i)памят[ьи]|memory', task)
            and 'gpt-6.1-terra' in available):
        return 'gpt-6.1-terra'
    return 'gpt-6-luna'


COMPACT_FORMAT = ('Пиши ясно и по существу на языке пользователя. Используй обычный Markdown; '
                  'код давай законченно в блоке с языком. Запрошенный JSON, перевод или готовый текст '
                  'верни без обрамления и вступления. При жёстком лимите объёма оставь небольшой запас. '
                  'Не добавляй непрошенные рекомендации и случайные факты.')


def compact_messages(messages, *, web=False):
    """Replace only our exact boilerplate; keep all custom rules, memory and history."""
    from config import SYSTEM_PROMPT
    from app.services.search_budget import SEARCH_PLAN
    from app.services.answer_quality import ANSWER_QUALITY_RULES, COMPACT_ANSWER_RULES, CONVERSATION_RULES
    task = next((m.get('content', '') for m in reversed(messages)
                 if m.get('role') == 'user' and isinstance(m.get('content'), str)), '')
    # shortcut: explicit Russian message-only requests; broaden after multilingual checks.
    draft = (not web and re.match(r'(?i)^\s*(?:напиши|составь|подготовь)\b', task)
             and re.search(r'(?i)\bтолько\s+(?:сообщение|письмо)\b', task)
             and compact_answer_kind(task) == 'text')
    paragraphs = SYSTEM_PROMPT.split('### КАК ДУМАТЬ О ФАКТАХ', 1)[0].split('\n\n')
    intro = '\n\n'.join(paragraphs[:2] + [p for p in paragraphs[2:] if p.startswith('По юридическим')])
    if '### ОГРАНИЧЕНИЯ' not in SYSTEM_PROMPT or '### КАК ДУМАТЬ О ФАКТАХ' not in SYSTEM_PROMPT:
        return [dict(message) for message in messages]
    safety = SYSTEM_PROMPT.split('### ОГРАНИЧЕНИЯ', 1)[-1].split('Оформление ответа в чате:', 1)[0]
    compact = intro.strip() + '\n' + safety.strip() + '\n' + COMPACT_FORMAT
    result = []
    for message in messages:
        row = dict(message)
        if row.get('role') == 'system' and row.get('content') == SYSTEM_PROMPT:
            row['content'] = compact
        if row.get('role') == 'system' and isinstance(row.get('content'), str) and row['content'].startswith(ANSWER_QUALITY_RULES):
            rules = COMPACT_ANSWER_RULES.replace(CONVERSATION_RULES, '') if draft else COMPACT_ANSWER_RULES
            row['content'] = rules + row['content'][len(ANSWER_QUALITY_RULES):]
        if not web and row.get('role') == 'system' and row.get('content') == SEARCH_PLAN:
            continue
        result.append(row)
    if draft:
        result.append({'role': 'system', 'content':
            'Сейчас нужен только готовый текст для адресата. Используй только сообщённые факты. '
            'Не добавляй обстоятельства, сроки, обещания написать или встретиться позже. '
            'Если пол автора неизвестен, выбери нейтральную формулировку. '
            'Не переноси ограничения пользователя в реплику адресату. Пример: '
            '«Напиши коллеге: отчёт ещё проверяю. Не обещай срок. Только сообщение» → '
            '«Я ещё проверяю отчёт». Закончи текст после последней нужной фразы, без приписок. '
            'Сохраняй язык и тон пользователя; не добавляй случайные слова на другом языке.'})
    elif not web:
        from app.services.orchestrator_policy import bounded_text_revision
        if bounded_text_revision(task, messages):
            result.append({'role':'system','content':
                'Отредактируй предыдущий текст по текущему уточнению и верни сам результат без вступления. '
                'Сохрани факты, даты, суммы, контакты, язык и прежние ограничения, которые пользователь '
                'не отменил. Новое уточнение меняет только названное свойство текста. '
                'Сохраняй признаки, ограничивающие предмет просьбы. Если пол автора неизвестен, '
                'оставь формулировку нейтральной. '
                'При сокращении убери повторы и необязательные слова. Более тёплый тон передай мягкой формулировкой '
                'без подколов, фамильярности и обвинений, если пользователь их не просил. '
                'Не добавляй обещания, обстоятельства и предложения сделать работу позже.'})
    return result
