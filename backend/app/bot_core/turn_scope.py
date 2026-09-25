"""Which conversation an in-flight reply belongs to.

Tool calls and file lookups must follow this id, not whichever chat the user
opens while the answer is still generating.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable, Iterator

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
    """Keep only the chosen files. An empty result would lose the work, so then keep all.
    Files already posted mid-turn by deliver_now never go out twice."""
    chosen = _chosen_deliverables.get()
    _chosen_deliverables.set(None)
    sent = _delivered.get() or set()
    files = [item for item in files if str(item.get("filename") or "").casefold() not in sent]
    if not chosen:
        return files
    wanted = {name.casefold() for name in chosen}
    picked = [item for item in files if str(item.get("filename") or "").casefold() in wanted]
    return picked or files


# Posting a finished file into the chat before the reply ends (Pilot's
# one-document-at-a-time packages). The web chat binds a callback; the
# Telegram bot does not, and there files go out with the final reply.
_deliver: ContextVar[Callable[[str, list[dict]], Awaitable[None]] | None] = ContextVar("deliver_now", default=None)
_delivered: ContextVar[set[str] | None] = ContextVar("delivered", default=None)


@contextmanager
def delivery(callback: Callable[[str, list[dict]], Awaitable[None]]) -> Iterator[None]:
    # The set is created here, in the caller's context, so tasks spawned
    # below share the same object and pick_deliverables sees their marks.
    token = _deliver.set(callback)
    sent_token = _delivered.set(set())
    try:
        yield
    finally:
        _deliver.reset(token)
        _delivered.reset(sent_token)


async def deliver_now(text: str, files: list[dict]) -> bool:
    """Post files as their own chat message now. False: nothing bound, keep them for the reply."""
    callback = _deliver.get()
    sent = _delivered.get()
    if callback is None or sent is None or not files:
        return False
    await callback(text, files)
    sent.update(str(item.get("filename") or "").casefold() for item in files)
    return True


# bot_core is on sys.path, so `import turn_scope` and `import app.bot_core.turn_scope`
# would otherwise be two modules and two context vars. Keep a single one.
import sys

sys.modules.setdefault("turn_scope", sys.modules[__name__])
sys.modules.setdefault("app.bot_core.turn_scope", sys.modules[__name__])
