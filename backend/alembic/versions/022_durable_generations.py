"""Durable generation queue and cross-process events; additive, rollback compatible."""
from alembic import op
import sqlalchemy as sa
revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('generations',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_email', sa.String(320), nullable=False),
        sa.Column('conversation_id', sa.String(64), nullable=False),
        sa.Column('active_key', sa.String(64), unique=True),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('request', sa.Text(), nullable=False),
        sa.Column('snapshot', sa.Text(), nullable=False),
        sa.Column('owner', sa.String(32), nullable=False),
        sa.Column('lease_until', sa.BigInteger(), nullable=False),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False))
    for name in ('user_email', 'conversation_id', 'status'):
        op.create_index('ix_generations_' + name, 'generations', [name])
    op.create_table('generation_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_email', sa.String(320), nullable=False),
        sa.Column('publisher', sa.String(32), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False))
    for name in ('user_email', 'created_at'):
        op.create_index('ix_generation_events_' + name, 'generation_events', [name])
    op.create_table('worker_heartbeats', sa.Column('id', sa.String(32), primary_key=True), sa.Column('seen_at', sa.BigInteger(), nullable=False))


def downgrade():
    op.drop_table('worker_heartbeats')
    op.drop_table('generation_events')
    op.drop_table('generations')
