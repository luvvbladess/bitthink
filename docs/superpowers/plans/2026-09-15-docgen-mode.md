# Docgen Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new chat mode ("docgen") that turns a prompt plus attached source documents (including .zip archives) into a single large .docx, written section-by-section by a cheap model with cost escalation only where needed.

**Architecture:** A new `docgen_router.py` module (same shape as the existing `hybrid_router.py`/`director_router.py`) extracts page-granular chunks from already-attached documents, has one strong-model call build a section outline, then writes every section in parallel batches with a cheap model (escalating per-section on a `complexity` flag), and assembles everything into one `.docx` via the existing `docx_generator.convert_markdown_to_docx`. The mode is wired into the existing chat dispatcher, bypassing the two context-reduction passes (`reduce_heavy_context`, `fit_for_mode`) that would otherwise summarize or truncate exactly the source detail docgen needs. Archive upload reuses the existing single-file upload endpoint and per-format parser.

**Tech Stack:** Python 3 / FastAPI backend (`backend/app/bot_core`, `backend/app/api`), existing OpenAI/DeepSeek client wrappers, `python-docx` via `docx_generator.py`, React/TypeScript frontend (`frontend/src`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-15-docgen-mode-design.md`

**Status:** Tasks 1-8 implemented, individually reviewed, and merged into branch `docgen-mode`. A final whole-branch review found 2 Critical + 5 Important cross-task integration issues (billing pool, zip decompression bomb, catalog-stub contamination, zip force-open matching, missing per-section timeout, undeletable archive documents, misleading frontend cost chip); all 7 were fixed in one consolidated fix-wave commit `8cf6143`. That review also surfaced a genuine plan/spec gap ("thousands of pages" of *source* material cannot reach docgen through the existing message-packing pipeline, which caps around ~500 pages) — this was parked, not silently patched. **Task 9 below is the follow-up that resolves that gap**, per direct user guidance during the final-review discussion.

## Global Constraints

(unchanged from original 8 tasks — see below for Task 9's own constraints)

- No new third-party dependencies.
- Output is `.docx` only, produced via the existing `docx_generator.convert_markdown_to_docx` — do not modify that function.
- Default writer model is the cheapest available (`gpt-5.6-luna`); escalate per-section only when the outline marks a section `complexity: "complex"`.
- A single failed section must not abort the whole document — it becomes a visibly marked placeholder in the output.
- Follow existing repo conventions exactly: bare module imports inside `backend/app/bot_core`, tests import `from app.config import get_settings  # noqa: F401` first.

---

## Task 9: Read the full document base directly, template-aware outline, higher extraction ceiling for docgen uploads

Resolves the "thousands of pages of *source*" gap the final review found. Three coordinated changes, one task (they only make sense together — reading the full document base is useless if extraction already truncated it, and template-awareness needs the full-base read to see a template's complete structure).

**User's framing (verbatim intent, translated):** docgen should work like Pilot/Director — it should be handed the whole document base and be able to draw on it at any point, not just what's packed into the current turn's chat context; it just needs a bigger allowance. It must also be able to tell which attached document is a *template* (structure/formatting basis for the output) versus which are *knowledge base* (content sources, not structure) — the user may say so explicitly in their prompt, and the system should also auto-detect this from filenames when the user doesn't say so, with the user's explicit words always taking priority over the auto-detected guess.

### Change A — read documents directly from storage, not from packed chat messages

**Why:** `conversation_manager.get_documents(user_id)` (used by Director's own `read_chat_document` tool, see `backend/app/bot_core/computer_tools.py:775`) returns the full stored text of every document in the active conversation — it is a raw DB read, unrelated to `db_conversations.build_document_contexts`'s packing budget (~1M chars total, 40k-chars-per-document cliff once multiple docs are open) that caps what reaches the LLM through the normal "документ для контекста" system messages. Reading via `get_documents` instead of parsing `messages` removes that ceiling, and — as a side effect — also makes the catalog-stub contamination fix from the final review's fix-wave moot for docgen specifically, since raw DB documents are never replaced by a `_catalog_stub`.

**File:** `backend/app/bot_core/docgen_router.py`

- Replace `_extract_source_chunks(messages: List[Dict[str, Any]]) -> List[Chunk]` with `_extract_source_chunks(user_id: int) -> List[Chunk]`:
  ```python
  def _extract_source_chunks(user_id: int) -> List[Chunk]:
      from conversations import conversation_manager

      docs = conversation_manager.get_documents(int(user_id))
      chunks: List[Chunk] = []
      for doc in docs:
          name = str(doc.get("filename") or "документ")
          body = str(doc.get("content") or "")
          if not body:
              continue
          chunks.extend(_split_into_chunks(name, body, len(chunks)))
      return chunks
  ```
- Remove `_extract_document_context` (no longer called by anything — it was only used to build the `messages`-derived blob for the old path, including the "не подмешан" stub-exclusion added in the fix-wave; that exclusion is now unnecessary because raw `get_documents()` content is never a stub).
- Update `_run_docgen`/`get_docgen_response` (whichever currently calls `_extract_source_chunks(messages)`) to call `_extract_source_chunks(user_id)` instead, and drop the now-unused `messages` parameter from both functions' signatures.
- **Update the one call site** in `backend/app/bot_core/handlers/core.py`'s `if model == "docgen":` branch: `return await get_docgen_response(user_text, user_id, status_msg)` (drop the `messages` argument).
- Update `backend/scripts/selfcheck_map_reduce.py`-style manual smoke checks / the Task 6 smoke-check pattern if still referenced anywhere as a committed script (it wasn't committed per Task 6's report, so nothing to update there) — not required, just don't leave a stale reference.

### Change B — template-aware outline, with auto-detection as a fallback hint

**Why:** the user names the template explicitly in their prompt most of the time ("сделай по шаблону X.docx"), but the system should also guess from filenames when they don't, without ever overriding an explicit instruction.

**File:** `backend/app/bot_core/docgen_router.py`, function `_plan_outline`

1. Add a cheap, no-LLM filename heuristic (mirrors the existing `_STYLE_NAME`/`_BRIEF_NAME` pattern already used for the same kind of role-classification in `backend/app/bot_core/studio/briefing.py`, adapted with document-template vocabulary instead of visual-design vocabulary):
   ```python
   _TEMPLATE_NAME_RE = re.compile(r"(?i)(шаблон|образец|форма|бланк|пример|template|form|sample)")


   def _classify_documents_hint(chunks: List[Chunk]) -> str:
       """Дешёвая подсказка планировщику по именам файлов —
       что похоже на шаблон оформления, а что на базу знаний. Планировщик
       вправе проигнорировать её, если пользователь в запросе явно называет
       другой файл шаблоном — это только эвристика на случай, когда
       пользователь не сказал прямо."""
       seen: List[str] = []
       for c in chunks:
           if c.doc_name not in seen:
               seen.append(c.doc_name)
       template_like = [n for n in seen if _TEMPLATE_NAME_RE.search(n)]
       if not template_like:
           return ""
       knowledge_like = [n for n in seen if n not in template_like]
       return (
           f"По именам файлов похоже на шаблон оформления: {', '.join(template_like)}. "
           f"Остальное похоже на базу знаний: {', '.join(knowledge_like) or '(нет других файлов)'}. "
           "Это только подсказка по имени файла — если пользователь в запросе прямо называет "
           "другой файл шаблоном, доверяй запросу, а не этой подсказке."
       )
   ```
2. Add a per-document preview catalog (distinct from the existing per-chunk `id: title` catalog): for each unique `doc_name` in `chunks`, the first ~1500 characters of that document's text (concatenate its chunks in order until the budget is hit). This lets the planner actually recognize a template's structure/heading list, which usually appears near the top of the file, without needing a separate document-structure-extraction pipeline — the planner model is capable enough to infer structure from a plain-text preview.
   ```python
   def _document_previews(chunks: List[Chunk], budget_per_doc: int = 1500) -> str:
       order: List[str] = []
       bodies: Dict[str, str] = {}
       for c in chunks:
           if c.doc_name not in bodies:
               order.append(c.doc_name)
               bodies[c.doc_name] = ""
           if len(bodies[c.doc_name]) < budget_per_doc:
               bodies[c.doc_name] += c.text
       return "\n\n".join(
           f"--- {name} (начало файла) ---\n{bodies[name][:budget_per_doc]}" for name in order
       )
   ```
3. In `_plan_outline`'s prompt, add both the classification hint (if non-empty) and the document previews, with an explicit instruction:
   ```
   Если запрос пользователя или подсказка ниже указывают, что один из документов — шаблон
   оформления (пример структуры для итогового документа), построй список разделов, максимально
   повторяя структуру (заголовки, их порядок) этого документа, а не придумывай новую. Слова
   пользователя в запросе всегда важнее подсказки по имени файла. Если ни то ни другое не
   указывает на шаблон, построй план свободно по сути запроса и остальных материалов.

   {classification_hint}

   Начало каждого документа (для распознавания шаблона):
   {document_previews}
   ```
   (fold into the existing prompt string next to the existing chunk-id catalog — don't replace the existing catalog, which retrieval still needs).

### Change C — higher extraction ceiling specifically for docgen uploads

**Why:** `document_parser.py`'s `MAX_PDF_PAGES = 40` / `MAX_EXTRACT_CHARS = 180_000` apply at upload time, before storage — Change A's "read the full base" is moot for any single file already truncated to 40 pages when it was uploaded. Raising this globally would affect every mode's per-turn context cost; scope it to uploads made while docgen is the active mode.

**Files:**
- `backend/app/bot_core/document_parser.py`: add
  ```python
  MAX_PDF_PAGES_EXTENDED = 200
  MAX_EXTRACT_CHARS_EXTENDED = 800_000
  ```
  next to the existing `MAX_PDF_PAGES`/`MAX_EXTRACT_CHARS`. Thread an `extended_limits: bool = False` parameter through `extract_text_from_file` → `extract_text_from_pdf` (and the plain-text/`extract_text_from_docx` char-cap check, which also uses `MAX_EXTRACT_CHARS`), selecting the `_EXTENDED` constants when `True`. Read each function's current body first — this is a parameter threaded through existing control flow, not a rewrite.
- `backend/app/api/documents.py`, `upload_document`: determine `extended_limits = (await repo.get_user_model(user_id)) == "docgen"` (same `repo.get_user_model` already used in `backend/app/api/models_router.py`'s `list_models`) and pass it to `extract_text_from_file(...)`. Apply the same to the `.zip` branch's per-entry `extract_text_from_file` calls inside `extract_zip_archive` — thread `extended_limits` through that function's signature too, from `documents.py`'s call site down to each inner `extract_text_from_file(data, name, user_id=user_id, extended_limits=extended_limits)` call.

### Testing

- Pure functions get plain `assert`-based tests, no LLM mocking, appended to `backend/tests/test_docgen.py`:
  - `_classify_documents_hint`: a chunk list with one filename matching `_TEMPLATE_NAME_RE` (e.g. `"шаблон_итт.docx"`) and one that doesn't (e.g. `"данные.xlsx"`) produces a non-empty hint naming both correctly; a chunk list with no template-like name returns `""`.
  - `_document_previews`: chunks from two different `doc_name`s produce two labeled preview blocks, each capped at `budget_per_doc`.
  - `_extract_source_chunks(user_id)` needs a way to test without a real DB — if `conversation_manager.get_documents` can't be exercised cheaply in a unit test, this one function is allowed to go untested at the unit level (covered by the Task 6-style manual smoke check instead), consistent with how `_plan_outline`/`_write_section` (which also touch external systems) have no dedicated unit test either.
- Manual smoke check (not committed, same throwaway pattern as Task 6): monkeypatch `conversation_manager.get_documents` to return a small fixture with one "шаблон"-named doc and one plain doc, monkeypatch `get_chat_response`, and confirm the outline call's prompt actually contains both the hint and the previews.

### Self-review checklist for whoever implements this

- `messages` parameter removal: confirm no other function in `docgen_router.py` still expects it, and the one call site in `handlers/core.py` is updated to match.
- `extended_limits` threading: confirm it reaches the *innermost* extraction functions (PDF page loop, plain-text char cap) and not just the outer dispatcher — a parameter that's accepted but not actually used anywhere downstream is a silent no-op bug.
- The classification hint must never be presented as more authoritative than the user's own words — re-read the prompt wording in Change B, item 3, and preserve that priority ordering exactly.
