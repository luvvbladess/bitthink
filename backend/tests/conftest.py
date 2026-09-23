import app.db.models  # noqa: F401 — register tables
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.engine import sync_engine


_POOL_COLUMNS = {
    "period_start": "ALTER TABLE subscriptions ADD COLUMN period_start VARCHAR(32)",
    "chat_tokens_used": "ALTER TABLE subscriptions ADD COLUMN chat_tokens_used BIGINT DEFAULT 0 NOT NULL",
    "computer_tokens_used": "ALTER TABLE subscriptions ADD COLUMN computer_tokens_used BIGINT DEFAULT 0 NOT NULL",
    "images_used": "ALTER TABLE subscriptions ADD COLUMN images_used INTEGER DEFAULT 0 NOT NULL",
    "nano_cushion_date": "ALTER TABLE subscriptions ADD COLUMN nano_cushion_date VARCHAR(32)",
    "nano_cushion_used": "ALTER TABLE subscriptions ADD COLUMN nano_cushion_used INTEGER DEFAULT 0 NOT NULL",
    "session_started_at": "ALTER TABLE subscriptions ADD COLUMN session_started_at BIGINT DEFAULT 0 NOT NULL",
    "session_chat_used": "ALTER TABLE subscriptions ADD COLUMN session_chat_used BIGINT DEFAULT 0 NOT NULL",
    "session_computer_used": "ALTER TABLE subscriptions ADD COLUMN session_computer_used BIGINT DEFAULT 0 NOT NULL",
    "week_start": "ALTER TABLE subscriptions ADD COLUMN week_start VARCHAR(32)",
    "week_chat_used": "ALTER TABLE subscriptions ADD COLUMN week_chat_used BIGINT DEFAULT 0 NOT NULL",
    "week_computer_used": "ALTER TABLE subscriptions ADD COLUMN week_computer_used BIGINT DEFAULT 0 NOT NULL",
}


_EXTRA_COLUMNS = {
    "subscriptions": _POOL_COLUMNS,
    "messages": {
        "attachment": "ALTER TABLE messages ADD COLUMN attachment TEXT",
        "search": "ALTER TABLE messages ADD COLUMN search TEXT",
        "author_user_id": "ALTER TABLE messages ADD COLUMN author_user_id BIGINT",
    },
}


def pytest_configure():
    Base.metadata.create_all(bind=sync_engine)
    inspector = inspect(sync_engine)
    with sync_engine.begin() as connection:
        for table, columns in _EXTRA_COLUMNS.items():
            if table not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(text(ddl))
