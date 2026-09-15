"""Build Studio artifacts from a normalized or raw JSON spec."""

from __future__ import annotations

import re
from typing import Any

from studio.schema import StudioSpecError, normalize_spec


def _safe_filename(name: str, suffix: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", (name or "studio").strip(), flags=re.U).strip("_") or "studio"
    return f"{stem[:60]}{suffix}"


def build_studio_artifact(
    raw_spec: dict[str, Any],
    *,
    with_previews: bool = True,
    already_normalized: bool = False,
) -> list[dict[str, Any]]:
    """
    Returns a list of generated file dicts: {filename, bytes, caption}.
    Pass already_normalized=True when image_bytes were resolved after normalize_spec.
    """
    if already_normalized or raw_spec.get("_normalized"):
        spec = raw_spec
    else:
        spec = normalize_spec(raw_spec)

    files: list[dict[str, Any]] = []

    if spec["kind"] == "deck":
        from studio.render_pptx import render_deck_pptx

        pptx = render_deck_pptx(spec)
        files.append(
            {
                "filename": _safe_filename(spec.get("title") or "presentation", ".pptx"),
                "bytes": pptx,
                "caption": spec.get("title") or "presentation",
            }
        )
        if with_previews:
            from studio.preview import render_deck_previews

            for name, png in render_deck_previews(spec, limit=2):
                files.append({"filename": name, "bytes": png, "caption": name})
    else:
        from studio.render_board import render_board_png

        png = render_board_png(spec)
        files.append(
            {
                "filename": _safe_filename(spec.get("headline") or "infographic", ".png"),
                "bytes": png,
                "caption": spec.get("headline") or "infographic",
            }
        )
    return files


async def build_studio_artifact_async(
    raw_spec: dict[str, Any],
    *,
    user_id: int | None = None,
    with_previews: bool = True,
    generate_images: bool = True,
) -> list[dict[str, Any]]:
    from studio.images import resolve_studio_images

    spec = normalize_spec(raw_spec)
    if generate_images:
        spec = await resolve_studio_images(spec, user_id)
    spec["_normalized"] = True
    return build_studio_artifact(spec, with_previews=with_previews, already_normalized=True)


def build_studio_from_json_text(text: str, *, with_previews: bool = True) -> list[dict[str, Any]]:
    import json

    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise StudioSpecError("JSON должен быть объектом")
    return build_studio_artifact(raw, with_previews=with_previews)
