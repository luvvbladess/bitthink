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
import logging
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "app" / "bot_core"))
sys.path.insert(0, str(BACKEND_DIR))

# openai_client builds its client at import time and refuses to load without a key.
os.environ.setdefault("OPENAI_API_KEY", "sk-selfcheck-dummy")

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
    '{"template_document": "%s", "sections": ['
    '{"title": "Общие положения", "brief": "Назначение и состав", "complexity": "simple"},'
    '{"title": "Требования к энергетической установке", "brief": "Мощность и тяга",'
    ' "complexity": "complex"}]}' % TEMPLATE_FILE
)


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
        attempt_counts[content] = attempt_counts.get(content, 0) + 1
        if writer_fails:
            raise RuntimeError("модель недоступна")
        if fail_first_attempt and attempt_counts[content] == 1:
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

    summary, files, _, _ = await dg.get_docgen_response(
        f"Сделай ИТТ по шаблону {TEMPLATE_FILE}", 777, status
    )

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

    summary, files, _, _ = await dg.get_docgen_response("Напиши регламент", 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "no-sources run must still produce a .docx"
    assert "не найдены" in summary, f"user was not told the sources are missing: {summary}"
    assert writer_prompts and "Релевантные фрагменты" not in writer_prompts[0], writer_prompts[:1]
    print("OK: no sources — document still produced, and the user is told sources were missing")


async def check_planning_failure_is_reported():
    _set_documents(DOCS)
    _install_fakes("это не json")

    summary, files, _, _ = await dg.get_docgen_response("Сделай ИТТ", 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "must still produce a .docx on planner failure"
    assert "План разделов построить не удалось" in summary, (
        f"planner fallback was not reported to the user: {summary}"
    )
    print("OK: planner failure — fallback is reported instead of silently shipping one section")


async def check_failed_sections_are_reported():
    _set_documents(DOCS)
    _, _, attempt_counts = _install_fakes(PLAN_JSON, writer_fails=True)

    summary, files, _, _ = await dg.get_docgen_response("Сделай ИТТ", 777, FakeStatus())

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

    summary, files, _, _ = await dg.get_docgen_response("Сделай ИТТ", 777, FakeStatus())

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

    summary, files, _, _ = await dg.get_docgen_response("Сделай ИТТ", 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK"
    assert "Прочитаны не целиком" in summary, (
        f"a source truncated at upload time was not reported: {summary}"
    )
    assert KNOWLEDGE_FILE in summary, f"the truncated file was not named: {summary}"
    assert TEMPLATE_FILE not in summary.split("Прочитаны не целиком")[1], (
        f"an untruncated file was wrongly reported as truncated: {summary}"
    )
    print("OK: truncated sources — named in the summary, with what to do about it")


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
        _, truncated = dg._extract_source_chunks(1)
        if not truncated:
            missed.append(tail)
    assert not missed, f"truncation went undetected for tail lengths {missed[:5]} (+{len(missed)} total)"

    _set_documents([{"filename": "чистый.pdf", "content": "Прочитал первые страницы отчёта и согласовал."}])
    _, truncated = dg._extract_source_chunks(1)
    assert not truncated, "an untruncated document was wrongly reported as truncated"
    print("OK: truncation marker — found on every chunk boundary, no false positive on similar prose")


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
        await check_truncation_marker_on_a_chunk_boundary()
    finally:
        asyncio.sleep = orig_sleep
    print("OK: docgen pipeline self-check passed")


if __name__ == "__main__":
    asyncio.run(main())
