"""Вход в общий диалог по ссылке."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.core.repository import repo

router = APIRouter()


@router.post("/{token}/join")
async def join_shared_conversation(token: str, user_id: str = Depends(get_current_user)):
    bot_id = await repo.ensure_user(user_id)
    joined = await asyncio.to_thread(repo._manager.join_share, bot_id, token)
    if not joined:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка недействительна")
    return joined
