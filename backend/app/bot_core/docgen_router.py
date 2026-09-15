"""
Дешёвый режим генерации больших документов (docgen).
Строит план документа, пишет разделы параллельно дешёвой моделью
с эскалацией по сложности, собирает единый .docx.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from config import DEEPSEEK_API_KEY
from openai_client import get_chat_response

logger = logging.getLogger(__name__)

MAX_SECTIONS = 400
MAX_PARALLEL_SECTIONS = 5
CHUNK_TARGET_CHARS = 3000
TOP_K_CHUNKS = 6
MAX_CHUNK_CHARS_PER_SECTION = 12000

PLANNER_MODEL = "gpt-5.6-terra"
DEFAULT_WRITER_MODEL = "gpt-5.6-luna"
ESCALATED_WRITER_MODEL = "gpt-5.6-terra"

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")
_PAGE_MARKER = re.compile(r"\n---\s*Страница\s+\d+\s*---\n")


@dataclass
class Chunk:
    id: int
    doc_name: str
    title: str
    text: str
    tokens: frozenset = field(default_factory=frozenset)


@dataclass
class Section:
    id: int
    title: str
    brief: str
    complexity: str  # "simple" | "complex"


def _tokenize(text: str) -> set:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _extract_document_context(messages: List[Dict[str, Any]]) -> str:
    """Достаёт системные сообщения с текстом прикреплённых документов — тот же
    приём, что уже использует hybrid_router.py и director_router.py."""
    doc_parts = []
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content", "")
            if "документ для контекста" in content or "предоставил документ" in content:
                doc_parts.append(content)
    return "\n\n".join(doc_parts)


def _split_into_chunks(doc_name: str, text: str, start_id: int) -> List[Chunk]:
    pieces = [p.strip() for p in _PAGE_MARKER.split(text) if p.strip()]
    chunks: List[Chunk] = []
    cid = start_id
    for piece in pieces:
        for i in range(0, len(piece), CHUNK_TARGET_CHARS):
            slice_text = piece[i:i + CHUNK_TARGET_CHARS].strip()
            if not slice_text:
                continue
            title = slice_text.splitlines()[0][:120]
            chunks.append(Chunk(
                id=cid, doc_name=doc_name, title=title, text=slice_text,
                tokens=frozenset(_tokenize(slice_text)),
            ))
            cid += 1
    return chunks


def _extract_source_chunks(messages: List[Dict[str, Any]]) -> List[Chunk]:
    from studio.briefing import iter_attached_docs

    document_context = _extract_document_context(messages)
    docs = iter_attached_docs(document_context)
    chunks: List[Chunk] = []
    for name, body in docs:
        if not body:
            continue
        chunks.extend(_split_into_chunks(name or "документ", body, len(chunks)))
    return chunks


def _select_relevant_chunks(
    section_title: str, section_brief: str, chunks: List[Chunk], top_k: int = TOP_K_CHUNKS
) -> List[Chunk]:
    if not chunks:
        return []
    query_tokens = _tokenize(f"{section_title} {section_brief}")
    if not query_tokens:
        return chunks[:top_k]
    scored = []
    for chunk in chunks:
        overlap = len(query_tokens & chunk.tokens)
        title_overlap = len(query_tokens & _tokenize(chunk.title))
        score = overlap + title_overlap * 3
        if score > 0:
            scored.append((score, chunk))
    if not scored:
        return chunks[:top_k]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def _build_context_block(chunks: List[Chunk], budget: int) -> str:
    parts = []
    remaining = budget
    for chunk in chunks:
        if remaining <= 0:
            break
        piece = chunk.text[:remaining]
        parts.append(f"[{chunk.doc_name}] {piece}")
        remaining -= len(piece)
    return "\n\n".join(parts)
