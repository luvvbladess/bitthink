"""Private protocol for the home reader. No public fetch/enqueue endpoint."""
import secrets
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.marketplace_relay import MAX_CONTENT, home_relay

router = APIRouter()


def agent_auth(authorization: str = Header(default="")):
    token = get_settings().HOME_RELAY_TOKEN
    if not token or not secrets.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        raise HTTPException(401, "Home reader authentication required")


class Result(BaseModel):
    status: Literal["ok", "blocked", "error"]
    url: str = Field(max_length=4096)
    text: str = Field(default="", max_length=MAX_CONTENT)
    title: str = Field(default="", max_length=500)
    reader_version: str | None = Field(default=None,max_length=24)
    review_diagnostics: dict[str,str | int | bool] | None = Field(default=None,max_length=16)


class InspectRequest(BaseModel):
    url: str = Field(max_length=4096)


@router.post('/inspect', dependencies=[Depends(agent_auth)])
async def inspect_card(data: InspectRequest):
    # Authenticated diagnostics can only enqueue an already supported public
    # card. No arbitrary fetches, scripts, cookies or account pages.
    from marketplace_verification import public_shop_url
    found=public_shop_url(data.url)
    if not found or found[0] not in {'card','short'}:
        raise HTTPException(422,'Only public product cards can be inspected')
    return {'reader_version':home_relay.reader_version,'result':await home_relay.fetch(found[1])}


@router.get('/diagnostics', dependencies=[Depends(agent_auth)])
async def diagnostics(response: Response):
    response.headers['Cache-Control']='no-store'
    return {'online':home_relay.online,'reader_version':home_relay.reader_version,'recent':home_relay.recent_reads}


class Heartbeat(BaseModel):
    reader_version: str = Field(max_length=24,pattern=r'^\d+\.\d+\.\d+$')


@router.get("/status", dependencies=[Depends(agent_auth)])
async def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"online": home_relay.online, "pending": len(home_relay.jobs)}


@router.post("/heartbeat", dependencies=[Depends(agent_auth)])
async def heartbeat(data: Heartbeat | None = None):
    home_relay.reader_version=data.reader_version if data else None
    home_relay.heartbeat()
    return {"connected": True}


@router.post("/disconnect", dependencies=[Depends(agent_auth)])
async def disconnect():
    home_relay.disconnect()
    return {"connected": False}


@router.get("/jobs", dependencies=[Depends(agent_auth)])
async def pull(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"job": await home_relay.pull()}


@router.post("/jobs/{job_id}", dependencies=[Depends(agent_auth)])
async def complete(job_id: str, request: Request):
    # Enforce a streaming byte limit as well as the model's character limit.
    # This avoids accepting an unbounded request before Pydantic validation.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 512_000:
            raise HTTPException(413, "Reader result too large")
    try:
        result = Result.model_validate_json(body)
    except ValueError:
        raise HTTPException(422, "Invalid reader result")
    from web_scraper import is_ru_marketplace

    parsed = urlparse(result.url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not is_ru_marketplace(result.url):
        raise HTTPException(422, "Reader result must come from a public marketplace")
    if not home_relay.complete(job_id, result.model_dump(exclude_none=True)):
        raise HTTPException(410, "Reader job expired")
    return {"accepted": True}
