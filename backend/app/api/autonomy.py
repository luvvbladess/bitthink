import asyncio
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user, require_admin
from app.core.repository import repo
from app.services.autonomy import CHARTER, recall

router = APIRouter(prefix='/autonomy', tags=['autonomy'])


@router.get('/identity')
async def identity(_: str = Depends(get_current_user)):
    return CHARTER


@router.get('/lessons')
async def lessons(query: str = '', user: str = Depends(get_current_user)):
    uid = await repo.ensure_user(user)
    return {'lessons': await asyncio.to_thread(recall, uid, query[:1000], 10)}


@router.get('/maintenance')
async def maintenance(_: str = Depends(require_admin)):
    from app.config import get_settings
    import json
    path = get_settings().DATA_DIR / 'autonomy' / 'maintenance-status.json'
    if not path.is_file():
        return {'status': 'not_configured', 'mutable_paths': ['backend/app/services/product_strategy.py']}
    try:
        return json.loads(await asyncio.to_thread(path.read_text, encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Не удалось прочитать журнал самообслуживания.') from exc
