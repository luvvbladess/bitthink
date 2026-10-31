"""Bounded conversation read models, search and recoverable deletion.

Queries never hydrate Conversation relationships: sidebar cost is independent of
the number of message bodies. All reads enforce owner/member access in SQL.
"""
import json
import time
from sqlalchemy import and_, or_, select, func, delete, update, exists
from sqlalchemy.orm import noload
from app.db.engine import SyncSessionLocal
from app.db.models import Conversation, ConversationMember, ConversationShare, Message, Document, User, ComputerTask
from app.db.generation_models import Generation

TRASH_DAYS = 30


def accessible(uid):
    return or_(Conversation.user_id == uid, Conversation.id.in_(
        select(ConversationMember.conversation_id).where(ConversationMember.user_id == uid)))


def _summary(row, uid):
    return dict(id=row.id, title=row.title, created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(), is_active=bool(row.is_active and row.user_id == uid),
        message_count=row.message_count, document_count=row.document_count,
        shared=row.member_count > 0, role='owner' if row.user_id == uid else 'member', deleted_at=row.deleted_at)


def discard_unused_drafts(uid):
    """A click on the logo used to save a chat before any message. Those rows are not conversations."""
    def absent(model, column):
        return ~exists(select(column).where(model.conversation_id == Conversation.id))
    unused = and_(
        Conversation.user_id == uid,
        Conversation.deleted_at.is_(None),
        Conversation.is_active.is_(False),
        Conversation.title.in_(('Новый чат', 'Новая беседа')),
        absent(Message, Message.id),
        absent(Document, Document.id),
        absent(ConversationMember, ConversationMember.id),
        ~exists(select(ConversationShare.token).where(
            ConversationShare.conversation_id == Conversation.id, ConversationShare.revoked.is_(False))),
    )
    with SyncSessionLocal.begin() as session:
        rows = session.scalars(select(Conversation).options(noload('*')).where(unused).limit(100)).all()
        for row in rows:
            session.delete(row)
    return len(rows)


def summaries(uid, limit=None, offset=0, trash=False, cid=None):
    counts = lambda model: select(func.count()).select_from(model).where(model.conversation_id == Conversation.id).scalar_subquery()
    query = select(Conversation.id, Conversation.title, Conversation.created_at, Conversation.updated_at,
        Conversation.user_id, Conversation.is_active, Conversation.deleted_at,
        counts(Message).label('message_count'), counts(Document).label('document_count'),
        (counts(ConversationMember) + select(func.count()).select_from(ConversationShare).where(ConversationShare.conversation_id == Conversation.id, ConversationShare.revoked.is_(False)).scalar_subquery()).label('member_count'))
    if trash:
        query = query.where(Conversation.user_id == uid, Conversation.deleted_at > int(time.time()) - TRASH_DAYS * 86400)
    else:
        query = query.where(accessible(uid), Conversation.deleted_at.is_(None))
    query = query.order_by(Conversation.updated_at.desc(), Conversation.created_at.desc(), Conversation.id.desc()).offset(offset)
    if cid:query = query.where(Conversation.id == cid)
    if limit is not None:query = query.limit(limit)
    with SyncSessionLocal() as session:return [_summary(row, uid) for row in session.execute(query)]


def trash(uid, cid, restore=False):
    with SyncSessionLocal.begin() as session:
        row = session.scalar(select(Conversation).options(noload('*')).where(Conversation.id == cid, Conversation.user_id == uid).with_for_update())
        if row is None:return False
        if restore:
            if row.deleted_at is None:return True
            if row.deleted_at <= int(time.time()) - TRASH_DAYS * 86400:return False
            row.deleted_at = None
        else:
            row.deleted_at = row.deleted_at or int(time.time())
            row.is_active = False
            session.execute(update(Generation).where(Generation.conversation_id == cid,
                Generation.status.in_(['queued', 'running', 'external'])).values(cancel_requested=True))
            session.execute(update(ComputerTask).where(ComputerTask.conversation_id == cid,
                ComputerTask.enabled.is_(True)).values(status='paused', enabled=False, updated_at=int(time.time())))
        return True


def purge_expired():
    cutoff = int(time.time()) - TRASH_DAYS * 86400
    with SyncSessionLocal.begin() as session:
        # ORM cascades clear child records as in the existing deletion path.
        for row in session.scalars(select(Conversation).where(Conversation.deleted_at <= cutoff).limit(50)):
            session.delete(row)


def search(uid, query, limit=30, offset=0):
    query = query.strip()[:200]
    if not query:return []
    escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    with SyncSessionLocal() as session:
        def matches(column):
            substring = column.ilike('%' + escaped + '%', escape='\\')
            if session.bind.dialect.name == 'postgresql':
                words = func.to_tsvector('russian', func.coalesce(column, '')).op('@@')(func.plainto_tsquery('russian', query))
                return words if column is Message.content else or_(substring, words)
            return substring
        # One matching message/file per conversation, without returning bodies.
        message = select(Message.id).where(Message.conversation_id == Conversation.id, matches(Message.content)).order_by(Message.id.desc()).limit(1).correlate(Conversation).scalar_subquery()
        snippet = select(func.substr(Message.content, 1, 400)).where(Message.id == message).correlate(Conversation).scalar_subquery()
        filename = select(Document.filename).where(Document.conversation_id == Conversation.id, matches(Document.filename)).limit(1).correlate(Conversation).scalar_subquery()
        rows = session.execute(select(Conversation.id, Conversation.title, message.label('message_id'), snippet.label('snippet'), filename.label('filename'))
            .where(accessible(uid), Conversation.deleted_at.is_(None), or_(matches(Conversation.title), message.is_not(None), filename.is_not(None)))
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc(), Conversation.id.desc()).limit(limit).offset(offset))
        return [dict(id=r.id, title=r.title, message_id=r.message_id, snippet=r.snippet or r.filename or 'Совпадение в названии', filename=r.filename) for r in rows]


def history(uid, cid, limit=80, before=None, around=None):
    with SyncSessionLocal() as session:
        owner = session.scalar(select(Conversation.user_id).where(Conversation.id == cid, accessible(uid), Conversation.deleted_at.is_(None)))
        if owner is None:raise PermissionError('Беседа недоступна')
        query = select(Message).where(Message.conversation_id == cid)
        if around:
            target = session.scalar(select(Message.id).where(Message.id == around, Message.conversation_id == cid))
            if target is None:raise ValueError('Сообщение не найдено')
            # Start at the matching message, followed by the newer messages.
            query = query.where(Message.id >= target).order_by(Message.id).limit(limit)
            rows = list(session.scalars(query))
        else:
            if before:query = query.where(Message.id < before)
            rows = list(reversed(session.scalars(query.order_by(Message.id.desc()).limit(limit)).all()))
        first = rows[0].id if rows else before
        earlier = session.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == cid, Message.id < first)) if first else 0
        last = rows[-1].id if rows else None
        later = bool(last and session.scalar(select(Message.id).where(Message.conversation_id == cid, Message.id > last).limit(1)))
        author_ids = {r.author_user_id or owner for r in rows if r.role == 'user'}
        cards = {u.bot_user_id:dict(name=u.first_name or u.email.split('@')[0], avatar_url=u.avatar_url) for u in session.scalars(select(User).where(User.bot_user_id.in_(author_ids)))}
        items = []
        for i, row in enumerate(rows):
            content = row.content
            extras = json.loads(row.search) if row.search else None
            if row.role == 'assistant':
                from app.bot_core.kimi_client import extract_domain_sources, strip_source_links
                extras = extras or extract_domain_sources(content)
                if extras:content = strip_source_links(content)
            author = row.author_user_id or owner
            items.append(dict(id=f'{cid}_{earlier+i}', message_id=row.id, role=row.role, content=content,
                created_at=row.created_at.isoformat(), attachment=json.loads(row.attachment) if row.attachment else None,
                search=extras, author=cards.get(author) if row.role == 'user' else None, mine=row.role == 'user' and author == uid))
        return dict(items=items, has_more=earlier > 0, before=first, has_newer=later, offset=earlier)
