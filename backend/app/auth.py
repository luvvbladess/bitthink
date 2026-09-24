import hashlib
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status, WebSocketException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.config import get_settings

security = HTTPBearer(auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(plain.encode(), hashed.encode())
        except ValueError:
            return False
    # Legacy SHA256+salt hashes ("salt:digest"), still present for users who
    # haven't logged in since the bcrypt migration. api/auth.py rehashes to
    # bcrypt on their next successful login.
    if ":" in hashed:
        salt, digest = hashed.split(":", 1)
        return secrets.compare_digest(hashlib.sha256((plain + salt).encode()).hexdigest(), digest)
    return False


def is_legacy_hash(hashed: str) -> bool:
    return not hashed.startswith(("$2a$", "$2b$", "$2y$"))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ponytail: in-memory fixed-window limiter, per-process. Fine as long as the
# app runs as a single uvicorn worker (see docker-compose.yml); move to a
# Redis-backed limiter before scaling to multiple workers/replicas.
_RATE_LIMIT_ATTEMPTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 60
_login_attempts: dict[str, list[float]] = defaultdict(list)


async def rate_limit_auth(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _login_attempts[ip]
    while window and now - window[0] > _RATE_LIMIT_WINDOW_SECONDS:
        window.pop(0)
    if len(window) >= _RATE_LIMIT_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts, try again later",
        )
    window.append(now)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token_for_user(email: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    return create_access_token({"sub": email, "role": role}, expires_delta)


def create_refresh_token(data: dict) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, *, expected_type: Optional[str] = None) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise JWTError("No subject")
        if expected_type is not None and payload.get("type") != expected_type:
            raise JWTError("Wrong token type")
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, expected_type="access")
    return payload["sub"]


async def get_current_user_ws(token: str) -> str:
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
    payload = decode_token(token, expected_type="access")
    return payload["sub"]


async def require_admin(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, expected_type="access")
    email = payload["sub"]
    from sqlalchemy import select
    from app.db.engine import AsyncSessionLocal
    from app.db.models import User

    async with AsyncSessionLocal() as session:
        account = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if account is None or account.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return email
