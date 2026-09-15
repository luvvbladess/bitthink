"""Art direction seed so Studio invents a unique look per brief, not a default teal template."""

from __future__ import annotations

import hashlib
import re

_VIBES = (
    (
        "editorial paper",
        "Тёплые кремы, espresso-акцент, крупный serif-заголовок, воздух как в журнале. "
        "Фото как кадр из эссе, не сток.",
        "editorial",
        {"bg": "#F4EFE6", "surface": "#FFFBF5", "text": "#1A1410", "muted": "#6E6458", "accent": "#9C3D1E", "line": "#DED4C4", "title_font": "Georgia", "body_font": "Calibri"},
    ),
    (
        "ink terminal",
        "Графит, один кислотный акцент, волосяные линии, цифры как экспонаты.",
        "data_dark",
        {"bg": "#07080A", "surface": "#11141A", "text": "#E8EDF2", "muted": "#7A8490", "accent": "#3DDC97", "line": "#222833", "title_font": "Consolas", "body_font": "Segoe UI"},
    ),
    (
        "poster manifesto",
        "Почти чёрный холст, огромный наборный заголовок, минимум хрома, один объект в кадре.",
        "noir",
        {"bg": "#050505", "surface": "#121212", "text": "#F3F3F3", "muted": "#8A8A8A", "accent": "#F0E6D8", "line": "#222222", "title_font": "Georgia", "body_font": "Segoe UI"},
    ),
    (
        "cinematic still",
        "Full-bleed фото, текст в безопасной зоне, тёмный оверлей, как кадр из фильма.",
        "noir",
        {"bg": "#0B0C0E", "surface": "#16181C", "text": "#F5F6F7", "muted": "#9AA3AB", "accent": "#E8C9A8", "line": "#2A2E34", "title_font": "Segoe UI", "body_font": "Segoe UI"},
    ),
    (
        "swiss catalog",
        "Холодный свет, сетка, нумерация 01/02, образцы, без декора.",
        "clean_light",
        {"bg": "#F7F6F3", "surface": "#FFFFFF", "text": "#111111", "muted": "#5C5C5C", "accent": "#C45C26", "line": "#E4E0D8", "title_font": "Segoe UI", "body_font": "Segoe UI"},
    ),
    (
        "oxblood studio",
        "Глубокий бордо и слоновая кость, театральный контраст, один золотой штрих.",
        "editorial",
        {"bg": "#1A0C10", "surface": "#26141A", "text": "#F7EFE8", "muted": "#B59A90", "accent": "#E0B56A", "line": "#3A2228", "title_font": "Georgia", "body_font": "Segoe UI"},
    ),
    (
        "forest instrument",
        "Тёмный лес и тёплый латунный акцент, как точный прибор, не эко-клише.",
        "quiet_teal",
        {"bg": "#0C1210", "surface": "#151C18", "text": "#F1F5F2", "muted": "#8A9890", "accent": "#C4A35A", "line": "#243028", "title_font": "Segoe UI", "body_font": "Segoe UI"},
    ),
    (
        "sand gallery",
        "Песок и сажа, музейная подпись, один крупный объект, много воздуха.",
        "editorial",
        {"bg": "#E7DFD2", "surface": "#F6F0E6", "text": "#1C1814", "muted": "#6F675C", "accent": "#2C4A3E", "line": "#D4C8B6", "title_font": "Georgia", "body_font": "Calibri"},
    ),
)

_SPINES = (
    "холодный visual-hook → манифест → мозаика доказательств → контраст двух путей → ask",
    "крупный объект → процесс как ритм → три цифры → split с кадром → закрытие одной фразой",
    "тихий титул → stack имён → один правдивый график или KPI → цитата/сцена → следующий шаг",
    "постер на весь кадр → statement → сравнение без таблиц → mosaic деталей → closing",
)

_INFO_SPINES = (
    "один сильный headline, 4–6 якорей в уникальной сетке, фон-кадр по теме",
    "слева огромная цифра, справа короткий путь из 4 шагов, без одинаковых карточек",
    "вертикальный ритм: объект сверху, лента фактов снизу, воздух между",
    "диаптих: фото-поле и типографический столбец, KPI внизу как подписи к экспонатам",
)

_TOPIC = re.compile(
    r"(?i)\b(инфографик\w*|infographic|презентац\w*|pptx|powerpoint|слайд\w*|питч\w*|pitch|decks?|выступлен\w*|студия|studio)\b"
)
_FILLER = re.compile(
    r"(?i)\b(сделай|создай|нужна|нужен|пожалуйста|режим|собери|нарисуй|сгенерируй|про|для)\b"
)


def _seed(text: str) -> int:
    return int(hashlib.md5((text or "studio").encode("utf-8")).hexdigest()[:8], 16)


def topic_words(user_text: str) -> list[str]:
    cleaned = _TOPIC.sub(" ", user_text or "")
    cleaned = _FILLER.sub(" ", cleaned)
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", cleaned)


def brief_is_thin(user_text: str) -> bool:
    return len(topic_words(user_text)) < 1


def pick_direction(user_text: str, *, infographic: bool = False) -> dict[str, str | dict]:
    text = (user_text or "").lower()
    seed = _seed(user_text)
    vibe_i = seed % len(_VIBES)
    lower = text
    if any(token in lower for token in ("цифр", "kpi", "данн", "метрик", "финанс", "банк")):
        vibe_i = 1
    elif any(token in lower for token in ("журнал", "мод", "эссе", "культур", "изда")):
        vibe_i = 0
    elif any(token in lower for token in ("кофе", "еда", "ресторан", "пекар", "вино")):
        vibe_i = 0 if seed % 2 == 0 else 7
    elif any(token in lower for token in ("ночь", "манифест", "смел", "чёрн", "черн")):
        vibe_i = 2
    elif any(token in lower for token in ("лес", "климат", "эко", "ферм")):
        vibe_i = 6
    name, brief, theme_id, theme = _VIBES[vibe_i]
    spine = (_INFO_SPINES if infographic else _SPINES)[seed % (len(_INFO_SPINES) if infographic else len(_SPINES))]
    return {
        "vibe": name,
        "brief": brief,
        "theme_id": theme_id,
        "theme": theme,
        "spine": spine,
    }
