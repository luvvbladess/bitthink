"""5-hour session and weekly token windows

Revision ID: 007
Revises: 006
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, Sequence[str], None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("session_started_at", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("session_chat_used", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("session_computer_used", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("subscriptions", sa.Column("week_start", sa.String(length=32), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("week_chat_used", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("week_computer_used", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "week_computer_used")
    op.drop_column("subscriptions", "week_chat_used")
    op.drop_column("subscriptions", "week_start")
    op.drop_column("subscriptions", "session_computer_used")
    op.drop_column("subscriptions", "session_chat_used")
    op.drop_column("subscriptions", "session_started_at")
