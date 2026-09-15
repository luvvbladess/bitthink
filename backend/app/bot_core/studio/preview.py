"""Preview PNGs that look like the actual slides, not a fake card grid."""

from __future__ import annotations

from typing import Any


def _composed_board(spec: dict[str, Any], elements: list[dict[str, Any]], image_bytes: bytes | None = None) -> dict[str, Any]:
    board: dict[str, Any] = {
        "kind": "infographic",
        "theme_id": spec.get("theme_id"),
        "layout_id": "composed",
        "orientation": "landscape",
        "headline": spec.get("title") or "Слайд",
        "elements": elements,
    }
    if spec.get("theme"):
        board["theme"] = spec["theme"]
    if image_bytes:
        board["image_bytes"] = image_bytes
    return board


def _slide_as_board(spec: dict[str, Any], slide: dict[str, Any]) -> dict[str, Any]:
    layout = slide.get("layout_id")
    if layout == "composed" and slide.get("elements"):
        return _composed_board(spec, slide["elements"], slide.get("image_bytes"))
    title = slide.get("title") or slide.get("quote") or slide.get("value") or ""
    subtitle = slide.get("subtitle") or slide.get("caption") or slide.get("cta") or ""
    if layout in {"visual", "poster"}:
        elements = [
            {"type": "text", "x": 7, "y": 68, "w": 78, "h": 16, "style": "display", "text": title or "Кадр"},
        ]
        if subtitle:
            elements.append({"type": "text", "x": 7, "y": 86, "w": 55, "h": 10, "style": "subtitle", "text": subtitle})
        return _composed_board(spec, elements, slide.get("image_bytes"))
    if layout == "metric_row":
        elements: list[dict[str, Any]] = [
            {"type": "text", "x": 6, "y": 10, "w": 80, "h": 10, "style": "caption", "text": title or "Цифры"},
        ]
        kpis = slide.get("kpis") or []
        n = max(len(kpis), 1)
        w = min(28, 90 // n)
        for i, kpi in enumerate(kpis):
            x = 6 + i * (w + 4)
            elements.append({"type": "number", "x": x, "y": 32, "w": w, "h": 22, "text": kpi.get("value") or ""})
            elements.append({"type": "text", "x": x, "y": 58, "w": w, "h": 14, "style": "body", "text": kpi.get("label") or ""})
        return _composed_board(spec, elements)
    if layout == "statement":
        return _composed_board(
            spec,
            [
                {"type": "rule", "x": 8, "y": 40, "w": 8, "h": 1, "fill": "accent"},
                {"type": "text", "x": 8, "y": 44, "w": 84, "h": 28, "style": "display", "text": title},
            ],
        )
    bullets = slide.get("bullets") or slide.get("items") or []
    elements = [
        {"type": "text", "x": 8, "y": 10, "w": 80, "h": 14, "style": "title", "text": title or "Слайд"},
    ]
    if bullets:
        elements.append({"type": "bullets", "x": 8, "y": 32, "w": 70, "h": 55, "items": [str(b) for b in bullets[:4]]})
    elif subtitle:
        elements.append({"type": "text", "x": 8, "y": 32, "w": 70, "h": 20, "style": "body", "text": subtitle})
    return _composed_board(spec, elements, slide.get("image_bytes"))


def render_deck_previews(spec: dict[str, Any], limit: int = 3) -> list[tuple[str, bytes]]:
    from studio.render_board import render_board_png

    previews: list[tuple[str, bytes]] = []
    for index, slide in enumerate(spec.get("slides") or []):
        if len(previews) >= limit:
            break
        try:
            png = render_board_png(_slide_as_board(spec, slide))
        except Exception:
            continue
        previews.append((f"preview-slide-{index + 1}.png", png))
    return previews
