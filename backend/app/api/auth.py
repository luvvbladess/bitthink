import asyncio
import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token_for_user,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    is_legacy_hash,
    rate_limit_auth,
    verify_password,
)
from app.avatars import delete_avatar as remove_avatar_files
from app.avatars import public_avatar_url, save_avatar, sniff_ext
from app.core.repository import repo
from app.db.engine import get_db
from app.db.models import User
from app.models.schemas import UserRegister, UserLogin, TokenResponse, UserProfile, ProfileUpdate

router = APIRouter()

MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _bot_user_id(email: str) -> int:
    """Deterministic mapping from email to bot integer id."""
    digest = hashlib.sha256(email.encode()).hexdigest()
    return 1_000_000_000 + (int(digest[:12], 16) % 1_000_000_000)


@router.post("/register", response_model=TokenResponse, dependencies=[Depends(rate_limit_auth)])
async def register(data: UserRegister, session: AsyncSession = Depends(get_db)):
    result = await session.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name or data.email.split("@")[0],
        role="user",
        bot_user_id=_bot_user_id(data.email),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    await repo.ensure_user(data.email, {"first_name": data.first_name, "username": data.email})

    access = create_access_token_for_user(user.email, user.role)
    refresh = create_refresh_token({"sub": user.email})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit_auth)])
async def login(data: UserLogin, session: AsyncSession = Depends(get_db)):
    result = await session.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if is_legacy_hash(user.password_hash):
        user.password_hash = hash_password(data.password)
        await session.commit()

    await repo.ensure_user(data.email)

    access = create_access_token_for_user(user.email, user.role)
    refresh = create_refresh_token({"sub": user.email})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(token_data: dict, session: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(token_data.get("refresh_token", ""), expected_type="refresh")
        email = payload["sub"]
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        access = create_access_token_for_user(user.email, user.role)
        refresh = create_refresh_token({"sub": user.email})
        return TokenResponse(access_token=access, refresh_token=refresh)
    except HTTPException:
        raise


@router.get("/me", response_model=UserProfile)
async def me(user_id: str = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    result = await session.execute(select(User).where(User.email == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    profile = await repo.get_profile(user_id)
    subscription = await repo.get_subscription(user_id)
    model = await repo.get_user_model(user_id)
    avatar_url = await asyncio.to_thread(public_avatar_url, user.id)
    if (user.avatar_url or None) != avatar_url:
        user.avatar_url = avatar_url
        await session.commit()
    return UserProfile(
        id=user.email,
        email=user.email,
        # user.first_name is the real, user-editable value (see PATCH /profile below).
        # profile["first_name"] is a legacy bot-profile placeholder ("User {id}")
        # that's always truthy, so it must only be a fallback, never take priority.
        first_name=user.first_name or profile.get("first_name"),
        avatar_url=avatar_url,
        subscription_tier=subscription.get("tier", "free"),
        selected_model=model,
        expires_at=subscription.get("expires_at", 0),
        role=user.role,
    )


@router.patch("/profile", response_model=UserProfile)
async def update_profile(
    data: ProfileUpdate,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(User).where(User.email == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.first_name = data.first_name.strip()
    await session.commit()
    return await me(user_id, session)


@router.post("/avatar", response_model=UserProfile)
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл больше 5 МБ")
    ext = sniff_ext(data, file.content_type)
    if not ext:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Поддерживаются только JPEG, PNG и WebP")

    result = await session.execute(select(User).where(User.email == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.avatar_url = await asyncio.to_thread(save_avatar, user.id, ext, data)
    await session.commit()
    return await me(user_id, session)


@router.delete("/avatar", response_model=UserProfile)
async def delete_avatar(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(User).where(User.email == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await asyncio.to_thread(remove_avatar_files, user.id)
    user.avatar_url = None
    await session.commit()
    return await me(user_id, session)
