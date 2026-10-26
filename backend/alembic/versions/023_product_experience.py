"""Recoverable conversations, submission receipts and anonymous performance buckets."""
from alembic import op
import sqlalchemy as sa

revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversations', sa.Column('deleted_at', sa.BigInteger(), nullable=True))
    op.create_index('ix_conversations_deleted_at', 'conversations', ['deleted_at'])
    op.create_table('chat_submissions', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_email', sa.String(320), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('generation_id', sa.String(32), nullable=False), sa.Column('conversation_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False))
    op.create_index('ix_chat_submissions_user_email', 'chat_submissions', ['user_email'])
    op.create_index('ix_chat_submissions_created_at', 'chat_submissions', ['created_at'])
    op.create_table('experience_metrics', sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('name', sa.String(32), nullable=False), sa.Column('device', sa.String(12), nullable=False),
        sa.Column('bucket', sa.BigInteger(), nullable=False), sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('total', sa.BigInteger(), nullable=False), sa.Column('fast', sa.Integer(), nullable=False),
        sa.Column('medium', sa.Integer(), nullable=False), sa.Column('slow', sa.Integer(), nullable=False))
    op.create_index('ix_experience_metrics_name', 'experience_metrics', ['name'])
    op.create_index('ix_experience_metrics_bucket', 'experience_metrics', ['bucket'])
    # Russian word forms and filenames are searchable without loading chat bodies.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("CREATE INDEX ix_messages_search ON messages USING gin(to_tsvector('russian', coalesce(content, ''))) ")
        op.execute("CREATE INDEX ix_documents_search ON documents USING gin(to_tsvector('russian', coalesce(filename, ''))) ")


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.drop_index('ix_documents_search', table_name='documents')
        op.drop_index('ix_messages_search', table_name='messages')
    op.drop_table('experience_metrics')
    op.drop_table('chat_submissions')
    op.drop_index('ix_conversations_deleted_at', table_name='conversations')
    op.drop_column('conversations', 'deleted_at')
