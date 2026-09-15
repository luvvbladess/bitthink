from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.core.repository import repo
from app.models.schemas import ConnectorCreate, ConnectorOut
from app.services import connectors as connector_store

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


@router.delete("/{connector_id}")
async def delete_connector(connector_id: int, user_id: str = Depends(get_current_user)):
    account_uid = await _account_uid(user_id)
    ok = connector_store.delete_connector(account_uid, connector_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    return {"ok": True}
