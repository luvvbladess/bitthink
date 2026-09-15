"""Visual themes for Studio presentations and infographics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    bg: str
    surface: str
    text: str
    muted: str
    accent: str
    line: str
    title_font: str
    body_font: str
    # Spacing / type scale hints for renderers (inches / pt)
    margin: float = 0.95
    display_pt: int = 44
    title_pt: int = 28
    body_pt: int = 16
    caption_pt: int = 13


THEMES: dict[str, Theme] = {
    "quiet_teal": Theme(
        id="quiet_teal",
        label="Bit-Think signal dark",
        bg="#070A0C",
        surface="#10161A",
        text="#F4F7F8",
        muted="#8B969E",
        accent="#21A0CE",
        line="#1E282E",
        title_font="Segoe UI",
        body_font="Segoe UI",
        margin=1.0,
        display_pt=46,
        title_pt=28,
        body_pt=16,
    ),
    "editorial": Theme(
        id="editorial",
        label="Editorial paper",
        bg="#F3EFE8",
        surface="#FFFCF8",
        text="#141210",
        muted="#6A635A",
        accent="#9C3D1E",
        line="#DDD5C8",
        title_font="Georgia",
        body_font="Calibri",
        margin=1.05,
        display_pt=48,
        title_pt=30,
        body_pt=16,
    ),
    "data_dark": Theme(
        id="data_dark",
        label="Terminal data",
        bg="#08090B",
        surface="#12151C",
        text="#E8EDF2",
        muted="#7D8794",
        accent="#3DDC97",
        line="#222833",
        title_font="Consolas",
        body_font="Segoe UI",
        margin=0.95,
        display_pt=42,
        title_pt=26,
        body_pt=15,
    ),
    "clean_light": Theme(
        id="clean_light",
        label="Product light",
        bg="#FAFBFC",
        surface="#FFFFFF",
        text="#0F1215",
        muted="#5C6770",
        accent="#1565C0",
        line="#E6EAEF",
        title_font="Segoe UI",
        body_font="Segoe UI",
        margin=1.0,
        display_pt=44,
        title_pt=28,
        body_pt=16,
    ),
    "noir": Theme(
        id="noir",
        label="Noir manifesto",
        bg="#050505",
        surface="#111111",
        text="#F5F5F5",
        muted="#8A8A8A",
        accent="#E8E8E8",
        line="#222222",
        title_font="Georgia",
        body_font="Segoe UI",
        margin=1.1,
        display_pt=52,
        title_pt=30,
        body_pt=16,
    ),
}

DEFAULT_THEME = "quiet_teal"
_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    if len(raw) != 6:
        return (20, 24, 28)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _norm_hex(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not _HEX.match(text):
        return fallback
    if not text.startswith("#"):
        text = "#" + text
    return text.upper()


def get_theme(theme_id: str | None = None, custom: dict[str, Any] | None = None) -> Theme:
    if isinstance(custom, dict) and custom:
        base = THEMES.get(str(custom.get("base") or theme_id or DEFAULT_THEME).lower()) or THEMES[DEFAULT_THEME]
        return Theme(
            id="custom",
            label=str(custom.get("label") or "Custom"),
            bg=_norm_hex(custom.get("bg"), base.bg),
            surface=_norm_hex(custom.get("surface"), base.surface),
            text=_norm_hex(custom.get("text"), base.text),
            muted=_norm_hex(custom.get("muted"), base.muted),
            accent=_norm_hex(custom.get("accent"), base.accent),
            line=_norm_hex(custom.get("line"), base.line),
            title_font=str(custom.get("title_font") or base.title_font),
            body_font=str(custom.get("body_font") or base.body_font),
            margin=float(custom.get("margin") or base.margin),
            display_pt=int(custom.get("display_pt") or base.display_pt),
            title_pt=int(custom.get("title_pt") or base.title_pt),
            body_pt=int(custom.get("body_pt") or base.body_pt),
            caption_pt=int(custom.get("caption_pt") or base.caption_pt),
        )
    key = (theme_id or DEFAULT_THEME).strip().lower()
    return THEMES.get(key) or THEMES[DEFAULT_THEME]


def theme_color(theme: Theme, token: str) -> str:
    mapping = {
        "bg": theme.bg,
        "surface": theme.surface,
        "text": theme.text,
        "muted": theme.muted,
        "accent": theme.accent,
        "line": theme.line,
    }
    if token in mapping:
        return mapping[token]
    if _HEX.match(str(token or "")):
        return _norm_hex(token, theme.accent)
    return theme.text
