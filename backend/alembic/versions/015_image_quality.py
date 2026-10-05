"""subscriptions.image_quality: how carefully the assistant draws pictures

Revision ID: 015
Revises: 014
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, Sequence[str], None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("image_quality", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "image_quality")
