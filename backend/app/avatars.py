"""Profile photos on the uploads volume, with a cache-busting public URL."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from app.config import get_settings

AVATAR_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/pjpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
AVATAR_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_NAME = re.compile(r"^[0-9]+(-[a-f0-9]{8,})?\.(jpg|jpeg|png|webp)$", re.I)


def sniff_ext(data: bytes, content_type: str | None) -> str | None:
    mapped = AVATAR_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if mapped:
        return mapped
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def avatar_dir() -> Path:
    folder = get_settings().UPLOAD_DIR / "avatars"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _is_avatar_file(path: Path, user_id: int) -> bool:
    if not path.is_file() or path.suffix.lower() not in AVATAR_SUFFIXES:
        return False
    name = path.name.lower()
    return name.startswith(f"{user_id}.") or name.startswith(f"{user_id}-")


def find_avatar_file(user_id: int) -> Path | None:
    folder = avatar_dir()
    matches = [path for path in folder.iterdir() if _is_avatar_file(path, user_id)]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def public_avatar_url(user_id: int) -> str | None:
    path = find_avatar_file(user_id)
    if path is None or not _NAME.match(path.name):
        return None
    version = int(path.stat().st_mtime)
    return f"/uploads/avatars/{path.name}?v={version}"


def save_avatar(user_id: int, ext: str, data: bytes) -> str:
    folder = avatar_dir()
    name = f"{user_id}-{secrets.token_hex(8)}.{ext}"
    dest = folder / name
    tmp = folder / f".{name}.tmp"
    tmp.write_bytes(data)
    tmp.replace(dest)
    for old in list(folder.iterdir()):
        if old != dest and _is_avatar_file(old, user_id):
            old.unlink(missing_ok=True)
    url = public_avatar_url(user_id)
    return url or f"/uploads/avatars/{name}"


def delete_avatar(user_id: int) -> None:
    folder = avatar_dir()
    for old in list(folder.iterdir()):
        if _is_avatar_file(old, user_id):
            old.unlink(missing_ok=True)
