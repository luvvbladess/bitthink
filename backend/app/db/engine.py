from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

settings = get_settings()

# Async engine for FastAPI endpoints
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Sync engine for bot core (ConversationManager is synchronous)
if settings.DATABASE_URL.startswith("sqlite"):
    sync_url = settings.DATABASE_URL.replace("+aiosqlite", "")
    sync_engine = create_engine(
        sync_url,
        echo=settings.DEBUG,
        future=True,
    )
elif settings.DATABASE_URL.startswith("postgresql+asyncpg"):
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
    sync_engine = create_engine(
        sync_url,
        echo=settings.DEBUG,
        future=True,
    )
else:
    raise ValueError(f"Unsupported DATABASE_URL scheme: {settings.DATABASE_URL}")

SyncSessionLocal = sessionmaker(
    sync_engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
