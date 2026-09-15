"""PNG infographic renderer for Studio boards."""

from __future__ import annotations

from typing import Any

from studio.themes import Theme, get_theme, hex_to_rgb


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    names = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        w, _ = _text_size(draw, trial, font)
        if w <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped(draw, xy, text, font, fill, max_width: int, line_gap: int = 8) -> int:
    x, y = xy
    lines = _wrap(draw, text, font, max_width)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        _, h = _text_size(draw, line, font)
        y += h + line_gap
    return y


def render_board_png(spec: dict[str, Any]) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw

    from studio.compose import STYLE_TEXT, clamp_box
    from studio.themes import theme_color

    theme = get_theme(spec.get("theme_id"), spec.get("theme"))
    landscape = spec.get("orientation") != "portrait"
    W, H = (1920, 1080) if landscape else (1080, 1920)
    margin = 72 if landscape else 64

    bg_bytes = spec.get("image_bytes")
    if bg_bytes:
        try:
            base = Image.open(BytesIO(bg_bytes)).convert("RGB").resize((W, H))
            # Soft darken/lighten overlay for readability
            overlay = Image.new("RGB", (W, H), hex_to_rgb(theme.bg))
            img = Image.blend(base, overlay, 0.45)
        except Exception:
            img = Image.new("RGB", (W, H), hex_to_rgb(theme.bg))
    else:
        img = Image.new("RGB", (W, H), hex_to_rgb(theme.bg))
    draw = ImageDraw.Draw(img)

    if spec.get("layout_id") == "composed":
        for el in spec.get("elements") or []:
            left, top, width, height = clamp_box(el.get("x"), el.get("y"), el.get("w"), el.get("h"), W, H)
            etype = el.get("type")
            if etype == "ellipse":
                draw.ellipse([left, top, left + width, top + height], fill=hex_to_rgb(theme_color(theme, el.get("fill") or "accent")))
            elif etype == "rounded":
                draw.rounded_rectangle([left, top, left + width, top + height], radius=22, fill=hex_to_rgb(theme_color(theme, el.get("fill") or "surface")))
            elif etype == "rule":
                draw.rectangle([left, top, left + max(width, 2), top + max(height, 4)], fill=hex_to_rgb(theme_color(theme, el.get("fill") or "accent")))
            elif etype == "number":
                font = _font(72 if landscape else 56, bold=True)
                draw.text((left, top), el.get("text") or "", font=font, fill=hex_to_rgb(theme.accent))
            elif etype in {"rect", "shape", "accent_bar"}:
                draw.rectangle([left, top, left + width, top + height], fill=hex_to_rgb(theme_color(theme, el.get("fill") or "surface")))
            elif etype == "text":
                style = STYLE_TEXT.get(el.get("style") or "body", STYLE_TEXT["body"])
                font = _font(style["size"] + 6 if landscape else style["size"], bold=style["bold"])
                _draw_wrapped(draw, (left, top), el.get("text") or "", font, hex_to_rgb(theme_color(theme, style["color"])), width)
            elif etype == "bullets":
                font = _font(22 if landscape else 18)
                y = top
                for bullet in el.get("items") or []:
                    draw.ellipse([left, y + 8, left + 14, y + 22], fill=hex_to_rgb(theme.accent))
                    y = _draw_wrapped(draw, (left + 28, y), bullet, font, hex_to_rgb(theme.text), width - 28) + 10
                    if y > top + height:
                        break
            elif etype == "card":
                draw.rounded_rectangle([left, top, left + width, top + height], radius=18, fill=hex_to_rgb(theme.surface), outline=hex_to_rgb(theme.line), width=2)
                title_font = _font(24, bold=True)
                body_font = _font(20)
                ty = _draw_wrapped(draw, (left + 24, top + 24), el.get("title") or "", title_font, hex_to_rgb(theme.accent), width - 48)
                if el.get("body"):
                    _draw_wrapped(draw, (left + 24, ty + 12), el["body"], body_font, hex_to_rgb(theme.text), width - 48)
            elif etype == "image":
                data = el.get("image_bytes")
                if data:
                    try:
                        patch = Image.open(BytesIO(data)).convert("RGB").resize((width, height))
                        img.paste(patch, (left, top))
                    except Exception:
                        draw.rectangle([left, top, left + width, top + height], fill=hex_to_rgb(theme.surface))
                else:
                    draw.rectangle([left, top, left + width, top + height], fill=hex_to_rgb(theme.surface))
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    title_font = _font(54, bold=True)
    sub_font = _font(26)
    card_title = _font(24, bold=True)
    card_body = _font(20)
    foot_font = _font(16)
    kpi_font = _font(48, bold=True)

    # Accent bar
    draw.rectangle([0, 0, 12, H], fill=hex_to_rgb(theme.accent))

    y = margin
    draw.text((margin, y), spec["headline"], font=title_font, fill=hex_to_rgb(theme.text))
    _, th = _text_size(draw, spec["headline"], title_font)
    y += th + 18
    if spec.get("subhead"):
        y = _draw_wrapped(draw, (margin, y), spec["subhead"], sub_font, hex_to_rgb(theme.muted), W - 2 * margin)
        y += 28
    else:
        y += 12

    layout = spec["layout_id"]
    content_bottom = H - margin - 40

    if layout in {"timeline", "process", "funnel"}:
        steps = spec["steps"]
        n = len(steps)
        if landscape:
            gap = 24
            box_w = (W - 2 * margin - gap * (n - 1)) // n
            box_h = min(360, content_bottom - y)
            for i, step in enumerate(steps):
                x = margin + i * (box_w + gap)
                # Funnel: shrink width visually by inset
                inset = int(i * 18) if layout == "funnel" else 0
                draw.rounded_rectangle(
                    [x + inset, y, x + box_w - inset, y + box_h],
                    radius=18,
                    fill=hex_to_rgb(theme.surface),
                    outline=hex_to_rgb(theme.line),
                    width=2,
                )
                draw.ellipse([x + inset + 22, y + 28, x + inset + 54, y + 60], fill=hex_to_rgb(theme.accent))
                num_font = _font(16, bold=True)
                draw.text((x + inset + 30, y + 32), str(i + 1), font=num_font, fill=hex_to_rgb(theme.bg))
                ty = y + 80
                ty = _draw_wrapped(draw, (x + inset + 22, ty), step["title"], card_title, hex_to_rgb(theme.text), box_w - inset * 2 - 44)
                if step.get("body"):
                    _draw_wrapped(draw, (x + inset + 22, ty + 10), step["body"], card_body, hex_to_rgb(theme.muted), box_w - inset * 2 - 44)
        else:
            box_h = max(120, (content_bottom - y - 16 * (n - 1)) // n)
            for i, step in enumerate(steps):
                yy = y + i * (box_h + 16)
                draw.rounded_rectangle(
                    [margin, yy, W - margin, yy + box_h],
                    radius=16,
                    fill=hex_to_rgb(theme.surface),
                    outline=hex_to_rgb(theme.line),
                    width=2,
                )
                draw.ellipse([margin + 22, yy + 28, margin + 54, yy + 60], fill=hex_to_rgb(theme.accent))
                draw.text((margin + 30, yy + 32), str(i + 1), font=_font(16, bold=True), fill=hex_to_rgb(theme.bg))
                _draw_wrapped(draw, (margin + 72, yy + 24), step["title"], card_title, hex_to_rgb(theme.text), W - 2 * margin - 90)
                if step.get("body"):
                    _draw_wrapped(draw, (margin + 72, yy + 60), step["body"], card_body, hex_to_rgb(theme.muted), W - 2 * margin - 90)

    elif layout == "kpi_strip":
        kpis = spec["kpis"]
        n = len(kpis)
        gap = 24
        box_w = (W - 2 * margin - gap * (n - 1)) // n
        box_h = 280 if landscape else 220
        for i, kpi in enumerate(kpis):
            x = margin + i * (box_w + gap)
            draw.rounded_rectangle(
                [x, y, x + box_w, y + box_h],
                radius=18,
                fill=hex_to_rgb(theme.surface),
                outline=hex_to_rgb(theme.line),
                width=2,
            )
            draw.text((x + 28, y + 48), kpi["value"], font=kpi_font, fill=hex_to_rgb(theme.accent))
            _draw_wrapped(draw, (x + 28, y + 140), kpi["label"], card_body, hex_to_rgb(theme.text), box_w - 56)

    elif layout == "compare_cards":
        cards = spec["cards"]
        n = len(cards)
        gap = 28
        box_w = (W - 2 * margin - gap * (n - 1)) // n
        box_h = min(420, content_bottom - y)
        for i, card in enumerate(cards):
            x = margin + i * (box_w + gap)
            draw.rounded_rectangle(
                [x, y, x + box_w, y + box_h],
                radius=18,
                fill=hex_to_rgb(theme.surface),
                outline=hex_to_rgb(theme.line),
                width=2,
            )
            draw.rectangle([x, y, x + box_w, y + 8], fill=hex_to_rgb(theme.accent))
            ty = _draw_wrapped(draw, (x + 28, y + 36), card["title"], card_title, hex_to_rgb(theme.text), box_w - 56)
            if card.get("body"):
                _draw_wrapped(draw, (x + 28, ty + 16), card["body"], card_body, hex_to_rgb(theme.muted), box_w - 56)

    elif layout == "hierarchy":
        levels = spec["levels"]
        n = len(levels)
        box_h = max(110, (content_bottom - y - 18 * (n - 1)) // n)
        for i, level in enumerate(levels):
            yy = y + i * (box_h + 18)
            inset = i * 36
            draw.rounded_rectangle(
                [margin + inset, yy, W - margin - inset, yy + box_h],
                radius=16,
                fill=hex_to_rgb(theme.surface),
                outline=hex_to_rgb(theme.line),
                width=2,
            )
            _draw_wrapped(draw, (margin + inset + 28, yy + 22), level["title"], card_title, hex_to_rgb(theme.accent), W - 2 * margin - 2 * inset - 56)
            if level.get("body"):
                _draw_wrapped(draw, (margin + inset + 28, yy + 58), level["body"], card_body, hex_to_rgb(theme.muted), W - 2 * margin - 2 * inset - 56)

    if spec.get("footnote"):
        draw.text((margin, H - margin), spec["footnote"], font=foot_font, fill=hex_to_rgb(theme.muted))

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
