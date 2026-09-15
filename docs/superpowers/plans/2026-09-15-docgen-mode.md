# Docgen Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new chat mode ("docgen") that turns a prompt plus attached source documents (including .zip archives) into a single large .docx, written section-by-section by a cheap model with cost escalation only where needed.

**Architecture:** A new `docgen_router.py` module (same shape as the existing `hybrid_router.py`/`director_router.py`) extracts page-granular chunks from already-attached documents, has one strong-model call build a section outline, then writes every section in parallel batches with a cheap model (escalating per-section on a `complexity` flag), and assembles everything into one `.docx` via the existing `docx_generator.convert_markdown_to_docx`. The mode is wired into the existing per-mode dispatch in `handlers/core.py`, bypassing the two context-reduction passes (`reduce_heavy_context`, `fit_for_mode`) that would otherwise summarize or truncate exactly the source detail docgen needs. Archive upload reuses the existing single-file upload endpoint and per-format parser.

**Tech Stack:** Python 3 / FastAPI backend (`backend/app/bot_core`, `backend/app/api`), existing OpenAI/DeepSeek client wrappers, `python-docx` via `docx_generator.py`, React/TypeScript frontend (`frontend/src`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-15-docgen-mode-design.md`

## Global Constraints

- No new third-party dependencies (spec: retrieval is pure Python, no embeddings).
- Output is `.docx` only, produced via the existing `docx_generator.convert_markdown_to_docx` — do not modify that function.
- Source documents may be very large; docgen must read the **full, un-reduced** text of attached documents, not a `reduce_heavy_context` summary.
- Default writer model is the cheapest available (`gpt-5.6-luna`); escalate per-section only when the outline marks a section `complexity: "complex"`.
- A single failed section must not abort the whole document — it becomes a visibly marked placeholder in the output.
- Every non-trivial pure function (chunking, retrieval ranking, outline JSON parsing, context-budget clamping) gets a plain `assert`-based pytest test with no LLM mocking — these functions must not call the network.
- Follow existing repo conventions exactly: bare module imports (`from document_parser import ...`, not `from app.bot_core.document_parser import ...`) inside `backend/app/bot_core`, `status_msg.edit_text(text, parse_mode="Markdown")` wrapped in try/except for progress updates, tests import `from app.config import get_settings  # noqa: F401` first to get `bot_core` on `sys.path`.

---

## File Structure

- `backend/app/bot_core/document_parser.py` — **modify**: add `extract_zip_archive`.
- `backend/app/api/documents.py` — **modify**: add a `.zip` branch to `upload_document`.
- `backend/app/bot_core/docgen_router.py` — **create**: the whole docgen pipeline (chunking, retrieval, outline, section writing, orchestration).
- `backend/app/bot_core/handlers/core.py` — **modify**: early-return dispatch to `docgen_router`, add `"docgen"` to the `pool` set.
- `backend/app/bot_core/config.py` — **modify**: register `"docgen"` in `AVAILABLE_MODELS`.
- `backend/app/billing/plans.py` — **modify**: add `"docgen"` to `PRO_MODELS`, add a `clamp_model` fallback branch.
- `backend/app/api/models_router.py` — **modify**: add `"docgen"` to `PUBLIC_MODEL_IDS`, `WEB_MODEL_INFO`, and expose `docgenAvailable`.
- `frontend/src/constants/modes.ts` — **modify**: add `DOCGEN_LABEL`.
- `frontend/src/components/ModelSelector.tsx` — **modify**: add the docgen entry to the mode picker.
- `backend/tests/test_docgen.py` — **create**: pure-function tests for chunking, retrieval ranking, context budgeting, outline parsing.
- `backend/tests/test_document_parser_zip.py` — **create**: test for `extract_zip_archive`.

---

### Task 1: Zip archive extraction in `document_parser.py`

**Files:**
- Modify: `backend/app/bot_core/document_parser.py`
- Test: `backend/tests/test_document_parser_zip.py`

**Interfaces:**
- Consumes: `extract_text_from_file(file_data: bytes, file_name: str, status_callback=None, user_id: int = None) -> Optional[str]` (already exists in this file, line ~488).
- Produces: `async def extract_zip_archive(file_data: bytes, archive_name: str, user_id: int = None) -> list[tuple[str, str]]` — list of `(display_name, extracted_text)`, one per readable file inside the archive. Consumed by Task 2.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_document_parser_zip.py
import asyncio
import io
import zipfile

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from document_parser import extract_zip_archive


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_zip_archive_reads_supported_files_and_skips_junk():
    zip_bytes = _make_zip({
        "spec.txt": "Техническое задание".encode("utf-8"),
        "notes.txt": "Заметки инженера".encode("utf-8"),
        "image.bin": b"\x00\x01\x02",
        "__MACOSX/._spec.txt": b"junk",
        "folder/": b"",
    })

    results = asyncio.run(extract_zip_archive(zip_bytes, "archive.zip", user_id=None))

    names = [name for name, _ in results]
    assert names == ["archive.zip/spec.txt", "archive.zip/notes.txt"]
    assert "Техническое задание" in dict(results)["archive.zip/spec.txt"]


def test_extract_zip_archive_empty_zip_returns_empty_list():
    zip_bytes = _make_zip({})

    results = asyncio.run(extract_zip_archive(zip_bytes, "empty.zip", user_id=None))

    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_document_parser_zip.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_zip_archive'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/bot_core/document_parser.py`, near `extract_text_from_zip_document` (this file already imports `zipfile` and `Path` at the top — no new imports needed):

```python
async def extract_zip_archive(file_data: bytes, archive_name: str, user_id: int = None) -> list[tuple[str, str]]:
    """Разворачивает .zip и извлекает текст из каждого файла внутри через уже
    существующий extract_text_from_file — никакой новой логики парсинга форматов.
    Неподдерживаемые форматы внутри архива молча пропускаются (extract_text_from_file
    вернёт None для них), как и служебные записи macOS/директории.
    """
    def _list_entries() -> list[tuple[str, bytes]]:
        entries = []
        with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                path = Path(info.filename)
                if path.name.startswith(".") or "__MACOSX" in path.parts:
                    continue
                entries.append((info.filename, archive.read(info.filename)))
        return entries

    entries = await asyncio.to_thread(_list_entries)
    results: list[tuple[str, str]] = []
    for name, data in entries:
        text = await extract_text_from_file(data, name, user_id=user_id)
        if text:
            results.append((f"{archive_name}/{name}", text))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_parser_zip.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/bot_core/document_parser.py backend/tests/test_document_parser_zip.py
git commit -m "feat(docgen): extract text from files inside a zip archive"
```

---

### Task 2: Wire `.zip` upload into the documents API

**Files:**
- Modify: `backend/app/api/documents.py:82-148` (`upload_document`)

**Interfaces:**
- Consumes: `extract_zip_archive(file_data, archive_name, user_id) -> list[tuple[str, str]]` (Task 1).
- Produces: nothing new consumed elsewhere — this is a leaf HTTP handler. Manually/integration-tested (see Step 2 below); no new unit test file, since this handler is a thin wrapper around already-tested pieces (`extract_zip_archive`, `repo.add_document`, `repo.add_message`), consistent with how the existing non-zip branch in this same function has no dedicated test.

- [ ] **Step 1: Add the `.zip` branch**

In `backend/app/api/documents.py`, inside `upload_document`, right after `is_image = declared_image or ext in IMAGE_EXTENSIONS` (current line 94) and before the `if not is_image and ext not in DOCUMENT_EXTENSIONS:` rejection (current line 95), insert:

```python
    if ext == ".zip":
        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="Архив слишком большой (максимум 20 МБ). Разбейте на несколько архивов.",
            )
        from document_parser import extract_zip_archive

        bot_user_id = await repo.ensure_user(user_id)
        try:
            documents = await extract_zip_archive(contents, filename, user_id=bot_user_id)
        except MemoryError as exc:
            raise HTTPException(
                status_code=400,
                detail="Архив слишком тяжёлый для разбора.",
            ) from exc
        if not documents:
            raise HTTPException(status_code=400, detail="В архиве не найдено файлов, которые можно прочитать")
        for doc_name, text in documents:
            await repo.add_document(user_id, doc_name, text, conv_id=conversation_id)
        msg = await repo.add_message(
            user_id,
            "user",
            filename,
            conv_id=conversation_id,
            attachment={
                "name": filename,
                "size": len(contents),
                "status": "done",
                "type": "document",
                "note": f"{len(documents)} файлов",
            },
        )
        return {"ok": True, "kind": "archive", "filename": filename, "documents": len(documents), "message": msg}

```

This mirrors the existing non-zip document branch below it (same `repo.add_document` / `repo.add_message` calls), just looping over multiple extracted documents instead of one, and returns early so the normal `DOCUMENT_EXTENSIONS` check never sees `.zip`.

- [ ] **Step 2: Manual smoke check**

Run the backend locally (`uvicorn app.main:app --reload` from `backend/`, or however this project normally starts it) and upload a small `.zip` containing two `.txt` files through the existing document-upload UI/endpoint. Confirm the response has `"kind": "archive"` and `"documents": 2`, and that `GET /documents` afterwards lists two separate document entries.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/documents.py
git commit -m "feat(docgen): accept .zip archives at the document upload endpoint"
```

---

### Task 3: `docgen_router.py` — chunking and keyword retrieval

**Files:**
- Create: `backend/app/bot_core/docgen_router.py`
- Test: `backend/tests/test_docgen.py`

**Interfaces:**
- Consumes: `studio.briefing.iter_attached_docs(document_context: str) -> list[tuple[str, str]]` (existing, `backend/app/bot_core/studio/briefing.py:23`).
- Produces:
  - `@dataclass Chunk(id: int, doc_name: str, title: str, text: str, tokens: frozenset)`
  - `@dataclass Section(id: int, title: str, brief: str, complexity: str)`
  - `_extract_document_context(messages: list[dict]) -> str`
  - `_extract_source_chunks(messages: list[dict]) -> list[Chunk]`
  - `_tokenize(text: str) -> set[str]`
  - `_select_relevant_chunks(section_title: str, section_brief: str, chunks: list[Chunk], top_k: int = TOP_K_CHUNKS) -> list[Chunk]`
  - `_build_context_block(chunks: list[Chunk], budget: int) -> str`

  All of the above are consumed by Task 4 and Task 5.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_docgen.py
from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

from docgen_router import Chunk, _build_context_block, _extract_source_chunks, _select_relevant_chunks


def _doc_message(name: str, body: str) -> dict:
    return {
        "role": "system",
        "content": f"Пользователь предоставил документ для контекста: {name}\n\nСодержание:\n{body}",
    }


def test_extract_source_chunks_splits_on_page_markers():
    pages = "\n\n".join(f"--- Страница {i} ---\nТекст страницы номер {i}." for i in range(1, 6))
    messages = [_doc_message("spec.pdf", pages), {"role": "user", "content": "Сделай документ"}]

    chunks = _extract_source_chunks(messages)

    assert len(chunks) == 5
    assert all(c.doc_name == "spec.pdf" for c in chunks)
    assert "страницы номер 3" in chunks[2].text.lower()


def test_extract_source_chunks_falls_back_to_fixed_size_without_markers():
    body = "слово " * 2000  # long plain text, no page markers
    messages = [_doc_message("plain.txt", body)]

    chunks = _extract_source_chunks(messages)

    assert len(chunks) > 1
    assert all(chunk.doc_name == "plain.txt" for chunk in chunks)


def test_extract_source_chunks_returns_empty_without_documents():
    messages = [{"role": "user", "content": "Просто вопрос"}]

    assert _extract_source_chunks(messages) == []


def test_select_relevant_chunks_ranks_keyword_match_first():
    chunks = [
        Chunk(id=0, doc_name="d", title="Гидравлическая система", text="Давление в гидравлической системе буксира составляет 250 бар.", tokens=frozenset()),
        Chunk(id=1, doc_name="d", title="Штатное расписание", text="В экипаж входят капитан, механик и два матроса.", tokens=frozenset()),
        Chunk(id=2, doc_name="d", title="Электрооборудование", text="Генератор мощностью 500 кВт питает силовую установку.", tokens=frozenset()),
    ]

    selected = _select_relevant_chunks("Гидравлическая система", "Опиши давление в гидравлике буксира", chunks, top_k=2)

    assert selected[0].id == 0


def test_select_relevant_chunks_falls_back_to_first_chunks_when_no_match():
    chunks = [Chunk(id=i, doc_name="d", title=f"Часть {i}", text="нейтральный текст без общих слов", tokens=frozenset()) for i in range(3)]

    selected = _select_relevant_chunks("совершенно другая тема", "ничего общего", chunks, top_k=2)

    assert [c.id for c in selected] == [0, 1]


def test_build_context_block_respects_char_budget():
    chunks = [Chunk(id=i, doc_name="d", title="t", text="x" * 5000, tokens=frozenset()) for i in range(5)]

    block = _build_context_block(chunks, budget=8000)

    # Allow a small, bounded overhead per chunk for the "[doc_name] " label.
    assert len(block) <= 8000 + len(chunks) * 10
```

Note: real callers get `Chunk.tokens` from `_extract_source_chunks` (which precomputes it); `test_select_relevant_chunks_ranks_keyword_match_first` relies on the fallback path inside `_select_relevant_chunks` that also checks `chunk.title` tokens, so it passes even with `tokens=frozenset()` — this is intentional: it proves title-matching alone is enough to rank correctly, independent of body pre-tokenization.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_docgen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docgen_router'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/bot_core/docgen_router.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_docgen.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/bot_core/docgen_router.py backend/tests/test_docgen.py
git commit -m "feat(docgen): chunk attached documents and rank them by keyword overlap"
```

---

### Task 4: `docgen_router.py` — outline planning

**Files:**
- Modify: `backend/app/bot_core/docgen_router.py` (append)
- Test: `backend/tests/test_docgen.py` (append)

**Interfaces:**
- Consumes: `Section` (Task 3), `get_chat_response(messages, model=..., user_id=..., use_tools=False, use_skills=False) -> Tuple[str, list, str, list]` (existing, `openai_client.py:313`).
- Produces: `_parse_outline_response(response_text: str) -> List[Section]`, `async def _plan_outline(user_text: str, chunks: List[Chunk], user_id: int) -> List[Section]`. Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_docgen.py`:

```python
from docgen_router import _parse_outline_response


def test_parse_outline_response_extracts_sections_from_fenced_json():
    response = (
        '```json\n'
        '[{"title": "Введение", "brief": "Общее описание", "complexity": "simple"},'
        ' {"title": "Расчёт нагрузки", "brief": "Числа", "complexity": "complex"}]\n'
        '```'
    )

    sections = _parse_outline_response(response)

    assert [s.title for s in sections] == ["Введение", "Расчёт нагрузки"]
    assert sections[0].complexity == "simple"
    assert sections[1].complexity == "complex"


def test_parse_outline_response_returns_empty_on_garbage():
    assert _parse_outline_response("не json вообще") == []


def test_parse_outline_response_defaults_unknown_complexity_to_simple():
    response = '[{"title": "Раздел", "brief": "текст", "complexity": "нечто странное"}]'

    sections = _parse_outline_response(response)

    assert sections[0].complexity == "simple"


def test_parse_outline_response_skips_items_without_title():
    response = '[{"brief": "нет заголовка"}, {"title": "Есть заголовок", "brief": "ок"}]'

    sections = _parse_outline_response(response)

    assert [s.title for s in sections] == ["Есть заголовок"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_docgen.py -v -k parse_outline`
Expected: FAIL with `ImportError: cannot import name '_parse_outline_response'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/bot_core/docgen_router.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_docgen.py -v`
Expected: PASS (10 tests total so far)

- [ ] **Step 5: Commit**

```bash
git add backend/app/bot_core/docgen_router.py backend/tests/test_docgen.py
git commit -m "feat(docgen): plan a document outline with a single LLM call"
```

---

### Task 5: `docgen_router.py` — section writing

**Files:**
- Modify: `backend/app/bot_core/docgen_router.py` (append)

**Interfaces:**
- Consumes: `Section`, `Chunk`, `_select_relevant_chunks`, `_build_context_block` (Task 3/4), `get_chat_response` (existing), `get_deepseek_response(messages, model="deepseek-v4-pro", user_id=..., use_tools=False) -> Tuple[str, list, str, list]` (existing, `deepseek_client.py:82`).
- Produces: `async def _write_section(section: Section, chunks: List[Chunk], previous_tail: str, user_id: int) -> str`. Consumed by Task 6.

No new pure-testable logic here (the function's only branch point — `complexity`-based model choice — requires a live LLM call to exercise meaningfully), so no new test file; this task is covered end-to-end by Task 6's manual smoke check.

- [ ] **Step 1: Implement `_write_section`**

Append to `backend/app/bot_core/docgen_router.py`:

```python
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
                text, _, _, _ = await get_deepseek_response(
                    messages, model="deepseek-v4-pro", user_id=user_id, use_tools=False,
                )
            else:
                text, _, _, _ = await get_chat_response(
                    messages, model=ESCALATED_WRITER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
                )
        else:
            text, _, _, _ = await get_chat_response(
                messages, model=DEFAULT_WRITER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
            )
        return text.strip()
    except Exception as e:
        logger.error(f"docgen section '{section.title}' failed: {e}")
        return f"[Не удалось сгенерировать раздел: {str(e)[:200]}]"
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

Run: `pytest tests/test_docgen.py -v`
Expected: PASS (unchanged — this task added no new tests, only a new function)

- [ ] **Step 3: Commit**

```bash
git add backend/app/bot_core/docgen_router.py
git commit -m "feat(docgen): write one section with cost-escalating model choice"
```

---

### Task 6: `docgen_router.py` — orchestrator and assembly

**Files:**
- Modify: `backend/app/bot_core/docgen_router.py` (append)

**Interfaces:**
- Consumes: `_extract_source_chunks`, `_plan_outline`, `_write_section` (Tasks 3-5), `docx_generator.convert_markdown_to_docx(markdown_text: str, base_template_bytes: Optional[bytes] = None) -> bytes` (existing, `docx_generator.py:491`, **do not modify**).
- Produces: `async def get_docgen_response(messages: List[Dict[str, Any]], user_text: str, user_id: int, status_msg: Any) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]` — same return contract as `hybrid_router.get_hybrid_response` / `director_router.get_director_response`. Consumed by Task 7.

- [ ] **Step 1: Implement `get_docgen_response`**

Append to `backend/app/bot_core/docgen_router.py`:

```python
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
    """Режим Документы: план -> параллельная генерация разделов -> сборка в .docx."""
    await _update_status(status_msg, "📄 Читаю исходники и строю план документа...")
    chunks = _extract_source_chunks(messages)
    outline = await _plan_outline(user_text, chunks, user_id)

    total = len(outline)
    await _update_status(status_msg, f"📄 План готов: {total} раздел(ов). Пишу текст...")

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
    files = [{"filename": "Документ.docx", "bytes": docx_bytes}]
    return summary, files, "", []
```

- [ ] **Step 2: Manual smoke check with a fake LLM**

This mirrors the existing `backend/scripts/selfcheck_map_reduce.py` pattern (monkeypatch `get_chat_response` to a no-op echo, no real API keys needed). Create a throwaway script (not committed) or run interactively:

```python
import asyncio, sys
sys.path.insert(0, "backend/app/bot_core")
sys.path.insert(0, "backend")
import docgen_router as dg

async def fake_get_chat_response(messages, model=None, user_id=None, use_tools=False, use_skills=True, **kw):
    if model == dg.PLANNER_MODEL:
        return '[{"title": "Раздел 1", "brief": "первая часть", "complexity": "simple"}, {"title": "Раздел 2", "brief": "вторая часть", "complexity": "simple"}]', [], "", []
    return f"Текст для {messages[-1]['content'][:30]}", [], "", []

dg.get_chat_response = fake_get_chat_response

async def main():
    messages = [{"role": "system", "content": "Пользователь предоставил документ для контекста: x.txt\n\nСодержание:\nПривет мир"}]
    summary, files, _, _ = await dg.get_docgen_response(messages, "Собери документ", user_id=1, status_msg=None)
    print(summary)
    assert files and files[0]["filename"] == "Документ.docx"
    assert len(files[0]["bytes"]) > 0
    print("OK")

asyncio.run(main())
```

Expected output: `Готово. Документ из 2 раздел(ов)...` followed by `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/bot_core/docgen_router.py
git commit -m "feat(docgen): orchestrate outline, parallel section writing and docx assembly"
```

---

### Task 7: Wire the "docgen" mode into dispatch, billing and the models API

**Files:**
- Modify: `backend/app/bot_core/config.py:36-49` (`AVAILABLE_MODELS`)
- Modify: `backend/app/billing/plans.py:37` (`PRO_MODELS`) and `:174-192` (`clamp_model`)
- Modify: `backend/app/bot_core/handlers/core.py:231-278` (`get_smart_response`)
- Modify: `backend/app/api/models_router.py:12-29` (`WEB_MODEL_INFO`, `PUBLIC_MODEL_IDS`) and `:74-96` (`list_models` response)

**Interfaces:**
- Consumes: `docgen_router.get_docgen_response` (Task 6).
- Produces: `model == "docgen"` becomes a valid, selectable, quota-gated chat mode reachable end-to-end from `POST /models/select`.

- [ ] **Step 1: Register the model id**

In `backend/app/bot_core/config.py`, in `AVAILABLE_MODELS` (after the `"studio"` entry, current line 40):

```python
    "docgen": "📄 Документы — большие .docx по промпту и файлам",
```

- [ ] **Step 2: Add billing/tier wiring**

In `backend/app/billing/plans.py`, line 37:

```python
PRO_MODELS = CHEAP_MODELS + ["director", "studio", "docgen"]
```

In `clamp_model` (same file), after the existing `if model == "studio" and "studio" not in allowed:` branch (current lines 188-189):

```python
    if model == "docgen" and "docgen" not in allowed:
        return "gpt-5.6-luna" if "gpt-5.6-luna" in allowed else "gpt-5-nano"
```

- [ ] **Step 3: Dispatch in `get_smart_response`, bypassing context reduction**

In `backend/app/bot_core/handlers/core.py`:

Change the `pool` line (current line 248):

```python
    pool = "computer" if model in {"director", "studio", "docgen"} else "chat"
```

Then, right after the existing empty-`user_text` fallback block and *before* the `messages = await reduce_heavy_context(...)` call (current lines 274-278), insert an early return:

```python
    if not user_text:
        logger.warning(f"Empty user_text in get_smart_response for user {user_id}")
        user_text = "Проанализируй предоставленные документы."

    if model == "docgen":
        # Работает по полному, не сжатому тексту исходников через собственный
        # отбор релевантных фрагментов — reduce_heavy_context/fit_for_mode
        # иначе обрежут или пересожмут именно те детали, ради которых и
        # существует этот режим.
        from docgen_router import get_docgen_response

        return await get_docgen_response(messages, user_text, user_id, status_msg)

    messages = await reduce_heavy_context(messages, user_text, status_msg, user_id=user_id, model=model)
```

(The `if not user_text:` block already exists — only the new `if model == "docgen":` block below it is added.)

- [ ] **Step 4: Expose it in the models API**

In `backend/app/api/models_router.py`, `WEB_MODEL_INFO` (after the `"studio"` entry, current line 16):

```python
    "docgen": {"name": "Документы", "description": "Большой .docx по промпту и вашим файлам"},
```

`PUBLIC_MODEL_IDS` (current line 29):

```python
PUBLIC_MODEL_IDS = ["auto", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra", "director", "studio", "docgen"]
```

In `list_models`, add a `docgenAvailable` flag next to the existing `studioAvailable`/`computerAvailable` (current lines 92-93):

```python
        "computerAvailable": "director" in allowed,
        "studioAvailable": "studio" in allowed,
        "docgenAvailable": "docgen" in allowed,
        "astraAvailable": "gpt-6-astra" in allowed,
```

- [ ] **Step 5: Run the existing test suite**

Run (from `backend/`): `pytest -q`
Expected: PASS, no regressions (this task only adds branches keyed on a brand-new model id string, so no existing test's behavior changes).

- [ ] **Step 6: Commit**

```bash
git add backend/app/bot_core/config.py backend/app/billing/plans.py backend/app/bot_core/handlers/core.py backend/app/api/models_router.py
git commit -m "feat(docgen): register the docgen mode across dispatch, billing and the models API"
```

---

### Task 8: Frontend — expose "Документы" in the mode picker

**Files:**
- Modify: `frontend/src/constants/modes.ts`
- Modify: `frontend/src/components/ModelSelector.tsx`

**Interfaces:**
- Consumes: `data.docgenAvailable` from `GET /models` (Task 7).
- Produces: a new selectable entry in the existing mode picker; no new exported interface (leaf UI change).

- [ ] **Step 1: Add the label constant**

In `frontend/src/constants/modes.ts`, append:

```typescript
/** Docgen mode: turns a prompt + attached files into one large .docx. */
export const DOCGEN_LABEL = 'Документы';
```

- [ ] **Step 2: Add the mode entry and availability wiring**

In `frontend/src/components/ModelSelector.tsx`:

Import the new icon and label (line 3 and line 8):

```typescript
import { CaretDown, Check, Sparkle, MagnifyingGlass, Books, Desktop, Presentation, Atom, FileText } from '@phosphor-icons/react';
```
```typescript
import { ASTRA_LABEL, PILOT_LABEL, STUDIO_LABEL, DOCGEN_LABEL } from '@/constants/modes';
```

Add `docgenAvailable` to the `ModelsCache` interface (after `studioAvailable`, current line 27):

```typescript
  studioAvailable?: boolean;
  docgenAvailable?: boolean;
```

Add an entry to `ANSWER_MODES` (after the `studio` entry, current line 37):

```typescript
  { id: 'studio', label: STUDIO_LABEL, description: 'Живой холст: картинки, слайды, лендинг', model: 'studio', icon: Presentation },
  { id: 'docgen', label: DOCGEN_LABEL, description: 'Большой документ .docx по промпту и вашим файлам', model: 'docgen', icon: FileText },
```

In `SearchModeSelector`, read the new flag next to the existing ones (after `const studioAvailable = ...`, current line 103):

```typescript
  const studioAvailable = Boolean(data?.studioAvailable);
  const docgenAvailable = Boolean(data?.docgenAvailable);
```

Add it to the `available` computation (after the `studio` clause, current line 188):

```typescript
              (mode.id === 'studio' && studioAvailable) ||
              (mode.id === 'docgen' && docgenAvailable) ||
              (mode.id === 'computer' && computerAvailable);
```

Add it to the `factor` (multiplier) ternary chain (after the `studio` clause, current lines 198-199):

```typescript
                    : mode.id === 'studio'
                      ? multipliers['studio']
                      : mode.id === 'docgen'
                        ? multipliers['gpt-5.6-luna']
                        : mode.id === 'auto'
```

Add it to the `lockedHint` clause (current line 204), grouping it with `studio`/`computer` (same tier requirement):

```typescript
            const lockedHint =
              mode.id === 'astra' ? 'Нужен Ultra' : mode.id === 'studio' || mode.id === 'computer' || mode.id === 'docgen' ? 'Нужен Pro' : 'Нужен Pro+';
```

- [ ] **Step 3: Manual check**

Run the frontend dev server, open the mode picker, and confirm a "Документы" entry with a file icon appears alongside "Пилот"/"Студия", is disabled on a tier without it, and calls `POST /models/select` with `{"model": "docgen"}` when clicked (selecting it should make the composer chip show "Документы").

- [ ] **Step 4: Commit**

```bash
git add frontend/src/constants/modes.ts frontend/src/components/ModelSelector.tsx
git commit -m "feat(docgen): add Документы entry to the chat mode picker"
```

---

## Self-Review Notes

- **Spec coverage:** zip ingestion (Task 1-2), chunking/retrieval (Task 3), outline (Task 4), section writing with cost escalation (Task 5), orchestration + docx assembly + progress status (Task 6), reachability/billing (Task 7), UI entry point (Task 8) — every section of the spec has a task.
- **reduce_heavy_context/fit_for_mode bypass:** called out explicitly in Task 7 Step 3 with the reasoning inline, since this was not named in the original spec text but is required for the spec's core "works from full source text" requirement to actually hold once wired into `get_smart_response`.
- **Type/signature consistency:** `Chunk`, `Section`, `_extract_source_chunks`, `_select_relevant_chunks`, `_build_context_block`, `_parse_outline_response`, `_plan_outline`, `_write_section`, `get_docgen_response` are defined once (Tasks 3-6) and referenced with the same names and signatures in every later task.
- **No placeholders:** every step has runnable code, not descriptions of code.
