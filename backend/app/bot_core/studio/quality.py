"""Quality gates for Studio decks: no empty slides, respect minimal briefs."""

from __future__ import annotations

import re
from typing import Any

_MINIMAL_HINT = re.compile(
    r"(?i)(без\s+лишн|стильн|лаконич|minimal|минимум\s+текст|мало\s+текст|"
    r"short\s+deck|кратко|без\s+воды|чисто\s+и\s+кратко|stylish)"
)

_PLACEHOLDER = re.compile(
    r"(?i)^(слева|справа|left|right|a|b|column\s*[12]|колонка\s*[12]|title|заголовок|текст|…|\.\.\.|—|-)$"
)


def wants_minimal(user_text: str) -> bool:
    return bool(_MINIMAL_HINT.search(user_text or ""))


def is_placeholder(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    return bool(_PLACEHOLDER.match(text))


def target_slide_count(user_text: str, *, default: int = 10) -> tuple[int, int]:
    """Return (min_slides, max_slides) preferred for this brief."""
    text = (user_text or "").lower()
    if wants_minimal(text) or "6–8" in text or "6-8" in text:
        return 6, 8
    if "больш" in text or "15" in text or "18" in text:
        return 12, 18
    if "коротк" in text:
        return 6, 8
    return 8, default


_META_CTA = re.compile(
    r"(?i)(опишите|напишите|уточните|расскажите).*(задач|продукт|бриф|чат|детал)|"
    r"(в\s+чат|в\s+сообщени)|напишите\s+детали|дополните\s+бриф"
)


def is_meta_cta(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    return bool(_META_CTA.search(text))


def sanitize_closing_slide(slide: dict[str, Any]) -> dict[str, Any]:
    """Drop chat-meta CTAs that look like UI prompts on the last slide."""
    if slide.get("layout_id") != "closing":
        return slide
    out = dict(slide)
    if is_meta_cta(out.get("cta")):
        out.pop("cta", None)
    # If title itself is a chat prompt, soften – keep subtitle as body if any
    if is_meta_cta(out.get("title")):
        out["title"] = out.get("subtitle") or "Дальше"
        out["subtitle"] = ""
    return out


def prune_weak_slides(spec: dict[str, Any], *, max_slides: int | None = None) -> dict[str, Any]:
    """Drop hollow slides that would look broken in PPTX."""
    if spec.get("kind") != "deck":
        return spec
    kept: list[dict[str, Any]] = []
    for slide in spec.get("slides") or []:
        layout = slide.get("layout_id")
        if layout == "two_column":
            if is_placeholder(slide.get("left_title")) or is_placeholder(slide.get("right_title")):
                continue
            if not (slide.get("left_body") or "").strip() or not (slide.get("right_body") or "").strip():
                continue
        elif layout == "comparison":
            if not slide.get("left_items") or not slide.get("right_items"):
                continue
            if is_placeholder(slide.get("left_label")) and is_placeholder(slide.get("right_label")):
                continue
        elif layout == "section":
            if max_slides and max_slides <= 8:
                continue
        elif layout == "bullets_focus":
            bullets = [b for b in (slide.get("bullets") or []) if str(b).strip()]
            if len(bullets) < 2:
                continue
        elif layout == "closing":
            slide = sanitize_closing_slide(slide)
        kept.append(slide)

    if max_slides and len(kept) > max_slides:
        # Keep title/visual first and closing last, trim middle fluff
        head = kept[:1]
        tail = [s for s in kept if s.get("layout_id") == "closing"][-1:]
        middle = [s for s in kept[1:] if s not in tail]
        budget = max_slides - len(head) - len(tail)
        kept = head + middle[: max(0, budget)] + tail

    if len(kept) < 3:
        return spec  # safer to keep original than an empty deck
    out = dict(spec)
    out["slides"] = kept
    return out


def strip_excess_classic_images(spec: dict[str, Any], *, keep: int = 3) -> dict[str, Any]:
    """
    For classic layouts, side images often look tacked-on.
    Keep image_prompt only on visual/split_visual/composed and a few hero slides.
    """
    if spec.get("kind") != "deck":
        return spec
    priority = {"visual", "split_visual", "composed", "title", "poster", "mosaic"}
    kept_prompts = 0
    slides = []
    for slide in spec.get("slides") or []:
        s = dict(slide)
        layout = s.get("layout_id")
        if layout in {"visual", "split_visual", "poster", "mosaic"}:
            slides.append(s)
            if s.get("image_prompt"):
                kept_prompts += 1
            continue
        if layout == "composed":
            slides.append(s)
            continue
        if s.get("image_prompt"):
            if layout in priority and kept_prompts < keep:
                kept_prompts += 1
            else:
                s.pop("image_prompt", None)
        slides.append(s)
    out = dict(spec)
    out["slides"] = slides
    return out
