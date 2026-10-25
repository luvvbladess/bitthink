"""Frozen schema for revision 021; independent of future ORM changes."""
from alembic import op
import sqlalchemy as sa
revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None

def upgrade():
    if not sa.inspect(op.get_bind()).has_table('project_context_settings'):
        op.create_table('project_context_settings',
            sa.Column('conversation_id', sa.String(length=64), sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True, nullable=False),
            sa.Column('project_id', sa.String(length=32), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=False, nullable=False),
            sa.Column('policy', sa.Text(), primary_key=False, nullable=False),
            sa.Column('last_used', sa.Text(), primary_key=False, nullable=False),
            sa.Column('updated_at', sa.BigInteger(), primary_key=False, nullable=False),
        )
        op.create_index('ix_project_context_settings_project_id', 'project_context_settings', ['project_id'], unique=False)


def downgrade():
    op.drop_table('project_context_settings')
