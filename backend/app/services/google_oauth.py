"""Google account connected by button: OAuth flow and authorized calls for Pilot tools."""

from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
from jose import JWTError, jwt

from app.config import get_settings
from app.services import connectors as store

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    # Send only (no drafts, no delete) and Drive files this app creates.
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
)
CALLBACK_PATH = "/api/connectors/google/callback"
NONCE_COOKIE = "bt_google_oauth"
STATE_TTL_SECONDS = 600
RECONNECT = "Google отключён или доступ отозван. Пусть человек заново нажмёт «Подключить Google» в Настройках."

# ponytail: per-process cache, each worker refreshes on its own; fine for hourly tokens.
_access_cache: dict[str, tuple[str, float]] = {}


class GoogleAuthError(Exception):
    pass


def configured() -> bool:
    settings = get_settings()
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def start(account_uid: int, app_url: str) -> tuple[str, str]:
    """Consent URL plus the nonce the browser must carry back in a cookie."""
    settings = get_settings()
    app_url = app_url.rstrip("/")
    nonce = secrets.token_urlsafe(24)
    # No "sub" and its own type: decode_token() never accepts this as a login token.
    state = jwt.encode(
        {"typ": "google_oauth", "uid": account_uid, "app": app_url, "n": nonce, "exp": int(time.time()) + STATE_TTL_SECONDS},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": app_url + CALLBACK_PATH,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}", nonce


def read_state(state: str, nonce: str | None) -> dict[str, Any]:
    settings = get_settings()
    try:
        data = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise GoogleAuthError("state") from exc
    if data.get("typ") != "google_oauth" or not isinstance(data.get("uid"), int):
        raise GoogleAuthError("state")
    # The cookie proves this browser started the flow: a victim opening someone
    # else's consent link cannot attach their Google to that person's account.
    if not nonce or not secrets.compare_digest(str(data.get("n")), nonce):
        raise GoogleAuthError("nonce")
    return data


async def _post_token(form: dict[str, str]) -> dict[str, Any]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(TOKEN_URL, data=form) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                raise GoogleAuthError(str(body.get("error") or resp.status))
            return body


async def finish(state: dict[str, Any], code: str) -> dict[str, Any]:
    settings = get_settings()
    tokens = await _post_token({
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": state["app"] + CALLBACK_PATH,
        "grant_type": "authorization_code",
    })
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise GoogleAuthError("no_refresh_token")
    granted = set(str(tokens.get("scope") or "").split())
    missing = [scope for scope in SCOPES if scope.startswith("https://") and scope not in granted]
    access_token = str(tokens["access_token"])
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}) as resp:
            info = await resp.json(content_type=None) if resp.status == 200 else {}
    email = str(info.get("email") or "").strip() or "google"
    _access_cache[refresh_token] = (access_token, time.time() + int(tokens.get("expires_in") or 3600) - 60)
    row = store.upsert_connector(
        int(state["uid"]),
        "google",
        email,
        {"email": email, "refresh_token": refresh_token, "scopes": sorted(granted)},
    )
    return {**row, "missing_scopes": missing}


async def revoke(payload: dict[str, Any]) -> None:
    token = str(payload.get("refresh_token") or "")
    _access_cache.pop(token, None)
    if not token:
        return
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            await session.post(REVOKE_URL, data={"token": token})
    except aiohttp.ClientError:
        pass


async def access_token(payload: dict[str, Any]) -> str:
    refresh_token = str(payload.get("refresh_token") or "")
    cached = _access_cache.get(refresh_token)
    if cached and cached[1] > time.time():
        return cached[0]
    settings = get_settings()
    try:
        tokens = await _post_token({
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
    except GoogleAuthError as exc:
        _access_cache.pop(refresh_token, None)
        raise GoogleAuthError(RECONNECT) from exc
    token = str(tokens["access_token"])
    _access_cache[refresh_token] = (token, time.time() + int(tokens.get("expires_in") or 3600) - 60)
    return token


async def api(
    payload: dict[str, Any],
    method: str,
    url: str,
    *,
    params: Any = None,
    json_body: dict[str, Any] | None = None,
    raw: bool = False,
    max_bytes: int = 0,
    data: bytes | None = None,
    content_type: str = "",
) -> Any:
    """One authorized Google API call. raw=True returns bytes (Drive downloads);
    data + content_type send a raw body (Drive multipart uploads)."""
    token = await access_token(payload)
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.request(
            method, url, params=params, json=json_body, data=data, headers=headers
        ) as resp:
            if resp.status == 401:
                _access_cache.pop(str(payload.get("refresh_token") or ""), None)
                raise GoogleAuthError(RECONNECT)
            if resp.status >= 400:
                text = await resp.text(errors="replace")
                raise GoogleAuthError(f"Google API {resp.status}: {text[:300]}")
            if raw:
                too_big = f"Файл больше {max_bytes // (1024 * 1024)} МБ."
                if max_bytes and (resp.content_length or 0) > max_bytes:
                    raise GoogleAuthError(too_big)
                data = bytearray()
                async for chunk in resp.content.iter_chunked(1 << 16):
                    data += chunk
                    if max_bytes and len(data) > max_bytes:
                        raise GoogleAuthError(too_big)
                return bytes(data)
            return await resp.json(content_type=None)
