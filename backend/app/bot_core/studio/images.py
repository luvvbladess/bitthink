"""Generate and attach images for Studio slides / boards."""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_DECK_IMAGES = 10
MAX_BOARD_IMAGES = 6
MAX_PROMPT_CHARS = 480

_STYLE_GUARD = (
    "Photoreal cinematic or refined editorial still for a designed presentation, "
    "subject must match the brief, one clear object or place, shallow depth or strong graphic crop, "
    "no text letters numbers logos watermarks or UI, no purple neon, no handshake stock, no collage clutter. "
)


def _decode_data_url(data_url: str) -> bytes | None:
    if not data_url:
        return None
    if data_url.startswith("data:") and "," in data_url:
        raw = data_url.split(",", 1)[1]
        try:
            return base64.b64decode(raw)
        except Exception:
            return None
    return None


def _clean_prompt(prompt: str, theme_hint: str = "") -> str:
    text = " ".join(str(prompt or "").split())
    text = text[:MAX_PROMPT_CHARS]
    if not text:
        return ""
    style = _STYLE_GUARD
    if theme_hint:
        style += f" Color mood: {theme_hint}."
    return f"{text}. {style}"


def collect_image_jobs(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ordered unique (job_id, prompt) pairs referenced by the spec."""
    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(job_id: str, prompt: str) -> None:
        prompt = (prompt or "").strip()
        if not prompt or job_id in seen:
            return
        seen.add(job_id)
        jobs.append((job_id, prompt))

    kind = spec.get("kind")
    if kind == "deck":
        for index, slide in enumerate(spec.get("slides") or []):
            if slide.get("image_prompt"):
                add(f"slide-{index}", slide["image_prompt"])
            for ti, tile in enumerate(slide.get("tiles") or []):
                if isinstance(tile, dict) and tile.get("image_prompt"):
                    add(f"slide-{index}-tile-{ti}", tile["image_prompt"])
            for ei, el in enumerate(slide.get("elements") or []):
                if isinstance(el, dict) and el.get("type") == "image" and el.get("prompt"):
                    add(f"slide-{index}-el-{ei}", el["prompt"])
    else:
        if spec.get("image_prompt"):
            add("board", spec["image_prompt"])
        for ei, el in enumerate(spec.get("elements") or []):
            if isinstance(el, dict) and el.get("type") == "image" and el.get("prompt"):
                add(f"board-el-{ei}", el["prompt"])
    limit = MAX_DECK_IMAGES if kind == "deck" else MAX_BOARD_IMAGES
    return jobs[:limit]


async def resolve_studio_images(spec: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    """
    Mutates a copy of spec: fills image_bytes maps and element/slide image payloads.
    Debits image quota per successful generation.
    """
    import copy

    from studio.themes import get_theme

    out = copy.deepcopy(spec)
    jobs = collect_image_jobs(out)
    if not jobs:
        out["_images"] = {}
        return out

    theme = get_theme(out.get("theme_id"), out.get("theme"))
    theme_hint = f"{theme.label}, accent {theme.accent}, background {theme.bg}"

    # Quota gate: need at least one image remaining
    if user_id:
        try:
            from app.billing.quota import QuotaError, assert_can_generate_image

            assert_can_generate_image(int(user_id))
        except Exception as exc:
            # QuotaError or import – continue without images
            logger.info("Studio images skipped (quota/access): %s", exc)
            out["_images"] = {}
            out["_images_skipped"] = str(exc)[:200]
            return out

    from openai_client import generate_image
    import asyncio

    images: dict[str, bytes] = {}
    sem = asyncio.Semaphore(3)
    quota_lock = asyncio.Lock()
    quota_ok = True

    async def _one(job_id: str, prompt: str) -> tuple[str, bytes] | None:
        nonlocal quota_ok
        if user_id:
            async with quota_lock:
                if not quota_ok:
                    return None
                try:
                    from app.billing.quota import assert_can_generate_image

                    assert_can_generate_image(int(user_id))
                except Exception as exc:
                    quota_ok = False
                    logger.info("Studio stopped image batch: %s", exc)
                    return None
        async with sem:
            full = _clean_prompt(prompt, theme_hint)
            data_url, err = await generate_image(full, size="1536x1024", quality="high")
        payload = _decode_data_url(data_url or "")
        if not payload and data_url and data_url.startswith("http"):
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.get(data_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            payload = await resp.read()
            except Exception:
                payload = None
        if not payload:
            logger.warning("Studio image failed for %s: %s", job_id, err)
            return None
        if user_id:
            try:
                from app.billing.quota import debit_images

                debit_images(int(user_id), 1)
            except Exception:
                logger.exception("Failed to debit studio image")
        return job_id, payload

    results = await asyncio.gather(*[_one(job_id, prompt) for job_id, prompt in jobs], return_exceptions=True)
    for item in results:
        if isinstance(item, tuple) and len(item) == 2:
            images[item[0]] = item[1]

    out["_images"] = images

    # Wire bytes onto slides/elements for renderers
    if out.get("kind") == "deck":
        for index, slide in enumerate(out.get("slides") or []):
            key = f"slide-{index}"
            if key in images:
                slide["image_bytes"] = images[key]
            for ti, tile in enumerate(slide.get("tiles") or []):
                if not isinstance(tile, dict):
                    continue
                tkey = f"slide-{index}-tile-{ti}"
                if tkey in images:
                    tile["image_bytes"] = images[tkey]
            for ei, el in enumerate(slide.get("elements") or []):
                if not isinstance(el, dict):
                    continue
                ekey = f"slide-{index}-el-{ei}"
                if ekey in images:
                    el["image_bytes"] = images[ekey]
    else:
        if "board" in images:
            out["image_bytes"] = images["board"]
        for ei, el in enumerate(out.get("elements") or []):
            if not isinstance(el, dict):
                continue
            ekey = f"board-el-{ei}"
            if ekey in images:
                el["image_bytes"] = images[ekey]
    return out


def strip_image_bytes_for_log(spec: dict[str, Any]) -> dict[str, Any]:
    """Drop binary blobs before logging/serializing specs."""
    import copy

    data = copy.deepcopy(spec)
    data.pop("_images", None)
    if "image_bytes" in data:
        data["image_bytes"] = f"<{len(data['image_bytes'])} bytes>"
    for slide in data.get("slides") or []:
        if isinstance(slide, dict) and "image_bytes" in slide:
            slide["image_bytes"] = f"<{len(slide['image_bytes'])} bytes>"
        for el in slide.get("elements") or [] if isinstance(slide, dict) else []:
            if isinstance(el, dict) and "image_bytes" in el:
                el["image_bytes"] = f"<{len(el['image_bytes'])} bytes>"
    for el in data.get("elements") or []:
        if isinstance(el, dict) and "image_bytes" in el:
            el["image_bytes"] = f"<{len(el['image_bytes'])} bytes>"
    return data
