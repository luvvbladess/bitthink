"""per-user switched-off common skills

Revision ID: 016
Revises: 015
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, Sequence[str], None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "disabled_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_disabled_skills_user_name"),
    )
    op.create_index("ix_disabled_skills_user_id", "disabled_skills", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_disabled_skills_user_id", table_name="disabled_skills")
    op.drop_table("disabled_skills")
