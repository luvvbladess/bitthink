"""Bounded, provider-independent task contract. No extra model/network hop.

Labels are planning hints, never evidence or permission to act. The answering
model still resolves the actual goal from the original conversation.
"""
from dataclasses import dataclass
import re

INTENT_MARKER = 'Задача текущего хода'


def _has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def forbids_web(text: str) -> bool:
    return _has(r'\bбез\s+(?:поиска|интернета|веба)\b|\bне\s+(?:ищи|гугли|используй\s+(?:интернет|поиск))\b|'
                r'\b(?:только|исключительно)\s+(?:по\s+)?(?:вложени\w*|файл\w*|данному\s+тексту)\b|'
                r'\b(?:do not|don.t)\s+(?:browse|search)\b', text or '')


@dataclass(frozen=True)
class RequestIntent:
    task: str
    topic: str
    needs_web: bool
    web_forbidden: bool = False
    followup: bool = False
    local: bool = False

    def note(self) -> str:
        contract = {
            'overview': 'Дай готовый обзор с конкретными вариантами и понятным критерием. Для общего топа выбери разумную доступную выборку и назови её; уточнение задачи не обязательно.',
            'comparison': 'Сравни кандидатов по одинаковым критериям, сохрани ограничения пользователя. Дай различия, компромиссы и вывод; таблица нужна только если упрощает сравнение.',
            'recommendation': 'Выбери подходящий вариант под задачу и бюджет, объясни решающие преимущества и ограничения. Отделяй оценку пригодности от проверенных фактов. Неполнота одного кандидата не отменяет сравнение остальных.',
            'fact': 'Сначала ответь на конкретный вопрос. Для изменчивого факта проверь источник, период, регион и единицы. Если фильтры не заданы, используй доступную разумную выборку и явно назови её.',
            'explanation': 'Объясни предмет и практические действия. Общие устойчивые знания можно использовать; точные детали свежей версии проверяй отдельно. Не заменяй инструкцию ссылкой на сборку или рейтинг.',
            'transformation': 'Преобразуй предоставленный материал, сохрани смысл и ограничения. Упоминания цен, новостей и ссылки внутри материала сами по себе не требуют поиска.',
            'creation': 'Создай запрошенный результат. Поиск нужен лишь для необходимых актуальных сведений, а не из-за названия продукта в тексте.',
            'conversation': 'Ответь прямо и естественно, без ненужного исследования.',
            'followup': 'Продолжи предыдущую задачу с её ограничениями, ответь именно на новое уточнение. Прошлый ответ ассистента не является доказательством фактов.',
        }[self.task]
        return (f'{INTENT_MARKER}: {self.task}; область: {self.topic}; '
                f'продолжение: {self.followup}. Это ориентир планирования, а не установленный факт. '
                'Приоритет у исходной просьбы пользователя и её ограничений. ' + contract +
                (' Пользователь запретил интернет: не вызывай поиск и чтение сайтов.' if self.web_forbidden else '') +
                ' Если поиск неполон, сделай ограниченную адресную проверку пробела, дай подтверждённую часть '
                'и кратко обозначь оставшийся пробел. Не выдумывай данные и не обещай безошибочность.')


def classify_request(query: str, history=()) -> RequestIntent:
    """Classify the current ask, inheriting topic only for explicit continuations.

    Quoted/pasted source text is not fed back as a trusted planning instruction.
    History is restricted to the last user ask, not assistant claims or other chats.
    """
    text = (query or '').strip().lower()[:16000]
    head = text.split('\n', 1)[0][:500]
    forbidden = forbids_web(head)
    previous = ''
    for row in reversed(list(history or [])[-8:]):
        role = row.get('role') if isinstance(row, dict) else getattr(row, 'role', None)
        content = row.get('content') if isinstance(row, dict) else getattr(row, 'content', '')
        if role == 'user' and isinstance(content, str) and content.strip().lower() != text:
            previous = content[:2000].lower()
            break
    followup = bool(previous and len(text) < 500 and not _has(r'новая тема|другой вопрос|сменим тему', head) and
                    _has(r'^а\s+как\b|^(?:а\s+)?(?:почему|как насч[её]т|версии?|цена|отзывы|ссылки|цифрами|подробнее|продолжай|сделай короче)\b|'
                         r'\b(?:у не[её]|у него|у них|е[её]|эт(?:о|от|ой|и|их)|он[аои]?)\b', head))
    subject = text + (' ' + previous if followup else '')
    topic = ('ai' if _has(r'нейро(?:нк|нок|сет)\w*|\b(?:llm|ии|ai|gpt|claude|gemini|deepseek|codex)\b|языков\w* модел', subject)
             else 'shopping' if _has(r'купить|в наличии|доставк|маркетплейс|\b(?:ozon|ozon.ru|вб|wb|dns|днс)\b|бюджет|тариф|подписк|корзин', subject)
             else 'games' if _has(r'винрейт|патч|геро\w*|играть\s+(?:за|на)\b|\b(?:дот\w*|dota|mlbb|млбб|млб)\b', subject)
             else 'general')
    game_guide = topic == 'games' and _has(r'как\s+(?:играть|побеждать)|\b(?:гайд|тактик\w*|комбинац\w*|сборк\w*)', head)
    local = False
    if _has(r'^(?:пожалуйста[, ]+)?(?:переведи|перефразируй|сократи|отредактируй|исправь опечатки|оформи|summarize|translate)\b|^сделай (?:короче|таблицу из|резюме текста)', head):
        task, local = 'transformation', True
    elif _has(r'^(?:привет|здравствуй\w*|спасибо|ок|понятно|hello|thanks)[!.\s]*$', text):
        task, local = 'conversation', True
    elif _has(r'^(?:напиши|сочини|придумай|нарисуй|создай|сделай)\b', head) and not _has(r'обзор|сравнен|подбор|топ\b|исследован|актуальн|интернет|поищи|загугли', head):
        task, local = 'creation', True
    elif _has(r'сравн\w*|отлич\w*|разниц\w*|\bvs\b|что лучше|какой из|кто лучше', head):
        task = 'comparison'
    elif _has(r'посовет\w*|порекоменд\w*|подбер\w*|подбери|что (?:взять|купить|выбрать)|как(?:ой|ую|ое|ие) .{0,100}(?:взять|купить|выбрать)|где (?:купить|заказать)|найди.{0,80}в наличии', head):
        task = 'recommendation'
    elif _has(r'\b(?:топ|лучш\w*|лидер\w*|обзор|рейтинг|best|leading)\b|сам(?:ый|ая|ое|ые) (?:сильн|мощн|крут)', head):
        task = 'overview'
    elif _has(r'^(?:а\s+)?(?:поищи\s+)?(?:как|объясни|расскажи|почему|что такое)\b', head):
        task = 'explanation'
        local = not _has(r'сегодня|сейчас|щас|актуальн|последн\w*|нов\w* патч|https?://|поищи|загугли', head) and not game_guide
    elif followup and _has(r'^(?:а\s+)?(?:подробнее|продолжай|почему)\b', head):
        task = 'followup'
    else:
        task = 'fact'
    explicit = _has(r'https?://|\b(?:загугл\w*|погугл\w*|поищи|гугли|найди в (?:интернете|сети)|web search|search online)\b', text)
    fresh = _has(r'сегодня|вчера|актуальн|последн\w* (?:верси|релиз)|новейш|свеж\w*|новост|винрейт|патч|'
                 r'сколько стоит|\bцен[аыуе]\b|в наличии|доставк|\bпогод\w*|курс (?:валют|доллар|евро)|котиров', head)
    fresh = fresh or _has(r'\b(?:что|кто|как(?:ой|ая|ое|ие|ую|овы))\s+(?:сейчас|щас)\b', head)
    # Stable definitions and transformations do not inherit volatile words from
    # their source material. An explicit request to search overrides only local
    # explanations/creation, not a pasted URL inside a translation.
    if explicit and task != 'transformation':
        local = False
    needs_web = not forbidden and not local and bool(
        explicit or fresh or task == 'recommendation' or
        (task == 'overview' and topic in {'ai', 'shopping', 'games'}) or
        (task == 'comparison' and topic in {'ai', 'shopping'}) or
        (task == 'explanation' and game_guide) or
        (followup and _has(r'верс\w*|цифр\w*|цен[аыуе]|отзыв\w*|ссыл\w*|проверь|подтверд\w*', head)))
    return RequestIntent(task, topic, needs_web, forbidden, followup, local)
