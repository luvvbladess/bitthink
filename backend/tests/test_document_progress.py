import asyncio
import io
import zipfile

from app.bot_core import document_parser as parser
from app.services.document_progress import iter_work_events


def _pdf(pages: int) -> bytes:
    import fitz

    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"MARKER_PAGE_{index + 1} readable paragraph for the progress test")
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_page_progress_is_monotonic():
    calls = []

    def on_progress(done, total, unit):
        calls.append((done, total, unit))

    text = asyncio.run(parser.extract_text_from_pdf(_pdf(5), on_progress=on_progress))
    assert "MARKER_PAGE_1" in text and "MARKER_PAGE_5" in text
    assert calls, "expected page progress"
    assert all(unit == "page" for _done, _total, unit in calls)
    assert calls[0][1] == 5
    assert calls[-1] == (5, 5, "page")
    assert [done for done, _total, _unit in calls] == sorted(done for done, _total, _unit in calls)
    assert calls[0][0] < calls[-1][0]


def test_single_page_pdf_does_not_invent_steps():
    calls = []
    asyncio.run(parser.extract_text_from_pdf(_pdf(1), on_progress=lambda *args: calls.append(args)))
    assert calls == []


def test_zip_progress_counts_files_not_a_timer():
    calls = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", "первый")
        archive.writestr("b.txt", "второй")
        archive.writestr("notes.md", "третий")

    docs = asyncio.run(
        parser.extract_zip_archive(buffer.getvalue(), "pack.zip", on_progress=lambda *args: calls.append(args))
    )
    assert len(docs) == 3
    assert [item[0] for item in calls] == [1, 2, 3]
    assert {item[1] for item in calls} == {3}
    assert {item[2] for item in calls} == {"file"}


def test_progress_events_come_from_the_worker_thread():
    async def work(report):
        def inner():
            report(1, 4, "page")
            report(4, 4, "page")

        await asyncio.to_thread(inner)
        return {"ok": True, "filename": "tome.pdf"}

    async def collect():
        return [event async for event in iter_work_events(work)]

    events = asyncio.run(collect())
    assert [event["label"] for event in events if event["type"] == "progress"] == [
        "Страница 1 из 4",
        "Страница 4 из 4",
    ]
    assert events[-1]["type"] == "result"
    assert events[-1]["filename"] == "tome.pdf"


def test_progress_label_uses_units():
    assert parser.progress_label(2, 9, "slide") == "Слайд 2 из 9"
    assert parser.progress_label(1, 3, "sheet") == "Лист 1 из 3"
