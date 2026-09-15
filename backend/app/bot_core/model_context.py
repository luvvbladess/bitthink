"""One conversation window per product mode.

Auto / Computer / Research / Luna / Terra all mix models on the same thread.
The thread is packed once to the mode window. Individual hops (Kimi search,
Luna OCR, Terra vision) do not re-pack to a different size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 3
IMAGE_TOKENS = 2_000
TOOL_RESERVE_TOKENS = 6_000
COMPACT_RATIO = 0.85
MEMORY_LABEL = "Сжатая память более раннего разговора"
DIALOGUE_SOFT_LIMIT_TOKENS = 36_000
DIALOGUE_KEEP_MESSAGES = 36
# Flattened history for Computer / Studio / Research planners
HISTORY_PROMPT_MAX_CHARS = 48_000
HISTORY_PIN_USER_TURNS = 4
HISTORY_TAIL_MESSAGES = 48
HISTORY_USER_LINE_CHARS = 4_000
HISTORY_ASSISTANT_LINE_CHARS = 2_500


@dataclass(frozen=True)
class ModeWindow:
    """Shared conversation window for a product mode."""

    context: int
    max_output: int


# Conversation windows. Mixed-model modes share GPT-5.6's 1.05M window
# (OpenAI Luna/Terra/Sol and DeepSeek V4). Search is Kimi-only, so 256K.
# Leaf output caps stay in LEAF_OUTPUT — that is generation, not thread size.
MODE_WINDOWS: Dict[str, ModeWindow] = {
    "auto": ModeWindow(1_050_000, 128_000),
    "correspondent": ModeWindow(1_050_000, 128_000),
    "director": ModeWindow(1_050_000, 128_000),
    "studio": ModeWindow(1_050_000, 128_000),
    "gpt-5.6-luna": ModeWindow(1_050_000, 128_000),
    "gpt-5.6-terra": ModeWindow(1_050_000, 128_000),
    "gpt-5.6-sol": ModeWindow(1_050_000, 128_000),
    "gpt-5.6-sol-pro": ModeWindow(1_050_000, 128_000),
    "gpt-6-astra": ModeWindow(1_050_000, 128_000),
    "kimi-k2.6": ModeWindow(262_144, 32_768),
    "gpt-5-nano": ModeWindow(400_000, 128_000),
    "deepseek-v4-pro": ModeWindow(1_048_576, 64_000),
    "deepseek-v4-flash": ModeWindow(1_048_576, 64_000),
}

LEAF_OUTPUT: Dict[str, int] = {
    "gpt-5-nano": 128_000,
    "gpt-5.6-luna": 128_000,
    "gpt-5.6-terra": 128_000,
    "gpt-5.6-sol": 128_000,
    "gpt-5.6-sol-pro": 128_000,
    "gpt-6-astra": 128_000,
    "kimi-k2.6": 32_768,
    "deepseek-v4-pro": 64_000,
    "deepseek-v4-flash": 64_000,
}


def window_for(mode: str) -> ModeWindow:
    return MODE_WINDOWS.get(mode) or MODE_WINDOWS["auto"]


def packing_mode_id(selected: str) -> str:
    """Selected chat mode. Alias kept so callers pack by mode, not by leaf model."""
    return selected if selected in MODE_WINDOWS else "auto"


def max_output_tokens(leaf_model: str) -> int:
    """Generation cap for the model that actually answers this hop."""
    if leaf_model in LEAF_OUTPUT:
        return LEAF_OUTPUT[leaf_model]
    return window_for(leaf_model).max_output


def input_budget_tokens(mode: str) -> int:
    spec = window_for(mode)
    return max(8_000, spec.context - spec.max_output - TOOL_RESERVE_TOKENS)


def tokens_to_chars(tokens: int) -> int:
    return max(1_000, int(tokens) * CHARS_PER_TOKEN)


def packing_char_budgets(mode: str) -> Tuple[int, int, int]:
    pack_chars = tokens_to_chars(int(input_budget_tokens(mode) * 0.92))
    document_chars = max(8_000, int(pack_chars * 0.40))
    history_chars = max(8_000, pack_chars - document_chars)
    recent_chars = max(4_000, int(history_chars * 0.70))
    return document_chars, history_chars, recent_chars


def attached_file_note(messages: Sequence[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Names only: Search hops must not carry PDF bodies, but must not forget files exist."""
    names: List[str] = []
    for message in messages:
        if message.get("role") != "system":
            continue
        text = _message_text(message)
        marker = "документ для контекста:"
        if marker not in text:
            continue
        name = text.split(marker, 1)[1].split("\n", 1)[0].strip()
        if name:
            names.append(name[:160])
    if not names:
        return None
    listed = ", ".join(dict.fromkeys(names))
    return {
        "role": "system",
        "content": (
            f"В этом чате уже загружены файлы: {listed}. "
            "Не проси пользователя прислать их снова."
        ),
    }


def search_hop_messages(
    messages: Sequence[Dict[str, Any]],
    user_text: str,
    turns: int = 6,
) -> List[Dict[str, Any]]:
    """Short retrieval view for Kimi inside mixed-model modes.

    Auto / Computer / Research keep the full thread at the mode window.
    Search hops must not inherit that million-token history.
    """
    dialogue: List[Dict[str, Any]] = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        text = _message_text(message).strip()
        if not text:
            continue
        dialogue.append({"role": message["role"], "content": text[:8_000]})
    tail = dialogue[-max(1, turns):]
    query = (user_text or "").strip()
    if query and (
        not tail
        or tail[-1].get("role") != "user"
        or query not in str(tail[-1].get("content") or "")
    ):
        tail.append({"role": "user", "content": query[:8_000]})
    if not tail and query:
        tail = [{"role": "user", "content": query[:8_000]}]
    note = attached_file_note(messages)
    if note:
        return [note, *tail]
    return tail


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def _part_tokens(part: Any) -> int:
    if not isinstance(part, dict):
        return estimate_tokens(str(part))
    kind = part.get("type")
    if kind in {"text", "input_text"}:
        return estimate_tokens(str(part.get("text") or ""))
    if kind in {"image_url", "input_image"}:
        return IMAGE_TOKENS
    if "text" in part:
        return estimate_tokens(str(part.get("text") or ""))
    return 8


def estimate_message_tokens(message: Dict[str, Any]) -> int:
    content = message.get("content")
    if isinstance(content, list):
        return 6 + sum(_part_tokens(part) for part in content)
    return 6 + estimate_tokens(str(content or ""))


def estimate_messages_tokens(messages: Sequence[Dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def _message_text(message: Dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, list):
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
        ]
        return "\n".join(item for item in parts if item)
    return str(content or "")


def _history_digest(messages: Sequence[Dict[str, Any]], budget_chars: int = 4_000) -> str:
    """Prefer user asks (longer clips); assistants get short reminders."""
    lines: List[str] = []
    used = 0

    def _append(role: str, text: str, limit: int) -> bool:
        nonlocal used
        label = "Пользователь" if role == "user" else "Ассистент"
        clipped = text if len(text) <= limit else text[:limit].rstrip() + "…"
        line = f"- {label}: {clipped}"
        if used + len(line) > budget_chars:
            return False
        lines.append(line)
        used += len(line) + 1
        return True

    users = []
    assistants = []
    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = " ".join(_message_text(message).split())
        if not text:
            continue
        if role == "user":
            users.append(text)
        else:
            assistants.append(text)

    for text in users:
        if not _append("user", text, 600):
            break
    for text in assistants:
        if used >= budget_chars:
            break
        if not _append("assistant", text, 180):
            break
    return "\n".join(lines)


def format_chat_history_for_prompt(
    messages: Sequence[Dict[str, Any]],
    *,
    max_chars: int = HISTORY_PROMPT_MAX_CHARS,
    pin_user_turns: int = HISTORY_PIN_USER_TURNS,
    tail_messages: int = HISTORY_TAIL_MESSAGES,
) -> str:
    """
    History string for Computer / Studio / Research planners.

    Always keeps the first user asks (constraints, earlier brief) plus a long
    recent tail. Never hard-cuts to 20 lines — that dropped early requirements.
    """
    dialogue: List[Tuple[str, str]] = []
    for message in messages:
        role = message.get("role")
        text = _message_text(message).strip()
        if not text:
            continue
        if role == "user":
            dialogue.append(("user", text))
        elif role == "assistant":
            dialogue.append(("assistant", text))
        elif role == "system" and text.startswith("Ниже результаты актуального веб-поиска"):
            dialogue.append(("search", text))

    if not dialogue:
        return ""

    pinned: set[int] = set()
    users_seen = 0
    for index, (role, _) in enumerate(dialogue):
        if role != "user":
            continue
        users_seen += 1
        if users_seen > pin_user_turns:
            break
        pinned.add(index)
        if index + 1 < len(dialogue) and dialogue[index + 1][0] == "assistant":
            pinned.add(index + 1)

    tail_start = max(0, len(dialogue) - max(1, tail_messages))
    selected = sorted(pinned | set(range(tail_start, len(dialogue))))

    labels = {
        "user": "Пользователь",
        "assistant": "Ассистент",
        "search": "Актуальные веб-материалы",
    }
    parts: List[Tuple[str, str]] = []
    for index in selected:
        role, text = dialogue[index]
        cap = HISTORY_USER_LINE_CHARS if role == "user" else HISTORY_ASSISTANT_LINE_CHARS
        if role == "search":
            cap = 3_000
        chunk = text if len(text) <= cap else text[:cap].rstrip() + "…"
        parts.append((role, f"{labels[role]}: {chunk}"))

    joined = "\n\n".join(text for _, text in parts)
    if len(joined) <= max_chars:
        return joined

    # Over budget: shrink assistant/search lines from the middle first; keep pinned users + last turns.
    protected_tail = set(range(max(0, len(parts) - 8), len(parts)))
    protected_pin = {i for i, idx in enumerate(selected) if idx in pinned and dialogue[idx][0] == "user"}
    protected = protected_tail | protected_pin

    mutable = [
        i for i, (role, _) in enumerate(parts)
        if role != "user" and i not in protected
    ]
    for index in mutable:
        role, line = parts[index]
        # Keep label + short reminder
        prefix = line.split(":", 1)[0] + ": "
        body = line[len(prefix):]
        parts[index] = (role, prefix + (body[:400].rstrip() + "…" if len(body) > 400 else body))
        joined = "\n\n".join(text for _, text in parts)
        if len(joined) <= max_chars:
            return joined

    # Still over: drop middle assistant blocks entirely
    droppable = [i for i in mutable if i not in protected]
    for index in droppable:
        parts[index] = ("", "")
        joined = "\n\n".join(text for _, text in parts if text)
        if len(joined) <= max_chars:
            return joined

    return joined[:max_chars].rstrip() + "…"


def _is_memory_message(message: Dict[str, Any]) -> bool:
    return message.get("role") == "system" and MEMORY_LABEL in _message_text(message)


def compact_dialogue_tail(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep roughly the last 12 turns of chat. Leave document system messages alone."""
    if not messages:
        return messages
    systems = [message for message in messages if message.get("role") == "system" and not _is_memory_message(message)]
    dialogue = [message for message in messages if message.get("role") != "system"]
    if len(dialogue) <= DIALOGUE_KEEP_MESSAGES:
        return messages
    if estimate_messages_tokens(dialogue) <= DIALOGUE_SOFT_LIMIT_TOKENS:
        return messages
    kept = dialogue[-DIALOGUE_KEEP_MESSAGES:]
    dropped = dialogue[:-DIALOGUE_KEEP_MESSAGES]
    digest = _history_digest(dropped, budget_chars=4_000)
    fitted = list(systems)
    if digest:
        fitted.append({
            "role": "system",
            "content": (
                f"{MEMORY_LABEL}. Краткое содержание более раннего разговора, "
                "чтобы не перечитывать всю историю.\n"
                f"{digest}"
            ),
        })
    fitted.extend(kept)
    return fitted


def fit_messages_to_mode(messages: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    """Pack the thread to the mode window. Keep the latest turn and images."""
    if not messages:
        return messages
    messages = compact_dialogue_tail(messages)
    budget = int(input_budget_tokens(mode) * COMPACT_RATIO)
    current = estimate_messages_tokens(messages)
    if current <= budget:
        return messages

    systems = [message for message in messages if message.get("role") == "system" and not _is_memory_message(message)]
    dialogue = [message for message in messages if message.get("role") != "system"]
    if not dialogue:
        return _trim_systems(systems, budget)

    kept: List[Dict[str, Any]] = [dialogue[-1]]
    kept_tokens = estimate_messages_tokens(systems) + estimate_message_tokens(dialogue[-1])
    older_reversed: List[Dict[str, Any]] = []
    for message in reversed(dialogue[:-1]):
        cost = estimate_message_tokens(message)
        if kept_tokens + cost <= budget:
            kept.insert(0, message)
            kept_tokens += cost
        else:
            older_reversed.append(message)
    dropped = list(reversed(older_reversed))

    memory_body = _history_digest(dropped, budget_chars=min(6_000, tokens_to_chars(max(800, budget // 20))))
    fitted = list(systems)
    if memory_body:
        fitted.append({
            "role": "system",
            "content": (
                f"{MEMORY_LABEL}. Это сжатое содержание более ранних сообщений, "
                f"чтобы хватило окна режима ({window_for(mode).context:,} токенов). "
                "Не говори, что не видишь предыдущий разговор.\n"
                f"{memory_body}"
            ),
        })
    fitted.extend(kept)

    while estimate_messages_tokens(fitted) > budget and len(fitted) > 2:
        drop_at = next(
            (
                index for index, message in enumerate(fitted)
                if message.get("role") != "system" and index < len(fitted) - 1
            ),
            None,
        )
        if drop_at is None:
            fitted = _trim_systems(fitted, budget)
            break
        del fitted[drop_at]

    logger.info(
        "Context compact mode=%s before=%s after=%s budget=%s dropped=%s",
        mode, current, estimate_messages_tokens(fitted), budget, len(dropped),
    )
    return fitted


def _trim_systems(messages: List[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
    fitted = list(messages)
    while estimate_messages_tokens(fitted) > budget and fitted:
        longest = max(range(len(fitted)), key=lambda index: estimate_message_tokens(fitted[index]))
        message = fitted[longest]
        content = message.get("content")
        if not isinstance(content, str) or len(content) < 2_000:
            if len(fitted) == 1:
                break
            del fitted[longest]
            continue
        message = dict(message)
        message["content"] = content[: max(1_200, len(content) // 2)] + "\n…[обрезано под окно режима]"
        fitted[longest] = message
    return fitted


async def fit_for_mode(messages: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    fitted = fit_messages_to_mode(messages, mode)
    if estimate_messages_tokens(fitted) + 80 < estimate_messages_tokens(messages):
        try:
            from status_feed import push_status
            await push_status("think", "Сжимаю предыдущие сообщения под окно режима")
        except Exception:
            pass
    return fitted


# Back-compat names used during the first pass.
fit_messages_to_model = fit_messages_to_mode
fit_for_call = fit_for_mode
packing_model_id = packing_mode_id
