"""Durable Computer queue, journal and account rules.

Revision ID: 018
Revises: 017
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("skill_resources"):
        op.create_table("skill_resources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("skill_name", sa.String(32), nullable=False),
            sa.Column("path", sa.String(240), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.UniqueConstraint("user_id", "skill_name", "path", name="uq_skill_resource"),
        )
        op.create_index("ix_skill_resources_user_id", "skill_resources", ["user_id"])
    if not inspector.has_table("computer_tasks"):
        op.create_table("computer_tasks",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_email", sa.String(320), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("conversation_id", sa.String(64)),
            sa.Column("interval_seconds", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("next_run_at", sa.BigInteger(), nullable=False),
            sa.Column("lease_until", sa.BigInteger(), nullable=False),
            sa.Column("run_number", sa.Integer(), nullable=False),
            sa.Column("resume_history", sa.Boolean(), nullable=False),
            sa.Column("progress", sa.Text(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
        )
        for column in ("user_email", "status", "next_run_at"):
            op.create_index("ix_computer_tasks_" + column, "computer_tasks", [column])
    if not inspector.has_table("computer_events"):
        op.create_table("computer_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.String(32), nullable=False),
            sa.Column("run_number", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
        )
        op.create_index("ix_computer_events_task_id", "computer_events", ["task_id"])
    if not inspector.has_table("computer_hooks"):
        op.create_table("computer_hooks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("event", sa.String(32), nullable=False),
            sa.Column("action", sa.String(24), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
        )
        op.create_index("ix_computer_hooks_user_id", "computer_hooks", ["user_id"])


def downgrade():
    for name in ("skill_resources", "computer_hooks", "computer_events", "computer_tasks"):
        op.drop_table(name)
