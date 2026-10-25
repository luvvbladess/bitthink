"""Transactional queue and event log shared by HTTP processes and workers.

Running work is leased, never automatically replayed after a crash: tools may
already have performed external actions. Queued work has not executed and is safe
to claim. An event and its snapshot are always committed in one transaction.
"""
import hashlib
import json
import time
import uuid
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.db.generation_models import Generation, GenerationEvent, WorkerHeartbeat

ACTIVE = ('queued', 'running', 'external')
LEASE = 90
INTERRUPTED = 'Выполнение было прервано перезапуском обработчика. Сохранённая история доступна; повторите запрос, чтобы продолжить.'


def _key(user, cid):
    return hashlib.sha256((user + '\0' + cid).encode()).hexdigest()


def _active(session, user, cid=None):
    query = select(Generation).where(Generation.user_email == user, Generation.status.in_(ACTIVE))
    if cid is not None:
        query = query.where(Generation.conversation_id == cid)
    return query


def count(user):
    with SyncSessionLocal() as session:
        return len(session.scalars(_active(session, user)).all())


def running(user, cid=None):
    with SyncSessionLocal() as session:
        query = _active(session, user, cid)
        if cid is None:
            query = query.where(Generation.conversation_id.like('pending:%'))
        return session.scalar(query.limit(1)) is not None


def reserve(user, cid, kind='external', request=None, owner='', limit=4):
    now = int(time.time())
    cid = cid or 'pending:' + uuid.uuid4().hex
    initial = {'conversation_id': cid, 'user_text': (request or {}).get('content', ''), 'thinking': True, 'text': '', 'status_text': 'Думаю'}
    try:
        with SyncSessionLocal.begin() as session:
            session.scalar(select(User).where(User.email == user).with_for_update())
            if session.scalar(_active(session, user, cid)) or (cid.startswith('pending:') and session.scalar(_active(session, user).where(Generation.conversation_id.like('pending:%')))):
                raise RuntimeError('Этот чат ещё отвечает. Дождитесь окончания или остановите ответ.')
            if len(session.scalars(_active(session, user)).all()) >= limit:
                raise RuntimeError('Слишком много ответов сразу. Дождитесь одного из них.')
            session.execute(update(Generation).where(Generation.user_email == user,
                Generation.conversation_id == cid, Generation.status == 'interrupted').values(status='archived', snapshot='{}'))
            row = Generation(id=uuid.uuid4().hex, user_email=user, conversation_id=cid,
                active_key=_key(user, cid), kind=kind, status='external' if kind == 'external' else 'queued',
                request=json.dumps(request or {}, ensure_ascii=False), snapshot=json.dumps(initial, ensure_ascii=False),
                owner=owner, lease_until=now + LEASE if owner else 0,
                cancel_requested=False, created_at=now, updated_at=now)
            session.add(row)
            session.flush()
            return row.id
    except IntegrityError as exc:
        raise RuntimeError('Этот чат ещё отвечает. Дождитесь окончания или остановите ответ.') from exc


def snapshot(user, cid):
    with SyncSessionLocal() as session:
        row = session.scalar(_active(session, user, cid))
        return json.loads(row.snapshot) if row else None


def subscription(user):
    # One SQL statement gives the snapshot and event cursor the same DB view,
    # including when there are no jobs. This prevents duplicate/missing chunks
    # at the boundary between reconnect and event delivery.
    with SyncSessionLocal() as session:
        cursor = select(func.coalesce(func.max(GenerationEvent.id), 0).label('cursor')).subquery()
        rows = session.execute(select(Generation, cursor.c.cursor).select_from(cursor).outerjoin(Generation,
            and_(Generation.user_email == user, Generation.status.in_((*ACTIVE, 'interrupted'))))).all()
        return [json.loads(row.snapshot) for row, _ in rows if row and not row.conversation_id.startswith('pending:')], rows[0][1]


def patch(user, cid, fields, owner=''):
    with SyncSessionLocal.begin() as session:
        row = session.scalar(_active(session, user, cid).with_for_update())
        if not row:
            return None
        data = json.loads(row.snapshot)
        data.update(fields)
        _bound(data)
        row.snapshot = json.dumps(data, ensure_ascii=False)
        row.updated_at = int(time.time())
        return data


def _bound(data):
    for key, limit in [('status_text', 4000), ('text', 120000), ('reasoning', 20000)]:
        if isinstance(data.get(key), str):
            data[key] = data[key][-limit:]


def emit(user, publisher, message, generation_id=None):
    with SyncSessionLocal.begin() as session:
        payload = dict(message.get('payload') or {})
        cid = payload.get('conversation_id')
        row = session.get(Generation, generation_id, with_for_update=True) if generation_id else session.scalar(_active(session, user, cid).with_for_update()) if cid else None
        if generation_id and (not row or row.owner != publisher or row.status not in ('running', 'external')):
            raise RuntimeError('Generation lease no longer owned')
        if row and row.user_email != user:
            raise ValueError('Generation owner mismatch')
        if row:
            data = json.loads(row.snapshot)
            kind = message['type']
            if kind == 'meta':
                row.conversation_id = cid
                row.active_key = _key(user, cid)
                data['conversation_id'] = cid
            elif kind == 'chunk':
                data['text'] = data.get('text', '') + payload.get('text', '')
                data['thinking'] = False
            elif kind == 'reasoning_delta':
                data['reasoning'] = data.get('reasoning', '') + payload.get('text', '')
            elif kind == 'status':
                data.update(status_text=payload.get('text', ''), thinking=True)
            elif kind == 'thinking':
                data['thinking'] = True
            elif kind == 'extras':
                data.update(reasoning=payload.get('reasoning', ''), search=payload.get('search', []))
            elif kind == 'error':
                data.update(error=payload.get('message', ''), thinking=False)
            elif kind in ('done', 'stopped'):
                data['thinking'] = False
            _bound(data)
            row.snapshot = json.dumps(data, ensure_ascii=False)
            row.updated_at = int(time.time())
        # Files with a durable URL do not need a second base64 copy in the log.
        if message['type'] == 'file' and payload.get('url'):
            payload.pop('data', None)
        session.add(GenerationEvent(user_email=user, publisher=publisher,
            payload=json.dumps({**message, 'payload': payload}, ensure_ascii=False), created_at=int(time.time())))


def events(after, users, limit=500):
    if not users:
        return []
    with SyncSessionLocal() as session:
        rows = session.scalars(select(GenerationEvent).where(GenerationEvent.id > after,
            GenerationEvent.user_email.in_(users)).order_by(GenerationEvent.id).limit(limit)).all()
        return [(row.id, row.user_email, json.loads(row.payload)) for row in rows]


def cancel(user, cid=None):
    with SyncSessionLocal.begin() as session:
        rows = session.scalars(_active(session, user, cid).with_for_update()).all()
        if cid is None:
            rows = [row for row in rows if row.conversation_id.startswith('pending:')]
        for row in rows:
            row.cancel_requested = True
        return bool(rows)


def cancellations(owner):
    with SyncSessionLocal() as session:
        return set(session.scalars(select(Generation.id).where(Generation.owner == owner,
            Generation.cancel_requested.is_(True), Generation.status.in_(ACTIVE))).all())


def finish(user, cid, status='completed', generation_id=None, owner=None):
    with SyncSessionLocal.begin() as session:
        row = session.get(Generation, generation_id, with_for_update=True) if generation_id else session.scalar(_active(session, user, cid).with_for_update())
        if row and row.user_email == user and row.status in ACTIVE and (owner is None or row.owner == owner):
            row.status = status
            row.active_key = None
            row.request = '{}'
            row.updated_at = int(time.time())
            if status != 'interrupted':
                row.snapshot = '{}'


def claim(owner):
    now = int(time.time())
    with SyncSessionLocal.begin() as session:
        row = session.scalar(select(Generation).where(Generation.status == 'queued').order_by(Generation.created_at, Generation.id).with_for_update(skip_locked=True).limit(1))
        if not row:
            return None
        # CAS also protects SQLite test/dev databases where FOR UPDATE is ignored.
        changed = session.execute(update(Generation).where(Generation.id == row.id, Generation.status == 'queued').values(status='running', owner=owner, lease_until=now + LEASE))
        if not changed.rowcount:
            return None
        return {'id': row.id, 'user': row.user_email, 'cid': row.conversation_id, 'kind': row.kind,
            'request': json.loads(row.request), 'cancel': row.cancel_requested}


def renew(owner, heartbeat=False):
    now = int(time.time())
    with SyncSessionLocal.begin() as session:
        session.execute(update(Generation).where(Generation.owner == owner, Generation.status.in_(('running', 'external'))).values(lease_until=now + LEASE))
        if heartbeat:
            row = session.get(WorkerHeartbeat, owner)
            if row:
                row.seen_at = now
            else:
                session.add(WorkerHeartbeat(id=owner, seen_at=now))
        return set(session.scalars(select(Generation.id).where(Generation.owner == owner, Generation.cancel_requested.is_(True), Generation.status.in_(ACTIVE))).all())


def recover(publisher):
    now = int(time.time())
    with SyncSessionLocal.begin() as session:
        rows = session.scalars(select(Generation).where(Generation.status.in_(('running', 'external')), Generation.lease_until < now).with_for_update(skip_locked=True)).all()
        for row in rows:
            data = json.loads(row.snapshot)
            data.update(thinking=False, error=INTERRUPTED, status_text='Выполнение прервано')
            row.snapshot = json.dumps(data, ensure_ascii=False)
            row.status, row.active_key, row.request, row.updated_at = 'interrupted', None, '{}', now
            for kind, payload in [('error', {'message': INTERRUPTED}), ('done', {})]:
                session.add(GenerationEvent(user_email=row.user_email, publisher=publisher, payload=json.dumps({'type': kind, 'payload': {**payload, 'conversation_id': row.conversation_id}}, ensure_ascii=False), created_at=now))
        session.execute(delete(GenerationEvent).where(GenerationEvent.created_at < now - 900))
        session.execute(delete(Generation).where(Generation.status.notin_(ACTIVE), Generation.updated_at < now - 86400))
        session.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.seen_at < now - 86400))


def ready():
    with SyncSessionLocal() as session:
        return bool(session.scalar(select(WorkerHeartbeat.id).where(WorkerHeartbeat.seen_at >= int(time.time()) - 30).limit(1)))
