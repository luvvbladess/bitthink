import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth import get_current_user
from app.config import get_settings
from app.core.repository import repo

router = APIRouter()

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".avif", ".ico", ".svg",
}
DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".markdown",
    ".xlsx", ".xls", ".ods", ".csv", ".tsv", ".ppt", ".pptx", ".odp",
    ".epub", ".html", ".htm", ".xml", ".json", ".jsonl", ".yaml", ".yml",
    ".log", ".ini", ".cfg", ".conf", ".sql", ".py", ".js", ".jsx", ".ts",
    ".tsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".php", ".rb", ".sh", ".ps1", ".tex",
}


def _safe_filename(filename: str) -> str:
    return Path(filename).name.replace("\x00", "")[:255] or "attachment"


async def _save_chat_image(contents: bytes, filename: str, user_id: str) -> tuple[str, str, int]:
    """Normalize browser/camera formats to a compact JPEG/PNG usable by vision APIs."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass

    def _convert() -> tuple[bytes, str, str]:
        source = contents
        if filename.lower().endswith(".svg"):
            try:
                import cairosvg
                source = cairosvg.svg2png(bytestring=contents, output_width=2048, output_height=2048)
            except Exception as exc:
                raise ValueError("Не удалось прочитать SVG") from exc
        try:
            with Image.open(__import__("io").BytesIO(source)) as opened:
                opened.load()
                image = ImageOps.exif_transpose(opened)
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                has_alpha = image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)
                output = __import__("io").BytesIO()
                if has_alpha:
                    image.convert("RGBA").save(output, format="PNG", optimize=True)
                    return output.getvalue(), "image/png", ".png"
                image.convert("RGB").save(output, format="JPEG", quality=86, optimize=True, progressive=True)
                return output.getvalue(), "image/jpeg", ".jpg"
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Файл не похож на поддерживаемое изображение") from exc

    normalized, mime_type, suffix = await asyncio.to_thread(_convert)
    settings = get_settings()
    user_key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]
    folder = settings.UPLOAD_DIR / "chat" / user_key
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = folder / stored_name
    await asyncio.to_thread(target.write_bytes, normalized)
    return f"/uploads/chat/{user_key}/{stored_name}", mime_type, len(normalized)


@router.get("")
async def list_documents(user_id: str = Depends(get_current_user)):
    return await repo.get_documents(user_id)


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename")

    filename = _safe_filename(file.filename)
    ext = Path(filename).suffix.lower()
    declared_image = (file.content_type or "").startswith("image/")
    is_image = declared_image or ext in IMAGE_EXTENSIONS
    if not is_image and ext not in DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Формат {ext or 'без расширения'} пока нельзя прочитать")

    contents = await file.read()
    max_size = 40 * 1024 * 1024 if is_image else 20 * 1024 * 1024
    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой (максимум {max_size // 1024 // 1024} МБ). Разбейте документ или пришлите нужные страницы.",
        )

    if is_image:
        try:
            url, mime_type, normalized_size = await _save_chat_image(contents, filename, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        msg = await repo.add_message(
            user_id,
            "user",
            filename,
            conv_id=conversation_id,
            attachment={
                "name": filename,
                "size": normalized_size,
                "status": "done",
                "type": "image",
                "mime_type": mime_type,
                "url": url,
            },
        )
        return {"ok": True, "kind": "image", "filename": filename, "message": msg}

    from document_parser import extract_text_from_file

    bot_user_id = await repo.ensure_user(user_id)
    try:
        text = await extract_text_from_file(contents, filename, user_id=bot_user_id)
    except MemoryError as exc:
        raise HTTPException(
            status_code=400,
            detail="Файл слишком тяжёлый для разбора. Пришлите часть документа или меньше страниц.",
        ) from exc
    if text is None:
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    await repo.add_document(user_id, filename, text, conv_id=conversation_id)
    msg = await repo.add_message(
        user_id,
        "user",
        filename,
        conv_id=conversation_id,
        attachment={"name": filename, "size": len(contents), "status": "done", "type": "document"},
    )
    return {"ok": True, "kind": "document", "filename": filename, "length": len(text), "message": msg}


@router.delete("/{filename}")
async def delete_document(filename: str, user_id: str = Depends(get_current_user)):
    ok = await repo.remove_document(user_id, filename)
    attachment = await repo.remove_attachment(user_id, filename)
    if attachment and attachment.get("url"):
        upload_root = get_settings().UPLOAD_DIR.resolve()
        candidate = (upload_root / str(attachment["url"]).removeprefix("/uploads/")).resolve()
        try:
            candidate.relative_to(upload_root)
            if candidate.is_file():
                await asyncio.to_thread(candidate.unlink)
        except ValueError:
            pass
    if not ok and not attachment:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@router.post("/docx")
async def convert_to_docx(data: dict, user_id: str = Depends(get_current_user)):
    from docx_generator import convert_markdown_to_docx

    markdown_text = data.get("markdown", "")
    bot_user_id = await repo.ensure_user(user_id)
    base_template = await asyncio.to_thread(repo._manager.get_base_template, bot_user_id)
    docx_bytes = await asyncio.to_thread(convert_markdown_to_docx, markdown_text, base_template)

    from fastapi.responses import Response
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename=response.docx"})


@router.post("/edit-docx")
async def edit_docx(file: UploadFile = File(...), replacements: str = Form(...), user_id: str = Depends(get_current_user)):
    from document_parser import edit_docx_with_replacements

    file_data = await file.read()
    reps = {}
    for line in replacements.split("\n"):
        if "::=" in line:
            key, value = line.split("::=", 1)
            reps[key.strip()] = value.strip()

    result = await asyncio.to_thread(edit_docx_with_replacements, file_data, reps)
    from fastapi.responses import Response
    return Response(content=result, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f"attachment; filename=edited_{file.filename}"})
