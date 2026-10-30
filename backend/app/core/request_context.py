"""Immutable per-generation choices, inherited by tool/thread calls."""
from contextvars import ContextVar

generation_preferences: ContextVar[dict | None] = ContextVar('generation_preferences', default=None)
generation_instructions: ContextVar[dict | None] = ContextVar('generation_instructions', default=None)


def preference(user_id, field):
    current = generation_preferences.get()
    return (True, current.get(field)) if current and current.get('user_id') == user_id else (False, None)
