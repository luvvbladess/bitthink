"""Validation for Studio deck / board JSON specs."""

from __future__ import annotations

from typing import Any

from studio.compose import ELEMENT_TYPES, STYLE_TEXT
from studio.layouts_board import BOARD_LAYOUT_IDS, BOARD_LAYOUTS, BOARD_ORIENTATIONS
from studio.layouts_deck import DECK_LAYOUT_IDS, DECK_LAYOUTS
from studio.themes import DEFAULT_THEME, THEMES


class StudioSpecError(ValueError):
    pass


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").replace("—", "–").split())
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _prompt(value: Any) -> str:
    return _clip(value, 480)


def _normalize_theme_fields(raw: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    theme_id = str(raw.get("theme_id") or DEFAULT_THEME).strip().lower()
    custom = raw.get("theme") if isinstance(raw.get("theme"), dict) else None
    if custom:
        return "custom", custom
    if theme_id not in THEMES:
        theme_id = DEFAULT_THEME
    return theme_id, None


def _normalize_elements(raw_elements: Any, *, max_elements: int, text_limit: int, bullet_limit: int, max_bullets: int) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for item in _as_list(raw_elements):
        if not isinstance(item, dict):
            continue
        etype = str(item.get("type") or "").strip().lower()
        if etype not in ELEMENT_TYPES:
            continue
        el: dict[str, Any] = {
            "type": etype,
            "x": item.get("x", 0),
            "y": item.get("y", 0),
            "w": item.get("w", 40),
            "h": item.get("h", 20),
        }
        if etype == "text":
            style = str(item.get("style") or "body").lower()
            if style not in STYLE_TEXT:
                style = "body"
            el["style"] = style
            el["text"] = _clip(item.get("text"), text_limit)
            if not el["text"]:
                continue
        elif etype == "bullets":
            bullets = [_clip(b, bullet_limit) for b in _as_list(item.get("items") or item.get("bullets"))]
            bullets = [b for b in bullets if b][:max_bullets]
            if not bullets:
                continue
            el["items"] = bullets
        elif etype == "image":
            el["prompt"] = _prompt(item.get("prompt") or item.get("image_prompt"))
            if not el["prompt"]:
                continue
        elif etype == "card":
            el["title"] = _clip(item.get("title"), 40)
            el["body"] = _clip(item.get("body") or item.get("text"), text_limit)
            if not el["title"] and not el["body"]:
                continue
        elif etype == "number":
            el["text"] = _clip(item.get("text") or item.get("value"), 18)
            if not el["text"]:
                continue
            el["style"] = "kpi"
        elif etype == "rule":
            el["fill"] = str(item.get("fill") or "accent")
        elif etype in {"rect", "shape", "accent_bar", "ellipse", "rounded"}:
            el["fill"] = str(item.get("fill") or ("accent" if etype in {"accent_bar", "ellipse"} else "surface"))
        elements.append(el)
        if len(elements) >= max_elements:
            break
    return elements


def normalize_deck(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StudioSpecError("DeckSpec должен быть объектом JSON")
    theme_id, custom_theme = _normalize_theme_fields(raw)
    title = _clip(raw.get("title") or "Презентация", 80)
    slides_in = _as_list(raw.get("slides"))
    if not slides_in:
        raise StudioSpecError("Нужен хотя бы один слайд")
    if len(slides_in) > 24:
        slides_in = slides_in[:24]

    slides: list[dict[str, Any]] = []
    for index, item in enumerate(slides_in):
        if not isinstance(item, dict):
            raise StudioSpecError(f"Слайд {index + 1}: ожидается объект")
        layout = str(item.get("layout_id") or item.get("layout") or "").strip().lower()
        if layout not in DECK_LAYOUT_IDS:
            raise StudioSpecError(f"Слайд {index + 1}: неизвестный layout_id «{layout}»")
        limits = DECK_LAYOUTS[layout]["limits"]
        slide: dict[str, Any] = {"layout_id": layout}
        if item.get("image_prompt"):
            slide["image_prompt"] = _prompt(item.get("image_prompt"))

        if layout == "title":
            slide["title"] = _clip(item.get("title"), limits["title"]) or f"Слайд {index + 1}"
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
            slide["footer"] = _clip(item.get("footer"), limits["footer"])
        elif layout == "section":
            slide["eyebrow"] = _clip(item.get("eyebrow"), limits["eyebrow"])
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Раздел"
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
        elif layout == "bullets_focus":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Ключевые пункты"
            bullets = [_clip(b, limits["bullet"]) for b in _as_list(item.get("bullets"))]
            bullets = [b for b in bullets if b][: int(limits["max_bullets"])]
            if not bullets:
                raise StudioSpecError(f"Слайд {index + 1}: нужны bullets")
            slide["bullets"] = bullets
        elif layout == "two_column":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Сравнение"
            left_title = _clip(item.get("left_title"), limits["left_title"])
            right_title = _clip(item.get("right_title"), limits["right_title"])
            left_body = _clip(item.get("left_body"), limits["left_body"])
            right_body = _clip(item.get("right_body"), limits["right_body"])
            from studio.quality import is_placeholder

            if is_placeholder(left_title) or is_placeholder(right_title) or not left_body or not right_body:
                raise StudioSpecError(
                    f"Слайд {index + 1}: two_column нужен с реальными заголовками и текстом в обеих колонках"
                )
            slide["left_title"] = left_title
            slide["left_body"] = left_body
            slide["right_title"] = right_title
            slide["right_body"] = right_body
        elif layout == "big_number":
            slide["title"] = _clip(item.get("title"), limits["title"])
            slide["value"] = _clip(item.get("value"), limits["value"]) or "—"
            slide["caption"] = _clip(item.get("caption"), limits["caption"])
            slide["note"] = _clip(item.get("note"), limits["note"])
        elif layout == "quote":
            slide["quote"] = _clip(item.get("quote"), limits["quote"]) or "…"
            slide["attribution"] = _clip(item.get("attribution"), limits["attribution"])
        elif layout == "comparison":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Сравнение"
            left_label = _clip(item.get("left_label"), limits["left_label"])
            right_label = _clip(item.get("right_label"), limits["right_label"])
            left_items = [_clip(x, limits["item"]) for x in _as_list(item.get("left_items"))]
            right_items = [_clip(x, limits["item"]) for x in _as_list(item.get("right_items"))]
            left_items = [x for x in left_items if x][: int(limits["max_items"])]
            right_items = [x for x in right_items if x][: int(limits["max_items"])]
            from studio.quality import is_placeholder

            if (
                is_placeholder(left_label)
                or is_placeholder(right_label)
                or len(left_items) < 2
                or len(right_items) < 2
            ):
                raise StudioSpecError(
                    f"Слайд {index + 1}: comparison нужен с понятными метками и минимум 2 пункта с каждой стороны"
                )
            slide["left_label"] = left_label
            slide["right_label"] = right_label
            slide["left_items"] = left_items
            slide["right_items"] = right_items
        elif layout == "chart_panel":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Данные"
            slide["caption"] = _clip(item.get("caption"), limits["caption"])
            chart = item.get("chart") if isinstance(item.get("chart"), dict) else {}
            points = []
            for point in _as_list(chart.get("data") or chart.get("points")):
                if not isinstance(point, dict):
                    continue
                label = _clip(point.get("label") or point.get("name"), 24)
                try:
                    value = float(str(point.get("value") or 0).replace(" ", "").replace(",", "."))
                except (TypeError, ValueError):
                    continue
                if label:
                    points.append({"label": label, "value": value})
            if len(points) < 2:
                raise StudioSpecError(f"Слайд {index + 1}: chart_panel нужен минимум с 2 точками")
            slide["chart"] = {
                "type": str(chart.get("type") or "bar").lower() if str(chart.get("type") or "bar").lower() in {"bar", "line"} else "bar",
                "data": points[:8],
            }
        elif layout == "closing":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Дальше"
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
            cta = _clip(item.get("cta"), limits["cta"])
            from studio.quality import is_meta_cta

            if cta and not is_meta_cta(cta):
                slide["cta"] = cta
        elif layout == "statement":
            slide["title"] = _clip(item.get("title") or item.get("text"), limits["title"]) or "…"
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
        elif layout == "stack":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Стек"
            items = [_clip(x, limits["item"]) for x in _as_list(item.get("items") or item.get("bullets"))]
            items = [x for x in items if x][: int(limits["max_items"])]
            if len(items) < 3:
                raise StudioSpecError(f"Слайд {index + 1}: stack нужен минимум с 3 пунктами")
            slide["items"] = items
        elif layout == "visual":
            slide["title"] = _clip(item.get("title"), limits["title"])
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
            anchor = str(item.get("anchor") or "bottom").lower()
            slide["anchor"] = anchor if anchor in {"bottom", "center", "top-left", "bottom-right", "bottom-left"} else "bottom"
            if not slide.get("image_prompt"):
                slide["image_prompt"] = _prompt(item.get("prompt") or f"Cinematic still related to {slide['title'] or 'the brief'}, no text")
        elif layout == "poster":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Кадр"
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
            anchor = str(item.get("anchor") or "bottom-left").lower()
            slide["anchor"] = anchor if anchor in {"bottom", "center", "top-left", "bottom-right", "bottom-left"} else "bottom-left"
            if not slide.get("image_prompt"):
                slide["image_prompt"] = _prompt(item.get("prompt") or f"Art directed poster photograph for {slide['title']}, no letters")
        elif layout == "mosaic":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Кадры"
            slide["subtitle"] = _clip(item.get("subtitle"), limits["subtitle"])
            tiles = []
            for tile in _as_list(item.get("tiles") or item.get("images")):
                if not isinstance(tile, dict):
                    prompt = _prompt(tile)
                    if prompt:
                        tiles.append({"image_prompt": prompt, "caption": ""})
                    continue
                prompt = _prompt(tile.get("image_prompt") or tile.get("prompt"))
                if not prompt:
                    continue
                tiles.append({
                    "image_prompt": prompt,
                    "caption": _clip(tile.get("caption") or tile.get("title"), limits["caption"]),
                })
            tiles = tiles[: int(limits["max_tiles"])]
            if len(tiles) < 2:
                raise StudioSpecError(f"Слайд {index + 1}: mosaic нужен минимум с 2 кадрами")
            slide["tiles"] = tiles
        elif layout == "metric_row":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Цифры"
            kpis = []
            for kpi in _as_list(item.get("kpis") or item.get("items")):
                if isinstance(kpi, dict):
                    value = _clip(kpi.get("value") or kpi.get("text"), limits["kpi_value"])
                    label = _clip(kpi.get("label") or kpi.get("title"), limits["kpi_label"])
                else:
                    value = _clip(kpi, limits["kpi_value"])
                    label = ""
                if value:
                    kpis.append({"value": value, "label": label})
            kpis = kpis[: int(limits["max_kpis"])]
            if len(kpis) < 2:
                raise StudioSpecError(f"Слайд {index + 1}: metric_row нужен минимум с 2 цифрами")
            slide["kpis"] = kpis
        elif layout == "split_visual":
            slide["title"] = _clip(item.get("title"), limits["title"]) or "Слайд"
            slide["body"] = _clip(item.get("body") or item.get("text"), limits["body"])
            bullets = [_clip(b, limits["bullet"]) for b in _as_list(item.get("bullets"))]
            slide["bullets"] = [b for b in bullets if b][: int(limits["max_bullets"])]
            side = str(item.get("image_side") or "right").lower()
            slide["image_side"] = "left" if side == "left" else "right"
            if not slide.get("image_prompt"):
                slide["image_prompt"] = _prompt(item.get("prompt") or f"Clean conceptual illustration for {slide['title']}")
        elif layout == "composed":
            if item.get("image_prompt"):
                slide["image_prompt"] = _prompt(item.get("image_prompt"))
            elements = _normalize_elements(
                item.get("elements"),
                max_elements=int(limits["max_elements"]),
                text_limit=int(limits["text"]),
                bullet_limit=int(limits["bullet"]),
                max_bullets=int(limits["max_bullets"]),
            )
            if len(elements) < 2:
                raise StudioSpecError(f"Слайд {index + 1}: composed нужен минимум с 2 элементами")
            slide["elements"] = elements
        slides.append(slide)

    result: dict[str, Any] = {"kind": "deck", "theme_id": theme_id, "title": title, "slides": slides}
    if custom_theme:
        result["theme"] = custom_theme
    return result


def normalize_board(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StudioSpecError("BoardSpec должен быть объектом JSON")
    theme_id, custom_theme = _normalize_theme_fields(raw)
    layout = str(raw.get("layout_id") or raw.get("layout") or "").strip().lower()
    if layout not in BOARD_LAYOUT_IDS:
        raise StudioSpecError(f"Неизвестный layout_id инфографики «{layout}»")
    orientation = str(raw.get("orientation") or "landscape").strip().lower()
    if orientation not in BOARD_ORIENTATIONS:
        orientation = "landscape"
    limits = BOARD_LAYOUTS[layout]["limits"]
    board: dict[str, Any] = {
        "kind": "infographic",
        "theme_id": theme_id,
        "layout_id": layout,
        "orientation": orientation,
        "headline": _clip(raw.get("headline") or raw.get("title"), limits.get("headline", 56)) or "Инфографика",
        "subhead": _clip(raw.get("subhead") or raw.get("subtitle"), limits.get("subhead", 100)),
        "footnote": _clip(raw.get("footnote"), limits.get("footnote", 90)),
    }
    if raw.get("image_prompt"):
        board["image_prompt"] = _prompt(raw.get("image_prompt"))
    if custom_theme:
        board["theme"] = custom_theme

    if layout == "composed":
        elements = _normalize_elements(
            raw.get("elements"),
            max_elements=int(limits["max_elements"]),
            text_limit=int(limits["text"]),
            bullet_limit=int(limits["bullet"]),
            max_bullets=int(limits["max_bullets"]),
        )
        if len(elements) < 2:
            raise StudioSpecError("composed-инфографика: минимум 2 элемента")
        board["elements"] = elements
        return board

    if layout in {"timeline", "process", "funnel"}:
        steps = []
        for item in _as_list(raw.get("steps") or raw.get("items")):
            if isinstance(item, dict):
                title = _clip(item.get("title") or item.get("label"), limits["step_title"])
                body = _clip(item.get("body") or item.get("text"), limits["step_body"])
            else:
                title = _clip(item, limits["step_title"])
                body = ""
            if title:
                steps.append({"title": title, "body": body})
        steps = steps[: int(limits["max_steps"])]
        if len(steps) < 3:
            raise StudioSpecError("Нужно минимум 3 шага")
        board["steps"] = steps
    elif layout == "kpi_strip":
        kpis = []
        for item in _as_list(raw.get("kpis") or raw.get("items")):
            if not isinstance(item, dict):
                continue
            value = _clip(item.get("value"), limits["kpi_value"])
            label = _clip(item.get("label") or item.get("title"), limits["kpi_label"])
            if value and label:
                kpis.append({"value": value, "label": label})
        kpis = kpis[: int(limits["max_kpis"])]
        if len(kpis) < 2:
            raise StudioSpecError("Нужно минимум 2 KPI")
        board["kpis"] = kpis
    elif layout == "compare_cards":
        cards = []
        for item in _as_list(raw.get("cards") or raw.get("items")):
            if not isinstance(item, dict):
                continue
            title = _clip(item.get("title") or item.get("label"), limits["card_title"])
            body = _clip(item.get("body") or item.get("text"), limits["card_body"])
            if title:
                cards.append({"title": title, "body": body})
        cards = cards[: int(limits["max_cards"])]
        if len(cards) < 2:
            raise StudioSpecError("Нужно минимум 2 карточки")
        board["cards"] = cards
    elif layout == "hierarchy":
        levels = []
        for item in _as_list(raw.get("levels") or raw.get("items")):
            if isinstance(item, dict):
                title = _clip(item.get("title") or item.get("label"), limits["level_title"])
                body = _clip(item.get("body") or item.get("text"), limits["level_body"])
            else:
                title = _clip(item, limits["level_title"])
                body = ""
            if title:
                levels.append({"title": title, "body": body})
        levels = levels[: int(limits["max_levels"])]
        if len(levels) < 2:
            raise StudioSpecError("Нужно минимум 2 уровня")
        board["levels"] = levels
    return board


def normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StudioSpecError("Спецификация должна быть JSON-объектом")
    kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    if kind in {"deck", "presentation", "pptx", "slides"}:
        return normalize_deck(raw)
    if kind in {"infographic", "board", "info"}:
        return normalize_board(raw)
    if "slides" in raw:
        return normalize_deck(raw)
    if any(key in raw for key in ("steps", "kpis", "cards", "levels", "layout_id", "elements")):
        return normalize_board(raw)
    raise StudioSpecError("Укажите kind: deck или infographic")
