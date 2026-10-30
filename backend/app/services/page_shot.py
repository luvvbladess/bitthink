"""Render a public page in the sandbox Chromium and return one JPEG.

Desktop frame on top, phone frame below. The website chat otherwise only
receives HTML text, which does not show heading alignment or layout.
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

DESKTOP = (1280, 900)
MOBILE = (390, 844)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
MAX_JPEG = 700_000
_LOCK = threading.Lock()


def public_http_url(url: str) -> str:
    """Reject local, private and non-web targets before Chromium starts."""
    raw = (url or "").strip()
    if len(raw) > 2000:
        raise ValueError("Слишком длинный адрес")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Нужен обычный http(s) URL")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Нужен обычный http(s) URL")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost"} or host.endswith(".localhost") or host.endswith(".internal"):
        raise ValueError("Этот адрес недоступен для Оркестратора")
    try:
        if _blocked_ip(host):
            raise ValueError("Этот адрес недоступен для Оркестратора")
    except ValueError as exc:
        if "недоступен" in str(exc):
            raise
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Не удалось разрешить хост {host}") from exc
    if not infos or any(_blocked_ip(item[4][0]) for item in infos):
        raise ValueError("Этот адрес недоступен для Оркестратора")
    return raw


def _blocked_ip(value: str) -> bool:
    addr = ipaddress.ip_address(value)
    return bool(
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def _chromium() -> str:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    for path in ("/usr/lib/chromium/chromium", "/usr/bin/chromium"):
        if os.path.isfile(path):
            return path
    return ""


def _shoot(binary: str, url: str, width: int, height: int, dest: Path, home: Path, user_agent: str = "") -> None:
    profile = home / f"profile-{width}x{height}"
    profile.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home), "XDG_CACHE_HOME": str(home), "LANG": "C.UTF-8"})
    command = [
        binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
        "--no-zygote", "--single-process", "--disable-crash-reporter",
        "--disable-extensions", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
        "--disable-background-networking", "--virtual-time-budget=12000",
        f"--window-size={width},{height}", f"--user-data-dir={profile}",
    ]
    if user_agent:
        command.append(f"--user-agent={user_agent}")
    command.extend([f"--screenshot={dest}", url])
    try:
        subprocess.run(command, cwd=str(home), env=env, timeout=28, check=False, capture_output=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Страница не успела отрисоваться") from exc
    if not dest.is_file() or dest.stat().st_size < 800:
        fallback = home / "screenshot.png"
        if fallback.is_file() and fallback.stat().st_size >= 800:
            fallback.replace(dest)
            return
        raise RuntimeError("Браузер не сохранил кадр")


def compose_frames(desktop: bytes | None, mobile: bytes | None) -> tuple[bytes, int, int]:
    """Stack the two viewports into one JPEG the model can see in a single image."""
    from PIL import Image, ImageDraw

    frames = []
    for blob, label in ((desktop, "desktop 1280x900"), (mobile, "mobile 390x844")):
        if not blob:
            continue
        frame = Image.open(io.BytesIO(blob)).convert("RGB")
        frames.append((frame, label))
    if not frames:
        raise ValueError("Нет кадров страницы")
    gap = 36
    width = max(frame.width for frame, _ in frames)
    height = sum(frame.height for frame, _ in frames) + gap * len(frames)
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    top = 0
    for frame, label in frames:
        draw.rectangle((0, top, width, top + gap), fill=(243, 244, 246))
        draw.text((12, top + 10), label, fill=(20, 20, 20))
        top += gap
        canvas.paste(frame, ((width - frame.width) // 2, top))
        top += frame.height
    quality = 72
    blob = b""
    while quality >= 40:
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=quality, optimize=True)
        blob = out.getvalue()
        if len(blob) <= MAX_JPEG:
            break
        quality -= 8
    if len(blob) > MAX_JPEG:
        canvas = canvas.resize((max(1, canvas.width // 2), max(1, canvas.height // 2)))
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=60, optimize=True)
        blob = out.getvalue()
    return blob, canvas.width, canvas.height


def capture(url: str) -> str:
    """JSON for the backend: one JPEG, or an error the model can quote honestly."""
    try:
        target = public_http_url(url)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    binary = _chromium()
    if not binary:
        return json.dumps({"error": "В песочнице нет браузера для снимка страницы."}, ensure_ascii=False)
    desktop = mobile = None
    try:
        with _LOCK, tempfile.TemporaryDirectory(prefix="page-shot-") as folder:
            home = Path(folder)
            try:
                desk = home / "desktop.png"
                _shoot(binary, target, DESKTOP[0], DESKTOP[1], desk, home)
                desktop = desk.read_bytes()
            except Exception:
                desktop = None
            try:
                phone = home / "mobile.png"
                _shoot(binary, target, MOBILE[0], MOBILE[1], phone, home, MOBILE_UA)
                mobile = phone.read_bytes()
            except Exception:
                mobile = None
    except Exception as exc:
        return json.dumps({"error": f"Снимок страницы не сделан: {exc}"[:300]}, ensure_ascii=False)
    if not desktop and not mobile:
        return json.dumps({"error": "Страница не отрисовалась ни на десктопе, ни на телефоне."}, ensure_ascii=False)
    try:
        jpeg, width, height = compose_frames(desktop, mobile)
    except Exception as exc:
        return json.dumps({"error": f"Кадр не собран: {exc}"[:300]}, ensure_ascii=False)
    return json.dumps({
        "jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
        "width": width,
        "height": height,
        "desktop": bool(desktop),
        "mobile": bool(mobile),
    })
