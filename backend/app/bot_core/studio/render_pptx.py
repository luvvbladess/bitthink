"""PPTX renderer for Studio decks – pitch-deck craft, not corporate templates."""

from __future__ import annotations

import io
from typing import Any

from studio.compose import STYLE_TEXT, clamp_box
from studio.themes import Theme, get_theme, hex_to_rgb, theme_color


def _rgb(theme_color_value: str):
    from pptx.dml.color import RGBColor

    r, g, b = hex_to_rgb(theme_color_value)
    return RGBColor(r, g, b)


def _set_run(paragraph, text: str, *, size_pt: int, bold: bool, color: str, font_name: str) -> None:
    from pptx.util import Pt

    paragraph.text = text
    for run in paragraph.runs:
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        run.font.color.rgb = _rgb(color)
        run.font.name = font_name


def _fill_shape(shape, color: str) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()


def _stroke_shape(shape, color: str, pt: float = 1.0) -> None:
    from pptx.util import Pt

    shape.line.color.rgb = _rgb(color)
    shape.line.width = Pt(pt)


def _add_rect(slide, left, top, width, height, color: str, *, stroke: str | None = None):
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    _fill_shape(shape, color)
    if stroke:
        _stroke_shape(shape, stroke, 1.0)
    return shape


def _add_textbox(
    slide,
    left,
    top,
    width,
    height,
    text: str,
    *,
    size: int,
    bold: bool,
    color: str,
    font: str,
    align=None,
    anchor=None,
):
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt

    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    if anchor is not None:
        tf.anchor = anchor
    else:
        tf.anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]
    p.alignment = align if align is not None else PP_ALIGN.LEFT
    _set_run(p, text, size_pt=size, bold=bold, color=color, font_name=font)
    p.space_after = Pt(0)
    p.space_before = Pt(0)
    return box


def _slide_bg(slide, theme: Theme) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(theme.bg)


def _add_picture(slide, data: bytes, left, top, width=None, height=None):
    if not data:
        return None
    stream = io.BytesIO(data)
    return slide.shapes.add_picture(stream, left, top, width=width, height=height)


def _hairline(slide, theme: Theme, left, top, width) -> None:
    from pptx.util import Inches

    _add_rect(slide, left, top, width, int(Inches(0.015)), theme.line)


def _accent_rule(slide, theme: Theme, left, top, width) -> None:
    from pptx.util import Inches

    _add_rect(slide, left, top, width, int(Inches(0.035)), theme.accent)


def _render_chart_image(chart: dict[str, Any], theme: Theme) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    labels = [p["label"] for p in chart["data"]]
    values = [p["value"] for p in chart["data"]]
    fig, ax = plt.subplots(figsize=(9.0, 3.8), dpi=140)
    fig.patch.set_facecolor(theme.bg)
    ax.set_facecolor(theme.bg)
    accent = [c / 255 for c in hex_to_rgb(theme.accent)]
    text = [c / 255 for c in hex_to_rgb(theme.text)]
    muted = [c / 255 for c in hex_to_rgb(theme.muted)]
    if chart.get("type") == "line":
        ax.plot(labels, values, color=accent, linewidth=2.2, marker="o", markersize=5)
    else:
        ax.bar(labels, values, color=accent, width=0.55)
    ax.tick_params(colors=muted, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(theme.line)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color(text)
    ax.grid(axis="y", color=theme.line, linewidth=0.6, alpha=0.7)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _add_oval(slide, left, top, width, height, color: str):
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, width, height)
    _fill_shape(shape, color)
    return shape


def _add_round(slide, left, top, width, height, color: str, *, stroke: str | None = None):
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    _fill_shape(shape, color)
    if stroke:
        _stroke_shape(shape, stroke, 1.0)
    return shape


def _text_band(anchor: str, W: int, H: int) -> tuple[int, int, int, int, int]:
    """Return overlay left, top, width, height and text left inset."""
    if anchor == "center":
        return 0, int(H * 0.32), W, int(H * 0.36), int(W * 0.12)
    if anchor == "top-left":
        return 0, 0, int(W * 0.58), int(H * 0.42), int(W * 0.06)
    if anchor == "bottom-right":
        return int(W * 0.38), int(H * 0.55), int(W * 0.62), int(H * 0.45), int(W * 0.06)
    if anchor == "bottom-left":
        return 0, int(H * 0.55), int(W * 0.62), int(H * 0.45), int(W * 0.07)
    return 0, int(H * 0.58), W, int(H * 0.42), int(W * 0.07)


def _render_poster_visual(slide, slide_spec: dict[str, Any], theme: Theme, W: int, H: int) -> None:
    from pptx.util import Inches

    data = slide_spec.get("image_bytes")
    if data:
        _add_picture(slide, data, 0, 0, width=W, height=H)
    else:
        _slide_bg(slide, theme)
    anchor = slide_spec.get("anchor") or "bottom"
    ox, oy, ow, oh, inset = _text_band(anchor, W, H)
    _add_rect(slide, ox, oy, ow, oh, theme.bg)
    _accent_rule(slide, theme, ox + inset, oy + int(oh * 0.18), int(Inches(1.15)))
    title_top = oy + int(oh * 0.26)
    if slide_spec.get("title"):
        _add_textbox(
            slide, ox + inset, title_top, ow - inset * 2, int(oh * 0.42),
            slide_spec["title"], size=theme.display_pt - 2, bold=True,
            color=theme.text, font=theme.title_font,
        )
    if slide_spec.get("subtitle"):
        _add_textbox(
            slide, ox + inset, oy + int(oh * 0.68), ow - inset * 2, int(oh * 0.24),
            slide_spec["subtitle"], size=theme.body_pt, bold=False,
            color=theme.muted, font=theme.body_font,
        )


def _render_composed(slide, slide_spec: dict[str, Any], theme: Theme, W: int, H: int) -> None:
    bg = slide_spec.get("image_bytes")
    if bg:
        _add_picture(slide, bg, 0, 0, width=W, height=H)
    for el in slide_spec.get("elements") or []:
        left, top, width, height = clamp_box(el.get("x"), el.get("y"), el.get("w"), el.get("h"), W, H)
        etype = el.get("type")
        if etype == "ellipse":
            _add_oval(slide, left, top, width, height, theme_color(theme, el.get("fill") or "accent"))
        elif etype == "rounded":
            _add_round(slide, left, top, width, height, theme_color(theme, el.get("fill") or "surface"), stroke=theme.line)
        elif etype == "rule":
            _add_rect(slide, left, top, max(width, 2), max(int(H * 0.004), height), theme_color(theme, el.get("fill") or "accent"))
        elif etype in {"rect", "shape", "accent_bar"}:
            fill = theme_color(theme, el.get("fill") or "surface")
            stroke = theme.line if etype != "accent_bar" else None
            _add_rect(slide, left, top, width, height, fill, stroke=stroke)
        elif etype == "number":
            _add_textbox(
                slide, left, top, width, height, el.get("text") or "",
                size=64, bold=True, color=theme.accent, font=theme.title_font,
            )
        elif etype == "text":
            style = STYLE_TEXT.get(el.get("style") or "body", STYLE_TEXT["body"])
            size = style["size"]
            if style.get("bold") and size < 22:
                size = max(size, 18)
            _add_textbox(
                slide, left, top, width, height, el.get("text") or "",
                size=size, bold=style["bold"],
                color=theme_color(theme, style["color"]),
                font=theme.title_font if style["bold"] else theme.body_font,
            )
        elif etype == "bullets":
            y = top
            for i, bullet in enumerate(el.get("items") or [], 1):
                num = f"{i:02d}"
                _add_textbox(
                    slide, left, y, int(W * 0.05), int(H * 0.06),
                    num, size=12, bold=True, color=theme.accent, font=theme.body_font,
                )
                _add_textbox(
                    slide, left + int(W * 0.055), y, width - int(W * 0.055), int(H * 0.07),
                    bullet, size=15, bold=False, color=theme.text, font=theme.body_font,
                )
                y += int(H * 0.085)
                if y > top + height:
                    break
        elif etype == "card":
            _add_round(slide, left, top, width, height, theme.surface, stroke=theme.line)
            _add_textbox(
                slide, left + int(W * 0.02), top + int(H * 0.03), width - int(W * 0.04), int(H * 0.06),
                el.get("title") or "", size=15, bold=True, color=theme.text, font=theme.title_font,
            )
            _add_textbox(
                slide, left + int(W * 0.02), top + int(H * 0.11), width - int(W * 0.04), height - int(H * 0.14),
                el.get("body") or "", size=13, bold=False, color=theme.muted, font=theme.body_font,
            )
        elif etype == "image":
            data = el.get("image_bytes")
            if data:
                _add_picture(slide, data, left, top, width=width, height=height)
            else:
                _add_round(slide, left, top, width, height, theme.surface, stroke=theme.line)


def render_deck_pptx(spec: dict[str, Any]) -> bytes:
    from pptx import Presentation
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches

    theme = get_theme(spec.get("theme_id"), spec.get("theme"))
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    W = int(prs.slide_width)
    H = int(prs.slide_height)
    M = int(Inches(theme.margin))
    content_w = W - 2 * M

    for slide_spec in spec["slides"]:
        slide = prs.slides.add_slide(blank)
        layout = slide_spec["layout_id"]

        if layout == "composed":
            _slide_bg(slide, theme)
            _render_composed(slide, slide_spec, theme, W, H)
            continue

        if layout in {"visual", "poster"}:
            _render_poster_visual(slide, slide_spec, theme, W, H)
            continue

        if layout == "mosaic":
            from pptx.util import Inches

            _slide_bg(slide, theme)
            tiles = slide_spec.get("tiles") or []
            _add_textbox(
                slide, M, int(H * 0.06), content_w, int(H * 0.1),
                slide_spec.get("title") or "", size=theme.title_pt, bold=True,
                color=theme.text, font=theme.title_font,
            )
            if slide_spec.get("subtitle"):
                _add_textbox(
                    slide, M, int(H * 0.15), content_w * 0.7, int(H * 0.07),
                    slide_spec["subtitle"], size=theme.body_pt, bold=False,
                    color=theme.muted, font=theme.body_font,
                )
            top = int(H * 0.24)
            box_h = H - top - M
            gap = int(Inches(0.22))
            if len(tiles) == 2:
                tw = (content_w - gap) // 2
                for i, tile in enumerate(tiles):
                    x = M + i * (tw + gap)
                    data = tile.get("image_bytes")
                    if data:
                        _add_picture(slide, data, x, top, width=tw, height=box_h)
                    else:
                        _add_round(slide, x, top, tw, box_h, theme.surface, stroke=theme.line)
                    if tile.get("caption"):
                        _add_textbox(
                            slide, x + int(Inches(0.2)), top + box_h - int(Inches(0.55)),
                            tw - int(Inches(0.4)), int(Inches(0.4)),
                            tile["caption"], size=12, bold=False, color=theme.text, font=theme.body_font,
                        )
            else:
                left_w = int(content_w * 0.58)
                right_w = content_w - left_w - gap
                first, rest = tiles[0], tiles[1:3]
                data = first.get("image_bytes")
                if data:
                    _add_picture(slide, data, M, top, width=left_w, height=box_h)
                else:
                    _add_round(slide, M, top, left_w, box_h, theme.surface, stroke=theme.line)
                rh = (box_h - gap) // 2
                rx = M + left_w + gap
                for i, tile in enumerate(rest):
                    y = top + i * (rh + gap)
                    data = tile.get("image_bytes")
                    if data:
                        _add_picture(slide, data, rx, y, width=right_w, height=rh)
                    else:
                        _add_round(slide, rx, y, right_w, rh, theme.surface, stroke=theme.line)
            continue

        if layout == "metric_row":
            from pptx.util import Inches

            _slide_bg(slide, theme)
            _add_textbox(
                slide, M, M, content_w, int(Inches(0.7)),
                slide_spec.get("title") or "", size=theme.caption_pt + 2, bold=False,
                color=theme.muted, font=theme.body_font,
            )
            kpis = slide_spec.get("kpis") or []
            n = max(len(kpis), 1)
            gap = int(Inches(0.35))
            col_w = (content_w - gap * (n - 1)) // n
            top = int(H * 0.32)
            for i, kpi in enumerate(kpis):
                x = M + i * (col_w + gap)
                _accent_rule(slide, theme, x, top, int(Inches(0.8)))
                _add_textbox(
                    slide, x, top + int(Inches(0.35)), col_w, int(Inches(1.4)),
                    kpi.get("value") or "", size=54, bold=True,
                    color=theme.accent, font=theme.title_font,
                )
                _add_textbox(
                    slide, x, top + int(Inches(1.9)), col_w, int(Inches(0.9)),
                    kpi.get("label") or "", size=theme.body_pt, bold=False,
                    color=theme.text, font=theme.body_font,
                )
            continue

        if layout == "split_visual":
            _slide_bg(slide, theme)
            image_right = slide_spec.get("image_side", "right") != "left"
            gap = int(Inches(0.55))
            # Asymmetric: text 42%, image 52%
            text_w = int(W * 0.40)
            img_w = W - text_w - 2 * M - gap
            text_x = M if image_right else M + img_w + gap
            img_x = M + text_w + gap if image_right else M
            _accent_rule(slide, theme, text_x, M, int(Inches(0.9)))
            _add_textbox(
                slide, text_x, M + int(Inches(0.35)), text_w, int(Inches(1.5)),
                slide_spec.get("title") or "", size=theme.title_pt + 4, bold=True,
                color=theme.text, font=theme.title_font,
            )
            y = M + int(Inches(2.1))
            if slide_spec.get("body"):
                _add_textbox(
                    slide, text_x, y, text_w, int(Inches(1.2)),
                    slide_spec["body"], size=theme.body_pt, bold=False,
                    color=theme.muted, font=theme.body_font,
                )
                y += int(Inches(1.35))
            for i, bullet in enumerate(slide_spec.get("bullets") or [], 1):
                _add_textbox(
                    slide, text_x, y, int(Inches(0.45)), int(Inches(0.4)),
                    f"{i:02d}", size=12, bold=True, color=theme.accent, font=theme.body_font,
                )
                _add_textbox(
                    slide, text_x + int(Inches(0.5)), y, text_w - int(Inches(0.5)), int(Inches(0.5)),
                    bullet, size=theme.body_pt, bold=False, color=theme.text, font=theme.body_font,
                )
                y += int(Inches(0.58))
            data = slide_spec.get("image_bytes")
            img_top = M
            img_h = H - 2 * M
            if data:
                _add_picture(slide, data, img_x, img_top, width=img_w, height=img_h)
            else:
                _add_rect(slide, img_x, img_top, img_w, img_h, theme.surface, stroke=theme.line)
            continue

        if layout == "statement":
            _slide_bg(slide, theme)
            _accent_rule(slide, theme, M, int(H * 0.38), int(Inches(1.1)))
            _add_textbox(
                slide, M, int(H * 0.42), content_w * 0.92, int(H * 0.28),
                slide_spec["title"], size=theme.display_pt, bold=True,
                color=theme.text, font=theme.title_font,
            )
            if slide_spec.get("subtitle"):
                _add_textbox(
                    slide, M, int(H * 0.72), content_w * 0.7, int(H * 0.12),
                    slide_spec["subtitle"], size=theme.body_pt, bold=False,
                    color=theme.muted, font=theme.body_font,
                )
            continue

        if layout == "stack":
            _slide_bg(slide, theme)
            _add_textbox(
                slide, M, M, content_w, int(Inches(0.7)),
                slide_spec.get("title") or "", size=theme.caption_pt + 1, bold=False,
                color=theme.muted, font=theme.body_font,
            )
            items = slide_spec.get("items") or []
            top = M + int(Inches(1.0))
            row_h = (H - top - M) // max(len(items), 1)
            for i, item in enumerate(items):
                y = top + i * row_h
                _hairline(slide, theme, M, y, content_w)
                _add_textbox(
                    slide, M, y + int(Inches(0.18)), int(Inches(0.7)), int(Inches(0.5)),
                    f"{i + 1:02d}", size=14, bold=True, color=theme.accent, font=theme.body_font,
                )
                _add_textbox(
                    slide, M + int(Inches(0.85)), y + int(Inches(0.12)), content_w - int(Inches(0.85)), int(Inches(0.55)),
                    item, size=theme.title_pt, bold=True, color=theme.text, font=theme.title_font,
                )
            continue

        # Classic layouts – no tacked-on side images (those looked cheap)
        _slide_bg(slide, theme)

        if layout == "title":
            _accent_rule(slide, theme, M, int(H * 0.52), int(Inches(1.25)))
            _add_textbox(
                slide, M, int(H * 0.56), content_w * 0.88, int(H * 0.22),
                slide_spec["title"], size=theme.display_pt, bold=True,
                color=theme.text, font=theme.title_font,
            )
            if slide_spec.get("subtitle"):
                _add_textbox(
                    slide, M, int(H * 0.78), content_w * 0.72, int(H * 0.1),
                    slide_spec["subtitle"], size=theme.body_pt + 1, bold=False,
                    color=theme.muted, font=theme.body_font,
                )
            if slide_spec.get("footer"):
                _add_textbox(
                    slide, M, H - M, content_w, int(Inches(0.35)),
                    slide_spec["footer"], size=11, bold=False,
                    color=theme.muted, font=theme.body_font,
                    anchor=MSO_ANCHOR.BOTTOM,
                )

        elif layout == "section":
            _accent_rule(slide, theme, M, int(H * 0.42), int(Inches(0.9)))
            if slide_spec.get("eyebrow"):
                _add_textbox(
                    slide, M, int(H * 0.34), content_w, int(Inches(0.35)),
                    slide_spec["eyebrow"], size=12, bold=False,
                    color=theme.accent, font=theme.body_font,
                )
            _add_textbox(
                slide, M, int(H * 0.46), content_w * 0.9, int(H * 0.22),
                slide_spec["title"], size=theme.display_pt - 2, bold=True,
                color=theme.text, font=theme.title_font,
            )
            if slide_spec.get("subtitle"):
                _add_textbox(
                    slide, M, int(H * 0.72), content_w * 0.7, int(H * 0.1),
                    slide_spec["subtitle"], size=theme.body_pt, bold=False,
                    color=theme.muted, font=theme.body_font,
                )

        elif layout == "bullets_focus":
            _add_textbox(
                slide, M, M, content_w, int(Inches(0.9)),
                slide_spec["title"], size=theme.title_pt + 2, bold=True,
                color=theme.text, font=theme.title_font,
            )
            _hairline(slide, theme, M, M + int(Inches(1.05)), content_w)
            bullets = slide_spec.get("bullets") or []
            y0 = M + int(Inches(1.35))
            row = (H - y0 - M) // max(len(bullets), 1)
            for i, bullet in enumerate(bullets):
                y = y0 + i * row
                _add_textbox(
                    slide, M, y + int(Inches(0.1)), int(Inches(0.7)), int(Inches(0.45)),
                    f"{i + 1:02d}", size=14, bold=True, color=theme.accent, font=theme.body_font,
                )
                _add_textbox(
                    slide, M + int(Inches(0.85)), y + int(Inches(0.08)), content_w - int(Inches(0.85)), int(Inches(0.7)),
                    bullet, size=theme.body_pt + 2, bold=False, color=theme.text, font=theme.body_font,
                )

        elif layout == "two_column":
            _add_textbox(
                slide, M, M, content_w, int(Inches(0.8)),
                slide_spec["title"], size=theme.title_pt, bold=True,
                color=theme.text, font=theme.title_font,
            )
            gap = int(Inches(0.45))
            col_w = (content_w - gap) // 2
            top = M + int(Inches(1.25))
            box_h = H - top - M
            for x, title_key, body_key in (
                (M, "left_title", "left_body"),
                (M + col_w + gap, "right_title", "right_body"),
            ):
                _add_rect(slide, x, top, col_w, box_h, theme.surface, stroke=theme.line)
                _accent_rule(slide, theme, x + int(Inches(0.4)), top + int(Inches(0.4)), int(Inches(0.7)))
                _add_textbox(
                    slide, x + int(Inches(0.4)), top + int(Inches(0.65)), col_w - int(Inches(0.8)), int(Inches(0.55)),
                    slide_spec[title_key], size=18, bold=True, color=theme.text, font=theme.title_font,
                )
                _add_textbox(
                    slide, x + int(Inches(0.4)), top + int(Inches(1.4)), col_w - int(Inches(0.8)), box_h - int(Inches(1.8)),
                    slide_spec[body_key], size=theme.body_pt, bold=False, color=theme.muted, font=theme.body_font,
                )

        elif layout == "big_number":
            if slide_spec.get("title"):
                _add_textbox(
                    slide, M, M, content_w, int(Inches(0.5)),
                    slide_spec["title"], size=theme.caption_pt + 1, bold=False,
                    color=theme.muted, font=theme.body_font,
                )
            _add_textbox(
                slide, M, int(H * 0.28), content_w, int(H * 0.28),
                slide_spec["value"], size=84, bold=True,
                color=theme.accent, font=theme.title_font,
            )
            if slide_spec.get("caption"):
                _add_textbox(
                    slide, M, int(H * 0.58), content_w * 0.8, int(Inches(0.55)),
                    slide_spec["caption"], size=theme.title_pt - 4, bold=True,
                    color=theme.text, font=theme.body_font,
                )
            if slide_spec.get("note"):
                _add_textbox(
                    slide, M, int(H * 0.7), content_w * 0.7, int(Inches(0.7)),
                    slide_spec["note"], size=theme.body_pt, bold=False,
                    color=theme.muted, font=theme.body_font,
                )

        elif layout == "quote":
            _accent_rule(slide, theme, M, int(H * 0.32), int(Inches(0.9)))
            _add_textbox(
                slide, M, int(H * 0.38), content_w * 0.88, int(H * 0.28),
                slide_spec["quote"], size=theme.title_pt + 2, bold=False,
                color=theme.text, font=theme.title_font,
            )
            if slide_spec.get("attribution"):
                _add_textbox(
                    slide, M, int(H * 0.72), content_w, int(Inches(0.45)),
                    slide_spec["attribution"], size=theme.body_pt - 1, bold=False,
                    color=theme.muted, font=theme.body_font,
                )

        elif layout == "comparison":
            _add_textbox(
                slide, M, M, content_w, int(Inches(0.75)),
                slide_spec["title"], size=theme.title_pt, bold=True,
                color=theme.text, font=theme.title_font,
            )
            gap = int(Inches(0.5))
            col_w = (content_w - gap) // 2
            top = M + int(Inches(1.15))
            box_h = H - top - M
            # Vertical divider instead of twin identical cards
            mid = M + col_w + gap // 2
            _add_rect(slide, mid, top, int(Inches(0.015)), box_h, theme.line)
            for x, label_key, items_key in (
                (M, "left_label", "left_items"),
                (M + col_w + gap, "right_label", "right_items"),
            ):
                _add_textbox(
                    slide, x, top, col_w, int(Inches(0.45)),
                    slide_spec[label_key], size=14, bold=True,
                    color=theme.accent, font=theme.body_font,
                )
                y = top + int(Inches(0.7))
                for item in slide_spec[items_key]:
                    _add_textbox(
                        slide, x, y, col_w, int(Inches(0.5)),
                        item, size=theme.body_pt, bold=False,
                        color=theme.text, font=theme.body_font,
                    )
                    y += int(Inches(0.55))

        elif layout == "chart_panel":
            _add_textbox(
                slide, M, M, content_w, int(Inches(0.7)),
                slide_spec["title"], size=theme.title_pt, bold=True,
                color=theme.text, font=theme.title_font,
            )
            png = _render_chart_image(slide_spec["chart"], theme)
            if png:
                _add_picture(slide, png, M, int(Inches(1.4)), width=content_w)
            if slide_spec.get("caption"):
                _add_textbox(
                    slide, M, H - M - int(Inches(0.35)), content_w, int(Inches(0.4)),
                    slide_spec["caption"], size=theme.caption_pt, bold=False,
                    color=theme.muted, font=theme.body_font,
                )

        elif layout == "closing":
            _slide_bg(slide, theme)
            # Closing = statement energy, not a chat prompt footer
            _accent_rule(slide, theme, M, int(H * 0.36), int(Inches(1.15)))
            _add_textbox(
                slide, M, int(H * 0.42), content_w * 0.88, int(H * 0.22),
                slide_spec["title"], size=theme.display_pt - 2, bold=True,
                color=theme.text, font=theme.title_font,
            )
            if slide_spec.get("subtitle"):
                _add_textbox(
                    slide, M, int(H * 0.66), content_w * 0.72, int(H * 0.1),
                    slide_spec["subtitle"], size=theme.body_pt + 1, bold=False,
                    color=theme.muted, font=theme.body_font,
                )
            cta = (slide_spec.get("cta") or "").strip()
            if cta:
                # Pill-like CTA – intentional button, not a stray blue link
                pill_w = min(int(Inches(0.18 * len(cta) + 1.1)), int(content_w * 0.5))
                pill_h = int(Inches(0.55))
                pill_top = int(H * 0.82)
                _add_rect(slide, M, pill_top, pill_w, pill_h, theme.surface, stroke=theme.accent)
                _add_textbox(
                    slide, M + int(Inches(0.28)), pill_top + int(Inches(0.12)),
                    pill_w - int(Inches(0.45)), int(Inches(0.35)),
                    cta, size=theme.body_pt - 1, bold=True,
                    color=theme.text, font=theme.body_font,
                )

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
