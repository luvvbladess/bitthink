"""Authenticated, bounded browser diagnostics with no raw messages or stack."""
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.auth import get_current_user, require_admin

router = APIRouter()
log = logging.getLogger('bitthink.client_error')
recent = defaultdict(deque)


class Frame(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,100}\.js$')
    line: int = Field(ge=0, le=10000000)
    column: int = Field(ge=0, le=10000000)


class ClientError(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_id: uuid.UUID
    category: Literal['render', 'chunk', 'unhandled']
    route: Literal['/', '/chat', '/settings', '/billing', '/login', '/register', '/privacy', '/admin', '/admin/users', '/admin/users/:id', '/admin/stats', '/join/:token', '/other']
    build: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,120}$')
    frames: list[Frame] = Field(default_factory=list, max_length=4)


@router.post('/client-error')
async def client_error(data: ClientError, user: str = Depends(get_current_user)):
    account = hashlib.sha256(user.encode()).hexdigest()[:16]
    now = time.monotonic()
    if len(recent) > 10000:
        for key in list(recent):
            if not recent[key] or recent[key][-1] < now - 60:
                del recent[key]
    queue = recent[account]
    while queue and queue[0] < now - 60:
        queue.popleft()
    if len(queue) >= 10:
        raise HTTPException(429, 'Too many diagnostic reports')
    queue.append(now)
    log.warning('client_error %s', json.dumps({**data.model_dump(mode='json'), 'account': account}, ensure_ascii=True))
    return {'report_id': str(data.report_id)}


class Measurement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['interaction', 'conversation_open', 'list_load', 'history_load', 'first_token', 'reconnect', 'disconnect']
    value: int = Field(ge=0, le=600000)
    device: Literal['mobile', 'desktop']


class Measurements(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metrics: list[Measurement] = Field(min_length=1, max_length=20)


@router.post('/performance')
async def performance(data: Measurements, user: str = Depends(get_current_user)):
    import asyncio
    from app.domains.experience import record
    account = 'performance:' + hashlib.sha256(user.encode()).hexdigest()[:16]
    now = time.monotonic()
    queue = recent[account]
    while queue and queue[0] < now - 60:queue.popleft()
    if len(queue) >= 12:raise HTTPException(429, 'Too many measurements')
    queue.append(now)
    for metric in data.metrics:await asyncio.to_thread(record, metric.name, metric.value, metric.device)
    return {'ok': True}


@router.get('/performance')
async def performance_summary(_: str = Depends(require_admin)):
    import asyncio
    from app.domains.experience import summary
    return {'days': 7, 'metrics': await asyncio.to_thread(summary)}
