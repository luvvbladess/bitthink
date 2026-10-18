"""Cloud Computer run identity; inherited by parallel model employees."""
from contextvars import ContextVar

computer_task_id: ContextVar[str | None] = ContextVar("computer_task_id", default=None)
computer_request: ContextVar[str] = ContextVar("computer_request", default="")
