"""Preserve the sum of per-request prices instead of repricing aggregate tokens."""
from alembic import op
import sqlalchemy as sa

revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('usage_records', sa.Column('estimated_usd', sa.Float(), nullable=True))
    op.add_column('usage_records', sa.Column('cost_is_complete', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('usage_records', 'cost_is_complete')
    op.drop_column('usage_records', 'estimated_usd')
