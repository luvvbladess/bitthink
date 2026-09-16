"""Self-check for the docgen pipeline (режим «Документы»).

Unit tests in tests/test_docgen.py cover the pure helpers (chunking, ranking,
context budgeting, outline parsing). The orchestrator itself — reading the
document base, planning, batching section writers, labelling template vs
knowledge content, assembling the .docx — has no unit coverage because every
step needs an LLM. This script fills that gap: it fakes the model and the
document store, then runs the real get_docgen_response end to end.

It guards, specifically:
  - documents are read from the document base, not from packed chat messages;
  - every model call is billed to the "computer" pool, and the pool is reset
    afterwards (a leak here bills docgen to the chat pool, where debits are
    silently dropped once that pool is exhausted);
  - the writer prompt separates "Формат по шаблону" from "Факты из базы знаний";
  - a failed outline and failed sections are reported to the user instead of
    silently degrading into a one-section document;
  - the result is a real .docx containing the generated text.

get_chat_response / get_deepseek_response / the document store are monkeypatched,
so this runs without API keys, network, or a database.

Run: python scripts/selfcheck_docgen.py
"""
import asyncio
import json
import logging
import os
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "app" / "bot_core"))
sys.path.insert(0, str(BACKEND_DIR))

# openai_client builds its client at import time and refuses to load without a key.
os.environ.setdefault("OPENAI_API_KEY", "sk-selfcheck-dummy")

import clarify  # noqa: E402
import docgen_router as dg  # noqa: E402
from app.billing.quota import billing_pool  # noqa: E402

# Two checks below deliberately fail the model; docgen logs those with a
# traceback, which is correct in production but noise here.
logging.getLogger(dg.__name__).setLevel(logging.CRITICAL)

TEMPLATE_FILE = "шаблон_итт.docx"
KNOWLEDGE_FILE = "данные_буксира.xlsx"

DOCS = [
    {
        "filename": TEMPLATE_FILE,
        "content": (
            "ИСХОДНО-ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ\n"
            "1. Общие положения\n"
            "2. Требования к энергетической установке\n"
        ),
    },
    {
        "filename": KNOWLEDGE_FILE,
        "content": (
            "--- Страница 1 ---\nМощность энергетической установки 2500 кВт.\n\n"
            "--- Страница 2 ---\nТяга на гаке 45 тонн, автономность 20 суток.\n"
        ),
    },
]

PLAN_JSON = (
    '{"template_documents": ["%s"], "sections": ['
    '{"title": "Общие положения", "brief": "Назначение и состав", "complexity": "simple"},'
    '{"title": "Требования к энергетической установке", "brief": "Мощность и тяга",'
    ' "complexity": "complex"}]}' % TEMPLATE_FILE
)

# Multi-archive fixture (Task 13): two archives that look like templates by
# name, two that look like knowledge. The planner only picks one of the two
# template archives, so the other must fall through to the knowledge side —
# this is what exercises _expand_template_names against a real archive prefix
# instead of a single flat file name.
ARCHIVE_TEMPLATE_CHOSEN = "shablony_0.zip"
ARCHIVE_TEMPLATE_OTHER = "shablony_1.zip"
ARCHIVE_KNOWLEDGE_A = "znaniya_0.zip"
ARCHIVE_KNOWLEDGE_B = "znaniya_1.zip"

# Exactly TOP_K_CHUNKS (6) documents total, one chunk each (short, no page
# markers), and a section brief with no keyword overlap with any of them —
# this keeps _select_relevant_chunks' scoring at zero across the board, so it
# falls back to "all chunks" instead of silently dropping some archives from
# the picture (its scored-path returns only positively-scored chunks, which
# would otherwise hide an entire archive from the assertions below).
MULTI_ARCHIVE_DOCS = [
    {"filename": f"{ARCHIVE_TEMPLATE_CHOSEN}/форма1.docx", "content": "Один. Два. Три."},
    {"filename": f"{ARCHIVE_TEMPLATE_CHOSEN}/форма2.docx", "content": "Четыре. Пять. Шесть."},
    {"filename": f"{ARCHIVE_TEMPLATE_OTHER}/форма1.docx", "content": "Семь. Восемь. Девять."},
    {"filename": f"{ARCHIVE_KNOWLEDGE_A}/данные1.xlsx", "content": "Десять. Одиннадцать."},
    {"filename": f"{ARCHIVE_KNOWLEDGE_A}/данные2.xlsx", "content": "Двенадцать. Тринадцать."},
    {"filename": f"{ARCHIVE_KNOWLEDGE_B}/данные1.xlsx", "content": "Четырнадцать. Пятнадцать."},
]
MULTI_ARCHIVE_PROMPT = "Собери документ по материалам из архивов"
MULTI_ARCHIVE_PLAN_JSON = (
    '{"template_documents": ["%s"], "sections": ['
    '{"title": "Общий раздел", "brief": "Обзорный текст без цифр", "complexity": "simple"}]}'
    % ARCHIVE_TEMPLATE_CHOSEN
)

# Task 14: one archive with two folders nested inside it — templates in one,
# knowledge in the other. Before the folder-grouping fix both collapsed into
# a single "arhiv.zip" group and the planner could never name just the
# templates folder. Same zero-overlap trick as MULTI_ARCHIVE_DOCS: none of
# these words share tokens with the section brief, so _select_relevant_chunks
# falls back to "all chunks" instead of hiding a folder from the assertions.
FOLDER_ARCHIVE = "arhiv.zip"
TEMPLATE_FOLDER = f"{FOLDER_ARCHIVE}/shablony"
KNOWLEDGE_FOLDER = f"{FOLDER_ARCHIVE}/baza"
FOLDER_DOCS = [
    {"filename": f"{TEMPLATE_FOLDER}/forma1.docx", "content": "Алеф. Бет. Гимель."},
    {"filename": f"{TEMPLATE_FOLDER}/forma2.docx", "content": "Далет. Хе. Вав."},
    {"filename": f"{KNOWLEDGE_FOLDER}/otchet1.docx", "content": "Зайин. Хет. Тет."},
    {"filename": f"{KNOWLEDGE_FOLDER}/otchet2.docx", "content": "Йод. Каф. Ламед."},
]
FOLDER_PROMPT = "Собери документ по шаблону из папки shablony архива arhiv.zip"
FOLDER_PLAN_JSON = (
    '{"template_documents": ["%s"], "sections": ['
    '{"title": "Общий раздел", "brief": "Обзорный текст без цифр", "complexity": "simple"}]}'
    % TEMPLATE_FOLDER
)

ORIGINAL_PROMPT = f"Сделай ИТТ по шаблону {TEMPLATE_FILE}"
# Built from the module's own option constants, not retyped literals — a
# retyped literal here would defeat the exact point of check_first_turn.
CONFIRM_REPLY_START = f"Уточнения по задаче:\n1. Начинать генерацию? – {dg._CONFIRM_START}"
CONFIRM_REPLY_CANCEL = f"Уточнения по задаче:\n1. Начинать генерацию? – {dg._CONFIRM_CANCEL}"

# Task 15 fixture: the same decimal designation and organisation name repeat
# across two documents, so both must be proposed as replacement candidates.
REPL_DOC_A = "форма1.docx"
REPL_DOC_B = "форма2.docx"
OLD_DESIGNATION = "АБВГ.123456.789"
OLD_ORG = "ООО «Ромашка»"
NEW_DESIGNATION = "ВГДЕ.000001.001"
NEW_ORG = "ООО «Новый Заказчик»"
REPL_DOCS = [
    {"filename": REPL_DOC_A, "content": f"Децимальный номер {OLD_DESIGNATION}. Заказчик {OLD_ORG}."},
    {"filename": REPL_DOC_B, "content": f"См. также {OLD_DESIGNATION}, заказчик — {OLD_ORG}."},
]
REPL_PROMPT = "Сделай документ по образцу форма1.docx"
REPL_PLAN_JSON = (
    '{"template_documents": [], "sections": ['
    '{"title": "Общий раздел", "brief": "Обзор", "complexity": "simple"}]}'
)


def _second_turn(prompt: str = ORIGINAL_PROMPT, reply: str = CONFIRM_REPLY_START):
    """The (messages, user_text) pair get_docgen_response now expects on the
    turn after confirmation. Shaped like the real conversation history
    (original request, then the confirmation question, then the clarify
    reply as the current — already-persisted — last message) so the recovery
    logic is actually exercised skipping the reply, not just handed a
    single-message shortcut."""
    messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": "Разделов: 2, примерно 3 стр. Начинать генерацию?"},
        {"role": "user", "content": reply},
    ]
    return messages, reply


class FakeStatus:
    def __init__(self):
        self.texts = []

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)


def _install_fakes(plan_response: str, writer_fails: bool = False, fail_first_attempt: bool = False):
    """Returns (writer_prompts, pools_seen, attempt_counts); all fill up as the run proceeds.

    writer_fails: every writer call for every section fails (tests that retry
    is bounded and the placeholder still appears).
    fail_first_attempt: each section's first attempt fails, subsequent ones
    succeed (tests that a transient failure is recovered by retry).
    attempt_counts: prompt content -> number of writer calls made for that
    section so far, keyed by content since each section has a distinct prompt.
    """
    writer_prompts: list[str] = []
    pools_seen: list[str] = []
    attempt_counts: dict[str, int] = {}

    async def fake_chat(messages, model=None, user_id=None, use_tools=False, use_skills=True, **kwargs):
        pools_seen.append(billing_pool.get())
        content = messages[-1]["content"]
        if model == dg.PLANNER_MODEL and "Построй план" in content:
            return plan_response, [], "", []
        # Keyed by the prompt's first line ("Раздел документа: <название>") rather
        # than the whole prompt: two differently-titled sections can otherwise only
        # be told apart by their retrieved context, and a same-titled pair would
        # merge their counts and hide a broken retry loop.
        key = content.splitlines()[0]
        attempt_counts[key] = attempt_counts.get(key, 0) + 1
        if writer_fails:
            raise RuntimeError("модель недоступна")
        if fail_first_attempt and attempt_counts[key] == 1:
            raise RuntimeError("модель временно недоступна")
        writer_prompts.append(content)
        return "Текст раздела. Мощность 2500 кВт.", [], "", []

    async def fake_deepseek(messages, model=None, user_id=None, use_tools=False, **kwargs):
        return await fake_chat(messages, model=model, user_id=user_id, use_tools=use_tools)

    import deepseek_client

    dg.get_chat_response = fake_chat
    deepseek_client.get_deepseek_response = fake_deepseek
    return writer_prompts, pools_seen, attempt_counts


def _set_documents(docs):
    from conversations import conversation_manager

    conversation_manager.get_documents = lambda uid: docs


async def check_happy_path():
    _set_documents(DOCS)
    writer_prompts, pools_seen, _ = _install_fakes(PLAN_JSON)
    status = FakeStatus()

    messages, reply = _second_turn()
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, status)

    assert len(files) == 1, f"expected exactly one file, got {files!r}"
    payload = files[0]["bytes"]
    assert files[0]["filename"].endswith(".docx"), files[0]["filename"]
    assert payload[:2] == b"PK", "result is not a real .docx container"

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
    assert "Общие положения" in document_xml, "section heading missing from the .docx"
    assert "2500" in document_xml, "section body missing from the .docx"

    assert set(pools_seen) == {"computer"}, f"docgen billed to the wrong pool: {set(pools_seen)}"
    assert billing_pool.get() == "chat", f"billing pool leaked: {billing_pool.get()}"

    assert len(writer_prompts) == 2, f"expected one writer call per section, got {len(writer_prompts)}"
    labelled = [p for p in writer_prompts if "Формат по шаблону:" in p and "Факты из базы знаний:" in p]
    assert labelled, "no writer prompt separated template from knowledge sources"
    prompt = labelled[0]
    template_at = prompt.index("Формат по шаблону:")
    knowledge_at = prompt.index("Факты из базы знаний:")
    assert template_at < knowledge_at, "template block must come before the knowledge block"
    assert f"[{TEMPLATE_FILE}]" in prompt[template_at:knowledge_at], "template block cites the wrong file"
    assert f"[{KNOWLEDGE_FILE}]" in prompt[knowledge_at:], "knowledge block cites the wrong file"

    assert "2 раздел" in summary, summary
    assert "не найдены" not in summary, summary
    assert any("Раздел" in text and "из" in text for text in status.texts), status.texts
    print("OK: happy path — .docx built, computer pool, template/knowledge split in writer prompt")


async def check_no_sources():
    _set_documents([])
    writer_prompts, _, _ = _install_fakes(PLAN_JSON)

    messages, reply = _second_turn("Напиши регламент")
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "no-sources run must still produce a .docx"
    assert "не найдены" in summary, f"user was not told the sources are missing: {summary}"
    assert writer_prompts and "Релевантные фрагменты" not in writer_prompts[0], writer_prompts[:1]
    print("OK: no sources — document still produced, and the user is told sources were missing")


async def check_planning_failure_is_reported():
    _set_documents(DOCS)
    _install_fakes("это не json")

    messages, reply = _second_turn("Сделай ИТТ")
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "must still produce a .docx on planner failure"
    assert "План разделов построить не удалось" in summary, (
        f"planner fallback was not reported to the user: {summary}"
    )
    print("OK: planner failure — fallback is reported instead of silently shipping one section")


async def check_failed_sections_are_reported():
    _set_documents(DOCS)
    _, _, attempt_counts = _install_fakes(PLAN_JSON, writer_fails=True)

    messages, reply = _second_turn("Сделай ИТТ")
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "must still produce a .docx when sections fail"
    assert "Не удалось сгенерировать разделов: 2 из 2" in summary, (
        f"failed sections were not reported to the user: {summary}"
    )
    assert attempt_counts and all(count == dg.SECTION_ATTEMPTS for count in attempt_counts.values()), (
        f"expected every failing section to be retried exactly SECTION_ATTEMPTS times, got {attempt_counts}"
    )
    print("OK: failed sections — retried SECTION_ATTEMPTS times each, counted and reported, document still assembled")


async def check_section_retry_recovers():
    """A transient failure on attempt 1 must be invisible in the final result:
    real text, no placeholder, no failure counted in the summary — this is the
    'the user definitely got a finished document' guarantee from the brief."""
    _set_documents(DOCS)
    writer_prompts, _, attempt_counts = _install_fakes(PLAN_JSON, fail_first_attempt=True)

    messages, reply = _second_turn("Сделай ИТТ")
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "must still produce a .docx after a retried section"
    assert dg._SECTION_FAILED_PREFIX not in summary, f"a recovered section left a placeholder trace: {summary}"
    assert "Не удалось сгенерировать" not in summary, f"summary wrongly reported a failed section: {summary}"
    assert len(writer_prompts) == 2, f"expected both sections to eventually succeed, got {len(writer_prompts)}"
    assert attempt_counts and all(count == 2 for count in attempt_counts.values()), (
        f"expected exactly 2 attempts (fail once, then succeed) per section, got {attempt_counts}"
    )
    with zipfile.ZipFile(BytesIO(files[0]["bytes"])) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
    assert "2500" in document_xml, "recovered section text is missing from the .docx"
    print("OK: section retry — first-attempt failure recovered silently, real content, no failure reported")


async def check_truncated_sources_are_reported():
    from document_parser import TEXT_TRUNCATED_NOTICE

    _set_documents([
        {"filename": KNOWLEDGE_FILE, "content": "Мощность 2500 кВт." + TEXT_TRUNCATED_NOTICE},
        {"filename": TEMPLATE_FILE, "content": "ИСХОДНО-ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ\n1. Общие положения\n"},
    ])
    _install_fakes(PLAN_JSON)

    messages, reply = _second_turn("Сделай ИТТ")
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK"
    assert "Прочитаны не целиком" in summary, (
        f"a source truncated at upload time was not reported: {summary}"
    )
    assert KNOWLEDGE_FILE in summary, f"the truncated file was not named: {summary}"
    assert TEMPLATE_FILE not in summary.split("Прочитаны не целиком")[1], (
        f"an untruncated file was wrongly reported as truncated: {summary}"
    )
    print("OK: truncated sources — named in the summary, with what to do about it")


async def check_first_turn_asks_and_never_writes():
    """The whole point of phase one: a plain prompt (not a clarify reply) must
    plan and ask, and burn nothing on the writer — thousands of writer calls
    is exactly the cost this confirmation step exists to gate."""
    _set_documents(DOCS)
    writer_prompts, pools_seen, _ = _install_fakes(PLAN_JSON)
    status = FakeStatus()

    text, files, _, search = await dg.get_docgen_response([], ORIGINAL_PROMPT, 777, status)

    assert files == [], f"phase one must generate nothing, got files: {files!r}"
    assert not writer_prompts, "phase one called the writer — it must plan and ask, not generate"
    assert len(pools_seen) == 1, f"phase one must make exactly one model call (the planner), got {pools_seen!r}"
    questions = clarify.unpack_search(search)
    assert questions, f"phase one must return at least one confirmation question, got search={search!r}"
    assert "2" in text, f"section count missing from the confirmation text: {text!r}"
    assert TEMPLATE_FILE in text, f"template file missing from the confirmation text: {text!r}"
    print("OK: first turn — plans and asks for confirmation, writer never called")


async def check_second_turn_generates():
    """A confirmed reply, with the original request recovered from messages,
    must run the real pipeline — asking a question and then not honouring
    'yes' would be worse than not asking."""
    _set_documents(DOCS)
    writer_prompts, _, _ = _install_fakes(PLAN_JSON)
    status = FakeStatus()

    messages, reply = _second_turn()
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, status)

    assert files and files[0]["bytes"][:2] == b"PK", "confirmed second turn must produce a real .docx"
    assert writer_prompts, "confirmed second turn must call the writer"
    print("OK: second turn — confirmation reply generates a real .docx, writer ran")


async def check_cancel_generates_nothing():
    """Cancel must exit before loading or planning anything — not just before
    the writer. pools_seen records every model call (planner included), so an
    empty list here proves get_chat_response was never invoked at all."""
    _set_documents(DOCS)
    writer_prompts, pools_seen, _ = _install_fakes(PLAN_JSON)
    status = FakeStatus()

    messages, reply = _second_turn(reply=CONFIRM_REPLY_CANCEL)
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, status)

    assert files == [], f"cancel must generate nothing, got files: {files!r}"
    assert not writer_prompts, "cancel must not call the writer"
    assert not pools_seen, f"cancel must not call the planner either, got calls: {pools_seen!r}"
    print("OK: cancel — nothing generated, no writer call, no planner call")


async def check_skipped_questions_do_not_start_generation():
    """The clarify card is shared across modes and has a "Пропустить" button
    bound to Enter. Skipping every question sends "Уточнения пропущены…", which
    is a clarify reply carrying neither the start nor the cancel label. Treating
    the absence of cancel as consent would launch thousands of model calls on a
    single accidental keypress, so the gate requires the start label explicitly."""
    _set_documents(DOCS)
    writer_prompts, pools_seen, _ = _install_fakes(PLAN_JSON)

    skip_reply = "Уточнения пропущены. Действуй по здравому смыслу."
    assert clarify.is_clarify_reply(skip_reply), "fixture no longer matches the skip shape clarify.py accepts"
    assert dg._CONFIRM_START not in skip_reply and dg._CONFIRM_CANCEL not in skip_reply

    messages, reply = _second_turn(reply=skip_reply)
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files == [], f"a skipped confirmation must generate nothing, got files: {files!r}"
    assert not writer_prompts, "a skipped confirmation must not call the writer"
    assert not pools_seen, f"a skipped confirmation must not call the planner either, got: {pools_seen!r}"
    assert dg._CONFIRM_START in summary, f"the reply should tell the user which button starts it: {summary}"
    print("OK: skipped questions — no generation, and the user is told which button starts it")


async def check_truncation_marker_on_a_chunk_boundary():
    """The notice is ~60 chars and the chunker slices at a fixed width, so for
    PDFs (whose page labels are stripped before slicing) the marker regularly
    straddles a chunk boundary. Detecting it per-chunk missed ~half of the tail
    lengths tried; detection therefore runs on the whole document text."""
    from document_parser import TEXT_TRUNCATED_NOTICE

    missed = []
    for tail in range(dg.CHUNK_TARGET_CHARS - 120, dg.CHUNK_TARGET_CHARS):
        body = "--- Страница 1 ---\n" + ("я" * tail) + TEXT_TRUNCATED_NOTICE
        _set_documents([{"filename": "том.pdf", "content": body}])
        _, truncated, _ = dg._extract_source_chunks(1)
        if not truncated:
            missed.append(tail)
    assert not missed, f"truncation went undetected for tail lengths {missed[:5]} (+{len(missed)} total)"

    _set_documents([{"filename": "чистый.pdf", "content": "Прочитал первые страницы отчёта и согласовал."}])
    _, truncated, _ = dg._extract_source_chunks(1)
    assert not truncated, "an untruncated document was wrongly reported as truncated"
    print("OK: truncation marker — found on every chunk boundary, no false positive on similar prose")


async def check_multi_archive_templates():
    """Task 13: many template files as a whole archive, and a knowledge base
    spread across several archives. The planner names only one of two
    template-shaped archives; the other archive must fall through to the
    knowledge side rather than vanishing or being wrongly treated as
    template — and the confirmation text (phase one) must name both groups."""
    _set_documents(MULTI_ARCHIVE_DOCS)

    # Phase one: confirmation text must name both the chosen template archive
    # and at least one of the knowledge archives.
    _install_fakes(MULTI_ARCHIVE_PLAN_JSON)
    text, files, _, search = await dg.get_docgen_response([], MULTI_ARCHIVE_PROMPT, 777, FakeStatus())
    assert files == [], "phase one must not generate anything"
    assert ARCHIVE_TEMPLATE_CHOSEN in text, f"chosen template archive missing from confirmation text: {text!r}"
    assert ARCHIVE_KNOWLEDGE_A in text or ARCHIVE_KNOWLEDGE_B in text, (
        f"knowledge archives missing from confirmation text: {text!r}"
    )

    # Phase two: the writer prompt must split template vs knowledge along
    # exactly the resolved archive membership, not the raw planner names.
    writer_prompts, _, _ = _install_fakes(MULTI_ARCHIVE_PLAN_JSON)
    messages, reply = _second_turn(MULTI_ARCHIVE_PROMPT)
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "multi-archive run must still produce a .docx"
    labelled = [p for p in writer_prompts if "Формат по шаблону:" in p and "Факты из базы знаний:" in p]
    assert labelled, "no writer prompt separated template from knowledge sources"
    prompt = labelled[0]
    template_at = prompt.index("Формат по шаблону:")
    knowledge_at = prompt.index("Факты из базы знаний:")
    template_block = prompt[template_at:knowledge_at]
    knowledge_block = prompt[knowledge_at:]

    assert f"[{ARCHIVE_TEMPLATE_CHOSEN}/" in template_block, (
        f"chosen template archive's files missing from the template block: {template_block!r}"
    )
    assert f"{ARCHIVE_TEMPLATE_OTHER}/" not in template_block, (
        f"unselected template-shaped archive leaked into the template block: {template_block!r}"
    )
    assert f"{ARCHIVE_TEMPLATE_OTHER}/" in knowledge_block, (
        f"unselected template-shaped archive did not fall through to the knowledge block: {knowledge_block!r}"
    )
    assert (f"{ARCHIVE_KNOWLEDGE_A}/" in knowledge_block) or (f"{ARCHIVE_KNOWLEDGE_B}/" in knowledge_block), (
        f"knowledge archives missing from the knowledge block: {knowledge_block!r}"
    )
    print("OK: multi-archive templates — only the chosen archive is the template, others fall through to knowledge, confirmation names both groups")


async def check_folder_inside_archive_is_its_own_group():
    """Task 14: a folder nested inside one archive must group on its own —
    naming just "arhiv.zip/shablony" must select that folder's files only,
    and the confirmation must still name both folders, even though they share
    an archive."""
    _set_documents(FOLDER_DOCS)

    # Phase one: confirmation text must name both folders as separate groups.
    _install_fakes(FOLDER_PLAN_JSON)
    text, files, _, search = await dg.get_docgen_response([], FOLDER_PROMPT, 777, FakeStatus())
    assert files == [], "phase one must not generate anything"
    assert TEMPLATE_FOLDER in text, f"template folder missing from confirmation text: {text!r}"
    assert KNOWLEDGE_FOLDER in text, f"knowledge folder missing from confirmation text: {text!r}"

    # Phase two: the writer prompt's "Формат по шаблону" block must cite only
    # the named folder's files, and "Факты из базы знаний" the other folder's.
    writer_prompts, _, _ = _install_fakes(FOLDER_PLAN_JSON)
    messages, reply = _second_turn(FOLDER_PROMPT)
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "folder-templated run must still produce a .docx"
    labelled = [p for p in writer_prompts if "Формат по шаблону:" in p and "Факты из базы знаний:" in p]
    assert labelled, "no writer prompt separated template from knowledge sources"
    prompt = labelled[0]
    template_at = prompt.index("Формат по шаблону:")
    knowledge_at = prompt.index("Факты из базы знаний:")
    template_block = prompt[template_at:knowledge_at]
    knowledge_block = prompt[knowledge_at:]

    assert f"[{TEMPLATE_FOLDER}/" in template_block, (
        f"named folder's files missing from the template block: {template_block!r}"
    )
    assert f"{KNOWLEDGE_FOLDER}/" not in template_block, (
        f"the other folder leaked into the template block: {template_block!r}"
    )
    assert f"{KNOWLEDGE_FOLDER}/" in knowledge_block, (
        f"the other folder did not fall through to the knowledge block: {knowledge_block!r}"
    )
    print("OK: folder inside archive — its own group, planner names the folder, template/knowledge split follows")


async def check_replacement_flow():
    """Task 15 — the whole point of the feature: phase one lists repeating
    requisites as a «было → стало» table; a filled reply (not a clarify chip)
    starts generation with that mapping; and the assembled .docx contains the
    new values and *not* the old ones, on the real .docx bytes.

    The fake writer here always emits the OLD requisites verbatim, regardless
    of what it was given — the worst case, where the model ignores the
    already-replaced context and writes from its own "memory" instead. This
    is exactly why the deterministic final sweep over the assembled markdown
    (not the per-section context replacement alone) is what has to catch it,
    independent of the model.
    """
    _set_documents(REPL_DOCS)

    async def fake_chat(messages, model=None, user_id=None, use_tools=False, use_skills=True, **kwargs):
        content = messages[-1]["content"]
        if model == dg.PLANNER_MODEL and "Построй план" in content:
            return REPL_PLAN_JSON, [], "", []
        if "Вот значения, повторяющиеся" in content:
            values = [v for v in content.split("Значения:\n", 1)[1].splitlines() if v.strip()]
            items = [{"value": v, "label": "Реквизит"} for v in values]
            return json.dumps({"items": items}, ensure_ascii=False), [], "", []
        # Writer call: ignores its prompt entirely and writes the old
        # requisites verbatim — the case the final markdown sweep must cover.
        return f"Текст раздела. Реквизит {OLD_DESIGNATION}, заказчик {OLD_ORG}.", [], "", []

    import deepseek_client

    dg.get_chat_response = fake_chat
    deepseek_client.get_deepseek_response = fake_chat

    text, files, _, search = await dg.get_docgen_response([], REPL_PROMPT, 777, FakeStatus())
    assert files == [], "phase one must not generate anything"
    assert OLD_DESIGNATION in text, f"candidate table missing the decimal designation: {text!r}"
    assert OLD_ORG in text, f"candidate table missing the organisation name: {text!r}"
    assert "→" in text, f"candidate table missing the было->стало arrow: {text!r}"

    reply = (
        f"Децимальный номер: {OLD_DESIGNATION} → {NEW_DESIGNATION}\n"
        f"Организация: {OLD_ORG} → {NEW_ORG}\n"
    )
    # A filled replacement list, not a clarify chip reply — this exercises
    # the second accepted confirmation shape end to end.
    assert not clarify.is_clarify_reply(reply)
    messages = [
        {"role": "user", "content": REPL_PROMPT},
        {"role": "assistant", "content": text},
        {"role": "user", "content": reply},
    ]
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "replacement run must still produce a real .docx"
    with zipfile.ZipFile(BytesIO(files[0]["bytes"])) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
    assert NEW_DESIGNATION in document_xml, "new decimal designation missing from the .docx"
    assert NEW_ORG in document_xml, "new organisation name missing from the .docx"
    assert OLD_DESIGNATION not in document_xml, "old decimal designation survived into the .docx"
    assert OLD_ORG not in document_xml, "old organisation name survived into the .docx"
    assert "Заменено реквизитов: 2" in summary, f"replacement count missing from summary: {summary!r}"
    print(
        "OK: replacement flow — было/стало table shown, filled reply starts generation, "
        "old requisites absent from the real .docx, new ones present"
    )


async def check_thousands_of_pages_are_planned_in_two_levels():
    """Task 16 — the page target the whole mode exists for.

    One planner answer physically cannot hold a plan of thousands of sections
    (a plan entry is ~85 tokens, the output cap is 128 000), so a request for
    5000 pages used to end in truncated JSON and a silent fallback to one
    section. Here the first turn must really produce thousands of sections via
    chapters, and a smaller request must really assemble a .docx whose chapter
    headings survive into the document.
    """
    _set_documents(DOCS)
    chapter_calls: list[str] = []
    expand_calls: list[str] = []

    def _plan_of(count: int, prefix: str) -> str:
        items = [
            {"title": f"{prefix} {i}", "brief": f"Содержание {prefix.lower()} {i}",
             "complexity": "simple"}
            for i in range(count)
        ]
        return json.dumps({"template_documents": [TEMPLATE_FILE], "sections": items},
                          ensure_ascii=False)

    async def fake_chat(messages, model=None, user_id=None, use_tools=False, use_skills=True, **kwargs):
        content = messages[-1]["content"]
        if "Построй план" in content:
            chapter_calls.append(content)
            # Obey the requested chapter count the way a real planner would.
            asked = int(re.search(r"верни ровно (\d+) глав", content).group(1))
            return _plan_of(asked, "Глава"), [], "", []
        if "Распиши одну главу" in content:
            expand_calls.append(content)
            asked = int(re.search(r"примерно (\d+) раздел", content).group(1))
            return _plan_of(asked, "Раздел"), [], "", []
        return "Текст раздела.", [], "", []

    import deepseek_client
    dg.get_chat_response = fake_chat
    deepseek_client.get_deepseek_response = fake_chat

    text, files, _, _ = await dg.get_docgen_response(
        [], "Сделай документацию на 5000 страниц", 777, FakeStatus()
    )
    assert files == [], "phase one must not generate anything"
    assert chapter_calls, "two-level planning never asked for chapters"
    planned = int(re.search(r"Разделов: (\d+)", text).group(1))
    assert planned >= 3000, f"5000 pages must plan thousands of sections, got {planned}"
    pages = int(re.search(r"примерно (\d+) стр", text).group(1))
    assert pages >= 4500, f"planned page count fell short of the request: {pages}"
    cost = float(re.search(r"не больше \$([\d.]+)", text).group(1))
    assert 0 < cost < 100, f"cost estimate must be shown and under $100, got ${cost}"

    # Smaller request, run end to end: chapters must reach the real .docx.
    chapter_calls.clear()
    messages, reply = _second_turn(prompt="Сделай документацию на 300 страниц")
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())
    assert chapter_calls, "the generating turn must plan in two levels as well"
    assert files and files[0]["bytes"][:2] == b"PK", "two-level run must produce a real .docx"
    with zipfile.ZipFile(BytesIO(files[0]["bytes"])) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
    assert "Глава 0" in document_xml, "chapter heading missing from the assembled .docx"
    assert "Раздел 0" in document_xml, "section heading missing from the assembled .docx"
    print(
        f"OK: thousands of pages — 5000 стр. -> {planned} разделов через главы, "
        f"оценка ${cost:.2f}, главы дошли до .docx"
    )


async def check_api_error_text_is_not_written_into_the_document():
    """Model clients do not raise on an API error — they return it as ordinary
    text, in two shapes: an «❌ …» banner, and the bare placeholder "Нет ответа
    от модели" that reads like prose. Without a check for both, a wrong model
    name or a dead key turns every section into one of those while the run
    still reports «Готово» and ships a .docx full of them. This is the exact
    failure a 3000-section run cannot be allowed to hide.
    """
    _set_documents(DOCS)
    writer_calls: list[str] = []

    async def fake_chat(messages, model=None, user_id=None, use_tools=False, use_skills=True, **kwargs):
        content = messages[-1]["content"]
        if model == dg.PLANNER_MODEL and "Построй план" in content:
            return PLAN_JSON, [], "", []
        # Alternate the two shapes so neither is the only one exercised.
        if len(writer_calls) % 2:
            writer_calls.append("banner")
            return "❌ Ошибка API DeepSeek: Model Not Exist", [], "", []
        writer_calls.append("placeholder")
        return "Нет ответа от модели", [], "", []

    import deepseek_client
    dg.get_chat_response = fake_chat
    deepseek_client.get_deepseek_response = fake_chat

    messages, reply = _second_turn()
    summary, files, _, _ = await dg.get_docgen_response(messages, reply, 777, FakeStatus())
    assert "placeholder" in writer_calls and "banner" in writer_calls, "both failure shapes must be exercised"
    # The load-bearing assertion: neither shape was accepted as section content.
    assert "Не удалось сгенерировать разделов: 2 из 2" in summary, (
        f"API failures were not reported as failures: {summary!r}"
    )
    with zipfile.ZipFile(BytesIO(files[0]["bytes"])) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
    # The reason may appear in the .docx, but only inside the explicit failure
    # marker — never as prose the reader would take for the document's text.
    assert document_xml.count(dg._SECTION_FAILED_PREFIX) == 2, "failed sections are not marked in the .docx"
    print("OK: API failure (banner and bare placeholder) — counted as failed sections, never passed off as text")


async def main() -> None:
    # The retry delays (SECTION_RETRY_DELAYS) are real seconds in production;
    # nothing here is testing timing, so collapse them to keep the self-check
    # fast. dg imports the same asyncio module object, so this patches both.
    orig_sleep = asyncio.sleep

    async def instant_sleep(_seconds):
        await orig_sleep(0)

    asyncio.sleep = instant_sleep
    try:
        await check_happy_path()
        await check_no_sources()
        await check_planning_failure_is_reported()
        await check_failed_sections_are_reported()
        await check_section_retry_recovers()
        await check_truncated_sources_are_reported()
        await check_first_turn_asks_and_never_writes()
        await check_second_turn_generates()
        await check_cancel_generates_nothing()
        await check_skipped_questions_do_not_start_generation()
        await check_truncation_marker_on_a_chunk_boundary()
        await check_multi_archive_templates()
        await check_folder_inside_archive_is_its_own_group()
        await check_replacement_flow()
        await check_thousands_of_pages_are_planned_in_two_levels()
        await check_api_error_text_is_not_written_into_the_document()
    finally:
        asyncio.sleep = orig_sleep
    print("OK: docgen pipeline self-check passed")


if __name__ == "__main__":
    asyncio.run(main())
