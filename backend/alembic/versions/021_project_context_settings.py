"""Explicit project context preferences. Revision 021, revises 020."""
from alembic import op
revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade():
    from app.db.project_models import ProjectContextSettings
    ProjectContextSettings.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table('project_context_settings')
