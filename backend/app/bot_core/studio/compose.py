"""Shared geometry helpers for composed Studio layouts (percent of canvas)."""

from __future__ import annotations

from typing import Any


def pct(value: Any, total: int, default: float = 0.0) -> int:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        ratio = default
    ratio = max(0.0, min(100.0, ratio))
    return int(total * ratio / 100.0)


def clamp_box(x: Any, y: Any, w: Any, h: Any, canvas_w: int, canvas_h: int) -> tuple[int, int, int, int]:
    left = pct(x, canvas_w)
    top = pct(y, canvas_h)
    width = max(pct(w, canvas_w, 10), int(canvas_w * 0.04))
    height = max(pct(h, canvas_h, 8), int(canvas_h * 0.04))
    if left + width > canvas_w:
        width = max(int(canvas_w * 0.04), canvas_w - left)
    if top + height > canvas_h:
        height = max(int(canvas_h * 0.04), canvas_h - top)
    return left, top, width, height


STYLE_TEXT = {
    "display": {"size": 44, "bold": True, "color": "text"},
    "display_xl": {"size": 64, "bold": True, "color": "text"},
    "title": {"size": 28, "bold": True, "color": "text"},
    "subtitle": {"size": 16, "bold": False, "color": "muted"},
    "body": {"size": 15, "bold": False, "color": "text"},
    "caption": {"size": 12, "bold": False, "color": "muted"},
    "accent": {"size": 14, "bold": True, "color": "accent"},
    "kpi": {"size": 56, "bold": True, "color": "accent"},
}

ELEMENT_TYPES = frozenset({
    "text", "bullets", "image", "rect", "card", "accent_bar", "shape",
    "ellipse", "rounded", "number", "rule",
})
