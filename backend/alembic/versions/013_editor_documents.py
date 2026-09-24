"""documents opened in the OnlyOffice editor

Revision ID: 013
Revises: 012
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, Sequence[str], None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "editor_documents",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("conversation_id", "filename"),
    )
    op.create_index("ix_editor_documents_conversation_id", "editor_documents", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_editor_documents_conversation_id", table_name="editor_documents")
    op.drop_table("editor_documents")
