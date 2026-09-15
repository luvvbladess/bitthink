"""add reasoning_effort to subscriptions

Revision ID: 002
Revises: 001
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, Sequence[str], None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('reasoning_effort', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'reasoning_effort')
