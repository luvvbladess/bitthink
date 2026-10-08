"""Run a local-history Orchestrator turn without creating a website conversation."""
import uuid
from app.core.repository import repo


def local_history(raw, content):
    if not isinstance(raw, list) or len(raw) > 1000:
        raise ValueError("Некорректная локальная история.")
    messages = []
    for item in raw:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        text = item.get("content")
        if isinstance(text, str) and text.strip():
            messages.append({"role": item["role"], "content": text})
    if not messages or messages[-1] != {"role": "user", "content": content}:
        messages.append({"role": "user", "content": content})
    from app.services.desktop_policy import history_char_limit
    if sum(len(m["content"]) for m in messages) > history_char_limit():
        raise ValueError("Локальная история слишком большая. Создайте новый чат.")
    return messages


async def run_local_chat(user, content, cid, status, chunk, file, *, history, send_extras=None, send_reasoning_delta=None):
    from handlers.core import get_smart_response, sanitize_response_text
    from status_feed import bind_status, push_status
    from turn_scope import turn_conversation, delivery
    from app.services.chat_service import WebStatusMessenger, _generated_filename
    from app.billing.quota import clear_quota_charge, refund_quota_charge

    bot_id = await repo.ensure_user(user)
    messages = local_history(history, content)
    bind_status(status)
    await push_status("think", "Думаю")

    async def deliver(text, files):
        if text:
            await chunk(sanitize_response_text(text))
        for item in files or []:
            if item.get("bytes"):
                await file(_generated_filename(item), item["bytes"])

    try:
        # A nonexistent scoped id prevents helpers from reading the website's active chat.
        # No conversation row, message, attachment or memory refresh is persisted here.
        with turn_conversation("local-" + uuid.uuid4().hex), delivery(deliver):
            text, files, reasoning, search = await get_smart_response(
                bot_id, content, messages, WebStatusMessenger(status), on_reasoning_delta=send_reasoning_delta,
            )
        clear_quota_charge()
        if send_extras and (reasoning or search):
            await send_extras(reasoning, search)
        await deliver(text, files)
        await status("")
    except BaseException:
        refund_quota_charge()
        raise
