import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response

from app.auth import get_current_user
from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.core.repository import repo
from app.models.schemas import SkillCreate, SkillOut, SkillUpdate, SkillsListOut
from computer_skills.loader import builtin_catalog
from computer_skills.store import MAX_SKILLS, public_skill

router = APIRouter()


@router.get('/templates')
async def skill_templates(user_id: str = Depends(get_current_user)):
    from computer_skills.adaptations import templates
    return {'items': templates()}


@router.post('/templates/{name}', response_model=SkillOut)
async def add_template(name: str, user_id: str = Depends(get_current_user)):
    from computer_skills.adaptations import install_template
    try:
        row = await asyncio.to_thread(install_template, await repo.ensure_user(user_id), name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _custom_out(row)


@router.post("/import")
async def import_skill(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    from app.services.skill_packages import import_package, MAX_PACKAGE
    data = await file.read(MAX_PACKAGE + 1)
    try:
        return await asyncio.to_thread(import_package, await repo.ensure_user(user_id), data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{name}/export")
async def export_skill(name: str, user_id: str = Depends(get_current_user)):
    from app.services.skill_packages import export_package
    from computer_skills.store import normalize_name
    name = normalize_name(name)
    data = await asyncio.to_thread(export_package, await repo.ensure_user(user_id), name)
    if data is None:
        raise HTTPException(404, "Скил не найден.")
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


@router.get("/{name}/resources/{path:path}")
async def skill_resource(name: str, path: str, user_id: str = Depends(get_current_user)):
    from app.services.skill_packages import read_resource
    try:
        data = await asyncio.to_thread(read_resource, await repo.ensure_user(user_id), name, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if data is None:
        raise HTTPException(404, "Ресурс не найден.")
    return Response(data, media_type="application/octet-stream")


def _custom_out(row: dict) -> SkillOut:
    data = public_skill(row, origin="custom")
    data["updated_at"] = int(row.get("updated_at") or 0)
    data["scope"] = "chat"
    return SkillOut(**data)


def _builtin_out(item: dict, enabled: bool = True) -> SkillOut:
    return SkillOut(
        name=item["name"],
        title=item.get("title") or item["name"],
        description=item.get("description") or "",
        body="",
        triggers="",
        enabled=enabled,
        origin="builtin",
        scope=item.get("scope") or "sandbox",
        updated_at=0,
    )


@router.get("", response_model=SkillsListOut)
async def list_skills(user_id: str = Depends(get_current_user)):
    custom = await repo.list_user_skills(user_id)
    off = await repo.disabled_builtin_skills(user_id)
    items = [_builtin_out(item, item["name"] not in off) for item in builtin_catalog()]
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
    builtin = next((item for item in builtin_catalog() if item["name"] == name.strip().lower()), None)
    if builtin is not None:
        # Common skills can't be edited, only switched on and off.
        if payload.enabled is None:
            raise HTTPException(status_code=400, detail="Общий скил можно только включить или выключить.")
        await repo.set_builtin_skill_enabled(user_id, builtin["name"], payload.enabled)
        return _builtin_out(builtin, payload.enabled)
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
