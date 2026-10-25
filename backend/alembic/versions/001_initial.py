"""Frozen schema for revision 001; independent of future ORM changes."""
from alembic import op
import sqlalchemy as sa
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    if not sa.inspect(op.get_bind()).has_table('users'):
        op.create_table('users',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('email', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('password_hash', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('first_name', sa.String(length=255), primary_key=False, nullable=True),
            sa.Column('role', sa.String(length=32), primary_key=False, nullable=False),
            sa.Column('bot_user_id', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_users_bot_user_id', 'users', ['bot_user_id'], unique=True)
        op.create_index('ix_users_email', 'users', ['email'], unique=True)
        op.create_index('ix_users_id', 'users', ['id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('conversations'):
        op.create_table('conversations',
            sa.Column('id', sa.String(length=64), primary_key=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('is_active', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_conversations_user_id', 'conversations', ['user_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('messages'):
        op.create_table('messages',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('conversation_id', sa.String(length=64), sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=False, nullable=False),
            sa.Column('role', sa.String(length=32), primary_key=False, nullable=False),
            sa.Column('content', sa.Text(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('documents'):
        op.create_table('documents',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('conversation_id', sa.String(length=64), sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=False, nullable=False),
            sa.Column('filename', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('content', sa.Text(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_documents_conversation_id', 'documents', ['conversation_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('subscriptions'):
        op.create_table('subscriptions',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('tier', sa.String(length=32), primary_key=False, nullable=False),
            sa.Column('expires_at', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('daily_nano_mini', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('daily_gpt54', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('daily_director', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('daily_images', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('daily_docs', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('last_reset_date', sa.String(length=32), primary_key=False, nullable=True),
            sa.Column('has_used_trial', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('active_promocode', sa.String(length=255), primary_key=False, nullable=True),
            sa.Column('last_reminded_date', sa.String(length=255), primary_key=False, nullable=True),
            sa.Column('selected_model', sa.String(length=128), primary_key=False, nullable=True),
        )
        op.create_index('ix_subscriptions_user_id', 'subscriptions', ['user_id'], unique=True)

    if not sa.inspect(op.get_bind()).has_table('custom_prompts'):
        op.create_table('custom_prompts',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('prompt', sa.Text(), primary_key=False, nullable=False),
            sa.Column('active', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), primary_key=False, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_custom_prompts_user_id', 'custom_prompts', ['user_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('usage_records'):
        op.create_table('usage_records',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), primary_key=False, nullable=False),
            sa.Column('date', sa.String(length=32), primary_key=False, nullable=False),
            sa.Column('model', sa.String(length=128), primary_key=False, nullable=False),
            sa.Column('input_tokens', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('output_tokens', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('images', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('calls', sa.Integer(), primary_key=False, nullable=False),
        )
        op.create_index('ix_usage_records_date', 'usage_records', ['date'], unique=False)
        op.create_index('ix_usage_records_user_id', 'usage_records', ['user_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('allowed_contexts'):
        op.create_table('allowed_contexts',
            sa.Column('context_id', sa.String(length=255), primary_key=True, nullable=False),
            sa.Column('allowed', sa.Boolean(), primary_key=False, nullable=False),
        )

    if not sa.inspect(op.get_bind()).has_table('base_templates'):
        op.create_table('base_templates',
            sa.Column('user_id', sa.BigInteger(), primary_key=True, nullable=False),
            sa.Column('filename', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('content', sa.LargeBinary(), primary_key=False, nullable=False),
        )


def downgrade():
    op.drop_table('base_templates')
    op.drop_table('allowed_contexts')
    op.drop_table('usage_records')
    op.drop_table('custom_prompts')
    op.drop_table('subscriptions')
    op.drop_table('documents')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('users')
