"""Immutable per-generation choices, inherited by tool/thread calls."""
from contextvars import ContextVar

generation_preferences: ContextVar[dict | None] = ContextVar('generation_preferences', default=None)


def preference(user_id, field):
    current = generation_preferences.get()
    return (True, current.get(field)) if current and current.get('user_id') == user_id else (False, None)
