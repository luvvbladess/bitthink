"""monthly token wallets on subscriptions

Revision ID: 006
Revises: 005
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("period_start", sa.String(length=32), nullable=True))
    op.add_column("subscriptions", sa.Column("chat_tokens_used", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("subscriptions", sa.Column("computer_tokens_used", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("subscriptions", sa.Column("images_used", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("subscriptions", sa.Column("nano_cushion_date", sa.String(length=32), nullable=True))
    op.add_column("subscriptions", sa.Column("nano_cushion_used", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("subscriptions", "nano_cushion_used")
    op.drop_column("subscriptions", "nano_cushion_date")
    op.drop_column("subscriptions", "images_used")
    op.drop_column("subscriptions", "computer_tokens_used")
    op.drop_column("subscriptions", "chat_tokens_used")
    op.drop_column("subscriptions", "period_start")
