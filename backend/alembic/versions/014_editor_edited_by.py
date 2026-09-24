"""who saved the last edit of an editor document

Revision ID: 014
Revises: 013
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, Sequence[str], None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("editor_documents", sa.Column("edited_by", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("editor_documents", "edited_by")
