"""Optional compact vectors, owned and deleted with the current source chunk."""
from alembic import op
import sqlalchemy as sa

revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('project_chunks', sa.Column('embedding', sa.LargeBinary(), nullable=True))
    op.add_column('project_chunks', sa.Column('embedding_model', sa.String(80), nullable=True))


def downgrade():
    op.drop_column('project_chunks', 'embedding_model')
    op.drop_column('project_chunks', 'embedding')
