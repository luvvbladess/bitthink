from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.core.repository import repo
from app.models.schemas import ConversationCreate, ConversationRename, ConversationOut, MessageOut

router = APIRouter()


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user_id: str = Depends(get_current_user)):
    return await repo.get_conversations(user_id)


@router.post("", response_model=ConversationOut)
async def create_conversation(data: ConversationCreate, user_id: str = Depends(get_current_user)):
    return await repo.create_conversation(user_id, title=data.title)


@router.post("/{conv_id}/activate")
async def activate_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    ok = await repo.set_active_conversation(user_id, conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.patch("/{conv_id}")
async def rename_conversation(conv_id: str, data: ConversationRename, user_id: str = Depends(get_current_user)):
    ok = await repo.rename_conversation(user_id, conv_id, data.title)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    ok = await repo.delete_conversation(user_id, conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.post("/{conv_id}/clear")
async def clear_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    ok = await repo.clear_conversation(user_id, conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def get_messages(conv_id: str, user_id: str = Depends(get_current_user)):
    messages = await repo.get_messages(user_id, conv_id)
    return messages


@router.post("/{conv_id}/messages/truncate")
async def truncate_messages(conv_id: str, data: dict, user_id: str = Depends(get_current_user)):
    """Drop every message after keep_count. Used by edit-and-resend on the
    frontend: rewind the conversation to just before the edited message."""
    keep_count = data.get("keep_count")
    if not isinstance(keep_count, int) or keep_count < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid keep_count")
    ok = await repo.truncate_messages(user_id, conv_id, keep_count)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}
