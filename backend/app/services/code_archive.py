"""Pack project code from a chat reply into a downloadable zip when needed."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

_ARCHIVE_HINT = re.compile(
    r"(?i)("
    r"\b(?:архив|zip|rar|tar\.gz)\b|"
    r"весь\s+код|"
    r"бот\s+на\s+питон|"
    r"telegram[\s-]?бот|"
    r"напиши\s+(?:мне\s+)?бот\w{0,3}\b|"
    r"(?:скинь|закинь|пришли|дай|кинь)\s+(?:мне\s+)?(?:архив|zip|весь\s+код)"
    r")"
)

_CODE_FENCE = re.compile(r"```([A-Za-z0-9_+-]*)\n([\s\S]*?)```")

_EXT_BY_LANG = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "tsx": ".tsx",
    "jsx": ".jsx",
    "html": ".html",
    "css": ".css",
    "json": ".json",
    "toml": ".toml",
    "yaml": ".yaml",
    "yml": ".yml",
    "bash": ".sh",
    "shell": ".sh",
    "sh": ".sh",
    "sql": ".sql",
    "markdown": ".md",
    "md": ".md",
    "text": ".txt",
    "txt": ".txt",
    "env": ".env.example",
    "dotenv": ".env.example",
    "ini": ".ini",
    "cfg": ".cfg",
    "dockerfile": "Dockerfile",
}

_NAMED_FILE = re.compile(
    r"(?i)^(?:#\s*)?(?:file(?:name)?|path|файл)\s*[:=]\s*([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)\s*$"
)

_EXCUSE = re.compile(
    r"(?im)^.*(?:файл физически не был|кнопки скачивания пока не будет|"
    r"архив не прикреп|не удалось прикреп|код проекта подготовлен выше).*\n?"
)


def wants_code_archive(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text:
        return False
    return bool(_ARCHIVE_HINT.search(text))


def _safe_name(name: str, used: set[str]) -> str:
    clean = Path(str(name).replace("\\", "/")).name.replace("\x00", "").strip() or "file.txt"
    if clean in {".", ".."}:
        clean = "file.txt"
    base = clean
    idx = 2
    while clean.lower() in used:
        stem = Path(base).stem
        suffix = Path(base).suffix
        clean = f"{stem}_{idx}{suffix}"
        idx += 1
    used.add(clean.lower())
    return clean


def _guess_name(lang: str, body: str, index: int, used: set[str]) -> str:
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    named = _NAMED_FILE.match(first)
    if named:
        return _safe_name(named.group(1), used)

    key = (lang or "").strip().lower()
    mapped = _EXT_BY_LANG.get(key)
    if mapped == "Dockerfile":
        return _safe_name("Dockerfile", used)
    if mapped:
        return _safe_name(f"file_{index}{mapped}", used)
    if key in {"requirements", "requirements.txt"}:
        return _safe_name("requirements.txt", used)
    return _safe_name(f"file_{index}.txt", used)


def extract_code_files(markdown: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    used: set[str] = set()
    for index, match in enumerate(_CODE_FENCE.finditer(markdown or ""), start=1):
        lang = (match.group(1) or "").strip()
        body = (match.group(2) or "").replace("\r\n", "\n")
        if not body.strip() or len(body.strip()) < 20:
            continue
        name = _guess_name(lang, body, index, used)
        # Drop a leading "filename: foo.py" comment line from the file body.
        lines = body.splitlines()
        if lines and _NAMED_FILE.match(lines[0].strip()):
            body = "\n".join(lines[1:]).lstrip("\n")
        if not body.strip():
            continue
        if not body.endswith("\n"):
            body += "\n"
        files.append((name, body))
    return files


def build_zip_bytes(files: list[tuple[str, str]], archive_name: str = "project.zip") -> Optional[dict[str, Any]]:
    if not files:
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in files:
            archive.writestr(name, body.encode("utf-8"))
    payload = buffer.getvalue()
    if not payload:
        return None
    return {
        "filename": archive_name if archive_name.endswith(".zip") else f"{archive_name}.zip",
        "bytes": payload,
        "caption": "project archive",
    }


def maybe_package_reply_archive(
    user_text: str,
    reply_text: str,
    existing_files: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """If the user asked for an archive and nothing usable was attached, zip code fences."""
    if not wants_code_archive(user_text):
        return None
    for item in existing_files or []:
        name = str(item.get("filename") or item.get("name") or "").lower()
        data = item.get("bytes") or b""
        if not data:
            continue
        if name.endswith(
            (".zip", ".py", ".tar.gz", ".docx", ".xlsx", ".xls", ".csv", ".pdf", ".pptx")
        ):
            return None
    files = extract_code_files(reply_text or "")
    if len(files) < 1:
        return None
    return build_zip_bytes(files, "project.zip")


def scrub_missing_archive_excuse(text: str, attached: bool) -> str:
    if not attached or not text:
        return text
    cleaned = _EXCUSE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    note = "Архив с кодом прикреплён к ответу – скачайте его кнопкой в чате."
    if "прикреплён" not in cleaned.lower() and "скача" not in cleaned.lower():
        cleaned = f"{cleaned}\n\n{note}" if cleaned else note
    return cleaned
