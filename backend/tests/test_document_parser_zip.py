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


def test_extract_zip_archive_normalizes_windows_backslash_paths():
    """Some Windows zip tools store 'shablony\\forma.txt' instead of '/'.
    Folder grouping in docgen splits on '/', so a backslash would hide the
    template folder from the planner.

    ZipInfo() itself rewrites os.sep to '/' on Windows, so the filename is
    assigned after construction to keep the backslash the way a foreign
    zip tool would have stored it.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for raw_name, body in (
            ("shablony\\forma.txt", "Шаблон формы".encode("utf-8")),
            ("baza\\otchet.txt", "База знаний".encode("utf-8")),
        ):
            info = zipfile.ZipInfo("placeholder.txt")
            info.filename = raw_name
            zf.writestr(info, body)
    zip_bytes = buf.getvalue()

    results = asyncio.run(extract_zip_archive(zip_bytes, "arhiv.zip", user_id=None))
    names = [name for name, _ in results]

    assert "arhiv.zip/shablony/forma.txt" in names
    assert "arhiv.zip/baza/otchet.txt" in names
    assert not any("\\" in name for name in names)


def test_extract_zip_archive_empty_zip_returns_empty_list():
    zip_bytes = _make_zip({})

    results = asyncio.run(extract_zip_archive(zip_bytes, "empty.zip", user_id=None))

    assert results == []
