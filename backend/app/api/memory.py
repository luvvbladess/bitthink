from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.core.repository import repo
from app.memory import sanitize_notes, scrub_notes
from app.models.schemas import MemoryOut, MemoryUpdate

router = APIRouter()


def _public(data: dict) -> MemoryOut:
    return MemoryOut(
        notes=scrub_notes(data.get("notes") or ""),
        enabled=bool(data.get("enabled", True)),
        updated_at=int(data.get("updated_at") or 0),
    )


@router.get("", response_model=MemoryOut)
async def get_memory(user_id: str = Depends(get_current_user)):
    return _public(await repo.get_user_memory(user_id))


@router.patch("", response_model=MemoryOut)
async def update_memory(payload: MemoryUpdate, user_id: str = Depends(get_current_user)):
    fields: dict = {}
    if payload.enabled is not None:
        fields["enabled"] = payload.enabled
    if payload.notes is not None:
        fields["notes"] = sanitize_notes(payload.notes)
    return _public(await repo.save_user_memory(user_id, **fields))


@router.delete("", response_model=MemoryOut)
async def clear_memory(user_id: str = Depends(get_current_user)):
    return _public(await repo.save_user_memory(user_id, notes="", last_hash=""))
