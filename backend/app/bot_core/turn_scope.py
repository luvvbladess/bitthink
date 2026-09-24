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


# Files the reply decided to hand over. None: no decision, everything the
# sandbox produced goes out (the behaviour of every mode except Pilot).
_chosen_deliverables: ContextVar[tuple[str, ...] | None] = ContextVar("chosen_deliverables", default=None)


def choose_deliverables(names: list[str] | None) -> None:
    _chosen_deliverables.set(tuple(names) if names else None)


def pick_deliverables(files: list[dict]) -> list[dict]:
    """Keep only the chosen files. An empty result would lose the work, so then keep all."""
    chosen = _chosen_deliverables.get()
    _chosen_deliverables.set(None)
    if not chosen:
        return files
    wanted = {name.casefold() for name in chosen}
    picked = [item for item in files if str(item.get("filename") or "").casefold() in wanted]
    return picked or files


# bot_core is on sys.path, so `import turn_scope` and `import app.bot_core.turn_scope`
# would otherwise be two modules and two context vars. Keep a single one.
import sys

sys.modules.setdefault("turn_scope", sys.modules[__name__])
sys.modules.setdefault("app.bot_core.turn_scope", sys.modules[__name__])
