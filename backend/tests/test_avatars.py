from pathlib import Path
from types import SimpleNamespace

from app.avatars import delete_avatar, public_avatar_url, save_avatar, sniff_ext


def test_sniff_jpeg_png_webp_and_aliases():
    jpeg = b"\xff\xd8\xff" + b"\x00" * 8
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    webp = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBP" + b"\x00" * 4
    assert sniff_ext(jpeg, "image/jpg") == "jpg"
    assert sniff_ext(jpeg, None) == "jpg"
    assert sniff_ext(png, "image/png") == "png"
    assert sniff_ext(webp, "") == "webp"
    assert sniff_ext(b"not-an-image", "text/plain") is None


def test_save_find_and_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.avatars.get_settings", lambda: SimpleNamespace(UPLOAD_DIR=tmp_path))
    jpeg = b"\xff\xd8\xff" + b"\x00" * 32
    url = save_avatar(7, "jpg", jpeg)
    assert url.startswith("/uploads/avatars/7-")
    assert "?v=" in url
    stored = tmp_path / "avatars" / url.split("?")[0].rsplit("/", 1)[-1]
    assert stored.is_file()
    assert public_avatar_url(7) == url
    assert public_avatar_url(8) is None
    save_avatar(7, "jpg", jpeg)
    remaining = list((tmp_path / "avatars").glob("7-*"))
    assert len(remaining) == 1
    delete_avatar(7)
    assert public_avatar_url(7) is None
