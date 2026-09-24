import asyncio
import base64
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, List, Optional

import config as bot_config
from app.core.repository import repo
from app.services import chat_access

logger = logging.getLogger(__name__)


def _generated_filename(item: dict) -> str:
    raw = str(item.get("filename") or item.get("name") or "").strip()
    if raw:
        name = Path(raw).name.replace("\x00", "")[:120]
        if name:
            return name
    caption = str(item.get("caption") or "generated").strip() or "generated"
    return f"{caption[:40]}.png"


async def _persist_generated_file(web_user_id: str, filename: str, data: bytes) -> dict:
    import hashlib
    import uuid

    from app.config import get_settings

    settings = get_settings()
    user_key = hashlib.sha256(web_user_id.encode("utf-8")).hexdigest()[:16]
    suffix = Path(filename).suffix.lower() or ".bin"
    folder = settings.UPLOAD_DIR / "generated" / user_key
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = folder / stored_name
    await asyncio.to_thread(target.write_bytes, data)
    return {
        "name": filename,
        "size": len(data),
        "status": "done",
        "type": "generated",
        "url": f"/uploads/generated/{user_key}/{stored_name}",
    }


_DATA_IMG_SRC = re.compile(
    r"""src=(['"])(data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\s]+))\1""",
    re.I,
)


async def _externalize_html_images(web_user_id: str, html: bytes) -> bytes:
    """Store embedded PNGs as files so the canvas HTML stays small enough to preview."""
    if b"data:image/" not in html:
        return html
    try:
        text = html.decode("utf-8")
    except Exception:
        return html
    matches = list(_DATA_IMG_SRC.finditer(text))
    if not matches:
        return html
    pieces: list[str] = []
    cursor = 0
    for index, match in enumerate(matches, start=1):
        pieces.append(text[cursor : match.start()])
        raw_b64 = re.sub(r"\s+", "", match.group(4))
        raw_b64 += "=" * ((4 - len(raw_b64) % 4) % 4)
        try:
            payload = base64.b64decode(raw_b64)
        except Exception:
            pieces.append(match.group(0))
            cursor = match.end()
            continue
        ext = "jpg" if match.group(3).lower() in {"jpeg", "jpg"} else match.group(3).lower()
        try:
            stored = await _persist_generated_file(web_user_id, f"studio-frame-{index}.{ext}", payload)
            url = stored.get("url") or ""
        except Exception:
            logger.exception("Failed to store studio canvas image")
            url = ""
        if url:
            quote = match.group(1)
            pieces.append(f"src={quote}{url}{quote}")
        else:
            pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces).encode("utf-8")


def schedule_memory_refresh(user_id: int) -> None:
    from app.memory import schedule_refresh

    schedule_refresh(user_id)


class WebStatusMessenger:
    """Captures status edits into a web callback."""

    def __init__(self, callback: Callable[[str], Coroutine[Any, Any, None]]):
        self.callback = callback

    async def edit_text(self, text: str, **kwargs) -> None:
        # Strip markdown formatting for the web status
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        plain = re.sub(r"__(.+?)__", r"\1", plain)
        from status_feed import is_bound, push_status

        if is_bound():
            await push_status("think", plain)
            return
        await self.callback(plain)


async def _generate_and_send(
    bot_user_id: int,
    web_user_id: str,
    prompt_content: str,
    api_messages: list,
    send_status: Callable[[str], Coroutine[Any, Any, None]],
    send_chunk: Callable[[str], Coroutine[Any, Any, None]],
    send_file: Callable[..., Coroutine[Any, Any, None]],
    send_extras: Optional[Callable[[str, list], Coroutine[Any, Any, None]]],
    send_reasoning_delta: Optional[Callable[[str], Coroutine[Any, Any, None]]],
    conversation_id: Optional[str] = None,
    supersede_message_id: Optional[int] = None,
) -> None:
    """Shared tail of run_chat/regenerate_chat: call the model, persist the
    assistant reply, and stream it back. Both callers have already prepared
    the conversation and the message history the model should see."""
    async def best_effort(callback, *args) -> None:
        if not callback:
            return
        try:
            await callback(*args)
        except Exception as exc:
            # A browser may reconnect while a long document analysis is running.
            # Delivery failure must never cancel the model or lose its persisted reply.
            logger.info("Client delivery skipped after disconnect: %s", exc)

    async def safe_status(text: str) -> None:
        await best_effort(send_status, text)

    status_msg = WebStatusMessenger(safe_status)
    from handlers.core import get_smart_response, sanitize_response_text
    from status_feed import bind_status, push_status

    bind_status(safe_status)
    await push_status("think", "Думаю")
    started = time.time()
    from turn_scope import turn_conversation

    with turn_conversation(conversation_id):
        response_text, generated_files, reasoning_text, search_results = await get_smart_response(
            bot_user_id, prompt_content, api_messages, status_msg, on_reasoning_delta=None
        )
    try:
        from app.services.sandbox_client import collect_workspace_files

        extra_files = await collect_workspace_files(bot_user_id, started)
        if extra_files:
            generated_files = list(generated_files or []) + extra_files
    except Exception:
        logger.exception("Failed to collect workspace deliverables")

    try:
        from app.services.code_archive import maybe_package_reply_archive, scrub_missing_archive_excuse

        packaged = maybe_package_reply_archive(prompt_content, response_text, generated_files)
        if packaged:
            generated_files = list(generated_files or []) + [packaged]
            response_text = scrub_missing_archive_excuse(response_text, attached=True)
    except Exception:
        logger.exception("Failed to package reply archive")

    response_text = sanitize_response_text(response_text)
    response_text = await asyncio.to_thread(chat_access.redact_for_user, bot_user_id, response_text)

    outgoing: list[tuple[str, bytes, dict]] = []
    for item in generated_files or []:
        file_bytes = item.get("bytes")
        if not file_bytes:
            continue
        filename = _generated_filename(item)
        if item.get("canvas") or filename.lower().endswith((".html", ".htm")):
            try:
                file_bytes = await _externalize_html_images(web_user_id, file_bytes)
            except Exception:
                logger.exception("Failed to extract studio canvas images")
        try:
            meta = await _persist_generated_file(web_user_id, filename, file_bytes)
        except Exception:
            logger.exception("Failed to store generated file %s", filename)
            meta = {"name": filename, "size": len(file_bytes), "status": "done", "type": "generated"}
        if item.get("mime_type"):
            meta["mime_type"] = str(item["mime_type"])
        if item.get("canvas"):
            meta["canvas"] = True
        outgoing.append((filename, file_bytes, meta))
    attachment = outgoing[0][2] if outgoing else None
    if attachment and len(outgoing) > 1:
        attachment = {**attachment, "files": [meta for _, _, meta in outgoing]}

    # Persistence is the commit point. UI delivery is best-effort and may be
    # resumed by polling/refetch after a WebSocket reconnect.
    await repo.add_message(
        web_user_id,
        "assistant",
        response_text,
        conv_id=conversation_id,
        search=search_results or None,
        attachment=attachment,
        supersede_message_id=supersede_message_id,
    )
    from app.billing.quota import clear_quota_charge

    clear_quota_charge()
    await asyncio.to_thread(chat_access.scrub_recent, bot_user_id, conversation_id)
    schedule_memory_refresh(bot_user_id)

    if send_extras and (reasoning_text or search_results):
        await best_effort(send_extras, reasoning_text, search_results)

    if len(response_text) > 8000:
        from docx_generator import convert_markdown_to_docx

        base_template = await asyncio.to_thread(repo._manager.get_base_template, bot_user_id)
        docx_bytes = await asyncio.to_thread(convert_markdown_to_docx, response_text, base_template)
        if docx_bytes:
            await best_effort(send_file, "response.docx", docx_bytes)
        else:
            await best_effort(send_chunk, response_text)
    else:
        await best_effort(send_chunk, response_text)

    for filename, file_bytes, meta in outgoing:
        url = str(meta.get("url") or "")
        canvas = bool(meta.get("canvas")) or filename.lower().endswith((".html", ".htm"))
        if canvas and url:
            await best_effort(send_file, filename, b"", url)
            continue
        if canvas and len(file_bytes) > 350_000:
            continue
        await best_effort(send_file, filename, file_bytes)

    await safe_status("")


async def run_chat(
    web_user_id: str,
    content: str,
    conversation_id: Optional[str],
    send_status: Callable[[str], Coroutine[Any, Any, None]],
    send_chunk: Callable[[str], Coroutine[Any, Any, None]],
    send_file: Callable[..., Coroutine[Any, Any, None]],
    send_meta: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
    send_extras: Optional[Callable[[str, list], Coroutine[Any, Any, None]]] = None,
    send_reasoning_delta: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
) -> None:
    """Main chat flow for the web assistant."""

    bot_user_id = await repo.ensure_user(web_user_id)

    # Select or create conversation. Without an explicit conversation_id, always
    # start a fresh conversation instead of silently falling through to whatever
    # conversation happens to be flagged active in the DB (that used to append
    # the message to an unrelated, previously-active conversation whenever the
    # user typed into a not-yet-created "Новая беседа" screen).
    if conversation_id:
        await repo.set_active_conversation(web_user_id, conversation_id)
    else:
        created = await repo.create_conversation(web_user_id, title="Новый чат")
        conversation_id = created["id"]

    if send_meta:
        await send_meta(conversation_id)

    await asyncio.to_thread(chat_access.ingest_from_text, bot_user_id, content)
    stored = await asyncio.to_thread(chat_access.redact_for_user, bot_user_id, content)
    await repo.add_message(web_user_id, "user", stored, conv_id=conversation_id)
    try:
        await repo.maybe_autotitle(web_user_id, conversation_id, stored)
    except Exception:
        logger.exception("maybe_autotitle failed")

    messages = await repo.get_messages_for_api(web_user_id, conversation_id)

    try:
        await _generate_and_send(
            bot_user_id, web_user_id, content, messages,
            send_status, send_chunk, send_file, send_extras, send_reasoning_delta,
            conversation_id=conversation_id,
        )
    except asyncio.CancelledError:
        from app.billing.quota import refund_quota_charge

        refund_quota_charge()
        raise
    except Exception as exc:
        from app.billing.quota import QuotaError, refund_quota_charge

        refund_quota_charge()
        if isinstance(exc, QuotaError):
            logger.info("Chat quota: %s", exc)
        else:
            logger.exception("Chat error")
        await send_status("")

        # Only this sender's own prompt. Another person's message in a shared room stays.
        await repo.delete_last_message(web_user_id, conversation_id, "user")

        messages_after = await repo.get_messages(web_user_id, conversation_id)
        for last_msg in reversed(messages_after):
            if last_msg["role"] != "user" or not last_msg.get("mine"):
                break
            att = last_msg.get("attachment")
            if att:
                name = att.get("name")
                if name:
                    if att.get("type") == "document":
                        await repo.remove_document(web_user_id, name, conv_id=conversation_id)
                    await repo.remove_attachment(web_user_id, name, conv_id=conversation_id)
            else:
                break

        raise


async def regenerate_chat(
    web_user_id: str,
    conversation_id: str,
    send_status: Callable[[str], Coroutine[Any, Any, None]],
    send_chunk: Callable[[str], Coroutine[Any, Any, None]],
    send_file: Callable[..., Coroutine[Any, Any, None]],
    send_meta: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
    send_extras: Optional[Callable[[str, list], Coroutine[Any, Any, None]]] = None,
    send_reasoning_delta: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
) -> None:
    """Ask the model to answer the same preceding user message again.
    The previous assistant reply stays until the new one is stored."""

    bot_user_id = await repo.ensure_user(web_user_id)
    await repo.set_active_conversation(web_user_id, conversation_id)

    if not await repo.can_regenerate(web_user_id, conversation_id):
        raise PermissionError("Нельзя повторить чужой ответ")

    messages = await repo.get_messages(web_user_id, conversation_id)
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("Нечего повторять — последнее сообщение не от ассистента")
    last_user = next((m for m in reversed(messages[:-1]) if m["role"] == "user"), None)
    if not last_user:
        raise ValueError("Не найдено предыдущее сообщение пользователя")
    previous_id = await repo.last_assistant_message_id(web_user_id, conversation_id)

    if send_meta:
        await send_meta(conversation_id)

    api_messages = await repo.get_messages_for_api(web_user_id, conversation_id)
    # The model should not see the answer it is replacing.
    if api_messages and api_messages[-1].get("role") == "assistant":
        api_messages = api_messages[:-1]

    try:
        await _generate_and_send(
            bot_user_id, web_user_id, last_user["content"], api_messages,
            send_status, send_chunk, send_file, send_extras, send_reasoning_delta,
            conversation_id=conversation_id,
            supersede_message_id=previous_id,
        )
    except asyncio.CancelledError:
        from app.billing.quota import refund_quota_charge

        refund_quota_charge()
        raise
    except Exception as exc:
        from app.billing.quota import QuotaError, refund_quota_charge

        refund_quota_charge()
        if isinstance(exc, QuotaError):
            logger.info("Chat regenerate quota: %s", exc)
        else:
            logger.exception("Chat regenerate error")
        await send_status("")
        raise
