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


def _install_fakes(plan_response: str, writer_fails: bool = False):
    """Returns (writer_prompts, pools_seen); both fill up as the run proceeds."""
    writer_prompts: list[str] = []
    pools_seen: list[str] = []

    async def fake_chat(messages, model=None, user_id=None, use_tools=False, use_skills=True, **kwargs):
        pools_seen.append(billing_pool.get())
        content = messages[-1]["content"]
        if model == dg.PLANNER_MODEL and "Построй план" in content:
            return plan_response, [], "", []
        if writer_fails:
            raise RuntimeError("модель недоступна")
        writer_prompts.append(content)
        return "Текст раздела. Мощность 2500 кВт.", [], "", []

    async def fake_deepseek(messages, model=None, user_id=None, use_tools=False, **kwargs):
        return await fake_chat(messages, model=model, user_id=user_id, use_tools=use_tools)

    import deepseek_client

    dg.get_chat_response = fake_chat
    deepseek_client.get_deepseek_response = fake_deepseek
    return writer_prompts, pools_seen


def _set_documents(docs):
    from conversations import conversation_manager

    conversation_manager.get_documents = lambda uid: docs


async def check_happy_path():
    _set_documents(DOCS)
    writer_prompts, pools_seen = _install_fakes(PLAN_JSON)
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
    writer_prompts, _ = _install_fakes(PLAN_JSON)

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
    _install_fakes(PLAN_JSON, writer_fails=True)

    summary, files, _, _ = await dg.get_docgen_response("Сделай ИТТ", 777, FakeStatus())

    assert files and files[0]["bytes"][:2] == b"PK", "must still produce a .docx when sections fail"
    assert "Не удалось сгенерировать разделов: 2 из 2" in summary, (
        f"failed sections were not reported to the user: {summary}"
    )
    print("OK: failed sections — counted and reported, document still assembled")


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


async def main() -> None:
    await check_happy_path()
    await check_no_sources()
    await check_planning_failure_is_reported()
    await check_failed_sections_are_reported()
    await check_truncated_sources_are_reported()
    print("OK: docgen pipeline self-check passed")


if __name__ == "__main__":
    asyncio.run(main())
