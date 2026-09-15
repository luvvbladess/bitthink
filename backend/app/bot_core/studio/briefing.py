"""Turn attached files into a style sample + TZ brief for Studio."""

from __future__ import annotations

import re
from pathlib import Path

_DOC_CHUNK = re.compile(
    r"Пользователь предоставил документ для контекста:\s*(.+?)\n\nСодержание:\n([\s\S]*?)"
    r"(?=\n\nПользователь предоставил документ|\Z)",
    re.I,
)
_STYLE_NAME = re.compile(r"(?i)(пример|образец|стиль|style|template|шаблон|бренд|brand|impact|импакт)")
_BRIEF_NAME = re.compile(r"(?i)(тз|tz|бриф|brief|задани|спецификац|контент|content|сценари)")
_SLIDE_HINT = re.compile(r"(?i)(слайд|презентац|питч|pitch|deck|powerpoint|выступлен)")
_HEX = re.compile(r"(?i)(Фон|Поверхность|Текст|Акцент):\s*(#[0-9A-Fa-f]{6})")
_FONT = re.compile(r"(?i)Шрифт (заголовков|тела):\s*(.+)")
_DECK_SUFFIX = {".pptx", ".ppt", ".odp"}
_STYLE_SUFFIX = {".pptx", ".ppt", ".odp", ".pdf"}
_BRIEF_SUFFIX = {".docx", ".doc", ".txt", ".md", ".rtf"}


def iter_attached_docs(document_context: str) -> list[tuple[str, str]]:
    found = [(m.group(1).strip(), (m.group(2) or "").strip()) for m in _DOC_CHUNK.finditer(document_context or "")]
    if found:
        return found
    text = (document_context or "").strip()
    return [("", text)] if text else []


def _is_style_file(name: str, *, sibling_names: list[str] | None = None) -> bool:
    suffix = Path(name or "").suffix.lower()
    if _BRIEF_NAME.search(name or ""):
        return False
    if suffix in _DECK_SUFFIX:
        return True
    if suffix == ".pdf":
        siblings = [item for item in (sibling_names or []) if item and item != name]
        if any(Path(item).suffix.lower() in _BRIEF_SUFFIX or _BRIEF_NAME.search(item) for item in siblings):
            return True
        if _STYLE_NAME.search(name or ""):
            return True
    return bool(_STYLE_NAME.search(name or ""))


def format_studio_documents(document_context: str) -> str:
    docs = iter_attached_docs(document_context)
    if not docs:
        return ""
    names = [name for name, _ in docs]
    style_parts: list[str] = []
    brief_parts: list[str] = []
    named = any(name for name, _ in docs)
    for name, body in docs:
        if not body:
            continue
        if named and _is_style_file(name, sibling_names=names):
            style_parts.append(f"ОБРАЗЕЦ СТИЛЯ ({name}):\n{body}")
        else:
            label = f" ({name})" if name else ""
            brief_parts.append(f"ТЗ / СОДЕРЖАНИЕ{label}:\n{body}")
    if not style_parts and not brief_parts:
        return f"\n\nДокументы пользователя:\n{document_context}"
    blocks: list[str] = []
    if style_parts:
        blocks.append(
            "Стиль заказчика (обязательно повторить палитру, шрифты, сетку и плотность кадра, "
            "не копировать чужую тему слово в слово):\n" + "\n\n".join(style_parts)
        )
    if brief_parts:
        blocks.append(
            "Содержание из ТЗ (факты, структура, формулировки. Не выдумывай слайды мимо этого файла):\n"
            + "\n\n".join(brief_parts)
        )
    return "\n\n" + "\n\n".join(blocks)


def attached_deck_sample(document_context: str) -> bool:
    names = [name for name, _ in iter_attached_docs(document_context) if name]
    return any(
        Path(name).suffix.lower() in _STYLE_SUFFIX and _is_style_file(name, sibling_names=names)
        for name in names
    )


def wants_slides_from_documents(document_context: str) -> bool:
    if attached_deck_sample(document_context):
        return True
    return bool(_SLIDE_HINT.search(document_context or ""))


def theme_from_documents(document_context: str) -> dict[str, str] | None:
    colors = {label.lower(): value.upper() for label, value in _HEX.findall(document_context or "")}
    if "фон" not in colors or "текст" not in colors:
        return None
    fonts = {kind.lower(): name.strip()[:48] for kind, name in _FONT.findall(document_context or "")}
    return {
        "bg": colors["фон"],
        "surface": colors.get("поверхность") or colors["фон"],
        "text": colors["текст"],
        "muted": colors.get("текст") or "#888888",
        "accent": colors.get("акцент") or colors["текст"],
        "line": colors.get("поверхность") or colors["фон"],
        "title_font": fonts.get("заголовков") or "Georgia",
        "body_font": fonts.get("тела") or "Segoe UI",
    }
