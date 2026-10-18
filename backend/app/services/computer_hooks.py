"""Account-owned declarative hooks. No shell or implicit outgoing requests."""
from sqlalchemy import select
from app.db.engine import SyncSessionLocal
from app.db.models import ComputerHook


def hooks(user_id: int, event: str) -> list[ComputerHook]:
    with SyncSessionLocal() as session:
        return list(session.scalars(select(ComputerHook).where(
            ComputerHook.user_id == user_id, ComputerHook.event == event,
            ComputerHook.enabled.is_(True),
        ).order_by(ComputerHook.id)))


def task_instructions(user_id: int) -> str:
    return "\n".join(row.value for row in hooks(user_id, "before_task") if row.action == "instruction")[:12000]


def blocked_tool(user_id: int, name: str) -> bool:
    return any(row.action == "deny" and name in row.value.split(",") for row in hooks(user_id, "before_tool"))


def output_limit(user_id: int) -> int:
    return min([12000] + [int(row.value) for row in hooks(user_id, "after_tool") if row.action == "limit"])
