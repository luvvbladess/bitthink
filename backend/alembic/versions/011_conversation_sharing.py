"""shared conversations: members, invite links, message authors

Revision ID: 011
Revises: 010
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, Sequence[str], None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("author_user_id", sa.BigInteger(), nullable=True))
    op.create_table(
        "conversation_shares",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversation_shares_conversation_id", "conversation_shares", ["conversation_id"])
    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_conversation_member"),
    )
    op.create_index("ix_conversation_members_conversation_id", "conversation_members", ["conversation_id"])
    op.create_index("ix_conversation_members_user_id", "conversation_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_members_user_id", table_name="conversation_members")
    op.drop_index("ix_conversation_members_conversation_id", table_name="conversation_members")
    op.drop_table("conversation_members")
    op.drop_index("ix_conversation_shares_conversation_id", table_name="conversation_shares")
    op.drop_table("conversation_shares")
    op.drop_column("messages", "author_user_id")
