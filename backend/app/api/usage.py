from datetime import datetime
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.core.repository import repo

router = APIRouter()


@router.get("/day")
async def day_usage(user_id: str = Depends(get_current_user)):
    today = datetime.now().strftime("%Y-%m-%d")
    usage = await repo.get_day_usage(user_id, today)
    return {"date": today, "usage": usage}


@router.get("/month")
async def month_usage(user_id: str = Depends(get_current_user)):
    month = datetime.now().strftime("%Y-%m")
    usage = await repo.get_month_usage(user_id, month)
    return {"month": month, "usage": usage}
