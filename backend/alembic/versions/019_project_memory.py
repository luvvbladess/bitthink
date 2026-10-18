"""Personal project knowledge and chat bindings (additive).
Revision ID: 019
Revises: 018
"""
from alembic import op
import sqlalchemy as sa
revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    from app.db.project_models import Project, ProjectChat, ProjectEntry
    for model in (Project, ProjectChat, ProjectEntry):
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for name in ("project_entries", "project_chats", "projects"):
        op.drop_table(name)
