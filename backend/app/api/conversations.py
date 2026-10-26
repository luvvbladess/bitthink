import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.domains import conversations as library

from app.auth import get_current_user
from app.core.repository import repo
from app.models.schemas import AsideCreate, AsideOut, ConversationCreate, ConversationRename, ConversationOut, MessageOut

router = APIRouter()


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user_id: str = Depends(get_current_user), limit: int | None = Query(None, ge=1, le=200), offset: int = Query(0, ge=0)):
    return await asyncio.to_thread(library.summaries, repo._bot_id(user_id), limit, offset)


@router.get('/search')
async def search_conversations(q: str = Query('', max_length=200), offset: int = Query(0, ge=0), user_id: str = Depends(get_current_user)):
    return await asyncio.to_thread(library.search, repo._bot_id(user_id), q, 30, offset)


@router.get('/trash')
async def trash_conversations(user_id: str = Depends(get_current_user), offset: int = Query(0, ge=0)):
    return await asyncio.to_thread(library.summaries, repo._bot_id(user_id), 50, offset, True)


@router.post('/{conv_id}/restore')
async def restore_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    if not await asyncio.to_thread(library.trash, repo._bot_id(user_id), conv_id, True):
        raise HTTPException(404, 'Беседа не найдена или срок восстановления истёк')
    return {'ok': True}


@router.get('/{conv_id}/history')
async def conversation_history(conv_id: str, limit: int = Query(80, ge=1, le=100), before: int | None = Query(None, ge=1), around: int | None = Query(None, ge=1), user_id: str = Depends(get_current_user)):
    try:
        return await asyncio.to_thread(library.history, repo._bot_id(user_id), conv_id, limit, before, around)
    except PermissionError:
        raise HTTPException(404, 'Беседа недоступна')
    except ValueError:
        raise HTTPException(404, 'Сообщение не найдено')


@router.get('/{conv_id}/summary', response_model=ConversationOut)
async def conversation_summary(conv_id: str, user_id: str = Depends(get_current_user)):
    rows = await asyncio.to_thread(library.summaries, repo._bot_id(user_id), 1, 0, False, conv_id)
    if not rows:raise HTTPException(404, 'Беседа недоступна')
    return rows[0]


@router.post("", response_model=ConversationOut)
async def create_conversation(data: ConversationCreate, user_id: str = Depends(get_current_user)):
    return await repo.create_conversation(user_id, title=data.title)


@router.get("/library")
async def library_files(user_id: str = Depends(get_current_user)):
    """Библиотека: файлы из всех бесед пользователя, свежие сверху."""
    from app.api.editor import conversation_files

    bot_id = await repo.ensure_user(user_id)

    def collect() -> list[dict]:
        # ponytail: читает все беседы разом; при сотнях бесед – отдельный запрос по вложениям.
        items = [
            {**item, "conversation_id": conv.id, "conversation_title": conv.title}
            for conv in repo.conversations.list(bot_id)
            for item in conversation_files(conv)
        ]
        items.sort(key=lambda f: str(f["edited_at"] or f["uploaded_at"]), reverse=True)
        return items

    return await asyncio.to_thread(collect)


@router.get("/{conv_id}/files")
async def list_conversation_files(conv_id: str, user_id: str = Depends(get_current_user)):
    from app.api.editor import _conversation_for, conversation_files

    _, conv = await _conversation_for(user_id, conv_id)
    return await asyncio.to_thread(conversation_files, conv)


@router.get("/{conv_id}/files/download")
async def download_conversation_file(conv_id: str, t: str = ""):
    """По ссылке из списка файлов: её выдают только участникам беседы, живёт час."""
    import mimetypes
    from urllib.parse import quote

    from fastapi.responses import Response

    from app.api.editor import check_file_link, file_bytes

    linked_conv, filename = check_file_link(t)
    if linked_conv != conv_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ссылка недействительна")
    owner = await asyncio.to_thread(repo.conversations.owner, conv_id)
    conv = await asyncio.to_thread(repo.conversations.view, owner, conv_id) if owner else None
    data = await asyncio.to_thread(file_bytes, conv, filename) if conv else None
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    media = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "Cache-Control": "private, no-store"},
    )


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
    from app.services.generation_store import cancel
    ok = await asyncio.to_thread(library.trash, repo._bot_id(user_id), conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    await asyncio.to_thread(cancel, user_id, conv_id)
    return {"ok": True}


@router.post("/{conv_id}/clear")
async def clear_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    ok = await repo.clear_conversation(user_id, conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.get("/{conv_id}/share")
async def share_status(conv_id: str, user_id: str = Depends(get_current_user)):
    bot_id = await repo.ensure_user(user_id)
    status_payload = await asyncio.to_thread(repo.sharing.status, bot_id, conv_id)
    if status_payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return status_payload


@router.post("/{conv_id}/share")
async def create_share(conv_id: str, user_id: str = Depends(get_current_user)):
    bot_id = await repo.ensure_user(user_id)
    token = await asyncio.to_thread(repo.sharing.create, bot_id, conv_id)
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return await asyncio.to_thread(repo.sharing.status, bot_id, conv_id)


@router.delete("/{conv_id}/share")
async def revoke_share(conv_id: str, user_id: str = Depends(get_current_user)):
    bot_id = await repo.ensure_user(user_id)
    ok = await asyncio.to_thread(repo.sharing.revoke, bot_id, conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.get("/{conv_id}/asides", response_model=list[AsideOut])
async def list_asides(conv_id: str, user_id: str = Depends(get_current_user)):
    """Людская переписка внутри беседы. В контекст ассистента не попадает."""
    bot_id = await repo.ensure_user(user_id)
    rows = await asyncio.to_thread(repo.asides.list, bot_id, conv_id)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return rows


@router.post("/{conv_id}/asides", response_model=AsideOut)
async def post_aside(conv_id: str, data: AsideCreate, user_id: str = Depends(get_current_user)):
    bot_id = await repo.ensure_user(user_id)
    row = await asyncio.to_thread(repo.asides.add, bot_id, conv_id, data.content)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    await repo.notify_room(conv_id)
    return row


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
    from app.services.generation_hub import hub

    if hub.is_running(user_id, conv_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Дождитесь окончания ответа или остановите его, затем отредактируйте сообщение.",
        )
    try:
        ok = await repo.truncate_messages(user_id, conv_id, keep_count)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}
