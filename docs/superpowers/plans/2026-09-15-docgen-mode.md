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

**Status:** Task 9 implemented, reviewed (both named risks independently verified), merged. Fix-wave-1 (commit `8cf6143`) also got its scoped re-review — all 6 findings ADDRESSED, no new breakage. The whole plan (Tasks 1-9 + fix-wave-1) was merged to `main` (commit `e363aa0`, fast-forward, branch `docgen-mode` deleted). **Task 10 below is a further refinement**, requested by the user after reviewing the merged result: template-vs-knowledge role currently only shapes the *outline* (Change B, above) — it was never threaded into per-*section* retrieval, so `_write_section` presents template and knowledge content to the writer model as one undifferentiated pool. Task 10 closes that gap.

---

## Task 10: Carry the template/knowledge distinction into per-section writing

**Why:** `_plan_outline` already determines (via the planner LLM, respecting the user's explicit words over the filename heuristic) which attached document, if any, is the structural template — but that determination is currently used only to shape the outline's section list, then discarded. `_write_section`'s own retrieval (`_select_relevant_chunks` → `_build_context_block`) treats all chunks as one undifferentiated pool regardless of which document they came from, so the writer model never gets an explicit "this is formatting reference" vs "this is a content fact" signal for the fragments it's given. Fix: make `_plan_outline` return which document it identified as the template (not just the section list), and thread that identifier into every `_write_section` call so the same, single determination (not a second, independently-computed one) labels retrieved content by role.

**File:** `backend/app/bot_core/docgen_router.py` (all changes in this one file; only the current bodies of `_parse_outline_response`, `_plan_outline`, `_build_context_block`, `_write_section`, `_run_docgen` change — nothing else does)

### Change 1 — `_parse_outline_response` returns `(sections, template_document)`

Current signature: `def _parse_outline_response(response_text: str) -> List[Section]:`, parsing a bare JSON array.

New signature: `def _parse_outline_response(response_text: str) -> Tuple[List[Section], Optional[str]]:`, parsing a JSON **object** shaped `{"template_document": "имя_файла.docx" | null, "sections": [...]}` instead of a bare array (the `sections` array's own item shape is unchanged — still `{"title", "brief", "complexity"}` per item).

```python
def _parse_outline_response(response_text: str) -> Tuple[List[Section], Optional[str]]:
    cleaned = (response_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        return [], None
    if not isinstance(raw, dict):
        return [], None
    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list):
        return [], None
    sections: List[Section] = []
    for i, item in enumerate(raw_sections):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        complexity = item.get("complexity") if item.get("complexity") in ("simple", "complex") else "simple"
        sections.append(Section(
            id=i,
            title=str(item["title"])[:200],
            brief=str(item.get("brief", ""))[:500],
            complexity=complexity,
        ))
    template_document = raw.get("template_document")
    template_document = template_document.strip() if isinstance(template_document, str) and template_document.strip() else None
    return sections[:MAX_SECTIONS], template_document
```

Add `Optional` to the existing `from typing import Any, Dict, List, Tuple` import line (becomes `from typing import Any, Dict, List, Optional, Tuple`).

### Change 2 — `_plan_outline` asks for and returns `template_document`

New signature: `async def _plan_outline(user_text: str, chunks: List[Chunk], user_id: int) -> Tuple[List[Section], Optional[str]]:`

Update the prompt's format instruction and priority-ordering paragraph (replacing the current "Если запрос пользователя или подсказка..." paragraph) to ask for the new object shape and name the field explicitly:

```python
    prompt = (
        "Построй план большого документа по запросу пользователя.\n"
        "Верни СТРОГО JSON-объект без markdown-обёрток и без пояснений, в формате:\n"
        '{"template_document": "точное имя файла из списка ниже" | null, '
        '"sections": [{"title": "Название раздела", "brief": "Что должно быть в разделе, 1-3 предложения", '
        '"complexity": "simple" | "complex"}, ...]}.\n'
        "complexity=complex — для расчётов, таблиц с цифрами, юридических формулировок, "
        "технических требований с точными значениями. Остальное — simple.\n\n"
        f"Запрос пользователя:\n{user_text}\n\n"
        f"Заголовки доступных фрагментов исходников (id: заголовок):\n{catalog}\n\n"
        "template_document — точное имя одного из документов ниже, ТОЛЬКО если запрос пользователя\n"
        "или подсказка ниже указывают, что этот документ — шаблон оформления (пример структуры для\n"
        "итогового документа). Слова пользователя в запросе всегда важнее подсказки по имени файла.\n"
        "Если ни то ни другое не указывает на шаблон, верни template_document: null. Если\n"
        "template_document задан, построй список разделов, максимально повторяя структуру (заголовки,\n"
        "их порядок) этого документа, а не придумывай новую; иначе строй план свободно по сути запроса\n"
        "и остальных материалов.\n\n"
        f"{classification_hint}\n\n"
        f"Начало каждого документа (для распознавания шаблона):\n{document_previews}"
    )
```

(Same variable references — `catalog`, `classification_hint`, `document_previews` — as the current function already builds; only the prompt's instruction text and requested JSON shape change.)

Update the system message too: `"Ты планировщик документов. Отвечаешь только валидным JSON-объектом."` (was "JSON-массивом").

Update the try/except body:
```python
    try:
        response_text, _, _, _ = await get_chat_response(
            messages, model=PLANNER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
        )
        sections, template_document = _parse_outline_response(response_text)
        if sections:
            return sections, template_document
    except Exception as e:
        logger.error(f"docgen outline planning failed: {e}", exc_info=True)
    return [Section(id=0, title="Документ", brief=user_text[:500], complexity="complex")], None
```

### Change 3 — `_build_context_block` labels template vs knowledge content when a template is known

New signature: `def _build_context_block(chunks: List[Chunk], budget: int, template_name: Optional[str] = None) -> str:`

Extract the current function's body into a small helper `_join_labeled` (identical logic, just renamed so it can be reused for both the template and knowledge halves), then have `_build_context_block` split by `chunk.doc_name == template_name` when `template_name` is given, labeling each non-empty half; falls back to the old unlabeled single-block behavior when `template_name` is `None` (preserves the existing default-call behavior exactly — this is what keeps the plan's already-committed `test_build_context_block_respects_char_budget` test passing unchanged, since it calls `_build_context_block(chunks, budget=8000)` with no third argument):

```python
def _join_labeled(chunks: List[Chunk], budget: int) -> str:
    parts = []
    remaining = budget
    for chunk in chunks:
        if remaining <= 0:
            break
        piece = chunk.text[:remaining]
        parts.append(f"[{chunk.doc_name}] {piece}")
        remaining -= len(piece)
    return "\n\n".join(parts)


def _build_context_block(chunks: List[Chunk], budget: int, template_name: Optional[str] = None) -> str:
    if not chunks:
        return ""
    if not template_name:
        return _join_labeled(chunks, budget)
    template_chunks = [c for c in chunks if c.doc_name == template_name]
    knowledge_chunks = [c for c in chunks if c.doc_name != template_name]
    if not knowledge_chunks:
        return f"Формат по шаблону:\n{_join_labeled(template_chunks, budget)}"
    if not template_chunks:
        return f"Факты из базы знаний:\n{_join_labeled(knowledge_chunks, budget)}"
    half = budget // 2
    template_block = _join_labeled(template_chunks, half)
    knowledge_block = _join_labeled(knowledge_chunks, budget - len(template_block))
    return f"Формат по шаблону:\n{template_block}\n\nФакты из базы знаний:\n{knowledge_block}"
```

### Change 4 — thread `template_document` through `_write_section` and `_run_docgen`

`_write_section` gains one optional parameter, used only to pass through to `_build_context_block`:

```python
async def _write_section(
    section: Section, chunks: List[Chunk], previous_tail: str, user_id: int,
    template_document: Optional[str] = None,
) -> str:
    relevant = _select_relevant_chunks(section.title, section.brief, chunks)
    context_block = _build_context_block(relevant, MAX_CHUNK_CHARS_PER_SECTION, template_document)
    ...  # rest of the function body is unchanged
```

In `_run_docgen`, update the outline call site and the per-batch job list:

```python
    outline, template_document = await _plan_outline(user_text, chunks, user_id)
    ...
    jobs = [
        _write_section(section, chunks, previous_tail, user_id, template_document)
        for section in batch
    ]
```

(Everything else in `_run_docgen` — status updates, batching loop, markdown assembly, docx conversion — is unchanged.)

### Testing

Update the existing outline-parsing tests in `backend/tests/test_docgen.py` (they currently assert against a bare-array response and a `List[Section]` return value — both need updating for the new object-shaped response and `Tuple[List[Section], Optional[str]]` return):

- `test_parse_outline_response_extracts_sections_from_fenced_json`: change the fixture's fenced JSON from an array to `{"template_document": null, "sections": [...]}` (or omit the key entirely — both must work), unpack `sections, template = _parse_outline_response(response)`, assert on `sections` as before plus `template is None`.
- `test_parse_outline_response_returns_empty_on_garbage`: `assert _parse_outline_response("не json вообще") == ([], None)`.
- `test_parse_outline_response_defaults_unknown_complexity_to_simple` / `test_parse_outline_response_skips_items_without_title`: wrap their fixture JSON in `{"sections": [...]}` and unpack the tuple return.
- Add one new test: a fixture with `"template_document": "шаблон.docx"` set produces `template == "шаблон.docx"` from the unpacked tuple.

Add tests for `_build_context_block`'s new labeling behavior:
- `test_build_context_block_labels_template_and_knowledge_when_both_present`: chunks from two different `doc_name`s, `template_name` set to one of them — result contains both "Формат по шаблону:" and "Факты из базы знаний:" labels, each followed by content from the correct chunk's `doc_name`.
- `test_build_context_block_falls_back_when_template_name_missing_from_chunks`: `template_name` set to a filename that doesn't match any chunk's `doc_name` — result is a single "Факты из базы знаний:" block containing all chunks (the `not template_chunks` branch), not an error.
- The existing `test_build_context_block_respects_char_budget` test is unchanged (still calls with 2 positional args) and must still pass — confirms the no-template-name default path is untouched.

No test is needed for `_plan_outline`'s prompt-string changes or `_write_section`'s new parameter itself (same reasoning as the rest of this plan: these touch a live LLM call and aren't unit-testable without mocking, which this plan avoids) — covered by a manual smoke check instead: extend the Task 6/9-style throwaway monkeypatch script so the fake planner response includes `"template_document"` and confirm the fake writer's received prompt contains the "Формат по шаблону:"/"Факты из базы знаний:" labels when the fixture has a matching document.

### Self-review checklist

- Every one of the 4 changes stays inside `docgen_router.py` — no other file should appear in this task's diff.
- `_parse_outline_response`'s new return shape (`Tuple[List[Section], Optional[str]]`) and `_plan_outline`'s matching new return shape must agree exactly — a mismatch here is a silent `ValueError: not enough values to unpack` the first time `_run_docgen` calls `_plan_outline`.
- The existing `test_build_context_block_respects_char_budget` test must still pass unmodified — if it needed changing, something about backward compatibility broke.
- Re-confirm the priority-ordering rule (user's words in the prompt beat the filename heuristic) survives in the rewritten prompt text from Change 2 — this was flagged as the single most important thing to get right in Task 9 and applies here too.

**Status:** Task 10 merged. A follow-up verification pass then measured the mode end to end and found it could not reach the promised scale, plus six defects (fixed in `9aa627c`, `6aa3e08`, `77764df`). Measurements from that pass, which Tasks 11-12 build on:

| Stage, at 5000+ pages | Cost | Where it runs |
|---|---|---|
| Loading a 48 MB / 24k-page document base into chunks | 11 s, 178 MB RAM | already off-loop |
| Assembling 10 MB of markdown into .docx | 92 s, 189 MB RAM, linear | already off-loop |
| Per-section retrieval over a 24k-chunk corpus | **37 ms/section — 126 s cumulative, ~740 ms per batch of 20** | **on the event loop** |
| `MAX_SECTIONS = 400` × ~3000 chars/section | **~600 pages — 10x short of the requirement** | — |

Volume comes from the *number* of sections, not their length: 3400 sections × 3000 chars ≈ 5100 pages. So no page target is added to the writer prompt — that would invite padding, which the user explicitly does not want, and cost more per call.

---

## Task 11: Scale the mode up without taking the server down

**User's requirement (verbatim intent):** this tariff is creator-only; drop the limits so the mode can generate huge documents; parallelise the load; the guarantee that matters is that if someone drops in a prompt plus archives of data and templates, the AI definitely finished the work and the user got a finished document; and the server must not die. Carefully.

**File:** `backend/app/bot_core/docgen_router.py`, plus two small gating edits elsewhere.

### Change 1 — docgen becomes creator-only

`backend/app/billing/plans.py`: remove `"docgen"` from `PRO_MODELS` (line 37) and add it to the creator list instead:
```python
PRO_MODELS = CHEAP_MODELS + ["director", "studio"]
...
CREATOR_MODELS = list(ULTRA_MODELS) + ["docgen"]
```
Leave `clamp_model`'s existing `docgen` fallback branch alone — it now fires for every non-creator tier, which is the intent.

Creator is `unlimited: True`, so `assert_can_use` (`app/billing/quota.py:297`) and `apply_token_debit` (`:130`) both return early — quota windows stop applying to docgen by construction. Nothing else needs "limits removed".

`frontend/src/components/ModelSelector.tsx`: the `lockedHint` ternary currently groups `docgen` with `studio`/`computer` as "Нужен Pro". Give docgen its own branch reading `'Нужен Creator'`.

### Change 2 — raise the volume ceiling

`MAX_SECTIONS: 400 → 5000`. Not unlimited by explicit decision: a planner that returns 50 000 sections would otherwise start a run lasting days. 5000 sections ≈ 7500 pages, which covers the 5–7 thousand requirement with margin. Keep a comment explaining why the number exists.

### Change 3 — parallelise, and get retrieval off the event loop

- `MAX_PARALLEL_SECTIONS: 5 → 12`. Keep the existing batch structure (it preserves `previous_tail` continuity and makes progress reporting natural) rather than switching to a global semaphore; the cost is that each batch waits for its slowest member, which is an acceptable trade at this size. State the trade-off in a comment so the next reader doesn't "fix" it blindly.
- In `_write_section`, move the two synchronous CPU steps off the loop:
  ```python
  context_block = await asyncio.to_thread(
      _section_context, section, chunks, template_document
  )
  ```
  with a small sync helper that does what the two lines do today:
  ```python
  def _section_context(
      section: Section, chunks: List[Chunk], template_document: Optional[str]
  ) -> str:
      relevant = _select_relevant_chunks(section.title, section.brief, chunks)
      return _build_context_block(relevant, MAX_CHUNK_CHARS_PER_SECTION, template_document)
  ```
  Measured reason: 37 ms × 12 concurrent writers is ~440 ms of event-loop blocking per batch, repeated for hours, which stalls every other request in the process.

### Change 4 — retry each section, because the guarantee is the point

At thousands of calls, transient failures (429, provider timeout, dropped connection) are certain, and today a single one turns into a permanent `[Не удалось сгенерировать раздел: …]` hole. Wrap the model call in a bounded retry:

```python
SECTION_ATTEMPTS = 3
SECTION_RETRY_DELAYS = (2, 8)  # seconds before attempts 2 and 3
```

Restructure `_write_section` so the existing model-dispatch block (the `complexity`-based if/else with its `asyncio.wait_for(..., timeout=120)` calls) is attempted up to `SECTION_ATTEMPTS` times, sleeping `SECTION_RETRY_DELAYS[attempt - 1]` between attempts, and only the last failure produces the placeholder. Log every retry at warning level with the section title and attempt number, so a run that succeeded only after retries is still visible in the logs. Do not retry forever and do not add jitter or further backoff — this is a bulk job, not a latency-sensitive path.

`asyncio.CancelledError` must NOT be retried or swallowed: it is how the user's stop button reaches a running job (`generation_hub.hub.cancel`). Today the bare `except Exception` already lets it through, since `CancelledError` derives from `BaseException`; keep that property — if you catch anything broader while adding retries, the stop button silently stops working.

### Testing

Extend `backend/scripts/selfcheck_docgen.py`:
- A scenario where the fake model fails a section's first attempt and succeeds on the second: assert the section's text is real content, not a placeholder, and that the summary reports no failed sections. This is the guarantee the user asked for, so it gets a check.
- A scenario where every attempt fails: assert the placeholder appears, the summary counts it, and `SECTION_ATTEMPTS` calls were made for that section (i.e. retries really happened, not just one try).
- Keep every existing scenario passing.

Unit tests: `MAX_SECTIONS` is asserted nowhere today; no new pytest is required for constants. Give `_section_context` one plain assert-based test in `backend/tests/test_docgen.py` (same conventions as the rest) since it is a pure function.

### Self-review checklist

- `CancelledError` still propagates out of `_write_section` — verify by reading the except clauses, and say so in the report.
- The retry loop cannot retry a non-transient error forever: confirm it ends after `SECTION_ATTEMPTS` regardless of the exception type.
- `frontend/src/components/ModelSelector.tsx` still type-checks (`npx tsc --noEmit`).
- No other tier gained or lost a mode by accident: grep `PRO_MODELS`/`CREATOR_MODELS` consumers after the edit.

---

## Task 12: Confirm with the user before burning thousands of calls

**User's requirement (verbatim intent):** maybe the AI should ask the user for confirmation before starting — is this really what you want, is this really the knowledge base, are these the templates — so tokens aren't burned for nothing.

Reuses the existing clarify machinery rather than inventing a flow: a mode returns its questions in the `search` slot via `clarify.pack_search`, the frontend renders them as chips (`frontend/src/features/chat/clarify.ts`), and the user's choice comes back as an ordinary user message starting `"Уточнения по задаче:"`, which `clarify.is_clarify_reply` detects. `studio_router.py:82` already uses the same idiom. Constraints of that machinery: **at most 3 questions, 2–6 options each, ≤160 chars per prompt, ≤80 per option** (`clarify.py:10-14`) — exceed them and the question is silently dropped.

**Files:** `backend/app/bot_core/docgen_router.py`, and the one call site in `backend/app/bot_core/handlers/core.py`.

### Change 1 — two-phase entry

`get_docgen_response` regains a `messages` parameter (dropped in Task 9) — needed *only* to recover the original request on the second turn, never for document text, which still comes from `conversation_manager.get_documents`. Signature becomes:

```python
async def get_docgen_response(
    messages: List[Dict[str, Any]], user_text: str, user_id: int, status_msg: Any
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
```

Update the call site in `handlers/core.py`'s `if model == "docgen":` branch to pass `messages` again.

Inside, split on the reply:
```python
from clarify import is_clarify_reply

if not is_clarify_reply(user_text):
    return await _confirm_before_generating(user_text, user_id, status_msg)
return await _run_docgen(...)
```
Both phases stay inside the `billing_pool.set("computer")` wrapper.

### Change 2 — phase one: plan, then ask

`_confirm_before_generating(user_text, user_id, status_msg)`:
1. Load the base and plan exactly as `_run_docgen` does today (one planner call — cheap next to thousands of writer calls, and it buys precise numbers instead of a blind question).
2. Compose a plain-text answer stating what was found: number of sections, estimated pages (`sections × 3000 / 2000`, stated as approximate), which file was identified as the formatting template (or that none was), and the knowledge-base files. Include the truncated-source warning if `_extract_source_chunks` reported any, and the planner-failure warning if planning fell back.
3. Return `(text, [], "", pack_search(questions))` with these questions, worded within the char limits:
   - `"Начинать генерацию? Разделов: N, примерно P страниц"` → options `["Да, начинай", "Нет, отменить"]`
   - `"Шаблон оформления определён верно?"` → options `["Да", "Шаблона нет, всё это база знаний", "Нет, шаблон другой файл"]` — only when a template was identified; skip this question entirely otherwise (a question about nothing wastes the user's attention).
4. Generate nothing in this phase.

Define the option labels as module constants (`_CONFIRM_START`, `_CONFIRM_CANCEL`, …) — phase two detects the user's choice by matching these strings in the reply text, so a literal typed twice would silently break the detection.

### Change 3 — phase two: honour the answers

When `is_clarify_reply(user_text)`:
1. Recover the original request: the last message in `messages` with `role == "user"` whose text is not itself a clarify reply. Fall back to `user_text` if none is found (a conversation that starts with a clarify reply shouldn't crash).
2. If the reply contains `_CONFIRM_CANCEL`, return a short "Отменил, ничего не генерировал." with no files — before loading anything.
3. Otherwise run the existing pipeline, and pass the reply text into `_plan_outline` as an extra instruction block (e.g. appended to the prompt as `"Уточнения пользователя: …"`), so answers like "шаблон другой файл" actually change the plan. Asking a question and then ignoring the answer is worse than not asking.

### Testing

Extend `backend/scripts/selfcheck_docgen.py`:
- First turn (plain prompt) → asserts: no files returned, the `search` slot unpacks via `clarify.unpack_search` to at least one question, the text names the section count and the template file, and **the fake writer was never called** (that is the whole point — no tokens burned).
- Second turn (`"Уточнения по задаче:\n1. Начинать генерацию? – Да, начинай"`) with the original prompt present in `messages` → asserts a real .docx comes back and the writer ran.
- Cancel turn (`"… – Нет, отменить"`) → asserts no files, no writer calls, and no planner call either.
- Keep every existing scenario passing; they now go through the second-turn path, so they need a clarify-reply `user_text` and a `messages` list.

### Self-review checklist

- Every question respects `clarify.py`'s limits (≤3 questions, 2–6 options, ≤160/≤80 chars) — a violated limit means `normalize_questions` drops the question and the user sees nothing to click.
- The original-request recovery genuinely finds the prompt from before the confirmation, and does not pick up the clarify reply itself.
- Phase one performs exactly one model call (the planner) and zero writer calls.
- The `handlers/core.py` call site matches the new signature — nothing else in the repo calls `get_docgen_response`.

---

## Task 13: Many templates, many archives

**User's requirement (verbatim intent):** there can be many template files, and a whole archive of them; the knowledge base likewise may be not one archive but several.

Two independent blockers, both measured:

1. **The template is a single file by construction.** `template_document: Optional[str]` threads through parsing, planning, the writer prompt and the confirmation (see every hit for `template_document`/`template_name` in `docgen_router.py`). A second template file is simply unrepresentable.
2. **Many files explode the planner prompt.** Measured with 149 files across 5 archives: document previews alone reach **230 801 chars**, plus a 64 059-char chunk catalog — about **300 000 chars ≈ 120 000 tokens** in the one call that is supposed to be cheap. It grows linearly with file count, so a few hundred files would exceed the model's input entirely. `_document_previews` has a per-document budget (1500) but no cap on the number of documents.

Uploading an archive already stores its members as separate documents named `f"{archive}/{inner}"` (see `extract_zip_archive` and the `.zip` branch in `backend/app/api/documents.py`), so "a whole archive of templates" is expressible as a name prefix — no new ingestion work is needed, only the ability to say it.

**Files:** `backend/app/bot_core/docgen_router.py` (all logic), plus its selfcheck and unit tests.

### Change 1 — templates become a set of documents

- `_parse_outline_response`: replace the `template_document` string field with `template_documents`, parsed from a JSON **array** of strings. Accept a bare string too and wrap it in a list (a planner that answers with the old shape must not silently produce "no template"). Return `Tuple[List[Section], List[str]]` — an empty list means "no template", replacing today's `None`.
- Add `_expand_template_names(names: List[str], chunks: List[Chunk]) -> set[str]`: every returned name that exactly matches a document name selects that document; a name that matches an *archive prefix* (i.e. some document name starts with `f"{name}/"`) selects every member of that archive. Unknown names are dropped. Returns the resolved set of document names. This is what lets the planner answer `"shablony.zip"` instead of enumerating 50 files, and it is also the safety net when it enumerates names that do not exist.
- `_plan_outline`: ask for `"template_documents": ["точное имя файла или имя архива", …]` (empty array when there is no template), keep the existing priority rule verbatim — the user's own words outrank the filename hint — and add one line telling the planner it may name a whole archive instead of listing its files. Return the expanded set.
- `_build_context_block(chunks, budget, template_names: set[str] | None)`: membership test becomes `c.doc_name in template_names` instead of `== template_name`. The "Формат по шаблону:" / "Факты из базы знаний:" split, the half-budget rule and the single-sided fallbacks are unchanged in behaviour.
- `_section_context` and `_write_section` thread the set through; `_run_docgen` passes it to every `_write_section` call.

### Change 2 — bound the planner's context

Add module constants with the measured reason in a comment:
```python
PLANNER_PREVIEW_BUDGET = 60_000   # total chars of document previews
PLANNER_CATALOG_CHUNKS = 400      # chunk titles shown, was an unbounded 2000
```
- `_document_previews(chunks, budget_per_doc=1500)` gains a total budget: the per-document share becomes `max(300, min(budget_per_doc, PLANNER_PREVIEW_BUDGET // max(1, number_of_documents)))`. With 149 files that is ~400 chars each — still enough to recognise a template's heading block, and the whole block stays inside the budget instead of reaching 230k chars.
- Group the previews and the name list **by archive prefix** (the part before the first `/`, or the bare name when there is none), so the planner sees `shablony.zip: 25 файлов` structure rather than 149 flat names. Keep it compact — this replaces, not supplements, the flat list.
- Cap the chunk catalog at `PLANNER_CATALOG_CHUNKS`. It exists only as a hint about available material; the planner's output never references chunk ids, so a bounded sample is sufficient.
- After the change, re-measure the same 149-file fixture and put the before/after char counts in the report.

### Change 3 — the confirmation must survive many files

`clarify.py`'s limits are silent: a prompt over 160 chars or an option over 80 is dropped, leaving the user nothing to click. With dozens of templates, naming them in a chip prompt would do exactly that.

- Keep the chip prompts short and count-based: `"Шаблоны определены верно? Файлов: N"`, options unchanged (`_TEMPLATE_CONFIRMED` / `_TEMPLATE_NONE` / `_TEMPLATE_WRONG`).
- Put the detail in the message **text**, which has no limit: list the template files grouped by archive, and the knowledge-base files the same way, truncating each group's member list after a handful with `… и ещё N` so a 200-file base stays readable.
- The existing start/cancel question and the fail-safe gate from the previous task are unchanged.

### Testing

`backend/tests/test_docgen.py` (pure functions, plain asserts, no LLM):
- `_parse_outline_response` with `"template_documents": ["a.docx", "b.docx"]` → both returned; with a bare string → wrapped into a one-element list; with `[]` or the key missing → empty list.
- `_expand_template_names`: an exact file name selects that file; an archive name selects every `archive/...` member and nothing else; an unknown name is dropped; a name that is both a real file and a prefix of others selects sensibly (state which behaviour you chose in the report).
- `_build_context_block` with a two-element template set spanning two files → both appear under "Формат по шаблону:", knowledge files under "Факты из базы знаний:".
- `_document_previews` with many documents → total length within `PLANNER_PREVIEW_BUDGET`, and every document still represented.

`backend/scripts/selfcheck_docgen.py`:
- A scenario with two template archives and two knowledge archives: the planner fake returns `["shablony_0.zip"]`; assert the writer prompt's "Формат по шаблону:" block cites files from that archive only, that the knowledge block cites the other archives, and that the confirmation text names both groups.
- Every existing scenario keeps passing; update the ones that assert on the old single-template shape.

### Self-review checklist

- No `Optional[str]` template remnant: grep `template_document` and confirm every site moved to the set/list form, including the confirmation text and `_run_docgen`'s call into `_write_section`.
- The planner prompt keeps the priority rule (user's words over the filename hint) word for word.
- Re-measured planner prompt size on the 149-file fixture is reported as a before/after number, not asserted to be "smaller".
- Confirmation questions still survive `clarify.normalize_questions` at large file counts — run them through it with 200 files and include the output.

---

## Task 14: 900-page files, and folders inside archives

**User's requirement (verbatim intent):** the test archive contains files of about 900 pages, and folders nested inside the archive have to be recognised too.

Both are real gaps, and the measurements below were taken on this checkout — use them, do not re-derive.

### Change A — let a big file through, end to end

A 900-page file is cheap to read and currently loses 78% of itself. Measured on a generated 900-page text PDF: **2 292 190 chars extracted in 1.2 s, peak 9 MB RAM**; at today's caps only 509 374 chars survive. Four separate gates cut it, and they must all move together or the file still gets truncated somewhere:

| Gate | Now | New | Why |
|---|---|---|---|
| `MAX_PDF_PAGES_EXTENDED` | 200 | 1200 | 900 pages plus margin |
| `MAX_EXTRACT_CHARS_EXTENDED` | 800 000 | 3 000 000 | 900 pages measured at 2.29M chars |
| `MAX_PDF_BYTES` | 20 MB, flat | add `MAX_PDF_BYTES_EXTENDED = 100 MB` | a big PDF is rejected outright before page limits even apply; this gate is not currently mode-aware, so thread `extended_limits` into the check at `document_parser.py:250` |
| upload size in `documents.py` | 20 MB for both the file and the `.zip` branch | 100 MB when docgen is the active mode | `frontend/nginx.conf:10` already allows `client_max_body_size 100M`, so this needs no infrastructure change — verified |

Also raise, for the extended path only, `MAX_ARCHIVE_ENTRIES` (200 → 2000) and `MAX_ARCHIVE_UNPACKED_BYTES` (200 MB → 1 GB): a knowledge base of many 900-page files hits both. Keep the non-extended values exactly as they are — those guards protect every other mode from zip bombs, and docgen is creator-only.

OCR cost does not scale with this: `MAX_IMAGES_PER_PDF = 8` caps vision calls per PDF regardless of page count. A 900-page *scanned* PDF therefore still yields almost nothing — state that in the report as a known limit rather than pretending otherwise.

### Change B — a total-corpus ceiling, because Change A removes the accidental one

Until now the per-file caps were what kept the corpus small. Measured with the new caps: **50 files × 900 pages = 118 MB of text → 57 500 chunks, 21.8 s, 420 MB RAM**. That is fine; 200 such files would be ~1.7 GB, which is not. Raising the per-file limits without a total ceiling turns "the server must not die" into luck.

Add `MAX_SOURCE_CHARS_TOTAL = 150_000_000` (~150 MB of text, ~530 MB RAM by the measurement above) to `docgen_router.py`. In `_extract_source_chunks`, stop adding documents once the accumulated character count would exceed it, and return the names of the documents that did not fit alongside the truncated ones. `_run_docgen` and `_confirm_before_generating` must name them in their text the same way truncated sources are named — a document silently missing from a 5000-page generation is exactly the kind of failure this mode has been hardened against all along.

### Change C — folders inside an archive are their own group

`_archive_of` (`docgen_router.py`) splits on the **first** `/`, so every folder inside `arhiv.zip` collapses into one group. A user who puts templates in `arhiv.zip/shablony/` and sources in `arhiv.zip/baza/` gives the planner one undifferentiated pile — it cannot name the template folder because it never sees that folders exist. (Extraction itself is fine: `extract_zip_archive` already stores nested members as `arhiv.zip/shablony/formy/forma1.docx` — verified.)

- Group by the **containing folder** instead: everything before the last `/`, or the bare name when there is none. Rename `_archive_of`/`_group_by_archive` to say what they now do (e.g. `_folder_of`/`_group_by_folder`) and update the docstrings — a name that lies about the grouping unit is how this kind of bug survives review.
- `_expand_template_names` already resolves any prefix, so naming a folder works with no change — add a unit test proving `arhiv.zip/shablony` selects exactly that folder's files (including deeper subfolders) and nothing from `arhiv.zip/baza`.
- The planner prompt must say it may name an archive, a folder inside one, or a single file. Keep the priority rule ("Слова пользователя в запросе всегда важнее подсказки по имени файла") word for word.
- The preview/confirmation grouping follows automatically, so the planner now sees `arhiv.zip/shablony: 40 файлов` next to `arhiv.zip/baza: 120 файлов`.

### Testing

`backend/tests/test_docgen.py`: folder grouping (nested paths group by their own folder, bare names still group alone); `_expand_template_names` selecting a folder including its subfolders; the corpus ceiling stopping at the limit and reporting the skipped names.

`backend/scripts/selfcheck_docgen.py`: a scenario with one archive holding two folders — templates in one, knowledge in the other, planner names the folder — asserting the writer's "Формат по шаблону" block cites only that folder and the confirmation names both groups. Keep all existing scenarios passing.

### Self-review checklist

- Every one of the four gates in Change A actually moves for docgen and stays put for other modes — trace `extended_limits` into each, including the `MAX_PDF_BYTES` check that was not previously mode-aware.
- The corpus ceiling reports what it dropped; it must not silently shorten the base.
- Grouping rename left no caller referring to the old names, and no docstring still claiming "part before the first /".
- Re-measure a 900-page PDF end to end through `extract_text_from_file(..., extended_limits=True)` and report the extracted character count — it should be ~2.29M, not ~509k.
