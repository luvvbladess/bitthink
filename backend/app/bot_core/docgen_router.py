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
            if "не подмешан" in content:
                continue  # каталожная заглушка, а не реальный текст документа
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


def _parse_outline_response(response_text: str) -> List[Section]:
    cleaned = (response_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    sections: List[Section] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        complexity = item.get("complexity") if item.get("complexity") in ("simple", "complex") else "simple"
        sections.append(Section(
            id=i,
            title=str(item["title"])[:200],
            brief=str(item.get("brief", ""))[:500],
            complexity=complexity,
        ))
    return sections[:MAX_SECTIONS]


async def _plan_outline(user_text: str, chunks: List[Chunk], user_id: int) -> List[Section]:
    if chunks:
        catalog = "\n".join(f"{c.id}: {c.title}" for c in chunks[:2000])
    else:
        catalog = "(исходники не найдены — опирайся только на запрос пользователя)"

    prompt = (
        "Построй план большого документа по запросу пользователя.\n"
        "Верни СТРОГО JSON-массив объектов без markdown-обёрток и без пояснений. "
        "Формат каждого элемента: "
        '{"title": "Название раздела", "brief": "Что должно быть в разделе, 1-3 предложения", '
        '"complexity": "simple" | "complex"}.\n'
        "complexity=complex — для расчётов, таблиц с цифрами, юридических формулировок, "
        "технических требований с точными значениями. Остальное — simple.\n\n"
        f"Запрос пользователя:\n{user_text}\n\n"
        f"Заголовки доступных фрагментов исходников (id: заголовок):\n{catalog}"
    )
    messages = [
        {"role": "system", "content": "Ты планировщик документов. Отвечаешь только валидным JSON-массивом."},
        {"role": "user", "content": prompt},
    ]
    try:
        response_text, _, _, _ = await get_chat_response(
            messages, model=PLANNER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
        )
        sections = _parse_outline_response(response_text)
        if sections:
            return sections
    except Exception as e:
        logger.error(f"docgen outline planning failed: {e}", exc_info=True)
    return [Section(id=0, title="Документ", brief=user_text[:500], complexity="complex")]


async def _write_section(section: Section, chunks: List[Chunk], previous_tail: str, user_id: int) -> str:
    relevant = _select_relevant_chunks(section.title, section.brief, chunks)
    context_block = _build_context_block(relevant, MAX_CHUNK_CHARS_PER_SECTION)

    prompt_parts = [f"Раздел документа: {section.title}", f"Задача раздела: {section.brief}"]
    if context_block:
        prompt_parts.append(f"Релевантные фрагменты исходников:\n{context_block}")
    if previous_tail:
        prompt_parts.append(
            "Конец предыдущего раздела (для согласованности терминов и стиля, не повторяй "
            f"его содержание):\n{previous_tail}"
        )
    prompt_parts.append(
        "Напиши текст ТОЛЬКО этого раздела в Markdown, без заголовка раздела (его добавят "
        "отдельно), без вступлений вида «в этом разделе» и без итоговых выводов в конце. "
        "Не выдумывай цифры и факты, которых нет в исходниках или в задаче раздела."
    )
    prompt = "\n\n".join(prompt_parts)

    messages = [
        {"role": "system", "content": "Ты технический писатель. Пишешь один раздел документа, по существу, без воды."},
        {"role": "user", "content": prompt},
    ]

    try:
        if section.complexity == "complex":
            if DEEPSEEK_API_KEY:
                from deepseek_client import get_deepseek_response
                text, _, _, _ = await asyncio.wait_for(
                    get_deepseek_response(
                        messages, model="deepseek-v4-pro", user_id=user_id, use_tools=False,
                    ),
                    timeout=120,
                )
            else:
                text, _, _, _ = await asyncio.wait_for(
                    get_chat_response(
                        messages, model=ESCALATED_WRITER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
                    ),
                    timeout=120,
                )
        else:
            text, _, _, _ = await asyncio.wait_for(
                get_chat_response(
                    messages, model=DEFAULT_WRITER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
                ),
                timeout=120,
            )
        return text.strip()
    except Exception as e:
        logger.error(f"docgen section '{section.title}' failed: {e}")
        return f"[Не удалось сгенерировать раздел: {str(e)[:200]}]"


async def _update_status(status_msg: Any, text: str) -> None:
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"Failed to edit docgen status message: {e}")


async def get_docgen_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    from app.billing.quota import billing_pool

    token = billing_pool.set("computer")
    try:
        return await _run_docgen(messages, user_text, user_id, status_msg)
    finally:
        billing_pool.reset(token)


async def _run_docgen(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Режим Документы: план -> параллельная генерация разделов -> сборка в .docx."""
    await _update_status(status_msg, "📄 Читаю исходники и строю план документа...")
    chunks = _extract_source_chunks(messages)
    no_sources = not chunks
    outline = await _plan_outline(user_text, chunks, user_id)

    total = len(outline)
    plan_status = f"📄 План готов: {total} раздел(ов). Пишу текст..."
    if no_sources:
        plan_status += " Исходники не найдены — пишу по одному промпту."
    await _update_status(status_msg, plan_status)

    section_texts: List[str] = [""] * total
    previous_tail = ""
    done = 0
    for batch_start in range(0, total, MAX_PARALLEL_SECTIONS):
        batch = outline[batch_start:batch_start + MAX_PARALLEL_SECTIONS]
        jobs = [_write_section(section, chunks, previous_tail, user_id) for section in batch]
        results = await asyncio.gather(*jobs)
        for offset, text in enumerate(results):
            section_texts[batch_start + offset] = text
        if results and results[-1]:
            previous_tail = results[-1][-500:]
        done += len(batch)
        await _update_status(status_msg, f"📄 Раздел {done} из {total}...")

    await _update_status(status_msg, "📄 Собираю итоговый .docx...")
    full_markdown = "\n\n".join(
        f"## {section.title}\n\n{text}" for section, text in zip(outline, section_texts)
    )

    from docx_generator import convert_markdown_to_docx
    try:
        docx_bytes = await asyncio.to_thread(convert_markdown_to_docx, full_markdown)
    except Exception as e:
        logger.error(f"docgen docx assembly failed: {e}", exc_info=True)
        return f"Не удалось собрать документ: {str(e)[:200]}", [], "", []

    summary = f"Готово. Документ из {total} раздел(ов) собран в .docx — файл во вложении."
    if no_sources:
        summary += " Исходники не найдены — документ написан по одному промпту."
    files = [{"filename": "Документ.docx", "bytes": docx_bytes}]
    return summary, files, "", []
