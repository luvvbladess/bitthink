import asyncio
import base64
import hashlib
import io
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import get_current_user
from app.config import get_settings
from app.core.repository import repo

router = APIRouter()

IMAGE_CAPTION = {
    "generate": "Сгенерированное изображение",
    "edit": "Отредактированное изображение",
}


def _decode_image_payload(url_or_data: str) -> tuple[bytes, str]:
    if url_or_data.startswith("data:"):
        header, encoded = url_or_data.split(",", 1)
        suffix = ".jpg" if "jpeg" in header else ".png"
        return base64.b64decode(encoded), suffix
    raise ValueError("expected data URL")


async def _download_image(url: str) -> tuple[bytes, str]:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
            if response.status >= 400:
                raise HTTPException(status_code=502, detail="Не удалось сохранить созданное изображение")
            payload = await response.read()
            suffix = ".jpg" if "jpeg" in response.headers.get("Content-Type", "") else ".png"
            return payload, suffix


def _resolve_upload_path(relative_url: str) -> Path:
    upload_root = get_settings().UPLOAD_DIR.resolve()
    relative = relative_url.split("?", 1)[0]
    if relative.startswith("/uploads/"):
        relative = relative[len("/uploads/") :]
    candidate = (upload_root / relative).resolve()
    candidate.relative_to(upload_root)
    if not candidate.is_file():
        raise FileNotFoundError(relative_url)
    return candidate


def _normalize_image_bytes(contents: bytes, filename: str = "image.png") -> bytes:
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    source = contents
    if filename.lower().endswith(".svg"):
        try:
            import cairosvg
            source = cairosvg.svg2png(bytestring=contents, output_width=2048, output_height=2048)
        except Exception as exc:
            raise ValueError("Не удалось прочитать SVG") from exc
    try:
        with Image.open(io.BytesIO(source)) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            has_alpha = image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)
            if has_alpha:
                image.convert("RGBA").save(output, format="PNG", optimize=True)
            else:
                image.convert("RGB").save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Файл не похож на поддерживаемое изображение") from exc


async def _load_source_bytes(user_id: str, source_url: str) -> bytes:
    if not source_url.startswith("/uploads/"):
        raise HTTPException(status_code=400, detail="Можно править только изображения из этого чата")
    try:
        path = _resolve_upload_path(source_url)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Исходное изображение не найдено")
    data = await asyncio.to_thread(path.read_bytes)
    return await asyncio.to_thread(_normalize_image_bytes, data, path.name)


async def _persist_chat_image(
    user_id: str,
    url_or_data: str,
    prompt: str,
    conversation_id: Optional[str],
    kind: str,
    persist_user: bool = True,
) -> tuple[str, Optional[dict]]:
    if url_or_data.startswith("data:"):
        image_bytes, suffix = _decode_image_payload(url_or_data)
    else:
        image_bytes, suffix = await _download_image(url_or_data)

    settings = get_settings()
    user_key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]
    folder = settings.UPLOAD_DIR / "generated" / user_key
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    await asyncio.to_thread((folder / stored_name).write_bytes, image_bytes)
    stored_url = f"/uploads/generated/{user_key}/{stored_name}"
    caption = IMAGE_CAPTION.get(kind, IMAGE_CAPTION["generate"])

    assistant = None
    if conversation_id:
        if persist_user:
            await repo.add_message(user_id, "user", prompt, conv_id=conversation_id)
            await repo.maybe_autotitle(user_id, conversation_id, prompt)
        assistant = await repo.add_message(
            user_id,
            "assistant",
            f"![{caption}]({stored_url})",
            conv_id=conversation_id,
        )
    return stored_url, assistant


async def _begin_image_job(user_id: str, conversation_id: Optional[str], prompt: str, status_text: str) -> bool:
    if not conversation_id:
        return False
    from app.services.generation_hub import hub

    await repo.add_message(user_id, "user", prompt, conv_id=conversation_id)
    await repo.maybe_autotitle(user_id, conversation_id, prompt)
    hub.upsert_job(
        user_id,
        conversation_id,
        user_text=prompt,
        thinking=True,
        status_text=status_text,
        text="",
        reasoning="",
        search=[],
    )
    await hub.broadcast(
        user_id,
        {"type": "status", "payload": {"text": status_text, "conversation_id": conversation_id}},
    )
    return True


async def _end_image_job(user_id: str, conversation_id: Optional[str]) -> None:
    if not conversation_id:
        return
    from app.services.generation_hub import hub

    hub.finish_job(user_id, conversation_id)


def _friendly_image_error(detail: object) -> str:
    text = detail if isinstance(detail, str) else "Не получилось нарисовать изображение"
    lower = text.lower()
    if "safety" in lower or "moderation" in lower:
        return "Запрос отклонен системой безопасности. Измените описание."
    if "таймаут" in lower or "timeout" in lower:
        return "Генерация заняла слишком много времени. Попробуйте упростить описание."
    if text.startswith("Не получилось") or text.startswith("Запрос отклонен") or text.startswith("Генерация заняла"):
        return text
    return f"Не получилось нарисовать изображение: {text}"


async def _gate_image(user_id: str) -> int:
    from app.billing.quota import QuotaError, assert_can_generate_image

    bot_id = await repo.ensure_user(user_id)
    try:
        await asyncio.to_thread(assert_can_generate_image, bot_id)
    except QuotaError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return bot_id


@router.post("/images/generate")
async def generate_image(data: dict, user_id: str = Depends(get_current_user)):
    from config import IMAGE_MODEL

    prompt = (data.get("prompt") or "").strip()
    conversation_id = data.get("conversation_id")
    source_urls = [str(item).strip() for item in (data.get("source_urls") or []) if str(item).strip()]
    if not prompt:
        raise HTTPException(status_code=400, detail="Опишите изображение")

    await _gate_image(user_id)

    from openai_client import edit_image, generate_image as openai_generate

    saved_user = False
    try:
        sources: list[bytes] = []
        if source_urls:
            sources = [await _load_source_bytes(user_id, url) for url in source_urls[:8]]
        saved_user = await _begin_image_job(
            user_id,
            conversation_id,
            prompt,
            "Меняю изображение" if sources else "Рисую изображение",
        )
        if sources:
            url_or_data, revised = await edit_image(sources, prompt)
            kind = "edit"
        else:
            url_or_data, revised = await openai_generate(prompt)
            kind = "generate"
        if not url_or_data:
            raise HTTPException(status_code=500, detail=revised or "Image generation failed")

        stored_url, assistant = await _persist_chat_image(
            user_id, url_or_data, prompt, conversation_id, kind, persist_user=not saved_user,
        )
        await repo.track_image(user_id, IMAGE_MODEL, 1)
        return {"url": stored_url, "revised_prompt": revised, "message": assistant, "kind": kind}
    except HTTPException as exc:
        if saved_user and conversation_id:
            await repo.add_message(user_id, "assistant", _friendly_image_error(exc.detail), conv_id=conversation_id)
        raise
    finally:
        await _end_image_job(user_id, conversation_id)


@router.post("/images/edit")
async def edit_image_endpoint(
    prompt: str = Form(...),
    conversation_id: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    files: Optional[list[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    user_id: str = Depends(get_current_user),
):
    from config import IMAGE_MODEL
    from openai_client import edit_image

    text = (prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Опишите, что изменить")

    await _gate_image(user_id)

    saved_user = False
    try:
        uploads = [item for item in ([file] if file else []) + list(files or []) if item is not None]
        sources: list[bytes] = []
        for upload in uploads[:8]:
            raw = await upload.read()
            try:
                sources.append(await asyncio.to_thread(_normalize_image_bytes, raw, upload.filename or "image.png"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if source_url:
            sources.append(await _load_source_bytes(user_id, source_url))
        if not sources:
            raise HTTPException(status_code=400, detail="Прикрепите изображение или выберите картинку из чата")

        saved_user = await _begin_image_job(user_id, conversation_id, text, "Меняю изображение")
        url_or_data, revised = await edit_image(sources, text)
        if not url_or_data:
            raise HTTPException(status_code=500, detail=revised or "Image edit failed")

        stored_url, assistant = await _persist_chat_image(
            user_id, url_or_data, text, conversation_id, "edit", persist_user=not saved_user,
        )
        await repo.track_image(user_id, IMAGE_MODEL, 1)
        return {"url": stored_url, "revised_prompt": revised, "message": assistant, "kind": "edit"}
    except HTTPException as exc:
        if saved_user and conversation_id:
            await repo.add_message(user_id, "assistant", _friendly_image_error(exc.detail), conv_id=conversation_id)
        raise
    finally:
        await _end_image_job(user_id, conversation_id)


@router.post("/audio/transcribe")
async def transcribe_audio(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    from openai_client import transcribe_audio

    file_data = await file.read()
    ext = Path(file.filename).suffix.lower().lstrip(".") or "ogg"
    text = await transcribe_audio(file_data, file_format=ext)
    return {"text": text}
