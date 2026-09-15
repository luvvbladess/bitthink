import json
import os
import sys
from functools import lru_cache
from pathlib import Path

# Project root: locally it is backend/app -> backend -> project_root.
# In the Docker image backend contents are copied to /app, so app/config.py lives
# at /app/app/config.py and the project root is /app.
_config_dir = Path(__file__).resolve().parent
_backend_or_app = _config_dir.parent
if _backend_or_app.name == "backend":
    PROJECT_ROOT = _backend_or_app.parent
else:
    PROJECT_ROOT = _backend_or_app

# Add the vendored bot core package to sys.path so that legacy top-level imports
# (e.g. `import config`, `from handlers.core import ...`) resolve inside the web
# project instead of relying on an external Telegram bot checkout.
BOT_CORE_DIR = Path(__file__).resolve().parent / "bot_core"
if str(BOT_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_CORE_DIR))

# Load project root .env into environment before bot config imports.
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv(PROJECT_ROOT / ".env")


def _default_database_url(project_root: Path) -> str:
    """Use SQLite by default for local dev; PostgreSQL is recommended for production."""
    sqlite_path = project_root / "data" / "gpt_ultra.db"
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{sqlite_path.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Bit-Think"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    # Short-lived on purpose: no server-side revocation list exists (see repository.py),
    # so a leaked/forged token's blast radius is bounded by this TTL. Frontend refreshes
    # transparently via /auth/refresh (see frontend/src/api/client.ts).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days
    ALGORITHM: str = "HS256"
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    DATABASE_URL: str = _default_database_url(PROJECT_ROOT)
    UPLOAD_DIR: Path = Path(__file__).resolve().parent.parent / "uploads"
    DATA_DIR: Path = PROJECT_ROOT / "data"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or isinstance(value, list):
            return value
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
