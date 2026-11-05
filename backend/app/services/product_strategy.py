"""Small, deterministic defaults; the architect may choose a better supported stack."""
import re

STACKS = {
    'static': 'HTML/CSS/JavaScript; Node test runner; static hosting',
    'react': 'React + TypeScript + Vite; npm build/test; static hosting or API',
    'next': 'Next.js + TypeScript; npm build/test; Node hosting',
    'astro': 'Astro + TypeScript; npm build/test; content/static hosting',
    'python': 'Python; requirements.txt; unittest; container hosting',
    'node': 'Node.js + TypeScript; npm build/test; container hosting',
}
_PRODUCT = re.compile(r'(?i)сайт|лендинг|приложен|веб.?сервис|интернет.?магазин|блог|личный кабинет|дашборд|\bбот[а-я]*\b|\bwebsite\b|\blanding\b|\bapp\b|\bapplication\b|\bsaas\b|\bweb ?app\b|\bbot\b|\bdashboard\b|\bblog\b|\bapi\s+service\b')
_API_SERVICE = re.compile(r'(?i)\bapi[\s\-\u2010-\u2015]*(?:сервис[а-яё]*|services?)\b')
_EXPLAIN = re.compile(r'(?i)^\s*(объясни|расскажи|как\b|почему\b|сколько\b|хочу (?:узнать|понять)|explain\b|how\b|tell me)')
# The verb is consumed whole, so the words after it are the requested result, not a stray topic.
_VERB = re.compile(
    r'(?i)(?P<idea>придума(?:й(?:те)?|ть)|предложи(?:те)?|подскажи(?:те)?|\b(?:brainstorm|suggest|propose)\b)(?![а-яёa-z])'
    r'|(?P<make>созда(?:й(?:те)?|ть|дим)|сдела(?:й(?:те)?|ть|ем)|собер(?:и(?:те)?|ём|ем)|собрать|'
    r'разработ(?:ай(?:те)?|ать)|реализ(?:уй(?:те)?|овать)|постро(?:й(?:те)?|ить)|напиш(?:и(?:те)?|ать)|'
    r'составь(?:те)?|составить|составим|подготов(?:ь(?:те)?|ить)|сформулиру(?:й(?:те)?|вать)|наброса(?:й(?:те)?|ть)|'
    r'\b(?:build|create|develop|implement|make|write|assemble)\b)(?![а-яёa-z])'
)
_NEGATED = re.compile(r'(?i)(?:не\s+надо|не\s+нужно|не\s+стоит|don\'?t|do\s+not|\bне|\bбез)\s+$')
# A new sentence inside a prompt or a spec is the text of that result.
# Only an explicit extra action ("и собери", "потом создай") starts another result.
_FRESH_ACTION = re.compile(r'(?i)(?:\b(?:и|затем|потом)\b|\bа\s+затем\b|\bа\s+потом\b|\band\s+then\b|\band\s+also\b)\s+$')
_PREP = re.compile(
    r'(?i)^(для|про|обо|об|о|на|под|ко|к|по|из|от|со|с|без|при|через|после|перед|во|в|'
    r'and|for|about|of|on|with|from|into|to)\b'
)
_WORD = re.compile(r'[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9.+_-]*')
_ADJ = re.compile(r'(?i)(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ых|их|ым|им|ую|юю|ом|ем|ого|его|ому|ему|ыми|ими|ою|ею)$')
_PUNCT = ' \t«»"\'`“”.,:;()[]-—–'
_MODIFIERS = frozenset({
    'мне', 'нам', 'вам', 'ему', 'ей', 'им', 'них', 'пожалуйста', 'плиз', 'просто', 'очень',
    'уже', 'ещё', 'еще', 'только', 'ну', 'ка', 'же', 'вот', 'этот', 'эта', 'это', 'эту', 'этого',
    'этому', 'этом', 'этой', 'эти', 'этих', 'этими', 'мой', 'моя', 'моё', 'мое', 'моего', 'моему',
    'моим', 'моей', 'мои', 'моих', 'наш', 'наша', 'наше', 'наш', 'такой', 'такая', 'такое', 'такую',
    'один', 'одну', 'одно', 'одного', 'весь', 'вся', 'всё', 'все', 'данный', 'данная', 'данное',
    'данную', 'ниже', 'выше', 'тут', 'здесь', 'там', 'дальше',
    'a', 'an', 'the', 'me', 'us', 'please', 'just', 'very', 'really', 'simple', 'modern', 'nice',
    'good', 'new', 'full', 'small', 'fast', 'responsive', 'custom', 'basic', 'complete', 'working',
    'ready', 'cool', 'great', 'professional', 'clean', 'minimal', 'static', 'mobile', 'online',
    'beautiful', 'little', 'big', 'whole', 'real', 'actual', 'below', 'above', 'next', 'following',
    'this', 'that', 'these', 'those', 'some', 'any', 'my', 'our', 'your',
    'telegram', 'телеграм', 'телеграме', 'discord', 'slack', 'whatsapp', 'вк', 'vk',
    'ios', 'android', 'андроид',
})
_PRODUCT_HEADS = (
    r'^(?:telegram|телеграм)[\s\-\u2010-\u2015]+бот(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b',
    r'^интернет[\s\-\u2010-\u2015]*магазин\w*',
    r'^личн\w+\s+кабинет\w*',
    r'^веб[\s\-\u2010-\u2015]*сервис\w*',
    r'^api[\s\-\u2010-\u2015]*(?:сервис\w*|services?)\b',
    r'^web[\s-]*apps?\b',
    r'^landings?(?:\s+pages?)?\b',
    r'^dashboards?\b',
    r'^websites?\b',
    r'^applications?\b',
    r'^saas\b',
    r'^blogs?\b',
    r'^apps?\b',
    r'^bots?\b',
    r'^sites?\b',
    r'^бот(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b',
    r'^сайт(?:а|у|ом|е|ы|ов|ам|ами|ах|(?:-[\w]+)*)?\b',
    r'^лендинг\w*',
    r'^приложени(?:е|я|ю|ем|и|й|ям|ями|ях)\b',
    r'^дашборд\w*',
    r'^блог(?:а|у|ом|е|и|ов|ам|ами|ах)?\b',
)
_TEXT_HEAD = (
    r'^(?:промпт\w*|prompts?|текст\w*|описан\w*|тз\b|техзадан\w*|задани\w*|структур\w*|'
    r'назван\w*|слоган\w*|спис(?:ок|ка|ку|ком|ке|ки|ков|кам|ками|ках)\b|инструкц\w*|'
    r'чеклист\w*|чек-лист\w*|сценари\w*|копирайт\w*|заголов\w*|контент\w*|'
    r'стать(?:я|ю|и|е|ёй|ей)\b|пост(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b|'
    r'иде(?:я|ю|и|е|ей)\b|концепц\w*|рекомендац\w*|совет\w*|пример(?:а|у|ом|е|ы|ов|ами|ах)?\b|'
    r'бриф\w*|требован\w*|спецификац\w*|письм\w*|перевод\w*|анализ\w*|сравнен\w*|обзор\w*|'
    r'стратег\w*|доклад\w*|реферат\w*|конспект\w*|аннотац\w*|отч[её]т\w*|'
    r'план(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b|семантик(?:а|и|у|ой|ею)\b|мета-?тег\w*|'
    r'код(?:а|у|ом|е|ы|ов)?\b|copy\b|headline\b|description\b|outline\b|briefs?\b|specs?\b|'
    r'specifications?\b|reports?\b|articles?\b|posts?\b|emails?\b|letters?\b|plans?\b|'
    r'names?\b|titles?\b|slogans?\b|lists?\b|guides?\b|checklists?\b|instructions?\b|'
    r'analysis\b|reviews?\b|summar(?:y|ies)\b|strateg(?:y|ies)\b|scripts?\b|snippets?\b|'
    r'functions?\b|code\b)\b'
)
_FRAGMENT_HEAD = (
    r'^(?:кнопк\w*|форм(?:а|у|ы|е|ой|ою|ам|ами|ах)\b|секци\w*|макет\w*|вайрфрейм\w*|'
    r'wireframes?\b|mockups?\b|hero\b|виджет\w*|карточк\w*|страниц\w*|pages?\b)\b'
)
_HEADS = (
    tuple(('product', re.compile(item, re.I)) for item in _PRODUCT_HEADS)
    + (('text', re.compile(_TEXT_HEAD, re.I)), ('fragment', re.compile(_FRAGMENT_HEAD, re.I)))
)
_AND_PRODUCT = re.compile(r'(?i)^(?:\s*,)?\s+(?:и|а\s+потом|а\s+затем|потом|затем|and)\s+')
_PRONOUN = re.compile(r'(?i)^(?:его|её|ее|него|неё|нее|это|it|one)\b')


def _word(rest):
    found = _WORD.match(rest or '')
    return found.group(0) if found else ''


def _match_head(rest):
    for kind, pattern in _HEADS:
        found = pattern.match(rest or '')
        if found:
            return kind, rest[found.end():]
    return '', rest


def _is_modifier(rest):
    if _match_head(rest)[0]:
        return False
    word = _word(rest).lower()
    if not word:
        return False
    if word in _MODIFIERS:
        return True
    return len(word) >= 5 and bool(_ADJ.search(word))


def _drop_word(rest):
    word = _word(rest)
    return rest[len(word):] if word else rest[1:]


def _coordinated_product(after):
    found = _AND_PRODUCT.match(after or '')
    if not found:
        return False
    return _object_kind(after[found.end():]) == 'product'


def _object_kind(tail):
    """Kind of the direct object: product, text, fragment, or unknown."""
    rest = tail or ''
    for _ in range(18):
        rest = rest.lstrip(_PUNCT)
        if not rest:
            return 'unknown'
        prep = _PREP.match(rest)
        if prep:
            rest = rest[prep.end():]
            while _is_modifier(rest.lstrip(_PUNCT)):
                rest = _drop_word(rest.lstrip(_PUNCT))
            kind, after = _match_head(rest.lstrip(_PUNCT))
            if kind:
                # "для лендинга" with nothing after is the result; "для сайта промпт" keeps going.
                if not after.lstrip(_PUNCT):
                    return kind
                rest = after
                continue
            rest = _drop_word(rest.lstrip(_PUNCT))
            continue
        kind, after = _match_head(rest)
        if kind in {'text', 'fragment'} and _coordinated_product(after):
            return 'product'
        if kind:
            return kind
        if _is_modifier(rest):
            rest = _drop_word(rest)
            continue
        word = _word(rest)
        nxt, _ = _match_head(rest[len(word):].lstrip(_PUNCT)) if word else ('', '')
        if word and re.fullmatch(r'[A-Za-z][A-Za-z0-9.+_-]*', word) and nxt:
            rest = rest[len(word):]
            continue
        return 'unknown'
    return 'unknown'


def expected_deliverable(text):
    """What this message asks to receive, before any tool or build starts.

    product — the site, app, bot or service itself.
    text — a prompt, spec, article, name or other writing about that thing.
    fragment — one piece (a button, a form), not a whole product.
    unknown — no creation verb with a recognizable object.
    """
    raw = text or ''
    if not raw.strip() or _EXPLAIN.search(raw):
        return 'unknown'
    result = 'unknown'
    for match in _VERB.finditer(raw):
        if _NEGATED.search(raw[max(0, match.start() - 32):match.start()]):
            continue
        if result == 'text' and not _FRESH_ACTION.search(raw[max(0, match.start() - 32):match.start()]):
            continue
        tail = raw[match.end():]
        kind = _object_kind(tail)
        if match.group('idea'):
            if kind != 'unknown':
                result = 'text'
            continue
        if kind == 'product':
            return 'product'
        fresh = _FRESH_ACTION.search(raw[max(0, match.start() - 32):match.start()])
        if fresh and _PRONOUN.match(tail.lstrip(_PUNCT)) and (_PRODUCT.search(raw) or _API_SERVICE.search(raw)):
            return 'product'
        if kind == 'text':
            result = 'text'
        elif kind == 'fragment' and result != 'text':
            result = 'fragment'
    return result


def is_product_request(text):
    return expected_deliverable(text) == 'product'


def select_stack(brief):
    text = (brief or '').lower()
    # Explicit choices take precedence over inferred defaults.
    for key, pattern in [('next', r'next\.?js'), ('astro', r'\bastro\b'),
                         ('react', r'\breact\b'), ('python', r'\bpython\b|fastapi|django'),
                         ('node', r'node\.?js|express'), ('static', r'чист\w* html|без фреймворк|vanilla')]:
        if re.search(pattern, text):
            return key
    if _API_SERVICE.search(text) or re.search(r'\bбот|\bbot\b|api.?сервис|обработк\w* данных', text):
        return 'python'
    if re.search(r'магазин|каталог|\bseo\b|маркетплейс|\bsaas\b', text):
        return 'next'
    if re.search(r'приложен|дашборд|личный кабинет|dashboard|application|\bapp\b', text):
        return 'react'
    if re.search(r'блог|документац|медиа|\bblog\b', text):
        return 'astro'
    return 'static'
