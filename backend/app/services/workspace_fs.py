"""Jailed per-user workspace. Stdlib only so the sandbox container can import it."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Optional

QUOTA_BYTES = 3 * 1024 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_READ_CHARS = 120_000
MAX_LS_ENTRIES = 400
MAX_PATH_DEPTH = 12
RUN_TIMEOUT_SECONDS = 90
PIP_TIMEOUT_SECONDS = 180
RUN_OUTPUT_CHARS = 80_000
RUN_MEMORY_BYTES = 512 * 1024 * 1024
MAX_RUN_FILE_BYTES = 256 * 1024 * 1024
_PIP_SPEC = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,_-]+\])?((==|>=|<=|~=)[A-Za-z0-9._+-]+)?$"
)

_FORBIDDEN_NAMES = {".env", ".git", "docker-compose.yml"}
_SKIP_DIRS = {".venv", ".tmp", "__pycache__"}
# One-off tooling the model writes while thinking. Not a user-facing project.
_HELPER_STEM = re.compile(
    r"(?i)^(inspect|extract|parse|debug|scratch|dump|probe|calc)_"
)
_DOC_ARTIFACT_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".csv",
    ".docx",
    ".pdf",
    ".pptx",
}
_CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sh", ".sql"}
_PROJECT_MARKERS = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "cargo.toml",
    "go.mod",
    "dockerfile",
}
DELIVER_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".csv",
    ".docx",
    ".pdf",
    ".zip",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".sql",
    ".sh",
    ".ini",
}
_SOURCE_FOR_AUTO_ZIP = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".sql",
    ".sh",
    ".ini",
}
MAX_DELIVER_FILES = 8
# Комплект из 18-40 документов не помещается в 8 отдельных вложений. Лишнее
# раньше молча отрезалось: человек получал 8 файлов из 18 и не знал об этом.
# Теперь, если файлов больше, чем влезает отдельными карточками, всё уходит
# одним архивом с сохранением папок.
MAX_BUNDLE_FILES = 200
MAX_BUNDLE_BYTES = 40 * 1024 * 1024
BUNDLE_NAME = "Комплект документов.zip"
MAX_AUTO_ZIP_FILES = 40
MAX_AUTO_ZIP_BYTES = 6 * 1024 * 1024
MAX_GREP_HITS = 80
MAX_GREP_FILES = 40
MAX_GREP_SCAN = 1500
MAX_GLOB_HITS = 200
MAX_LINE_PREVIEW = 220
_SKIP_GREP_SUFFIX = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".pdf",
    ".xlsx",
    ".xls",
    ".docx",
    ".zip",
    ".pptx",
    ".pyc",
    ".ico",
}



def workspaces_root() -> Path:
    raw = (os.environ.get("WORKSPACES_DIR") or "").strip()
    if not raw:
        raise RuntimeError("WORKSPACES_DIR is not set")
    root = Path(raw).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_root(user_id: int) -> Path:
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("Нужен пользователь")
    root = (workspaces_root() / f"u{user_id}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _safe_rel(path: str) -> str:
    text = (path or "").replace("\\", "/").strip()
    if not text:
        return "."
    if text.startswith("/") or text.startswith("~") or ":" in text[:3]:
        raise ValueError("Только относительный путь внутри песочницы")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise ValueError("Путь с .. запрещён")
    if len(parts) > MAX_PATH_DEPTH:
        raise ValueError("Слишком глубокий путь")
    for part in parts:
        if part in _FORBIDDEN_NAMES or len(part) > 120:
            raise ValueError("Недопустимое имя файла")
        if part.startswith(".") and part not in (".gitignore",):
            raise ValueError("Скрытые файлы в песочнице не используются")
    return "/".join(parts) if parts else "."


def resolve_in_jail(user_id: int, path: str) -> Path:
    root = user_root(user_id)
    rel = _safe_rel(path)
    candidate = (root / rel).resolve() if rel != "." else root
    root_s = str(root)
    cand_s = str(candidate)
    if cand_s != root_s and not cand_s.startswith(root_s + os.sep):
        raise ValueError("Путь вне песочницы")
    for current in [candidate, *candidate.parents]:
        if current == root.parent:
            break
        try:
            if current.is_symlink():
                raise ValueError("Симлинки в песочнице запрещены")
        except ValueError:
            raise
        except OSError:
            continue
        if current == root:
            break
    return candidate


def _dir_size(root: Path) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in _FORBIDDEN_NAMES]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.is_symlink():
                    continue
                total += path.stat().st_size
            except OSError:
                continue
    return total


def _quota_line(user_id: int) -> str:
    used = _dir_size(user_root(user_id))
    gb = QUOTA_BYTES / (1024 ** 3)
    used_mb = used / (1024 ** 2)
    return f"Квота: {used_mb:.1f} МБ из {gb:.0f} ГБ"


def ls(user_id: int, path: str = ".") -> str:
    target = resolve_in_jail(user_id, path)
    if not target.exists():
        return "Нет такого пути."
    if target.is_file():
        size = target.stat().st_size
        return f"{path}  файл  {size} байт\n{_quota_line(user_id)}"
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if item.name in _FORBIDDEN_NAMES or item.name.startswith("."):
            continue
        kind = "папка" if item.is_dir() else "файл"
        size = ""
        try:
            if item.is_file() and not item.is_symlink():
                size = f"  {item.stat().st_size} байт"
        except OSError:
            size = ""
        entries.append(f"{item.name}  {kind}{size}")
        if len(entries) >= MAX_LS_ENTRIES:
            entries.append("...")
            break
    body = "\n".join(entries) if entries else "(пусто)"
    return f"{body}\n\n{_quota_line(user_id)}"


def read(user_id: int, path: str, start_line: int = 0, end_line: int = 0) -> str:
    target = resolve_in_jail(user_id, path)
    if not target.is_file() or target.is_symlink():
        return "Это не файл."
    data = target.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        return "Файл слишком большой, чтобы читать его целиком."
    text = data.decode("utf-8", errors="replace")
    if start_line > 0 or end_line > 0:
        lines = text.splitlines()
        total = len(lines)
        start = start_line if start_line > 0 else 1
        end = end_line if end_line > 0 else start + 199
        if start > total:
            return f"В файле {total} строк, start_line={start} за концом."
        end = min(max(start, end), total)
        numbered = "\n".join(f"{idx}|{line}" for idx, line in enumerate(lines[start - 1 : end], start))
        out = f"{path} строки {start}–{end} из {total}\n{numbered}"
        if len(out) > MAX_READ_CHARS:
            out = out[:MAX_READ_CHARS] + "\n\n[...обрезано...]"
        return out
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n\n[...обрезано...]"
    return text


def write(user_id: int, path: str, content: str) -> str:
    target = resolve_in_jail(user_id, path)
    if target.exists() and (target.is_dir() or target.is_symlink()):
        return "Нельзя записать поверх папки."
    payload = (content or "").encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        return f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ."
    used = _dir_size(user_root(user_id))
    existing = target.stat().st_size if target.is_file() else 0
    if used - existing + len(payload) > QUOTA_BYTES:
        return "Квота песочницы 3 ГБ закончилась. Удали лишнее."
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(target)
    return f"Записал {path} ({len(payload)} байт).\n{_quota_line(user_id)}"


def edit(user_id: int, path: str, old: str, new: str) -> str:
    current = read(user_id, path)
    if current.startswith("Это не файл") or current.startswith("Файл слишком"):
        return current
    if not old:
        return "Нужен old_string."
    count = current.count(old)
    if count == 0:
        return "Фрагмент не найден. Сначала workspace_read."
    if count > 1:
        return "Фрагмент встречается несколько раз. Возьми кусок длиннее."
    return write(user_id, path, current.replace(old, new or "", 1))


def delete(user_id: int, path: str) -> str:
    rel_raw = (path or "").replace("\\", "/").strip()
    if rel_raw in {".venv", "./.venv"}:
        target = user_root(user_id) / ".venv"
        if not target.exists():
            return "Уже нет."
        shutil.rmtree(target)
        return "Удалил .venv. Пакеты pip нужно поставить снова."
    rel = _safe_rel(path)
    if rel == ".":
        return "Корень песочницы удалять нельзя."
    target = resolve_in_jail(user_id, path)
    if not target.exists():
        return "Уже нет."
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
        return f"Удалил папку {path}."
    target.unlink()
    return f"Удалил {path}."


# Landlock filesystem access bits (linux/landlock.h). ABI 5+ also has
# IOCTL_DEV at bit 15; handled bits we don't know stay unrestricted.
_LANDLOCK_FS_BITS = (
    (1, (1 << 13) - 1),
    (2, 1 << 13),
    (3, 1 << 14),
    (5, 1 << 15),
)
_LANDLOCK_READ = (1 << 0) | (1 << 2) | (1 << 3)
_LANDLOCK_RW = (
    _LANDLOCK_READ
    | (1 << 1)
    | (1 << 4)
    | (1 << 5)
    | (1 << 6)
    | (1 << 7)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 11)
    | (1 << 12)
    | (1 << 13)
    | (1 << 14)
    | (1 << 15)
)


def _landlock_mask(abi: int) -> int:
    mask = 0
    for version, bits in _LANDLOCK_FS_BITS:
        if abi >= version:
            mask |= bits
    return mask


def _landlock_allow(libc, ruleset_fd, mask: int, path: str, access: int) -> None:
    import ctypes

    if not path or not os.path.exists(path):
        return

    class Beneath(ctypes.Structure):
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    flags = os.O_PATH | getattr(os, "O_CLOEXEC", 0)
    try:
        parent = os.open(path, flags)
    except OSError:
        return
    try:
        rule = Beneath(int(access) & mask, parent)
        rc = libc.syscall(445, ruleset_fd, 1, ctypes.byref(rule), 0)
        if rc != 0:
            err = ctypes.get_errno()
            raise OSError(err, f"landlock add_rule {path}")
    finally:
        os.close(parent)


def confine_user_filesystem(user_id: int) -> None:
    """Deny the child every filesystem path except its workspace and the runtime.

    Same uid owns every workspace, so directory mode alone does not isolate
    users. Landlock is applied in the forked child before exec. stat() is not
    covered by current kernels; open/read/write/create/unlink are.
    """
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    abi = int(libc.syscall(444, None, 0, 1))
    if abi < 1:
        raise OSError(ctypes.get_errno() or 1, "landlock недоступен")
    mask = _landlock_mask(abi)

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    attr = Ruleset(mask)
    ruleset = int(libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0))
    if ruleset < 0:
        raise OSError(ctypes.get_errno() or 1, "landlock ruleset")
    try:
        root = user_root(user_id)
        _landlock_allow(libc, ruleset, mask, str(root), _LANDLOCK_RW)
        for path in ("/usr", "/lib", "/lib64", "/bin", "/etc", sys.prefix, sys.base_prefix):
            _landlock_allow(libc, ruleset, mask, path, _LANDLOCK_READ)
        executable = os.path.realpath(sys.executable)
        prefix = os.path.dirname(executable)
        # venv/bin/python -> allow the venv root, not only bin/
        if os.path.basename(prefix) == "bin":
            prefix = os.path.dirname(prefix)
        _landlock_allow(libc, ruleset, mask, prefix, _LANDLOCK_READ)
        _landlock_allow(libc, ruleset, mask, "/dev/urandom", 1 << 2)
        _landlock_allow(libc, ruleset, mask, "/dev/null", (1 << 1) | (1 << 2))
        _landlock_allow(libc, ruleset, mask, "/proc/self", _LANDLOCK_READ)
        # Required before landlock_restrict_self on unprivileged processes.
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno() or 1, "no_new_privs")
        if libc.syscall(446, ruleset, 0) != 0:
            raise OSError(ctypes.get_errno() or 1, "landlock restrict")
    finally:
        os.close(ruleset)


def _prepare_child(user_id: int, cpu_seconds: int, memory: bool) -> None:
    _apply_limits(cpu_seconds, memory)
    if os.environ.get("SANDBOX_MODE") == "1" or os.environ.get("WORKSPACE_LANDLOCK") == "1":
        confine_user_filesystem(user_id)


def _apply_limits(cpu_seconds: int, memory: bool = True) -> None:
    try:
        import resource
    except ImportError:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RUN_FILE_BYTES, MAX_RUN_FILE_BYTES))
    if memory:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (RUN_MEMORY_BYTES, RUN_MEMORY_BYTES))
        except (ValueError, resource.error):
            pass
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _python_bin(root: Path) -> str:
    venv = _venv_python(root)
    if venv.is_file():
        return str(venv)
    return os.environ.get("WORKSPACE_PYTHON") or sys.executable


def _copy_sitecustomize(venv_root: Path) -> None:
    src = Path("/usr/local/lib/python3.12/site-packages/sitecustomize.py")
    if not src.is_file():
        return
    for dest_dir in (venv_root / "lib").glob("python*/site-packages"):
        dest = dest_dir / "sitecustomize.py"
        if not dest.exists():
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return


def ensure_venv(user_id: int) -> str:
    root = user_root(user_id)
    venv = _venv_python(root)
    if venv.is_file():
        return str(venv)
    (root / ".tmp").mkdir(exist_ok=True)
    base = os.environ.get("WORKSPACE_PYTHON") or sys.executable
    created = subprocess.run(
        [base, "-m", "venv", "--system-site-packages", str(root / ".venv")],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "HOME": str(root),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "TMPDIR": str(root / ".tmp"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    if created.returncode != 0 or not venv.is_file():
        raise RuntimeError((created.stderr or created.stdout or "venv не создался")[:400])
    _copy_sitecustomize(root / ".venv")
    return str(venv)


def valid_pip_spec(spec: str) -> bool:
    text = (spec or "").strip()
    if not text or len(text) > 80:
        return False
    if any(token in text for token in ("://", "/", "\\", "..", " ", ";", "|", "&", "`", "$")):
        return False
    return bool(_PIP_SPEC.match(text))


def _run_cmd(user_id: int, argv: list[str], timeout: int, limit_memory: bool = True) -> str:
    if os.environ.get("WORKSPACE_ALLOW_LOCAL_RUN") != "1" and not os.environ.get("SANDBOX_MODE"):
        return "Запуск Python только внутри песочницы."
    root = user_root(user_id)
    (root / ".tmp").mkdir(exist_ok=True)
    venv_bin = str(_venv_python(root).parent)
    env = {
        "HOME": str(root),
        "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(root / ".tmp"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_INDEX_URL": "https://pypi.org/simple",
    }
    if _venv_python(root).is_file():
        env["VIRTUAL_ENV"] = str(root / ".venv")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=(lambda: _prepare_child(user_id, timeout, limit_memory)) if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return f"Процесс превысил {timeout} с и был остановлен."
    except PermissionError:
        return "Запуск в песочнице запрещён системой."
    elapsed = time.monotonic() - started
    chunks = [
        f"exit {completed.returncode}  {elapsed:.1f}с",
        completed.stdout or "",
        completed.stderr or "",
    ]
    text = "\n".join(part for part in chunks if part).strip()
    if len(text) > RUN_OUTPUT_CHARS:
        text = text[:RUN_OUTPUT_CHARS] + "\n\n[...обрезано...]"
    return text or "(ничего не напечатал)"


def run_python(user_id: int, path: str, argv: list[str] | None = None) -> str:
    target = resolve_in_jail(user_id, path)
    if not target.is_file() or target.suffix.lower() != ".py":
        return "Запускать можно только файл .py в песочнице."
    extra: list[str] = []
    for item in argv or []:
        text = str(item)
        if text.startswith("-"):
            return "Аргументы скрипта не могут начинаться с -."
        extra.append(text[:200])
        if len(extra) >= 8:
            break
    python = _python_bin(user_root(user_id))
    return _run_cmd(user_id, [python, str(target), *extra], RUN_TIMEOUT_SECONDS)


def pip_install(user_id: int, packages: list[str]) -> str:
    specs: list[str] = []
    for item in packages:
        spec = str(item).strip()
        if not valid_pip_spec(spec):
            return f"Нельзя ставить «{spec}». Только имя пакета с PyPI, без URL и путей."
        specs.append(spec)
        if len(specs) >= 8:
            break
    if not specs:
        return "Укажи пакеты, например requests или pandas."
    try:
        python = ensure_venv(user_id)
    except Exception as exc:
        return f"Не удалось создать venv: {exc}"
    argv = [
        python,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--no-cache-dir",
        "--disable-pip-version-check",
        "--index-url",
        "https://pypi.org/simple",
        "--trusted-host",
        "pypi.org",
        "--trusted-host",
        "files.pythonhosted.org",
        *specs,
    ]
    result = _run_cmd(user_id, argv, PIP_TIMEOUT_SECONDS, limit_memory=False)
    return result + f"\n\n{_quota_line(user_id)}"


def _recent_workspace_files(
    root: Path,
    cutoff: float,
    suffixes: set[str],
) -> list[tuple[float, str, Path, int]]:
    found: list[tuple[float, str, Path, int]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and name not in _FORBIDDEN_NAMES]
        for name in filenames:
            path = Path(dirpath) / name
            suffix = path.suffix.lower()
            if suffix not in suffixes and path.name not in {"Dockerfile", "requirements.txt", ".env.example"}:
                continue
            try:
                if path.is_symlink():
                    continue
                stat = path.stat()
            except OSError:
                continue
            if cutoff and stat.st_mtime < cutoff:
                continue
            if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
                continue
            rel = path.relative_to(root).as_posix()
            found.append((stat.st_mtime, rel, path, stat.st_size))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def _is_helper_source(rel: str) -> bool:
    name = Path((rel or "").replace("\\", "/")).name
    return bool(_HELPER_STEM.match(name))


def _auto_zip_sources(root: Path, cutoff: float) -> Optional[dict[str, Any]]:
    """Pack a real code project into one archive.

    Zip when there is a project marker (requirements.txt, package.json, …)
    and at least one code file. bot.py plus requirements.txt is a project.
    A lone script without a marker stays internal.
    """
    import zipfile
    from io import BytesIO

    sources = _recent_workspace_files(root, cutoff, _SOURCE_FOR_AUTO_ZIP)
    if not sources:
        return None
    names = {Path(rel).name.lower() for _, rel, _, _ in sources}
    # A project marker plus at least one code file (bot.py + requirements.txt
    # is the usual one-script bot). A lone script without a marker stays internal.
    if not (names & _PROJECT_MARKERS):
        return None
    code_files = [s for s in sources if Path(s[1]).suffix.lower() in _CODE_SUFFIXES]
    if len(code_files) < 1:
        return None
    buffer = BytesIO()
    packed = 0
    total = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for _, rel, path, size in sources:
            if packed >= MAX_AUTO_ZIP_FILES or total + size > MAX_AUTO_ZIP_BYTES:
                break
            try:
                payload = path.read_bytes()
            except OSError:
                continue
            archive.writestr(rel, payload)
            packed += 1
            total += len(payload)
    if packed < 1:
        return None
    data = buffer.getvalue()
    return {
        "path": "project.zip",
        "name": "project.zip",
        "size": len(data),
        "data_b64": base64.b64encode(data).decode("ascii"),
    }


def _bundle_deliverables(entries: list[tuple[float, str, Path, int]]) -> Optional[dict[str, Any]]:
    """Все готовые файлы задания одним архивом, папки сохраняются.

    Собственные .zip модели в архив не кладутся, если рядом есть сами
    документы: такой zip обычно и есть эти же документы, и комплект вышел бы
    вдвое тяжелее. Что не влезло в лимит, перечислено в файле внутри архива,
    чтобы недостача была видна, а не молча терялась.
    """
    import zipfile
    from io import BytesIO

    loose = [entry for entry in entries if entry[2].suffix.lower() != ".zip"]
    chosen = sorted(loose or entries, key=lambda entry: entry[1].lower())
    buffer = BytesIO()
    packed = 0
    total = 0
    skipped: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for _, rel, path, size in chosen:
            if packed >= MAX_BUNDLE_FILES or total + size > MAX_BUNDLE_BYTES:
                skipped.append(rel)
                continue
            try:
                payload = path.read_bytes()
            except OSError:
                skipped.append(rel)
                continue
            archive.writestr(rel, payload)
            packed += 1
            total += len(payload)
        if skipped and packed:
            note = "Не поместились в архив (лимит размера), лежат в песочнице:\n" + "\n".join(skipped) + "\n"
            archive.writestr("НЕ ВОШЛО В АРХИВ.txt", note.encode("utf-8"))
    if packed < 1:
        return None
    data = buffer.getvalue()
    return {
        "path": BUNDLE_NAME,
        "name": BUNDLE_NAME,
        "size": len(data),
        "files": packed,
        "data_b64": base64.b64encode(data).decode("ascii"),
    }


def collect_deliverables(user_id: int, since: float = 0) -> str:
    """Newest user-facing files written during a job, as JSON with base64 bodies."""
    root = (workspaces_root() / f"u{user_id}").resolve()
    if not isinstance(user_id, int) or user_id <= 0 or not root.is_dir():
        return "[]"
    cutoff = float(since or 0) - 2
    # Deliverable suffixes that the user actually wants to download
    _DIRECT_DELIVER = _DOC_ARTIFACT_SUFFIXES | {".zip", ".png", ".jpg", ".jpeg", ".webp"}
    found = _recent_workspace_files(root, cutoff, DELIVER_SUFFIXES)
    has_zip = any(path.suffix.lower() == ".zip" for _, _, path, _ in found)
    has_doc = any(path.suffix.lower() in _DOC_ARTIFACT_SUFFIXES for _, _, path, _ in found)
    direct = [entry for entry in found if entry[2].suffix.lower() in _DIRECT_DELIVER]
    direct_bytes = sum(size for _, _, _, size in direct)
    if len(direct) > MAX_DELIVER_FILES or direct_bytes > MAX_FILE_BYTES:
        bundle = _bundle_deliverables(direct)
        if bundle:
            return json.dumps([bundle], ensure_ascii=False)
    items = []
    total = 0
    for _, rel, path, size in found:
        suffix = path.suffix.lower()
        # Only deliver real artifacts (docs, images, zips). Scripts stay internal.
        if suffix not in _DIRECT_DELIVER:
            continue
        if len(items) >= MAX_DELIVER_FILES or total + size > MAX_FILE_BYTES:
            break
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        items.append(
            {
                "path": rel,
                "name": path.name,
                "size": len(payload),
                "data_b64": base64.b64encode(payload).decode("ascii"),
            }
        )
        total += len(payload)
    if not has_zip and not has_doc:
        auto_zip = _auto_zip_sources(root, cutoff)
        if auto_zip:
            # Prefer a single project archive over a pile of individual sources.
            source_only = {
                item["name"]
                for item in items
                if Path(item["name"]).suffix.lower() in _SOURCE_FOR_AUTO_ZIP
            }
            items = [item for item in items if item["name"] not in source_only]
            items.insert(0, auto_zip)
            items = items[:MAX_DELIVER_FILES]
    return json.dumps(items, ensure_ascii=False)


def _int_arg(args: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(args.get(key) or default)
    except (TypeError, ValueError):
        return default


def _path_matches(rel: str, pattern: str) -> bool:
    pattern = (pattern or "").replace("\\", "/").strip().lstrip("./")
    rel = (rel or "").replace("\\", "/").lstrip("./")
    name = rel.rsplit("/", 1)[-1]
    if not pattern or pattern in ("*", "**"):
        return True
    if fnmatch(rel, pattern) or fnmatch(name, pattern):
        return True
    if pattern.startswith("**/"):
        rest = pattern[3:]
        if fnmatch(rel, rest) or fnmatch(name, rest):
            return True
        parts = rel.split("/")
        for index in range(len(parts)):
            if fnmatch("/".join(parts[index:]), rest):
                return True
    return False


def _walk_files(user_id: int, path: str):
    target = resolve_in_jail(user_id, path or ".")
    if target.is_file() and not target.is_symlink():
        yield target
        return
    if not target.exists() or not target.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_DIRS and name not in _FORBIDDEN_NAMES and not name.startswith(".")
        ]
        for name in filenames:
            if name in _FORBIDDEN_NAMES or name.startswith("."):
                continue
            item = Path(dirpath) / name
            try:
                if item.is_symlink():
                    continue
            except OSError:
                continue
            yield item


def grep(user_id: int, pattern: str, path: str = ".", glob: str = "") -> str:
    needle = (pattern or "").strip()
    if len(needle) < 2:
        return "Нужна подстрока от 2 символов. Регулярок нет: для сложного поиска – python_run."
    lowered = needle.lower()
    glob_pat = (glob or "").replace("\\", "/").strip()
    root = user_root(user_id)
    hits: list[str] = []
    files_hit = 0
    scanned = 0
    try:
        resolve_in_jail(user_id, path or ".")
    except ValueError as exc:
        return str(exc)
    for file in _walk_files(user_id, path or "."):
        if scanned >= MAX_GREP_SCAN or len(hits) >= MAX_GREP_HITS or files_hit >= MAX_GREP_FILES:
            break
        try:
            rel = str(file.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if glob_pat and not _path_matches(rel, glob_pat):
            continue
        if file.suffix.lower() in _SKIP_GREP_SUFFIX:
            continue
        try:
            if file.stat().st_size > MAX_FILE_BYTES:
                continue
            raw = file.read_bytes()
        except OSError:
            continue
        scanned += 1
        if b"\x00" in raw[:4096]:
            continue
        file_hits: list[str] = []
        for index, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if lowered not in line.lower():
                continue
            file_hits.append(f"{rel}:{index}:{line.strip()[:MAX_LINE_PREVIEW]}")
            if len(hits) + len(file_hits) >= MAX_GREP_HITS:
                break
        if file_hits:
            files_hit += 1
            hits.extend(file_hits)
    extra = ""
    if scanned >= MAX_GREP_SCAN or len(hits) >= MAX_GREP_HITS:
        extra = "\n[...обрезано, уточни path или glob...]"
    if not hits:
        return f"Нет совпадений для «{needle}» (файлов просмотрено: {scanned})."
    return f"Совпадений: {len(hits)}\n" + "\n".join(hits) + extra


def glob_paths(user_id: int, pattern: str, path: str = ".") -> str:
    glob_pat = (pattern or "").replace("\\", "/").strip()
    if not glob_pat:
        return "Нужен glob, например **/*.py или data/*.csv."
    root = user_root(user_id)
    matches: list[str] = []
    try:
        resolve_in_jail(user_id, path or ".")
    except ValueError as exc:
        return str(exc)
    for file in _walk_files(user_id, path or "."):
        try:
            rel = str(file.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if not _path_matches(rel, glob_pat):
            continue
        matches.append(rel)
        if len(matches) >= MAX_GLOB_HITS:
            break
    if not matches:
        return f"Ничего не найдено по «{glob_pat}»."
    extra = "\n[...обрезано...]" if len(matches) >= MAX_GLOB_HITS else ""
    return "\n".join(matches) + extra


def dispatch(user_id: int, op: str, args: dict[str, Any]) -> str:
    op = (op or "").strip().lower()
    path = str(args.get("path") or ".")
    if op in ("ls", "list"):
        return ls(user_id, path)
    if op == "stat":
        return _quota_line(user_id)
    if op == "read":
        return read(
            user_id,
            path,
            start_line=_int_arg(args, "start_line"),
            end_line=_int_arg(args, "end_line"),
        )
    if op == "write":
        return write(user_id, path, str(args.get("content") or ""))
    if op == "edit":
        return edit(user_id, path, str(args.get("old_string") or ""), str(args.get("new_string") or ""))
    if op in ("delete", "rm"):
        return delete(user_id, path)
    if op == "grep":
        return grep(user_id, str(args.get("pattern") or ""), path, str(args.get("glob") or ""))
    if op == "glob":
        return glob_paths(user_id, str(args.get("pattern") or ""), path)
    if op in ("run", "python"):
        argv = args.get("argv") or []
        if not isinstance(argv, list):
            argv = []
        return run_python(user_id, path, argv)
    if op in ("pip", "pip_install"):
        packages = args.get("packages") or args.get("package") or []
        if isinstance(packages, str):
            packages = [packages]
        if not isinstance(packages, list):
            packages = []
        return pip_install(user_id, packages)
    if op in ("deliverables", "collect"):
        try:
            since = float(args.get("since") or 0)
        except (TypeError, ValueError):
            since = 0
        return collect_deliverables(user_id, since)
    return f"Неизвестная операция {op}."
