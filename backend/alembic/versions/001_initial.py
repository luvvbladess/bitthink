"""initial

Revision ID: 001
Revises:
Create Date: 2026-07-10 22:04:47.506780

"""
from typing import Sequence, Union

from alembic import op

# Import Base and all models so metadata knows every table.
from app.db.base import Base
from app.db import models  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop all tables."""
    Base.metadata.drop_all(bind=op.get_bind())
