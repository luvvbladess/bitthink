"""Which conversation an in-flight reply belongs to.

Tool calls and file lookups must follow this id, not whichever chat the user
opens while the answer is still generating.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_turn_conversation_id: ContextVar[str | None] = ContextVar("turn_conversation_id", default=None)


def turn_conversation_id() -> str | None:
    return _turn_conversation_id.get()


@contextmanager
def turn_conversation(conv_id: str | None) -> Iterator[None]:
    token = _turn_conversation_id.set(conv_id or None)
    try:
        yield
    finally:
        _turn_conversation_id.reset(token)


# bot_core is on sys.path, so `import turn_scope` and `import app.bot_core.turn_scope`
# would otherwise be two modules and two context vars. Keep a single one.
import sys

sys.modules.setdefault("turn_scope", sys.modules[__name__])
sys.modules.setdefault("app.bot_core.turn_scope", sys.modules[__name__])
