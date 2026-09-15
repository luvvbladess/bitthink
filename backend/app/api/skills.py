from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.core.repository import repo
from app.models.schemas import SkillCreate, SkillOut, SkillUpdate, SkillsListOut
from computer_skills.loader import builtin_catalog
from computer_skills.store import MAX_SKILLS, public_skill

router = APIRouter()


def _custom_out(row: dict) -> SkillOut:
    data = public_skill(row, origin="custom")
    data["updated_at"] = int(row.get("updated_at") or 0)
    data["scope"] = "chat"
    return SkillOut(**data)


def _builtin_out(item: dict) -> SkillOut:
    return SkillOut(
        name=item["name"],
        title=item.get("title") or item["name"],
        description=item.get("description") or "",
        body="",
        triggers="",
        enabled=True,
        origin="builtin",
        scope=item.get("scope") or "sandbox",
        updated_at=0,
    )


@router.get("", response_model=SkillsListOut)
async def list_skills(user_id: str = Depends(get_current_user)):
    custom = await repo.list_user_skills(user_id)
    items = [_builtin_out(item) for item in builtin_catalog()]
    items.extend(_custom_out(row) for row in custom)
    return SkillsListOut(items=items, custom_count=len(custom), custom_limit=MAX_SKILLS)


@router.post("", response_model=SkillOut)
async def create_skill(payload: SkillCreate, user_id: str = Depends(get_current_user)):
    try:
        row = await repo.save_user_skill(
            user_id,
            name=payload.name,
            title=payload.title or "",
            description=payload.description,
            body=payload.body,
            triggers=payload.triggers or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _custom_out(row)


@router.patch("/{name}", response_model=SkillOut)
async def update_skill(name: str, payload: SkillUpdate, user_id: str = Depends(get_current_user)):
    try:
        row = await repo.save_user_skill(
            user_id,
            name=name,
            title=payload.title,
            description=payload.description,
            body=payload.body,
            triggers=payload.triggers,
            enabled=payload.enabled,
            partial=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Скил не найден. Общие скилы менять нельзя — добавьте свой.")
    return _custom_out(row)


@router.delete("/{name}")
async def delete_skill(name: str, user_id: str = Depends(get_current_user)):
    try:
        ok = await repo.delete_user_skill(user_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Скил не найден")
    return {"ok": True}
