import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import models as _db_models  # noqa: F401 — register tables for create_all
from app.api import admin, auth, chat, conversations, models_router, documents, editor, media, billing, usage, connectors, memory, skills, share
from app.db.base import Base
from app.db.engine import sync_engine


def _ensure_runtime_tables() -> None:
    from sqlalchemy import inspect, text

    from app.db.models import ConversationAside, ConversationMember, ConversationShare, EditorDocument, UserSkill

    UserSkill.__table__.create(bind=sync_engine, checkfirst=True)
    EditorDocument.__table__.create(bind=sync_engine, checkfirst=True)
    ConversationShare.__table__.create(bind=sync_engine, checkfirst=True)
    ConversationMember.__table__.create(bind=sync_engine, checkfirst=True)
    ConversationAside.__table__.create(bind=sync_engine, checkfirst=True)
    inspector = inspect(sync_engine)
    if "messages" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("messages")}
        if "author_user_id" not in columns:
            with sync_engine.begin() as connection:
                connection.execute(text("ALTER TABLE messages ADD COLUMN author_user_id BIGINT"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (settings.UPLOAD_DIR / "avatars").mkdir(parents=True, exist_ok=True)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Create DB tables for SQLite dev mode; for PostgreSQL use Alembic in production
    if settings.DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=sync_engine)
    _ensure_runtime_tables()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if not settings.DEBUG and settings.SECRET_KEY == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is still the default placeholder. Set a random SECRET_KEY "
            "in .env before running with DEBUG=false (JWTs can otherwise be forged)."
        )
    app = FastAPI(
        title=settings.APP_NAME,
        lifespan=lifespan,
        debug=settings.DEBUG,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(admin.router, tags=["admin"])
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
    app.include_router(share.router, prefix="/share", tags=["share"])
    app.include_router(chat.router, prefix="/chat", tags=["chat"])
    app.include_router(models_router.router, prefix="/models", tags=["models"])
    app.include_router(documents.router, prefix="/documents", tags=["documents"])
    app.include_router(editor.router, prefix="/editor", tags=["editor"])
    app.include_router(media.router, prefix="/media", tags=["media"])
    app.include_router(billing.router, prefix="/billing", tags=["billing"])
    app.include_router(usage.router, prefix="/usage", tags=["usage"])
    app.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
    app.include_router(memory.router, prefix="/memory", tags=["memory"])
    app.include_router(skills.router, prefix="/skills", tags=["skills"])

    # Chat and generated files are stored as sha256(email)[:16]/uuid.hex.ext.
    # Anything else under those trees is not a file we wrote.
    _PRIVATE_UPLOAD = re.compile(
        r"^/uploads/(?:chat|generated)/[0-9a-f]{16}/[0-9a-f]{32}\.[A-Za-z0-9]{1,10}$"
    )

    @app.middleware("http")
    async def cache_avatars(request, call_next):
        path = request.url.path
        # Originals for document styling live on disk for the parser only.
        if path.startswith("/uploads/docgen_sources/"):
            from fastapi.responses import Response

            return Response(status_code=404)
        if path.startswith("/uploads/chat/") or path.startswith("/uploads/generated/"):
            if not _PRIVATE_UPLOAD.match(path):
                from fastapi.responses import Response

                return Response(status_code=404)
        response = await call_next(request)
        if path.startswith("/uploads/avatars/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/uploads/") and not path.startswith("/uploads/avatars/") and response.status_code == 200:
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.mount("/uploads", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="uploads")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
