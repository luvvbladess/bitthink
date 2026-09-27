import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth import get_current_user
from app.config import get_settings
from app.core.repository import repo
from app.models.schemas import ConnectorCreate, ConnectorOut
from app.services import connectors as connector_store
from app.services import google_oauth

logger = logging.getLogger(__name__)

router = APIRouter()


async def _account_uid(user_id: str) -> int:
    return await repo.ensure_user(user_id)


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(user_id: str = Depends(get_current_user)):
    account_uid = await _account_uid(user_id)
    return connector_store.list_public(account_uid)


@router.post("", response_model=ConnectorOut)
async def create_connector(data: ConnectorCreate, user_id: str = Depends(get_current_user)):
    account_uid = await _account_uid(user_id)
    try:
        return connector_store.create_connector(account_uid, data.type, data.name, data.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/google/start")
async def google_start(origin: str = "", user_id: str = Depends(get_current_user)):
    if not google_oauth.configured():
        raise HTTPException(status_code=503, detail="Подключение Google пока не настроено")
    # Google only accepts redirect URIs registered in the Cloud console,
    # so a forged origin cannot send the code anywhere else.
    app_url = (get_settings().PUBLIC_APP_URL or origin).rstrip("/")
    if not app_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise HTTPException(status_code=400, detail="Не удалось определить адрес сайта")
    account_uid = await _account_uid(user_id)
    url, nonce = google_oauth.start(account_uid, app_url)
    response = JSONResponse({"url": url})
    response.set_cookie(
        google_oauth.NONCE_COOKIE,
        nonce,
        max_age=google_oauth.STATE_TTL_SECONDS,
        httponly=True,
        secure=app_url.startswith("https://"),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    try:
        data = google_oauth.read_state(state, request.cookies.get(google_oauth.NONCE_COOKIE))
    except google_oauth.GoogleAuthError:
        return RedirectResponse("/settings?google=expired")
    if error or not code:
        result = "denied"
    else:
        try:
            row = await google_oauth.finish(data, code)
            result = "partial" if row["missing_scopes"] else "connected"
        except Exception:
            logger.exception("Google OAuth callback failed")
            result = "error"
    response = RedirectResponse(data["app"] + "/settings?google=" + result)
    response.delete_cookie(google_oauth.NONCE_COOKIE, path="/")
    return response


@router.delete("/{connector_id}")
async def delete_connector(connector_id: int, user_id: str = Depends(get_current_user)):
    account_uid = await _account_uid(user_id)
    try:
        loaded = connector_store.get_secret(account_uid, connector_id)
    except ValueError:
        loaded = None
    if loaded and loaded[0].type == "google":
        await google_oauth.revoke(loaded[1])
    ok = connector_store.delete_connector(account_uid, connector_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    return {"ok": True}
