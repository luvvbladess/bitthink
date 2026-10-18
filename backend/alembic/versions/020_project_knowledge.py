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
    from app.db.project_models import ProjectChunk, ProjectRevision, ProjectEntry
    from app.services.project_memory import chunks
    connection = op.get_bind()
    for model in (ProjectRevision, ProjectChunk):
        model.__table__.create(bind=connection, checkfirst=True)
    # Backfill current notes so retrieval also covers already saved projects.
    rows = connection.execute(sa.select(ProjectEntry.__table__)).mappings()
    for row in rows:
        exists = connection.scalar(sa.select(ProjectRevision.id).where(ProjectRevision.entry_id == row['id']).limit(1))
        if exists:
            continue
        connection.execute(ProjectRevision.__table__.insert(), dict(
            id=uuid.uuid4().hex, entry_id=row['id'], number=1, title=row['title'],
            kind=row['kind'], body=row['body'], source_url=row['source_url'],
            document_id=None, created_at=row['updated_at']))
        parts = [dict(id=uuid.uuid4().hex, entry_id=row['id'], position=i, body=body, folded=row['title'].casefold() + '\n' + body.casefold())
                 for i, body in enumerate(chunks(row['body']))]
        if parts:
            connection.execute(ProjectChunk.__table__.insert(), parts)


def downgrade():
    op.drop_table("project_chunks")
    op.drop_table("project_revisions")
