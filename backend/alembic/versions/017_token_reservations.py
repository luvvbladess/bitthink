"""Reserve each model call before it reaches a provider.

Revision ID: 017
Revises: 016
"""
import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("token_reservations"):
        return
    op.create_table(
        "token_reservations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("pool", sa.String(16), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("subscription_expires_at", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.String(32), nullable=False),
        sa.Column("week_start", sa.String(32), nullable=False),
        sa.Column("session_started_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_token_reservations_user_id", "token_reservations", ["user_id"])


def downgrade():
    op.drop_index("ix_token_reservations_user_id", table_name="token_reservations")
    op.drop_table("token_reservations")
