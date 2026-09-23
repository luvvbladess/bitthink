"""human-only side chat inside a conversation

Revision ID: 012
Revises: 011
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, Sequence[str], None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_asides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversation_asides_conversation_id", "conversation_asides", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_asides_conversation_id", table_name="conversation_asides")
    op.drop_table("conversation_asides")
