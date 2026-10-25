"""Versioned project knowledge and bounded document passages.
Revision ID: 020
Revises: 019
"""
from alembic import op
import uuid
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    # Freeze the backfill algorithm along with its schema.
    def chunks(body):
        return [body[start:start + 6000] for start in range(0, len(body), 5700)]
    connection = op.get_bind()
    if not sa.inspect(op.get_bind()).has_table('project_revisions'):
        op.create_table('project_revisions',
            sa.Column('id', sa.String(length=32), primary_key=True, nullable=False),
            sa.Column('entry_id', sa.String(length=32), sa.ForeignKey('project_entries.id', ondelete='CASCADE'), primary_key=False, nullable=False),
            sa.Column('number', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
            sa.Column('kind', sa.String(length=16), primary_key=False, nullable=False),
            sa.Column('body', sa.Text(), primary_key=False, nullable=False),
            sa.Column('source_url', sa.String(length=2048), primary_key=False, nullable=False),
            sa.Column('document_id', sa.BigInteger(), primary_key=False, nullable=True),
            sa.Column('created_at', sa.BigInteger(), primary_key=False, nullable=False),
            sa.UniqueConstraint('entry_id', 'number'),
        )
        op.create_index('ix_project_revisions_document_id', 'project_revisions', ['document_id'], unique=False)
        op.create_index('ix_project_revisions_entry_id', 'project_revisions', ['entry_id'], unique=False)

    if not sa.inspect(op.get_bind()).has_table('project_chunks'):
        op.create_table('project_chunks',
            sa.Column('id', sa.String(length=32), primary_key=True, nullable=False),
            sa.Column('entry_id', sa.String(length=32), sa.ForeignKey('project_entries.id', ondelete='CASCADE'), primary_key=False, nullable=False),
            sa.Column('position', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('body', sa.Text(), primary_key=False, nullable=False),
            sa.Column('folded', sa.Text(), primary_key=False, nullable=False),
            sa.UniqueConstraint('entry_id', 'position'),
        )
        op.create_index('ix_project_chunks_entry_id', 'project_chunks', ['entry_id'], unique=False)
    # Backfill current notes so retrieval also covers already saved projects.
    entries = sa.table('project_entries', *(sa.column(name) for name in ['id', 'title', 'kind', 'body', 'source_url', 'updated_at']))
    revisions = sa.table('project_revisions', *(sa.column(name) for name in ['id', 'entry_id', 'number', 'title', 'kind', 'body', 'source_url', 'document_id', 'created_at']))
    passages = sa.table('project_chunks', *(sa.column(name) for name in ['id', 'entry_id', 'position', 'body', 'folded']))
    rows = connection.execute(sa.select(entries)).mappings()
    for row in rows:
        exists = connection.scalar(sa.select(revisions.c.id).where(revisions.c.entry_id == row['id']).limit(1))
        if exists:
            continue
        connection.execute(revisions.insert(), dict(
            id=uuid.uuid4().hex, entry_id=row['id'], number=1, title=row['title'],
            kind=row['kind'], body=row['body'], source_url=row['source_url'],
            document_id=None, created_at=row['updated_at']))
        parts = [dict(id=uuid.uuid4().hex, entry_id=row['id'], position=i, body=body, folded=row['title'].casefold() + '\n' + body.casefold())
                 for i, body in enumerate(chunks(row['body']))]
        if parts:
            connection.execute(passages.insert(), parts)


def downgrade():
    op.drop_table("project_chunks")
    op.drop_table("project_revisions")
