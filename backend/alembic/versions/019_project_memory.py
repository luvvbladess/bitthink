"""Frozen schema for revision 019; independent of future ORM changes."""
from alembic import op
import sqlalchemy as sa
revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None

def upgrade():
    if not sa.inspect(op.get_bind()).has_table('projects'):
        op.create_table('projects',
            sa.Column('id', sa.String(length=32), primary_key=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('name', sa.String(length=160), primary_key=False, nullable=False),
            sa.Column('created_at', sa.BigInteger(), primary_key=False, nullable=False),
        )
        op.create_index('ix_projects_user_id', 'projects', ['user_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('project_chats'):
        op.create_table('project_chats',
            sa.Column('conversation_id', sa.String(length=64), sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True, nullable=False),
            sa.Column('project_id', sa.String(length=32), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=False, nullable=False),
        )
        op.create_index('ix_project_chats_project_id', 'project_chats', ['project_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('project_entries'):
        op.create_table('project_entries',
            sa.Column('id', sa.String(length=32), primary_key=True, nullable=False),
            sa.Column('project_id', sa.String(length=32), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=False, nullable=False),
            sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('kind', sa.String(length=16), primary_key=False, nullable=False),
            sa.Column('body', sa.Text(), primary_key=False, nullable=False),
            sa.Column('source_url', sa.String(length=2048), primary_key=False, nullable=False),
            sa.Column('updated_at', sa.BigInteger(), primary_key=False, nullable=False),
        )
        op.create_index('ix_project_entries_project_id', 'project_entries', ['project_id'], unique=False)


def downgrade():
    op.drop_table('project_entries')
    op.drop_table('project_chats')
    op.drop_table('projects')
