"""
PostgreSQL-backed drop-in replacement for the JSON-based ConversationManager.

Public API is preserved so existing bot core modules (handlers/core.py,
openai_client.py, etc.) continue to work without changes.
"""

import asyncio
import base64
import hashlib
import logging
import math
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.engine import SyncSessionLocal
from app.db.models import (
    AllowedContext,
    BaseTemplate,
    Conversation,
    ConversationAside,
    ConversationMember,
    ConversationShare,
    CustomPrompt,
    Document,
    Message,
    Subscription,
    UsageRecord,
    User,
    UserMemory,
    UserSkill,
)

logger = logging.getLogger(__name__)

# Fallbacks for unit tests that pass explicit budgets. Live packing uses
# model_context.packing_char_budgets() — one window per product mode.
DOCUMENT_CONTEXT_BUDGET = 240_000
HISTORY_CONTEXT_BUDGET = 60_000
RECENT_HISTORY_BUDGET = 30_000
DOCUMENT_CHUNK_SIZE = 6_000
DOCUMENT_CHUNK_OVERLAP = 600

_QUERY_STOP_WORDS = {
    "который", "которая", "которые", "этого", "этому", "этот", "эта", "это",
    "пожалуйста", "нужно", "надо", "можно", "также", "после", "перед", "между",
    "what", "which", "that", "this", "with", "from", "about", "please",
}


def _query_terms(text: str) -> List[str]:
    words = re.findall(r"[a-zа-яё0-9]{3,}", (text or "").lower())
    return list(dict.fromkeys(word for word in words if word not in _QUERY_STOP_WORDS))[:40]


def _escape_like(term: str) -> str:
    return (term or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_needles(terms: List[str]) -> List[str]:
    needles: List[str] = []
    seen: set[str] = set()
    for term in terms:
        variants = {term, term.lower()}
        if term:
            variants.add(term[:1].upper() + term[1:])
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                needles.append(variant)
    return needles


def _fmt_chat_date(value: Any) -> str:
    if not value:
        return ""
    try:
        return value.strftime("%Y-%m-%d")
    except Exception:
        return str(value)[:10]


def _chat_snippet(content: str, terms: List[str], width: int = 220) -> str:
    text = " ".join((content or "").split())
    lowered = text.lower()
    pos = -1
    for term in terms:
        pos = lowered.find(term.lower())
        if pos >= 0:
            break
    if pos < 0:
        pos = 0
    start = max(0, pos - 70)
    chunk = text[start : start + width]
    if start > 0:
        chunk = "…" + chunk
    if start + width < len(text):
        chunk += "…"
    return chunk


def _skip_search_message(content: str) -> bool:
    text = (content or "").strip()
    if len(text) < 8:
        return True
    if text.startswith("[Файл") or text.startswith("Документы пользователя"):
        return True
    return False


def _redact_chat_text(user_id: int, text: str) -> str:
    try:
        from app.security.redact import labeled_secret_spans, redact_text
        from app.services.connectors import secret_values

        secrets = list(secret_values(user_id)) + labeled_secret_spans(text or "")
        return redact_text(text or "", secrets)
    except Exception:
        return "[скрыто]"


def _relevant_document_excerpt(content: str, query: str, budget: int) -> str:
    """Deterministic retrieval for a large document without another model call."""
    if len(content) <= budget:
        return content

    step = DOCUMENT_CHUNK_SIZE - DOCUMENT_CHUNK_OVERLAP
    chunks = [content[start:start + DOCUMENT_CHUNK_SIZE] for start in range(0, len(content), step)]
    terms = _query_terms(query)
    lowered_query = (query or "").lower()
    holistic = any(marker in lowered_query for marker in (
        "целиком", "полный анализ", "весь документ", "все документы",
        "каждый документ", "сравни документы", "проанализируй документ",
        "проверь документ", "резюме документов", "проверь", "свер", "сравни",
    ))

    def score(index: int) -> tuple[int, int]:
        lowered = chunks[index].lower()
        matches = sum(lowered.count(term) for term in terms)
        # Prefer the beginning on a tie because it normally contains title,
        # structure, definitions and document metadata.
        return matches, -index

    ranked = sorted(range(len(chunks)), key=score, reverse=True)
    chosen = {0}
    if holistic and len(chunks) > 1:
        target_count = max(2, budget // DOCUMENT_CHUNK_SIZE)
        for position in range(target_count):
            chosen.add(round(position * (len(chunks) - 1) / max(1, target_count - 1)))
    elif not terms and len(chunks) > 2:
        chosen.add(len(chunks) // 2)
        chosen.add(len(chunks) - 1)
    for index in ranked:
        if sum(len(chunks[item]) for item in chosen) >= budget:
            break
        chosen.add(index)

    pieces: List[str] = []
    used = 0
    holistic_piece_budget = max(1, budget // len(chosen) - 80) if holistic else None
    for index in sorted(chosen):
        remaining = budget - used
        if remaining <= 0:
            break
        start = index * step
        if holistic_piece_budget and index == len(chunks) - 1:
            chunk = chunks[index][-min(holistic_piece_budget, remaining):]
            start += len(chunks[index]) - len(chunk)
        else:
            piece_budget = min(holistic_piece_budget or remaining, remaining)
            chunk = chunks[index][:piece_budget]
        pieces.append(f"[Фрагмент {start + 1}–{start + len(chunk)}]\n{chunk}")
        used += len(chunk) + 40
    return "\n\n".join(pieces)


_FILE_QUERY_MARKERS = (
    "документ", "файл", "вложен", "pdf", "таблиц", "договор", "отчёт", "отчет",
    "прикреп", "по файлу", "из файла", "приложен",
    "invoice", "proforma", "контракт", "спецификац",
)
_IMAGE_QUERY_MARKERS = (
    "фото", "картин", "изображ", "скрин", "пиксе", "цвет", "оттенок",
    "на фото", "на картинке", "что это", "что на", "видишь", "что изображ",
)


def query_needs_documents(query: str, documents: List[dict] | None = None) -> bool:
    """True when this turn is about files in general, so leftover bodies should open.

    Filename hits are handled separately and open only the named file.
    documents is kept for callers; it does not make a stem match open every file.
    """
    del documents
    text = (query or "").lower()
    return bool(text) and any(marker in text for marker in _FILE_QUERY_MARKERS)


def _whole_token_in_text(token: str, text: str) -> bool:
    if not token or not text:
        return False
    return re.search(rf"(?<![a-zа-яё0-9]){re.escape(token)}(?![a-zа-яё0-9])", text, re.I) is not None


def query_named_documents(query: str, documents: List[dict] | None = None) -> set[str]:
    """Filenames mentioned in this turn, not a license to open the whole catalog."""
    text = (query or "").lower()
    named: set[str] = set()
    if not text:
        return named
    for document in documents or []:
        name = str(document.get("filename") or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered in text:
            named.add(name)
            continue
        stem = Path(name).stem.lower()
        if len(stem) >= 4 and _whole_token_in_text(stem, text):
            named.add(name)
    return named


def query_needs_images(query: str) -> bool:
    text = (query or "").lower()
    return bool(text) and any(marker in text for marker in _IMAGE_QUERY_MARKERS)


def document_matches_query(document: dict, query: str) -> bool:
    terms = _query_terms(query)
    if not terms:
        return False
    haystack = f"{document.get('filename', '')}\n{document.get('content', '')}".lower()
    hits = sum(1 for term in terms if term in haystack)
    if hits >= 2:
        return True
    return any(len(term) >= 6 and term in haystack for term in terms)


def _catalog_stub(document: dict) -> dict:
    name = document.get("filename") or "документ"
    chars = len(document.get("content") or "")
    return {
        "filename": name,
        "content": (
            f"Файл уже в этом чате: {name} ({chars} символов). "
            "Полный текст не подмешан в этот ход, потому что вопрос не про документы. "
            "Не проси пользователя прислать этот файл снова — он уже загружен."
        ),
    }


def build_document_contexts(
    documents: List[dict],
    query: str,
    max_chars: int = DOCUMENT_CONTEXT_BUDGET,
    force_filenames: Optional[set[str]] = None,
) -> List[dict]:
    """Open a file only when this turn needs it. Otherwise keep a cheap catalog.

    Current-turn uploads are passed via force_filenames. Other files stay listed
    by name until the question is actually about them.
    """
    if not documents:
        return []
    forced = {str(name) for name in (force_filenames or set()) if name}
    forced.update(query_named_documents(query, documents))
    needs_all = query_needs_documents(query)
    open_docs: List[dict] = []
    catalog: List[dict] = []
    for document in documents:
        name = document.get("filename") or "документ"
        if name in forced or any(name.startswith(f"{f}/") for f in forced) or needs_all or document_matches_query(document, query):
            open_docs.append(document)
        else:
            catalog.append(_catalog_stub(document))

    if not open_docs:
        return catalog

    total = sum(len(document.get("content", "")) for document in open_docs)
    if total <= max_chars:
        return open_docs + catalog

    per_document = max(400, min(40_000, max_chars // len(open_docs)))
    packed: List[dict] = []
    remaining = max_chars
    for index, document in enumerate(open_docs):
        documents_left = len(open_docs) - index
        fair_budget = min(per_document, max(200, remaining // documents_left))
        excerpt = _relevant_document_excerpt(document.get("content", ""), query, fair_budget)[:fair_budget]
        packed.append({"filename": document.get("filename", "документ"), "content": excerpt})
        remaining -= len(excerpt)
    return packed + catalog


def _memory_terms(text: str) -> set[str]:
    """Normalized exact/prefix keys provide cheap Russian-friendly retrieval."""
    keys: set[str] = set()
    for word in _query_terms(text):
        keys.add(word)
        if len(word) >= 7:
            keys.add(word[:5])
    return keys


def _memory_excerpt(message: "MessageData", terms: set[str], budget: int) -> "MessageData":
    content = message.content or ""
    if len(content) <= budget:
        return message
    lowered = content.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - budget // 3)
    end = min(len(content), start + budget)
    start = max(0, end - budget)
    excerpt = content[start:end]
    if start:
        excerpt = "…" + excerpt
    if end < len(content):
        excerpt += "…"
    return MessageData(
        role=message.role,
        content=excerpt,
        timestamp=message.timestamp,
        search=message.search,
    )


def _history_visible(message: "MessageData") -> "MessageData":
    """Keep attachment uploads as a short filename line in the dialogue."""
    attachment = message.attachment or {}
    if not attachment:
        return message
    name = str(attachment.get("name") or "файл").strip() or "файл"
    kind = str(attachment.get("type") or "")
    mime = str(attachment.get("mime_type") or "")
    label = "изображение" if kind == "image" or mime.startswith("image/") else "файл"
    caption = (message.content or "").strip()
    if caption and caption != name:
        prefix = caption if len(caption) <= 180 else caption[:180].rstrip() + "…"
        text = f"{prefix}\n[{label}: {name}]"
    else:
        text = f"[{label}: {name}]"
    return MessageData(
        role=message.role,
        content=text,
        timestamp=message.timestamp,
        search=message.search,
    )


def pack_chat_history(
    messages: List["MessageData"],
    query: str = "",
    max_chars: int = HISTORY_CONTEXT_BUDGET,
    recent_chars: int = RECENT_HISTORY_BUDGET,
) -> List["MessageData"]:
    """Recent context plus query-relevant old question/answer pairs.

    This is local retrieval: it consumes no model tokens of its own. Attachment
    cards become a short "[файл: name]" line so the model sees the upload even
    when the document body lives in the document table.
    Early user asks are pinned as short excerpts so constraints survive packing.
    """
    clean = [_history_visible(message) for message in messages]
    if sum(len(message.content or "") for message in clean) <= max_chars:
        return clean

    pin_budget = min(1_800, max(600, max_chars // 5))
    pin_excerpts: List[MessageData] = []
    pin_used = 0
    users_pinned = 0
    for message in clean:
        if users_pinned >= 2 or pin_used >= pin_budget:
            break
        if message.role != "user":
            continue
        content = message.content or ""
        if not content.strip():
            continue
        room = pin_budget - pin_used
        take = min(len(content), room, 900)
        if take < 40:
            break
        excerpt = content if len(content) <= take else content[:take].rstrip() + "…"
        pin_excerpts.append(
            MessageData(
                role="user",
                content=f"[Ранний запрос]\n{excerpt}",
                timestamp=message.timestamp,
                search=message.search,
            )
        )
        pin_used += len(excerpt)
        users_pinned += 1

    recent_indices: List[int] = []
    recent_used = 0
    for index in range(len(clean) - 1, -1, -1):
        length = len(clean[index].content or "")
        if recent_indices and recent_used + length > min(recent_chars, max_chars):
            break
        recent_indices.append(index)
        recent_used += length
    recent_set = set(recent_indices)
    old_limit = min(recent_indices) if recent_indices else len(clean)
    leftover = max(0, max_chars - recent_used - pin_used)
    digest_budget = min(1_800, leftover // 4) if leftover else 0
    query_keys = _memory_terms(query)

    def _finalize(packed: List[MessageData], dropped: List[MessageData]) -> List[MessageData]:
        packed = _dedupe_pin_against_recent(packed, recent_set, clean)
        digest = _dropped_history_digest(dropped, budget=digest_budget)
        if digest:
            packed.insert(0, MessageData(role="user", content=f"[Память диалога]\n{digest}"))
        return _trim_packed_to_budget(packed, max_chars)

    if not query_keys or old_limit <= 0:
        packed = list(pin_excerpts)
        packed.extend(clean[index] for index in sorted(recent_set))
        dropped = clean[:old_limit] if old_limit > 0 else []
        return _finalize(packed, dropped)

    old_messages = clean[:old_limit]
    old_message_keys = [_memory_terms(message.content or "") for message in old_messages]
    document_frequency = {
        term: sum(term in message_keys for message_keys in old_message_keys)
        for term in query_keys
    }

    scored: List[tuple[float, int]] = []
    for index, message in enumerate(old_messages):
        message_keys = old_message_keys[index]
        score = sum(
            1.0 + math.log((len(old_messages) + 1) / (document_frequency[term] + 1))
            for term in query_keys
            if term in message_keys
        )
        if message.role == "user":
            score = score * 1.35 + 0.15
        if score:
            scored.append((score, index))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    memory_budget = max(0, leftover - digest_budget)
    memory_indices: set[int] = set()
    memory_used = 0
    for _, index in scored:
        pair = {index}
        if old_messages[index].role == "user" and index + 1 < old_limit and old_messages[index + 1].role == "assistant":
            pair.add(index + 1)
        elif old_messages[index].role == "assistant" and index > 0 and old_messages[index - 1].role == "user":
            pair.add(index - 1)
        new_indices = sorted(pair - memory_indices)
        if not new_indices:
            continue
        estimated = sum(min(len(old_messages[item].content or ""), 6_000) for item in new_indices)
        if memory_indices and memory_used + estimated > memory_budget:
            continue
        memory_indices.update(new_indices)
        memory_used += estimated
        if memory_used >= memory_budget:
            break

    result: List[MessageData] = list(pin_excerpts)
    remaining = memory_budget
    for index in sorted(memory_indices):
        if remaining <= 0:
            break
        excerpt = _memory_excerpt(old_messages[index], query_keys, min(6_000, remaining))
        result.append(excerpt)
        remaining -= len(excerpt.content or "")
    result.extend(clean[index] for index in sorted(recent_set))
    dropped = [old_messages[index] for index in range(old_limit) if index not in memory_indices]
    return _finalize(result, dropped)


def _dedupe_pin_against_recent(
    packed: List["MessageData"],
    recent_set: set[int],
    clean: List["MessageData"],
) -> List["MessageData"]:
    recent_texts = {(clean[i].content or "")[:160] for i in recent_set if clean[i].role == "user"}
    out: List[MessageData] = []
    for message in packed:
        content = message.content or ""
        if content.startswith("[Ранний запрос]\n"):
            body = content.split("\n", 1)[-1]
            if any(body[:80] and body[:80] in text for text in recent_texts):
                continue
        out.append(message)
    return out


def _trim_packed_to_budget(packed: List["MessageData"], max_chars: int) -> List["MessageData"]:
    if sum(len(message.content or "") for message in packed) <= max_chars:
        return packed
    kept = list(packed)
    while kept and sum(len(m.content or "") for m in kept) > max_chars:
        drop_at = next(
            (
                i
                for i, message in enumerate(kept[:-1])
                if message.role == "assistant"
                or (message.content or "").startswith("[Память диалога]")
                or (message.content or "").startswith("[Ранний запрос]")
            ),
            0 if len(kept) > 1 else None,
        )
        if drop_at is None:
            break
        del kept[drop_at]
    return kept


def _dropped_history_digest(messages: List["MessageData"], budget: int = 4_000) -> str:
    """Prefer earlier user asks with longer clips so constraints survive packing."""
    lines: List[str] = []
    used = 0

    def _add(label: str, text: str, limit: int) -> bool:
        nonlocal used
        clipped = text if len(text) <= limit else text[:limit].rstrip() + "…"
        line = f"- {label}: {clipped}"
        if used + len(line) > budget:
            return False
        lines.append(line)
        used += len(line) + 1
        return True

    users: List[str] = []
    assistants: List[str] = []
    for message in messages:
        text = " ".join((message.content or "").split())
        if not text:
            continue
        if message.role == "user":
            users.append(text)
        else:
            assistants.append(text)

    for text in users:
        if not _add("Пользователь", text, 600):
            break
    for text in assistants:
        if used >= budget:
            break
        if not _add("Ассистент", text, 160):
            break
    return "\n".join(lines)

MSK_TZ = timezone(timedelta(hours=3))


def _msk_now() -> datetime:
    return datetime.now(MSK_TZ)


def _msk_today() -> str:
    return _msk_now().strftime("%Y-%m-%d")


def _msk_period() -> str:
    return _msk_now().strftime("%Y-%m")


_SUB_FIELDS = (
    "tier",
    "expires_at",
    "daily_nano_mini",
    "daily_gpt54",
    "daily_director",
    "daily_images",
    "daily_docs",
    "last_reset_date",
    "has_used_trial",
    "active_promocode",
    "last_reminded_date",
    "period_start",
    "chat_tokens_used",
    "computer_tokens_used",
    "images_used",
    "nano_cushion_date",
    "nano_cushion_used",
    "session_started_at",
    "session_chat_used",
    "session_computer_used",
    "week_start",
    "week_chat_used",
    "week_computer_used",
)


def _subscription_payload(sub: Subscription) -> dict:
    return {name: getattr(sub, name, None) for name in _SUB_FIELDS}


def _apply_subscription_payload(sub: Subscription, data: dict) -> None:
    for name in _SUB_FIELDS:
        if name in data:
            setattr(sub, name, data[name])


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class MessageData:
    role: str
    content: str
    timestamp: str = field(default_factory=_now_iso)
    attachment: Optional[dict] = None
    search: Optional[List[Dict[str, str]]] = None
    author_user_id: Optional[int] = None
    db_id: Optional[int] = None

    def to_dict(self) -> dict:
        data = {"role": self.role, "content": self.content, "timestamp": self.timestamp}
        if self.attachment:
            data["attachment"] = self.attachment
        if self.search:
            data["search"] = self.search
        return data


@dataclass
class ConversationData:
    id: str
    title: str
    messages: List[MessageData] = field(default_factory=list)
    documents: List[dict] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = ""
    is_active: bool = False
    owner_id: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "documents": self.documents,
            "created_at": self.created_at,
        }

    @classmethod
    def from_model(cls, conv: Conversation) -> "ConversationData":
        import json

        def _attachment(m: Message) -> Optional[dict]:
            if not m.attachment:
                return None
            try:
                return json.loads(m.attachment)
            except Exception:
                return {"name": m.attachment}

        def _search(m: Message) -> Optional[List[Dict[str, str]]]:
            if not m.search:
                return None
            try:
                value = json.loads(m.search)
                return value if isinstance(value, list) else None
            except Exception:
                return None

        return cls(
            id=conv.id,
            title=conv.title,
            messages=[
                MessageData(
                    role=m.role,
                    content=m.content,
                    timestamp=m.created_at.isoformat(),
                    attachment=_attachment(m),
                    search=_search(m),
                    author_user_id=getattr(m, "author_user_id", None),
                    db_id=int(m.id),
                )
                for m in sorted(conv.messages, key=lambda item: item.id)
            ],
            documents=[
                {"filename": d.filename, "content": d.content}
                for d in sorted(conv.documents, key=lambda item: item.id)
            ],
            created_at=conv.created_at.isoformat(),
            updated_at=(conv.updated_at or conv.created_at).isoformat(),
            is_active=bool(conv.is_active),
            owner_id=int(conv.user_id),
        )


def _attachment_is_interim(raw: Optional[str]) -> bool:
    if not raw:
        return False
    import json

    try:
        data = json.loads(raw)
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("interim"))


class DatabaseConversationManager:
    """Synchronous PostgreSQL-backed conversation manager."""

    def __init__(self, data_dir: str = "data") -> None:
        # data_dir is kept for API compatibility but no longer used for JSON storage
        self.data_dir = data_dir

        # ponytail: in-memory transient state (same as original JSON manager),
        # keyed by user_id on this process only — no cross-worker sync, no TTL.
        # Correct only for a single uvicorn worker (pinned via --workers 1 in
        # docker-compose.yml). Move to Redis before running >1 worker/replica.
        self._edit_mode: Dict[int, bool] = {}
        self._user_images: Dict[int, bytes] = {}
        self._dalle_mode: Dict[int, bool] = {}
        self._dalle_images: Dict[int, bytes] = {}
        self._template_mode: Dict[int, bool] = {}
        self._template_docs: Dict[int, bytes] = {}
        self._template_names: Dict[int, str] = {}
        self._base_template_mode: Dict[int, bool] = {}
        self._base_template_cache: Dict[int, bytes] = {}
        self._base_template_name_cache: Dict[int, str] = {}
        self._active_custom_prompt: Dict[int, Optional[str]] = {}
        self._user_tasks: Dict[int, asyncio.Task] = {}
        self._quota_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Context allow-list
    # ------------------------------------------------------------------
    def is_context_allowed(self, context_id: Union[int, str]) -> bool:
        if isinstance(context_id, int) or (isinstance(context_id, str) and context_id.isdigit()):
            return True
        with SyncSessionLocal() as session:
            record = session.get(AllowedContext, str(context_id))
            if record:
                return record.allowed
            # Fallback: topic_CHATID_THREADID -> CHATID
            if "_" in str(context_id):
                base = str(context_id).split("_")[0]
                record = session.get(AllowedContext, base)
                if record:
                    return record.allowed
            return False

    def set_context_allowed(self, context_id: str, status: bool) -> None:
        with SyncSessionLocal() as session:
            record = session.get(AllowedContext, str(context_id))
            if record:
                record.allowed = status
            else:
                session.add(AllowedContext(context_id=str(context_id), allowed=status))
            session.commit()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def get_all_users(self) -> List[Union[int, str]]:
        with SyncSessionLocal() as session:
            result = session.execute(func.distinct(Conversation.user_id))
            return [row[0] for row in result.all()]

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    def get_user_profile(self, user_id: Union[int, str]) -> dict:
        # Profile is not stored separately in DB; return defaults
        return {"first_name": f"User {user_id}", "username": str(user_id)}

    def update_user_profile(self, user_id: Union[int, str], first_name=None, username=None) -> None:
        # No-op for now; profile lives in web User table
        pass

    # ------------------------------------------------------------------
    # Usage
    # ------------------------------------------------------------------
    def track_tokens(
        self,
        user_id: int,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        date = _msk_today()
        with SyncSessionLocal() as session:
            record = self._get_usage_record(session, user_id, date, model)
            record.input_tokens += input_tokens
            record.output_tokens += output_tokens
            record.cached_input_tokens = (record.cached_input_tokens or 0) + max(0, int(cached_input_tokens or 0))
            session.commit()
        try:
            from app.billing.quota import debit_model_usage

            debit_model_usage(
                user_id, model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens
            )
        except Exception:
            logger.exception("Failed to debit plan tokens for user %s", user_id)

    def track_image(self, user_id: int, model: str, count: int = 1) -> None:
        date = _msk_today()
        with SyncSessionLocal() as session:
            record = self._get_usage_record(session, user_id, date, model)
            record.images += count
            session.commit()
        # Plan images are reserved in assert_can_generate_image. This row is usage history only.

    def track_calls(self, user_id: int, model: str, count: int = 1) -> None:
        date = _msk_today()
        with SyncSessionLocal() as session:
            record = self._get_usage_record(session, user_id, date, model)
            record.calls += count
            session.commit()

    def _get_usage_record(self, session: Session, user_id: int, date: str, model: str) -> UsageRecord:
        record = session.query(UsageRecord).filter_by(user_id=user_id, date=date, model=model).first()
        if not record:
            record = UsageRecord(
                user_id=user_id,
                date=date,
                model=model,
                input_tokens=0,
                output_tokens=0,
                images=0,
                calls=0,
            )
            session.add(record)
        else:
            # Rows migrated from legacy JSON usage data may carry NULL counters
            # (JSON `null` survives `.get(key, 0)` since the key was present).
            # Heal them here so `+=` below never hits NoneType.
            record.input_tokens = record.input_tokens or 0
            record.output_tokens = record.output_tokens or 0
            record.images = record.images or 0
            record.calls = record.calls or 0
            record.cached_input_tokens = record.cached_input_tokens or 0
        return record

    def get_day_usage(self, user_id: int, day: Optional[str] = None) -> dict:
        day = day or _msk_today()
        with SyncSessionLocal() as session:
            records = session.query(UsageRecord).filter_by(user_id=user_id, date=day).all()
            return {r.model: {
                "input": r.input_tokens,
                "output": r.output_tokens,
                "images": r.images,
                "calls": r.calls,
                "cached": r.cached_input_tokens or 0,
            } for r in records}

    def get_month_usage(self, user_id: int, month: Optional[str] = None) -> dict:
        month = month or _msk_today()[:7]
        with SyncSessionLocal() as session:
            records = session.query(UsageRecord).filter(
                UsageRecord.user_id == user_id,
                UsageRecord.date.startswith(month),
            ).all()
            result: Dict[str, dict] = {}
            for r in records:
                result.setdefault(r.model, {"input": 0, "output": 0, "images": 0, "calls": 0, "cached": 0})
                result[r.model]["input"] += r.input_tokens
                result[r.model]["output"] += r.output_tokens
                result[r.model]["images"] += r.images
                result[r.model]["calls"] += r.calls
                result[r.model]["cached"] += r.cached_input_tokens or 0
            return result

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------
    def _default_subscription(self, user_id: int) -> dict:
        return {
            "tier": "free",
            "expires_at": 0,
            "daily_nano_mini": 0,
            "daily_gpt54": 0,
            "daily_director": 0,
            "daily_images": 0,
            "daily_docs": 0,
            "last_reset_date": _msk_today(),
            "has_used_trial": False,
            "active_promocode": None,
            "last_reminded_date": None,
            "period_start": _msk_period(),
            "chat_tokens_used": 0,
            "computer_tokens_used": 0,
            "images_used": 0,
            "nano_cushion_date": _msk_today(),
            "nano_cushion_used": 0,
            "session_started_at": 0,
            "session_chat_used": 0,
            "session_computer_used": 0,
            "week_start": "",
            "week_chat_used": 0,
            "week_computer_used": 0,
        }

    def _get_or_create_subscription(self, session: Session, user_id: int) -> Subscription:
        sub = session.query(Subscription).filter_by(user_id=user_id).first()
        if not sub:
            defaults = self._default_subscription(user_id)
            sub = Subscription(user_id=user_id, **defaults)
            session.add(sub)
            session.commit()
            session.refresh(sub)
        return sub

    def _reset_daily_if_needed(self, sub: Subscription) -> None:
        from app.billing.quota import refresh_windows

        data = _subscription_payload(sub)
        refresh_windows(data)
        _apply_subscription_payload(sub, data)

    def get_subscription(self, user_id: int) -> dict:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            self._reset_daily_if_needed(sub)
            account = session.scalar(select(User).where(User.bot_user_id == user_id))
            # Admins default to Creator, but an explicit paid plan must stick.
            # Overwriting on every read made «Назначить тариф» look broken.
            from app.billing.plans import canonical_tier

            if account is not None and account.role == "admin" and canonical_tier(sub.tier) == "free":
                sub.tier = "creator"
            session.commit()
            from app.billing.quota import effective_tier

            raw_tier = sub.tier
            payload = {
                "tier": raw_tier,
                "tier_raw": raw_tier,
                "expires_at": sub.expires_at,
                "daily_nano_mini": sub.daily_nano_mini,
                "daily_gpt54": sub.daily_gpt54,
                "daily_director": sub.daily_director,
                "daily_images": sub.daily_images,
                "daily_docs": sub.daily_docs,
                "last_reset_date": sub.last_reset_date,
                "has_used_trial": sub.has_used_trial,
                "active_promocode": sub.active_promocode,
                "last_reminded_date": sub.last_reminded_date,
                "period_start": sub.period_start,
                "chat_tokens_used": sub.chat_tokens_used or 0,
                "computer_tokens_used": sub.computer_tokens_used or 0,
                "images_used": sub.images_used or 0,
                "nano_cushion_date": sub.nano_cushion_date,
                "nano_cushion_used": sub.nano_cushion_used or 0,
                "session_started_at": sub.session_started_at or 0,
                "session_chat_used": sub.session_chat_used or 0,
                "session_computer_used": sub.session_computer_used or 0,
                "week_start": sub.week_start or "",
                "week_chat_used": sub.week_chat_used or 0,
                "week_computer_used": sub.week_computer_used or 0,
            }
            payload["tier"] = effective_tier(payload)
            return payload

    def update_subscription_limits(self, user_id: int, field: str, value: int = 1) -> None:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            self._reset_daily_if_needed(sub)
            current = getattr(sub, field, 0) or 0
            setattr(sub, field, current + value)
            session.commit()

    def set_active_promocode(self, user_id: int, promocode: str) -> None:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            sub.active_promocode = promocode
            session.commit()

    def get_active_promocode(self, user_id: int) -> Optional[str]:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            return sub.active_promocode

    def set_reminded_date(self, user_id: int) -> None:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            sub.last_reminded_date = _msk_today()
            session.commit()

    def set_subscription_tier(self, user_id: int, tier: str, duration_days: int = 30, from_today: bool = False) -> None:
        import time
        from app.billing.plans import canonical_tier

        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            sub.tier = canonical_tier(tier)
            now = int(time.time())
            if sub.tier == "free":
                sub.expires_at = 0
            elif from_today:
                sub.expires_at = now + max(1, int(duration_days)) * 86400
            else:
                sub.expires_at = max(now, sub.expires_at or 0) + duration_days * 86400
            if sub.tier == "trial":
                sub.has_used_trial = True
            if sub.tier in ("pro", "proplus", "ultra"):
                sub.active_promocode = None
            sub.period_start = _msk_period()
            sub.chat_tokens_used = 0
            sub.computer_tokens_used = 0
            sub.images_used = 0
            sub.nano_cushion_date = _msk_today()
            sub.nano_cushion_used = 0
            sub.session_started_at = 0
            sub.session_chat_used = 0
            sub.session_computer_used = 0
            from app.billing.quota import msk_monday
            sub.week_start = msk_monday()
            sub.week_chat_used = 0
            sub.week_computer_used = 0
            session.commit()

    def reset_non_admin_subscriptions(
        self,
        tier: str = "free",
        duration_days: int = 30,
        bot_user_ids: Optional[List[int]] = None,
    ) -> dict:
        """Reset non-admin accounts to a chosen plan starting today."""
        from app.billing.plans import canonical_tier

        chosen = canonical_tier(tier)
        with SyncSessionLocal() as session:
            admin_ids = {
                row[0]
                for row in session.query(User.bot_user_id).filter(User.role == "admin").all()
            }
            account_ids = {
                row[0]
                for row in session.query(User.bot_user_id).filter(User.role != "admin").all()
            }
        targets = account_ids - admin_ids
        if bot_user_ids is not None:
            targets &= set(bot_user_ids)
        for bot_id in targets:
            self.set_subscription_tier(bot_id, chosen, duration_days, from_today=True)
        return {"reset": len(targets), "skipped_admins": len(admin_ids), "tier": chosen}

    def _lock_subscription(self, session: Session, user_id: int) -> Subscription:
        """Create the row if needed, then lock it for a check-and-update."""
        self._get_or_create_subscription(session, user_id)
        query = session.query(Subscription).filter_by(user_id=user_id)
        bind = session.get_bind()
        if bind is not None and bind.dialect.name != "sqlite":
            query = query.with_for_update()
        return query.one()

    def debit_plan_tokens(self, user_id: int, pool: str, amount: int, model: str = "", already: int = 0) -> None:
        if amount <= 0:
            return
        from app.billing.quota import apply_token_debit

        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                data = _subscription_payload(sub)
                apply_token_debit(data, pool, amount, already=already)
                _apply_subscription_payload(sub, data)
                session.commit()

    def check_and_hold_quota(self, user_id: int, pool: str, model: str) -> bool:
        """Under the row lock: block if the window is closed, otherwise reserve 1 token."""
        from app.billing.quota import raise_if_blocked

        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                data = _subscription_payload(sub)
                hold = raise_if_blocked(data, pool, model)
                if hold:
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    if not int(data.get("session_started_at") or 0):
                        data["session_started_at"] = now_ts
                    if pool == "computer":
                        data["computer_tokens_used"] = int(data.get("computer_tokens_used") or 0) + 1
                        data["session_computer_used"] = int(data.get("session_computer_used") or 0) + 1
                        data["week_computer_used"] = int(data.get("week_computer_used") or 0) + 1
                    else:
                        data["chat_tokens_used"] = int(data.get("chat_tokens_used") or 0) + 1
                        data["session_chat_used"] = int(data.get("session_chat_used") or 0) + 1
                        data["week_chat_used"] = int(data.get("week_chat_used") or 0) + 1
                _apply_subscription_payload(sub, data)
                session.commit()
                return bool(hold)

    def release_paid_window(self, user_id: int, pool: str) -> None:
        """Give back the 1-unit hold. Does not reset the session window."""
        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                if pool == "computer":
                    fields = ("computer_tokens_used", "session_computer_used", "week_computer_used")
                else:
                    fields = ("chat_tokens_used", "session_chat_used", "week_chat_used")
                for name in fields:
                    current = int(getattr(sub, name) or 0)
                    setattr(sub, name, max(0, current - 1))
                session.commit()

    def try_consume_images(self, user_id: int, count: int = 1) -> bool:
        """Atomically reserve image quota. Unlimited plans succeed without incrementing."""
        if count <= 0:
            return True
        from app.billing.plans import plan_for
        from app.billing.quota import effective_tier

        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                self._reset_daily_if_needed(sub)
                tier = effective_tier(_subscription_payload(sub))
                plan = plan_for(tier)
                if plan.get("unlimited"):
                    session.commit()
                    return True
                limit = int(plan.get("images") or 0)
                used = int(sub.images_used or 0)
                if limit and used + count > limit:
                    session.commit()
                    return False
                sub.images_used = used + count
                session.commit()
                return True

    def refund_plan_images(self, user_id: int, count: int = 1) -> None:
        if count <= 0:
            return
        from app.billing.plans import plan_for
        from app.billing.quota import effective_tier

        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                tier = effective_tier(_subscription_payload(sub))
                if plan_for(tier).get("unlimited"):
                    session.commit()
                    return
                sub.images_used = max(0, int(sub.images_used or 0) - int(count))
                session.commit()

    def debit_plan_images(self, user_id: int, count: int = 1) -> None:
        if count <= 0:
            return
        from app.billing.plans import plan_for
        from app.billing.quota import effective_tier

        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                self._reset_daily_if_needed(sub)
                tier = effective_tier(_subscription_payload(sub))
                if plan_for(tier).get("unlimited"):
                    session.commit()
                    return
                limit = int(plan_for(tier).get("images") or 0)
                used = int(sub.images_used or 0)
                if limit and used + count > limit:
                    sub.images_used = limit
                else:
                    sub.images_used = used + count
                session.commit()

    _DAILY_COUNTERS = frozenset({
        "daily_gpt54",
        "daily_nano_mini",
        "daily_director",
        "daily_images",
        "daily_docs",
        "nano_cushion_used",
    })

    def consume_daily_counter(self, user_id: int, field: str, limit: int) -> bool:
        """Atomically increment a free-tier counter when it is still under limit."""
        if field not in self._DAILY_COUNTERS:
            raise ValueError(field)
        limit = int(limit or 0)
        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = self._lock_subscription(session, user_id)
                self._reset_daily_if_needed(sub)
                current = int(getattr(sub, field) or 0)
                if limit and current >= limit:
                    session.commit()
                    return False
                setattr(sub, field, current + 1)
                session.commit()
                return True

    def refund_daily_counter(self, user_id: int, field: str) -> None:
        if field not in self._DAILY_COUNTERS:
            return
        with self._quota_lock:
            with SyncSessionLocal() as session:
                sub = session.query(Subscription).filter_by(user_id=user_id).first()
                if not sub:
                    return
                bind = session.get_bind()
                if bind is not None and bind.dialect.name != "sqlite":
                    sub = session.query(Subscription).filter_by(user_id=user_id).with_for_update().one()
                current = int(getattr(sub, field) or 0)
                if current > 0:
                    setattr(sub, field, current - 1)
                session.commit()

    def increment_nano_cushion(self, user_id: int) -> None:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            self._reset_daily_if_needed(sub)
            sub.nano_cushion_used = (sub.nano_cushion_used or 0) + 1
            session.commit()

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    def get_user_model(self, user_id: int) -> str:
        # Новый человек без выбора – «Авто», как и показывает интерфейс, а не Nano.
        with SyncSessionLocal() as session:
            sub = session.query(Subscription).filter_by(user_id=user_id).first()
            return sub.selected_model if sub and sub.selected_model else "auto"

    def set_user_model(self, user_id: int, model: str) -> None:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            sub.selected_model = model
            session.commit()

    def get_user_reasoning_effort(self, user_id: int) -> Optional[str]:
        with SyncSessionLocal() as session:
            sub = session.query(Subscription).filter_by(user_id=user_id).first()
            return sub.reasoning_effort if sub else None

    def set_user_reasoning_effort(self, user_id: int, effort: Optional[str]) -> None:
        with SyncSessionLocal() as session:
            sub = self._get_or_create_subscription(session, user_id)
            sub.reasoning_effort = effort
            session.commit()

    # ------------------------------------------------------------------
    # Edit mode
    # ------------------------------------------------------------------
    def is_edit_mode(self, user_id: int) -> bool:
        return self._edit_mode.get(user_id, False)

    def set_edit_mode(self, user_id: int, enabled: bool) -> None:
        self._edit_mode[user_id] = enabled
        if not enabled:
            self._user_images.pop(user_id, None)

    def get_user_image(self, user_id: int) -> Optional[bytes]:
        return self._user_images.get(user_id)

    def set_user_image(self, user_id: int, image_bytes: bytes) -> None:
        self._user_images[user_id] = image_bytes

    def clear_user_image(self, user_id: int) -> None:
        self._user_images.pop(user_id, None)

    # ------------------------------------------------------------------
    # DALL-E mode
    # ------------------------------------------------------------------
    def is_dalle_mode(self, user_id: int) -> bool:
        return self._dalle_mode.get(user_id, False)

    def set_dalle_mode(self, user_id: int, enabled: bool) -> None:
        self._dalle_mode[user_id] = enabled
        if not enabled:
            self._dalle_images.pop(user_id, None)

    def get_dalle_image(self, user_id: int) -> Optional[bytes]:
        return self._dalle_images.get(user_id)

    def set_dalle_image(self, user_id: int, image_bytes: bytes) -> None:
        self._dalle_images[user_id] = image_bytes

    # ------------------------------------------------------------------
    # Temporary template mode
    # ------------------------------------------------------------------
    def is_template_mode(self, user_id: int) -> bool:
        return self._template_mode.get(user_id, False)

    def set_template_mode(self, user_id: int, enabled: bool) -> None:
        self._template_mode[user_id] = enabled
        if not enabled:
            self._template_docs.pop(user_id, None)
            self._template_names.pop(user_id, None)

    def get_template_doc(self, user_id: int) -> Optional[bytes]:
        return self._template_docs.get(user_id)

    def get_template_name(self, user_id: int) -> Optional[str]:
        return self._template_names.get(user_id)

    def set_template_doc(self, user_id: int, doc_bytes: bytes, filename: str) -> None:
        self._template_docs[user_id] = doc_bytes
        self._template_names[user_id] = filename

    # ------------------------------------------------------------------
    # Base template (persisted)
    # ------------------------------------------------------------------
    def is_base_template_mode(self, user_id: int) -> bool:
        return self._base_template_mode.get(user_id, False)

    def set_base_template_mode(self, user_id: int, enabled: bool) -> None:
        self._base_template_mode[user_id] = enabled

    def get_base_template(self, user_id: int) -> Optional[bytes]:
        if user_id in self._base_template_cache:
            return self._base_template_cache[user_id]
        with SyncSessionLocal() as session:
            record = session.get(BaseTemplate, user_id)
            if record:
                self._base_template_cache[user_id] = record.content
                return record.content
        return None

    def get_base_template_name(self, user_id: int) -> Optional[str]:
        if user_id in self._base_template_name_cache:
            return self._base_template_name_cache[user_id]
        with SyncSessionLocal() as session:
            record = session.get(BaseTemplate, user_id)
            if record:
                self._base_template_name_cache[user_id] = record.filename
                return record.filename
        return None

    def set_base_template(self, user_id: int, doc_bytes: bytes, filename: str) -> None:
        with SyncSessionLocal() as session:
            record = session.get(BaseTemplate, user_id)
            if record:
                record.content = doc_bytes
                record.filename = filename
            else:
                session.add(BaseTemplate(user_id=user_id, filename=filename, content=doc_bytes))
            session.commit()
        self._base_template_cache[user_id] = doc_bytes
        self._base_template_name_cache[user_id] = filename

    def clear_base_template(self, user_id: int) -> bool:
        existed = False
        with SyncSessionLocal() as session:
            record = session.get(BaseTemplate, user_id)
            if record:
                session.delete(record)
                existed = True
            session.commit()
        self._base_template_cache.pop(user_id, None)
        self._base_template_name_cache.pop(user_id, None)
        return existed

    def get_user_memory(self, user_id: int) -> dict:
        with SyncSessionLocal() as session:
            row = session.query(UserMemory).filter_by(user_id=user_id).first()
            if not row:
                return {"notes": "", "enabled": True, "updated_at": 0, "last_hash": ""}
            return {
                "notes": row.notes or "",
                "enabled": bool(row.enabled),
                "updated_at": int(row.updated_at or 0),
                "last_hash": row.last_hash or "",
            }

    def save_user_memory(
        self,
        user_id: int,
        notes: str | None = None,
        enabled: bool | None = None,
        last_hash: str | None = None,
        updated_at: int | None = None,
    ) -> dict:
        import time

        with SyncSessionLocal() as session:
            row = session.query(UserMemory).filter_by(user_id=user_id).first()
            if not row:
                row = UserMemory(user_id=user_id, notes="", enabled=True, updated_at=0, last_hash="")
                session.add(row)
            if notes is not None:
                row.notes = notes
            if enabled is not None:
                row.enabled = enabled
            if last_hash is not None:
                row.last_hash = last_hash
            if updated_at is not None:
                row.updated_at = int(updated_at)
            elif notes is not None:
                row.updated_at = int(time.time())
            session.commit()
            return {
                "notes": row.notes or "",
                "enabled": bool(row.enabled),
                "updated_at": int(row.updated_at or 0),
                "last_hash": row.last_hash or "",
            }

    def _user_skill_dict(self, row: UserSkill) -> dict:
        return {
            "name": row.name,
            "title": row.title or row.name,
            "description": row.description or "",
            "body": row.body or "",
            "triggers": row.triggers or "",
            "enabled": bool(row.enabled),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        }

    def list_user_skills(self, user_id: int, enabled_only: bool = False) -> list[dict]:
        with SyncSessionLocal() as session:
            query = session.query(UserSkill).filter_by(user_id=user_id)
            if enabled_only:
                query = query.filter_by(enabled=True)
            rows = query.order_by(UserSkill.name).all()
            return [self._user_skill_dict(row) for row in rows]

    def get_user_skill(self, user_id: int, name: str) -> dict | None:
        slug = (name or "").strip().lower()
        if not slug:
            return None
        with SyncSessionLocal() as session:
            row = session.query(UserSkill).filter_by(user_id=user_id, name=slug).first()
            return self._user_skill_dict(row) if row else None

    def save_user_skill(
        self,
        user_id: int,
        name: str,
        description: str | None = None,
        body: str | None = None,
        title: str | None = None,
        triggers: str | None = None,
        enabled: bool | None = None,
        partial: bool = False,
    ) -> dict | None:
        import time

        from computer_skills.store import MAX_SKILLS, normalize_name, validate_payload

        slug = normalize_name(name)
        now = int(time.time())
        with SyncSessionLocal() as session:
            row = session.query(UserSkill).filter_by(user_id=user_id, name=slug).first()
            if partial and row is None:
                return None
            if row is None:
                payload = validate_payload(
                    name=name,
                    description=description or "",
                    body=body or "",
                    title=title or "",
                    triggers=triggers or "",
                )
                count = session.query(UserSkill).filter_by(user_id=user_id).count()
                if count >= MAX_SKILLS:
                    raise ValueError(f"Можно сохранить не больше {MAX_SKILLS} своих скилов.")
                row = UserSkill(
                    user_id=user_id,
                    name=payload["name"],
                    title=payload["title"],
                    description=payload["description"],
                    body=payload["body"],
                    triggers=payload["triggers"],
                    enabled=True if enabled is None else bool(enabled),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                merged_title = row.title if title is None else title
                merged_description = row.description if description is None else description
                merged_body = row.body if body is None else body
                merged_triggers = row.triggers if triggers is None else triggers
                if any(value is not None for value in (title, description, body, triggers)):
                    payload = validate_payload(
                        name=row.name,
                        description=merged_description or "",
                        body=merged_body or "",
                        title=merged_title or "",
                        triggers=merged_triggers or "",
                        allow_reserved=True,
                    )
                    row.title = payload["title"]
                    row.description = payload["description"]
                    row.body = payload["body"]
                    row.triggers = payload["triggers"]
                if enabled is not None:
                    row.enabled = bool(enabled)
                row.updated_at = now
            session.commit()
            session.refresh(row)
            return self._user_skill_dict(row)

    def delete_user_skill(self, user_id: int, name: str) -> bool:
        from computer_skills.loader import builtin_names
        from computer_skills.store import normalize_name

        slug = normalize_name(name)
        if slug in builtin_names():
            raise ValueError("Общий скил нельзя удалить. Можно добавить свой с другим именем.")
        with SyncSessionLocal() as session:
            row = session.query(UserSkill).filter_by(user_id=user_id, name=slug).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    # ------------------------------------------------------------------
    # Custom prompts
    # ------------------------------------------------------------------
    def get_custom_prompts(self, user_id: int) -> List[str]:
        with SyncSessionLocal() as session:
            prompts = session.query(CustomPrompt).filter_by(user_id=user_id).order_by(CustomPrompt.id).all()
            return [p.prompt for p in prompts]

    def add_custom_prompt(self, user_id: int, prompt: str) -> int:
        with SyncSessionLocal() as session:
            prompts = session.query(CustomPrompt).filter_by(user_id=user_id).order_by(CustomPrompt.id).all()
            if len(prompts) >= 2:
                # Replace oldest
                session.delete(prompts[0])
                session.flush()
            new_prompt = CustomPrompt(user_id=user_id, prompt=prompt, active=False)
            session.add(new_prompt)
            session.commit()
            session.refresh(new_prompt)
            return new_prompt.id

    def get_active_custom_prompt(self, user_id: int) -> Optional[str]:
        if user_id in self._active_custom_prompt:
            return self._active_custom_prompt[user_id]
        with SyncSessionLocal() as session:
            active = session.query(CustomPrompt).filter_by(user_id=user_id, active=True).first()
            return active.prompt if active else None

    def set_active_custom_prompt(self, user_id: int, index: Optional[int]) -> None:
        with SyncSessionLocal() as session:
            session.query(CustomPrompt).filter_by(user_id=user_id).update({"active": False})
            if index is not None:
                prompt = session.query(CustomPrompt).filter_by(user_id=user_id, id=index).first()
                if prompt:
                    prompt.active = True
                    self._active_custom_prompt[user_id] = prompt.prompt
                else:
                    self._active_custom_prompt[user_id] = None
            else:
                self._active_custom_prompt[user_id] = None
            session.commit()

    def delete_custom_prompt(self, user_id: int, index: int) -> bool:
        with SyncSessionLocal() as session:
            prompt = session.query(CustomPrompt).filter_by(user_id=user_id, id=index).first()
            if not prompt:
                return False
            session.delete(prompt)
            session.commit()
            if self._active_custom_prompt.get(user_id) == prompt.prompt:
                self._active_custom_prompt[user_id] = None
            return True

    # ------------------------------------------------------------------
    # Shared conversations
    # ------------------------------------------------------------------
    def _allows(self, session: Session, user_id: int, conv: Conversation) -> bool:
        if conv.user_id == user_id:
            return True
        return (
            session.query(ConversationMember)
            .filter_by(conversation_id=conv.id, user_id=user_id)
            .first()
            is not None
        )

    def _open_conv(self, session: Session, user_id: int, conv_id: Optional[str] = None) -> Optional[Conversation]:
        """Беседа, в которую писать. Явный id — если человек владелец или участник.
        Без id — его личная активная, как раньше."""
        if conv_id:
            conv = session.get(Conversation, conv_id)
            if conv and self._allows(session, user_id, conv):
                return conv
            return None
        return session.query(Conversation).filter_by(user_id=user_id, is_active=True).first()

    def conversation_view(self, user_id: int, conv_id: str) -> Optional[ConversationData]:
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            return ConversationData.from_model(conv) if conv else None

    def conversation_owner(self, conv_id: str) -> Optional[int]:
        with SyncSessionLocal() as session:
            conv = session.get(Conversation, conv_id)
            return conv.user_id if conv else None

    def is_shared(self, conv_id: str) -> bool:
        with SyncSessionLocal() as session:
            return (
                session.query(ConversationMember).filter_by(conversation_id=conv_id).first() is not None
            )

    def participant_emails(self, conv_id: str) -> List[str]:
        """Почты участников, которым слать живое обновление. Пусто, если диалог личный."""
        with SyncSessionLocal() as session:
            conv = session.get(Conversation, conv_id)
            if not conv:
                return []
            member_ids = [
                row.user_id
                for row in session.query(ConversationMember).filter_by(conversation_id=conv_id).all()
            ]
            if not member_ids:
                return []
            ids = set(member_ids)
            ids.add(conv.user_id)
            rows = session.query(User).filter(User.bot_user_id.in_(ids)).all()
            return [row.email for row in rows if row.email]

    def _editor_edit_notes(self, conv_id: str) -> Dict[str, str]:
        """Файлы беседы, изменённые в редакторе: имя → «изменён 24.09.2026 13:20, Мария, версия 3»."""
        from zoneinfo import ZoneInfo

        from app.db.models import EditorDocument

        with SyncSessionLocal() as session:
            rows = [
                (row.filename, row.version, row.edited_by, row.updated_at)
                for row in session.query(EditorDocument).filter_by(conversation_id=conv_id).all()
                if row.version > 1 or row.edited_by
            ]
        if not rows:
            return {}
        cards = self.author_cards([edited_by for _, _, edited_by, _ in rows if edited_by])
        notes = {}
        for filename, version, edited_by, updated_at in rows:
            when = ""
            if updated_at is not None:
                stamp = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
                when = f" {stamp.astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M')} по Москве"
            who = f", правил {cards[edited_by]['name']}" if edited_by in cards else ""
            notes[filename] = (
                f"Изменён в редакторе{when}{who}, версия {version}. Это текущая версия файла."
            )
        return notes

    def author_cards(self, bot_ids: List[int]) -> Dict[int, dict]:
        ids = [item for item in dict.fromkeys(bot_ids) if item]
        if not ids:
            return {}
        with SyncSessionLocal() as session:
            rows = session.query(User).filter(User.bot_user_id.in_(ids)).all()
        cards = {}
        for row in rows:
            name = (row.first_name or "").strip() or str(row.email or "").split("@", 1)[0] or "Участник"
            cards[row.bot_user_id] = {"name": name, "avatar_url": row.avatar_url}
        return cards

    def create_share(self, user_id: int, conv_id: str) -> Optional[str]:
        import secrets
        with SyncSessionLocal() as session:
            conv = session.query(Conversation).filter_by(id=conv_id, user_id=user_id).first()
            if not conv:
                return None
            current = (
                session.query(ConversationShare)
                .filter_by(conversation_id=conv_id, revoked=False)
                .order_by(ConversationShare.created_at.desc())
                .first()
            )
            if current:
                return current.token
            token = secrets.token_urlsafe(18)
            session.add(ConversationShare(token=token, conversation_id=conv_id, created_by=user_id, revoked=False))
            session.commit()
            return token

    def revoke_share(self, user_id: int, conv_id: str) -> bool:
        with SyncSessionLocal() as session:
            conv = session.query(Conversation).filter_by(id=conv_id, user_id=user_id).first()
            if not conv:
                return False
            session.query(ConversationShare).filter_by(conversation_id=conv_id, revoked=False).update({"revoked": True})
            session.query(ConversationMember).filter_by(conversation_id=conv_id).delete()
            session.commit()
            return True

    def share_status(self, user_id: int, conv_id: str) -> Optional[dict]:
        with SyncSessionLocal() as session:
            conv = session.get(Conversation, conv_id)
            if not conv or not self._allows(session, user_id, conv):
                return None
            share = (
                session.query(ConversationShare)
                .filter_by(conversation_id=conv_id, revoked=False)
                .order_by(ConversationShare.created_at.desc())
                .first()
            )
            members = session.query(ConversationMember).filter_by(conversation_id=conv_id).all()
            owner_id = conv.user_id
            token = share.token if share else None
            ids = [owner_id] + [row.user_id for row in members]
            shared = bool(share) or bool(members)
        cards = self.author_cards(ids)
        people = []
        for bot_id in ids:
            card = cards.get(bot_id) or {"name": "Участник", "avatar_url": None}
            people.append({**card, "owner": bot_id == owner_id})
        return {
            "shared": shared,
            "token": token if owner_id == user_id else None,
            "role": "owner" if owner_id == user_id else "member",
            "people": people,
        }

    def join_share(self, user_id: int, token: str) -> Optional[dict]:
        with SyncSessionLocal() as session:
            share = session.query(ConversationShare).filter_by(token=token, revoked=False).first()
            if not share:
                return None
            conv = session.get(Conversation, share.conversation_id)
            if not conv:
                return None
            if conv.user_id != user_id:
                exists = (
                    session.query(ConversationMember)
                    .filter_by(conversation_id=conv.id, user_id=user_id)
                    .first()
                )
                if not exists:
                    session.add(ConversationMember(conversation_id=conv.id, user_id=user_id))
                    session.commit()
            return {"id": conv.id, "title": conv.title}

    def list_asides(self, user_id: int, conv_id: str) -> Optional[List[dict]]:
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return None
            rows = (
                session.query(ConversationAside)
                .filter_by(conversation_id=conv_id)
                .order_by(ConversationAside.id.asc())
                .all()
            )
            packed = [
                {
                    "id": row.id,
                    "content": row.content,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "author_user_id": row.author_user_id,
                }
                for row in rows
            ]
        cards = self.author_cards([item["author_user_id"] for item in packed])
        result = []
        for item in packed:
            author_id = item.pop("author_user_id")
            item["author"] = cards.get(author_id) or {"name": "Участник", "avatar_url": None}
            item["mine"] = author_id == user_id
            result.append(item)
        return result

    def add_aside(self, user_id: int, conv_id: str, content: str) -> Optional[dict]:
        text = (content or "").strip()
        if not text:
            return None
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return None
            row = ConversationAside(
                conversation_id=conv.id,
                author_user_id=user_id,
                content=text[:4000],
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            created = row.created_at.isoformat() if row.created_at else ""
            aside_id = row.id
        card = self.author_cards([user_id]).get(user_id) or {"name": "Участник", "avatar_url": None}
        return {
            "id": aside_id,
            "content": text[:4000],
            "created_at": created,
            "author": card,
            "mine": True,
        }

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    def _conv_id(self) -> str:
        now = datetime.now()
        return f"conv_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"

    def get_conversations(self, user_id: int) -> List[ConversationData]:
        with SyncSessionLocal() as session:
            owned = session.query(Conversation).filter_by(user_id=user_id).order_by(Conversation.created_at.desc()).all()
            joined_ids = [
                row.conversation_id
                for row in session.query(ConversationMember).filter_by(user_id=user_id).all()
            ]
            seen = {conv.id for conv in owned}
            joined = []
            if joined_ids:
                joined = (
                    session.query(Conversation)
                    .filter(Conversation.id.in_(joined_ids))
                    .order_by(Conversation.updated_at.desc())
                    .all()
                )
            return [ConversationData.from_model(c) for c in owned + [c for c in joined if c.id not in seen]]

    def conversation_roles(self, user_id: int, conv_ids: List[str]) -> Dict[str, str]:
        """id беседы → owner | member. Нужно списку чатов, чтобы отметить общие."""
        if not conv_ids:
            return {}
        with SyncSessionLocal() as session:
            owned = {
                row.id
                for row in session.query(Conversation).filter(
                    Conversation.id.in_(conv_ids), Conversation.user_id == user_id
                ).all()
            }
            member = {
                row.conversation_id
                for row in session.query(ConversationMember).filter(
                    ConversationMember.user_id == user_id,
                    ConversationMember.conversation_id.in_(conv_ids),
                ).all()
            }
            shared = {
                row.conversation_id
                for row in session.query(ConversationMember).filter(
                    ConversationMember.conversation_id.in_(conv_ids)
                ).all()
            }
            shared |= {
                row.conversation_id
                for row in session.query(ConversationShare).filter(
                    ConversationShare.conversation_id.in_(conv_ids),
                    ConversationShare.revoked.is_(False),
                ).all()
            }
        roles = {}
        for conv_id in conv_ids:
            if conv_id in member or conv_id in shared:
                roles[conv_id] = "owner" if conv_id in owned else "member"
        return roles

    def get_active_conversation(self, user_id: int) -> Optional[ConversationData]:
        with SyncSessionLocal() as session:
            conv = session.query(Conversation).filter_by(user_id=user_id, is_active=True).first()
            return ConversationData.from_model(conv) if conv else None

    def create_conversation(self, user_id: int, title: Optional[str] = None) -> ConversationData:
        from sqlalchemy.exc import IntegrityError

        last_error: Exception | None = None
        for _ in range(5):
            try:
                with SyncSessionLocal() as session:
                    session.query(Conversation).filter_by(user_id=user_id, is_active=True).update({"is_active": False})
                    conv = Conversation(
                        id=self._conv_id(),
                        user_id=user_id,
                        title=title or "Новый чат",
                        is_active=True,
                    )
                    session.add(conv)
                    session.commit()
                    session.refresh(conv)
                    return ConversationData.from_model(conv)
            except IntegrityError as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("Не удалось создать беседу")

    def set_active_conversation(self, user_id: int, conv_id: str) -> Optional[ConversationData]:
        with SyncSessionLocal() as session:
            conv = session.get(Conversation, conv_id)
            if not conv or not self._allows(session, user_id, conv):
                return None
            # Чужую беседу не делаем «активной» у владельца: иначе гость
            # переключал бы его личные чаты. Писать в неё всё равно можно по id.
            if conv.user_id != user_id:
                return ConversationData.from_model(conv)
            session.query(Conversation).filter_by(user_id=user_id, is_active=True).update({"is_active": False})
            conv.is_active = True
            session.commit()
            session.refresh(conv)
            return ConversationData.from_model(conv)

    def delete_conversation(self, user_id: int, conv_id: str) -> bool:
        with SyncSessionLocal() as session:
            conv = session.query(Conversation).filter_by(user_id=user_id, id=conv_id).first()
            if not conv:
                return False
            session.delete(conv)
            session.commit()
            return True

    def delete_all_conversations(self, user_id: int) -> None:
        with SyncSessionLocal() as session:
            session.query(Conversation).filter_by(user_id=user_id).delete()
            session.commit()

    def delete_last_message(self, user_id: int, conv_id: str, role: str) -> bool:
        """Drop this user's own latest message of a role. User rows of other people stay."""
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return False
            rows = (
                session.query(Message)
                .filter_by(conversation_id=conv.id, role=role)
                .order_by(Message.id.desc())
                .all()
            )
            for msg in rows:
                if role == "user":
                    author = msg.author_user_id
                    if author is None:
                        if conv.user_id != user_id:
                            continue
                    elif author != user_id:
                        continue
                session.delete(msg)
                session.commit()
                return True
            return False

    def can_regenerate(self, user_id: int, conv_id: str) -> bool:
        """Owner may retry any trailing answer. A guest may retry only their own question."""
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return False
            msgs = session.query(Message).filter_by(conversation_id=conv.id).order_by(Message.id.asc()).all()
            if not msgs or msgs[-1].role != "assistant":
                return False
            if conv.user_id == user_id:
                return True
            previous_user = next((item for item in reversed(msgs[:-1]) if item.role == "user"), None)
            if previous_user is None:
                return False
            author = previous_user.author_user_id or conv.user_id
            return author == user_id

    def last_assistant_message_id(self, user_id: int, conv_id: str) -> Optional[int]:
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return None
            last = (
                session.query(Message)
                .filter_by(conversation_id=conv.id)
                .order_by(Message.id.desc())
                .first()
            )
            if last is None or last.role != "assistant":
                return None
            return int(last.id)

    def truncate_after(self, user_id: int, conv_id: str, keep_count: int) -> bool:
        """Used by edit-and-resend: drop every message after the first keep_count,
        so an edited user message can be resent as if the rest never happened."""
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return False
            msgs = session.query(Message).filter_by(conversation_id=conv_id).order_by(Message.id.asc()).all()
            if conv.user_id != user_id:
                for item in msgs[keep_count:]:
                    if item.role != "user":
                        continue
                    author = item.author_user_id or conv.user_id
                    if author != user_id:
                        raise PermissionError("Нельзя удалить чужие реплики")
            for m in msgs[keep_count:]:
                session.delete(m)
            session.commit()
            return True

    def clear_conversation(self, user_id: int, conv_id: str, new_title: Optional[str] = None) -> bool:
        with SyncSessionLocal() as session:
            conv = session.query(Conversation).filter_by(user_id=user_id, id=conv_id).first()
            if not conv:
                return False
            session.query(Message).filter_by(conversation_id=conv.id).delete()
            session.query(Document).filter_by(conversation_id=conv.id).delete()
            if new_title:
                conv.title = new_title
            session.commit()
            self._template_docs.pop(user_id, None)
            self._template_names.pop(user_id, None)
            return True

    def rename_conversation(self, user_id: int, conv_id: str, new_title: str) -> bool:
        with SyncSessionLocal() as session:
            conv = session.query(Conversation).filter_by(user_id=user_id, id=conv_id).first()
            if not conv:
                return False
            conv.title = new_title
            session.commit()
            return True

    # ------------------------------------------------------------------
    # Messages and documents
    # ------------------------------------------------------------------
    def add_message(
        self, user_id: int, role: str, content: str, max_messages: int = 2_000,
        attachment: Optional[dict] = None, search: Optional[List[Dict[str, str]]] = None,
        conv_id: Optional[str] = None, author_user_id: Optional[int] = None,
        supersede_message_id: Optional[int] = None,
    ) -> MessageData:
        import json
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                # Явный id чужой беседы не подменяем новым личным чатом.
                if conv_id:
                    raise PermissionError("Нет доступа к беседе")
                conv_data = self.create_conversation(user_id)
                conv = session.query(Conversation).filter_by(id=conv_data.id).first()
            msg = Message(
                conversation_id=conv.id,
                role=role,
                content=content,
                attachment=json.dumps(attachment, ensure_ascii=False) if attachment else None,
                search=json.dumps(search, ensure_ascii=False) if search else None,
                author_user_id=author_user_id if role == "user" else None,
            )
            session.add(msg)
            session.flush()
            if supersede_message_id:
                previous = session.get(Message, int(supersede_message_id))
                if previous is not None and previous.conversation_id == conv.id and previous.id != msg.id:
                    prior_user = (
                        session.query(Message)
                        .filter(
                            Message.conversation_id == conv.id,
                            Message.role == "user",
                            Message.id < previous.id,
                        )
                        .order_by(Message.id.desc())
                        .first()
                    )
                    floor = prior_user.id if prior_user else 0
                    stale = (
                        session.query(Message)
                        .filter(
                            Message.conversation_id == conv.id,
                            Message.role == "assistant",
                            Message.id > floor,
                            Message.id < previous.id,
                        )
                        .all()
                    )
                    for row in stale:
                        if _attachment_is_interim(row.attachment):
                            session.delete(row)
                    session.delete(previous)
            conv.updated_at = datetime.now(timezone.utc)
            session.commit()
            # Trim to last max_messages
            all_msgs = session.query(Message).filter_by(conversation_id=conv.id).order_by(Message.id.asc()).all()
            if len(all_msgs) > max_messages:
                for old in all_msgs[: len(all_msgs) - max_messages]:
                    session.delete(old)
                session.commit()
            return MessageData(
                role=role,
                content=content,
                timestamp=msg.created_at.isoformat(),
                attachment=attachment,
                search=search,
                db_id=int(msg.id),
            )

    def redact_recent_messages(self, user_id: int, secret_values: list[str], limit: int = 8, conv_id: Optional[str] = None) -> None:
        values = [item for item in secret_values if item and len(item) >= 4]
        if not values:
            return
        from app.security.redact import redact_text

        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return
            rows = (
                session.query(Message)
                .filter_by(conversation_id=conv.id)
                .order_by(Message.id.desc())
                .limit(limit)
                .all()
            )
            changed = False
            for row in rows:
                cleaned = redact_text(row.content or "", values)
                if cleaned != row.content:
                    row.content = cleaned
                    changed = True
            if changed:
                session.commit()

    def add_document(self, user_id: int, filename: str, content: str, conv_id: Optional[str] = None) -> None:
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return
            existing = session.query(Document).filter_by(conversation_id=conv.id, filename=filename).first()
            if existing:
                existing.content = content
            else:
                session.add(Document(conversation_id=conv.id, filename=filename, content=content))
            session.commit()

    def _scoped_conv_id(self, conv_id: Optional[str] = None) -> Optional[str]:
        if conv_id:
            return conv_id
        from turn_scope import turn_conversation_id

        return turn_conversation_id()

    def conversation_for_turn(self, user_id: int) -> Optional[ConversationData]:
        """Conversation the current reply is about, else the caller's active chat."""
        conv_id = self._scoped_conv_id(None)
        if conv_id:
            return self.conversation_view(int(user_id), str(conv_id))
        return self.get_active_conversation(user_id)

    def get_documents(self, user_id: int, conv_id: Optional[str] = None) -> List[dict]:
        conv_id = self._scoped_conv_id(conv_id)
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return []
            docs = session.query(Document).filter_by(conversation_id=conv.id).all()
            return [{"filename": d.filename, "content": d.content} for d in docs]

    def _attachment_disk_path(self, attachment: Optional[dict]) -> Optional[Path]:
        if not attachment or not attachment.get("url"):
            return None
        relative_url = str(attachment.get("url") or "").split("?", 1)[0]
        relative_path = relative_url.removeprefix("/uploads/")
        if relative_path == relative_url and "/uploads/" in relative_url:
            relative_path = relative_url.split("/uploads/", 1)[1]
        upload_root = get_settings().UPLOAD_DIR.resolve()
        candidate = (upload_root / relative_path).resolve()
        try:
            candidate.relative_to(upload_root)
        except ValueError:
            logger.warning("Rejected image path outside upload dir: %s", relative_url)
            return None
        return candidate

    def list_chat_image_files(self, user_id: int) -> List[dict]:
        """Фото беседы текущего ответа: имя, путь, mime. Порядок как в переписке."""
        conv = self.conversation_for_turn(user_id)
        if not conv:
            return []
        items: List[dict] = []
        seen: set[str] = set()
        for message in conv.messages:
            attachment = message.attachment or {}
            if not self._is_image_attachment(attachment):
                continue
            path = self._attachment_disk_path(attachment)
            name = str(attachment.get("name") or (path.name if path else "photo.jpg")).strip() or "photo.jpg"
            key = str(attachment.get("url") or name)
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "name": name,
                "path": path,
                "mime": str(attachment.get("mime_type") or "image/jpeg"),
            })
        return items

    def load_chat_image(self, user_id: int, filename: str = "") -> Optional[dict]:
        """Байты названного фото или последнего в чате."""
        files = self.list_chat_image_files(user_id)
        if not files:
            return None
        wanted = (filename or "").strip().lower()
        match = None
        if wanted:
            match = next((item for item in files if item["name"].lower() == wanted), None)
            if match is None:
                match = next((item for item in files if wanted in item["name"].lower()), None)
            if match is None:
                names = ", ".join(item["name"] for item in files)
                return {"error": f"Фото {filename} не найдено. В чате: {names}."}
        else:
            match = files[-1]
        path = match.get("path")
        if path is None or not path.is_file():
            return {"error": f"Файл {match.get('name') or 'фото'} есть в чате, но его нет на диске."}
        data = path.read_bytes()
        if not data:
            return {"error": f"Файл {match['name']} пустой."}
        return {"name": match["name"], "mime": match["mime"], "bytes": data}

    def vision_parts_for_chat(self, user_id: int, query: str = "") -> List[dict]:
        conv = self.conversation_for_turn(user_id)
        if not conv:
            return []
        return self._image_parts_for_conversation(conv, query)

    def list_chat_files(self, user_id: int) -> str:
        docs = self.get_documents(user_id)
        images = self.list_chat_image_files(user_id)
        if not docs and not images:
            return "В этом чате нет загруженных файлов."
        lines = [
            "Файлы этого чата. Документ читай read_chat_document, фото ищи image_search. Имя бери точное:"
        ]
        for item in docs:
            name = str(item.get("filename") or "файл")
            size = len(str(item.get("content") or ""))
            lines.append(f"- {name} ({size} символов текста)")
        for item in images:
            lines.append(f"- {item['name']} (изображение, image_search)")
        return "\n".join(lines)

    def search_user_chats(self, user_id: int, query: str, limit: int = 5) -> str:
        query = " ".join((query or "").split())
        if len(query) < 2:
            return "Нужен короткий запрос: тема, имя, цифра. Не целое предложение."
        try:
            limit = max(1, min(int(limit or 5), 10))
        except (TypeError, ValueError):
            limit = 5
        terms = _query_terms(query) or [query.lower()[:60]]
        needles = _like_needles(terms[:5])
        if not needles:
            return "Нужен короткий запрос: тема, имя, цифра."
        filters = [Message.content.like(f"%{_escape_like(item)}%", escape="\\") for item in needles]
        filters += [Message.content.ilike(f"%{_escape_like(term)}%", escape="\\") for term in terms[:5]]
        with SyncSessionLocal() as session:
            rows = (
                session.query(Message, Conversation)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .filter(Conversation.user_id == user_id)
                .filter(Message.role.in_(["user", "assistant"]))
                .filter(or_(*filters))
                .order_by(Message.id.desc())
                .limit(120)
                .all()
            )
            active_id = None
            active = session.query(Conversation).filter_by(user_id=user_id, is_active=True).first()
            if active:
                active_id = active.id
        best: dict[str, dict[str, Any]] = {}
        for message, conv in rows:
            content = message.content or ""
            if _skip_search_message(content):
                continue
            lowered = content.lower()
            score = sum(lowered.count(term) for term in terms)
            if score <= 0:
                continue
            current = best.get(conv.id)
            if current and current["score"] >= score:
                continue
            marker = "этот чат" if conv.id == active_id else "другой чат"
            snippet = _redact_chat_text(user_id, _chat_snippet(content, terms))
            best[conv.id] = {
                "score": score,
                "when": message.id,
                "block": (
                    f"### {conv.title or 'Чат'} ({marker}, {_fmt_chat_date(conv.updated_at or message.created_at)})\n"
                    f"{snippet}"
                ),
            }
        ranked = sorted(best.values(), key=lambda item: (item["score"], item["when"]), reverse=True)[:limit]
        if not ranked:
            return "В прошлых чатах ничего не нашлось. Это не поиск по интернету."
        return (
            "Найдено в чатах этого человека. Не проси открыть другой чат: перескажи факт.\n\n"
            + "\n\n".join(item["block"] for item in ranked)
        )

    def recent_user_chats(self, user_id: int, limit: int = 8) -> str:
        try:
            limit = max(1, min(int(limit or 8), 20))
        except (TypeError, ValueError):
            limit = 8
        with SyncSessionLocal() as session:
            convs = (
                session.query(Conversation)
                .filter_by(user_id=user_id)
                .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
                .limit(limit)
                .all()
            )
            if not convs:
                return "Чатов пока нет."
            lines = ["Недавние чаты. search_chats – если нужно найти конкретный факт."]
            for conv in convs:
                marker = "этот" if conv.is_active else "другой"
                last = (
                    session.query(Message)
                    .filter_by(conversation_id=conv.id)
                    .filter(Message.role.in_(["user", "assistant"]))
                    .order_by(Message.id.desc())
                    .first()
                )
                snippet = ""
                if last and not _skip_search_message(last.content or ""):
                    snippet = _redact_chat_text(user_id, _chat_snippet(last.content or "", [], 140))
                line = f"- {conv.title or 'Чат'} ({marker}, {_fmt_chat_date(conv.updated_at or conv.created_at)})"
                if snippet:
                    line += f": {snippet}"
                lines.append(line)
            return "\n".join(lines)

    def remove_document(self, user_id: int, filename: str, conv_id: Optional[str] = None) -> bool:
        conv_id = self._scoped_conv_id(conv_id)
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return False
            docs = [
                doc for doc in session.query(Document).filter_by(conversation_id=conv.id).all()
                if doc.filename == filename or doc.filename.startswith(f"{filename}/")
            ]
            if not docs:
                return False
            for doc in docs:
                session.delete(doc)
            session.commit()
            return True

    def latest_message_id(self, user_id: int, conv_id: Optional[str] = None) -> Optional[int]:
        conv_id = self._scoped_conv_id(conv_id)
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return None
            last = (
                session.query(Message)
                .filter_by(conversation_id=conv.id)
                .order_by(Message.id.desc())
                .first()
            )
            return int(last.id) if last is not None else None

    def delete_interim_after(self, user_id: int, conv_id: Optional[str], after_id: int) -> int:
        """Drop Pilot interim cards created after this turn's watermark."""
        conv_id = self._scoped_conv_id(conv_id)
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return 0
            rows = (
                session.query(Message)
                .filter(
                    Message.conversation_id == conv.id,
                    Message.role == "assistant",
                    Message.id > int(after_id),
                )
                .all()
            )
            removed = 0
            for row in rows:
                if _attachment_is_interim(row.attachment):
                    session.delete(row)
                    removed += 1
            if removed:
                session.commit()
            return removed

    def attachment_filename_used(self, user_id: int, filename: str, conv_id: Optional[str] = None) -> bool:
        import json

        conv_id = self._scoped_conv_id(conv_id)
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return False
            for message in session.query(Message).filter_by(conversation_id=conv.id).all():
                if not message.attachment:
                    continue
                try:
                    attachment = json.loads(message.attachment)
                except Exception:
                    continue
                if not isinstance(attachment, dict):
                    continue
                names = [attachment.get("name")]
                for extra in attachment.get("files") or []:
                    if isinstance(extra, dict):
                        names.append(extra.get("name"))
                if filename in names:
                    return True
            return False

    def remove_attachment(
        self,
        user_id: int,
        filename: str,
        conv_id: Optional[str] = None,
        message_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Remove this user's own attachment card. Filename alone is not enough."""
        import json

        if not message_id:
            return None
        conv_id = self._scoped_conv_id(conv_id)
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return None
            message = session.get(Message, int(message_id))
            if message is None or message.conversation_id != conv.id or message.role != "user":
                return None
            author = message.author_user_id
            if author is None:
                if conv.user_id != user_id:
                    return None
            elif author != user_id:
                return None
            if not message.attachment:
                return None
            try:
                attachment = json.loads(message.attachment)
            except Exception:
                return None
            if not isinstance(attachment, dict) or attachment.get("name") != filename:
                return None
            session.delete(message)
            session.commit()
            return attachment

    def clear_documents(self, user_id: int, conv_id: Optional[str] = None) -> bool:
        with SyncSessionLocal() as session:
            conv = self._open_conv(session, user_id, conv_id)
            if not conv:
                return False
            session.query(Document).filter_by(conversation_id=conv.id).delete()
            session.commit()
            self._template_docs.pop(user_id, None)
            self._template_names.pop(user_id, None)
            return True

    # ------------------------------------------------------------------
    # API formatting
    # ------------------------------------------------------------------
    _IMAGE_SUFFIXES = {
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".heic", ".heif", ".avif",
    }

    @staticmethod
    def _is_image_attachment(attachment: Optional[dict]) -> bool:
        if not attachment or not attachment.get("url"):
            return False
        if attachment.get("type") == "image":
            return True
        mime = str(attachment.get("mime_type") or "")
        if mime.startswith("image/"):
            return True
        url = str(attachment.get("url") or "").split("?", 1)[0]
        name = str(attachment.get("name") or "")
        suffix = Path(url).suffix.lower() or Path(name).suffix.lower()
        return suffix in DatabaseConversationManager._IMAGE_SUFFIXES

    def _image_parts_for_conversation(self, conv: ConversationData, query: str = "") -> List[dict]:
        """Load attached images from disk only when this turn needs them.

        A leftover screenshot must not ride along with every later question:
        that burns vision tokens. Current-turn uploads always go in. Older
        photos open when the question is actually about the picture.
        """
        image_messages = [
            (index, message) for index, message in enumerate(conv.messages)
            if self._is_image_attachment(message.attachment)
        ]
        if not image_messages:
            return []
        last_assistant_index = max(
            (index for index, message in enumerate(conv.messages) if message.role == "assistant"),
            default=-1,
        )
        selected_images = [item for item in image_messages if item[0] > last_assistant_index]
        if not selected_images and query_needs_images(query):
            selected_images = image_messages[-4:]
        if not selected_images:
            return []

        image_parts: List[dict] = []
        for _, image_message in selected_images[-8:]:
            attachment = image_message.attachment or {}
            candidate = self._attachment_disk_path(attachment)
            if candidate is None:
                continue
            if not candidate.is_file():
                logger.warning("Attached image missing on disk: %s", attachment.get("url"))
                continue
            encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
            mime_type = attachment.get("mime_type") or "image/jpeg"
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
            })
        return image_parts

    @staticmethod
    def _attach_images_to_last_user(messages: List[dict], image_parts: List[dict]) -> None:
        if not image_parts:
            return
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") != "user":
                continue
            existing = messages[index].get("content", "")
            if isinstance(existing, list):
                messages[index]["content"] = [*existing, *image_parts]
            else:
                text = existing if isinstance(existing, str) and existing.strip() else "Посмотри прикреплённое изображение."
                messages[index]["content"] = [
                    {"type": "text", "text": text},
                    *image_parts,
                ]
            return
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "Посмотри прикреплённое изображение."},
                *image_parts,
            ],
        })

    def get_messages_for_api(
        self, context_id: Union[int, str], system_prompt: str,
        requesting_user_id: Optional[int] = None, conv_id: Optional[str] = None,
    ) -> List[dict]:
        user_id = requesting_user_id or context_id
        messages = [{"role": "system", "content": system_prompt}]

        from model_context import packing_char_budgets

        try:
            selected = self.get_user_model(int(user_id)) if isinstance(user_id, int) else "auto"
        except Exception:
            selected = "auto"
        document_budget, history_budget, recent_budget = packing_char_budgets(selected)

        if conv_id and isinstance(user_id, int):
            conv = self.conversation_view(int(user_id), str(conv_id))
        else:
            conv = self.get_active_conversation(user_id) if isinstance(user_id, int) else None
        shared = bool(conv and self.is_shared(conv.id))
        recent_user_messages: List[str] = []
        for message in (conv.messages if conv else []):
            if message.role != "user":
                continue
            text = (message.content or "").strip()
            if not text:
                continue
            name = str((message.attachment or {}).get("name") or "").strip()
            if message.attachment and text == name:
                continue
            recent_user_messages.append(text)
        current_query = recent_user_messages[-1] if recent_user_messages else ""
        force_filenames: set[str] = set()
        if conv:
            last_assistant = max(
                (index for index, message in enumerate(conv.messages) if message.role == "assistant"),
                default=-1,
            )
            for message in conv.messages[last_assistant + 1 :]:
                attachment = message.attachment or {}
                name = str(attachment.get("name") or "").strip()
                if not name:
                    continue
                kind = str(attachment.get("type") or "")
                mime = str(attachment.get("mime_type") or "")
                if kind == "image" or mime.startswith("image/"):
                    continue
                force_filenames.add(name)
        docs = build_document_contexts(
            self.get_documents(int(user_id), conv_id=conv.id if conv else None) if isinstance(user_id, int) else [],
            current_query,
            max_chars=document_budget,
            force_filenames=force_filenames,
        )
        edit_notes = self._editor_edit_notes(conv.id) if conv else {}
        for doc in docs:
            # Имя файла – первой строкой: по ней его находят сжатие контекста и поиск.
            note = edit_notes.get(doc["filename"])
            header = f"Пользователь предоставил документ для контекста: {doc['filename']}"
            if note:
                header += f"\n{note}"
            messages.append({
                "role": "system",
                "content": f"{header}\n\nСодержание:\n{doc['content']}\n\nИспользуй эту информацию при ответе.",
            })
        if edit_notes:
            messages.append({
                "role": "system",
                "content": (
                    "Файлы этой беседы правили в редакторе: " + ", ".join(f"«{name}»" for name in edit_notes) + ". "
                    "Работай с их текущей версией выше. Если в истории переписки цитировался или обсуждался "
                    "прежний текст, он мог устареть: сверяйся с документом, а не с репликами. "
                    "Новый файл по такому документу собирай из текущей версии."
                ),
            })
        if docs:
            messages.append({
                "role": "system",
                "content": (
                    "Файлы пользователя уже загружены в этот чат. "
                    "Запрещено просить прислать их повторно."
                ),
            })

        if shared:
            messages.append({
                "role": "system",
                "content": (
                    "Это общий диалог нескольких людей с ассистентом. "
                    "Реплики людей помечены именем в начале. Отвечай на последнее сообщение, "
                    "учитывая общую историю и файлы этой беседы. "
                    "Личные заметки и настройки отдельных участников сюда не входят."
                ),
            })
        elif isinstance(user_id, int):
            from app.memory import memory_system_message

            mem_msg = memory_system_message(self.get_user_memory(user_id))
            if mem_msg:
                messages.append(mem_msg)

        active_prompt = None if shared else (self.get_active_custom_prompt(user_id) if isinstance(user_id, int) else None)
        if active_prompt:
            messages.append({"role": "system", "content": active_prompt})

        if conv:
            speaker_names: Dict[int, str] = {}
            if shared:
                author_ids = [m.author_user_id for m in conv.messages if m.author_user_id]
                owner_id = self.conversation_owner(conv.id)
                if owner_id:
                    author_ids.append(owner_id)
                speaker_names = {
                    bot_id: card["name"] for bot_id, card in self.author_cards(author_ids).items()
                }
            for msg in pack_chat_history(
                conv.messages,
                current_query,
                max_chars=history_budget,
                recent_chars=recent_budget,
            ):
                content = self._clean_text(msg.content)
                if shared and msg.role == "user":
                    speaker_id = msg.author_user_id or self.conversation_owner(conv.id)
                    label = speaker_names.get(speaker_id or 0) or "Участник"
                    content = f"{label}: {content}"
                messages.append({"role": msg.role, "content": content})
            image_parts = self._image_parts_for_conversation(conv, current_query)
            if not image_parts:
                leftover = [
                    str((message.attachment or {}).get("name") or "изображение")
                    for message in conv.messages
                    if self._is_image_attachment(message.attachment)
                ]
                if leftover:
                    names = ", ".join(dict.fromkeys(leftover))
                    messages.append({
                        "role": "system",
                        "content": (
                            f"В чате есть изображения: {names}. "
                            "Они не подмешаны в этот ход. Открой их, только если вопрос про фото."
                        ),
                    })
            self._attach_images_to_last_user(messages, image_parts)

        return messages

    def _clean_text(self, text: str) -> str:
        return text.replace("\x00", "")


conversation_manager = DatabaseConversationManager()
