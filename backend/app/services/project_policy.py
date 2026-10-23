"""Explicit per-chat project context, with run-scoped enforcement for model tools."""
import json
import time
from contextvars import ContextVar
from contextlib import contextmanager
from sqlalchemy import select, delete
from app.db.engine import SyncSessionLocal
from app.db.project_models import ProjectContextSettings, ProjectEntry

active_policy: ContextVar[dict | None] = ContextVar('project_policy', default=None)


@contextmanager
def scope(policy):
    token = active_policy.set(policy)
    try:yield
    finally:active_policy.reset(token)


def settings(uid, cid):
    from app.services import project_memory as memory
    pid = memory.attached(uid, cid)['project_id']
    default = {'project_id': pid, 'entry_ids': None, 'include_memory': True, 'web': True, 'last_used': []}
    if not pid:return default
    with SyncSessionLocal() as session:
        row = session.get(ProjectContextSettings, cid)
        if row and row.project_id == pid:
            default.update(json.loads(row.policy))
            default['last_used'] = json.loads(row.last_used)
    return default


def save(uid, cid, entry_ids, include_memory, web):
    policy = settings(uid, cid)
    pid = policy['project_id']
    if not pid:raise ValueError('Сначала подключите беседу к проекту.')
    if entry_ids is not None and (len(entry_ids) > 300 or len(set(entry_ids)) != len(entry_ids)):
        raise ValueError('Нужен список уникальных материалов проекта.')
    with SyncSessionLocal() as session:
        if entry_ids:
            found = set(session.scalars(select(ProjectEntry.id).where(ProjectEntry.project_id == pid,
                ProjectEntry.id.in_(entry_ids), ProjectEntry.kind.not_in(['suggestion', 'dismissed']))))
            if found != set(entry_ids):raise ValueError('Один из выбранных материалов не найден в проекте.')
        row = session.get(ProjectContextSettings, cid)
        if not row:row = ProjectContextSettings(conversation_id=cid, project_id=pid, last_used='[]');session.add(row)
        row.policy = json.dumps({'entry_ids': entry_ids, 'include_memory': bool(include_memory), 'web': bool(web)})
        row.updated_at = int(time.time());session.commit()
    return settings(uid, cid)


def allows(pid, eid, kind):
    policy = active_policy.get()
    if not policy or policy['project_id'] != pid:return True
    if kind in {'note', 'decision'} and not policy['include_memory']:return False
    return policy['entry_ids'] is None or eid in policy['entry_ids']


def filters(pid):
    policy = active_policy.get()
    if not policy or policy['project_id'] != pid:return []
    conditions = []
    if not policy['include_memory']:conditions.append(ProjectEntry.kind.not_in(['note', 'decision']))
    if policy['entry_ids'] is not None:conditions.append(ProjectEntry.id.in_(policy['entry_ids']))
    return conditions


def remember_used(uid, cid, rows):
    policy = active_policy.get()
    if not policy or not policy['project_id']:return
    with SyncSessionLocal() as session:
        from app.services.project_memory import _private_chat, _owned
        _private_chat(session, uid, cid);_owned(session, uid, policy['project_id'])
        row = session.get(ProjectContextSettings, cid)
        if row and row.project_id != policy['project_id']:return
        if not row:
            row = ProjectContextSettings(conversation_id=cid, project_id=policy['project_id'], policy='{}')
            session.add(row)
        row.last_used = json.dumps([{'id': r['id'], 'title': r['title'], 'kind': r['kind'],
            'revision': r['revision'], 'offset': r.get('offset', 0)} for r in rows], ensure_ascii=False)
        row.updated_at = int(time.time());session.commit()


def clear(session, cid=None, pid=None):
    stmt = delete(ProjectContextSettings)
    if cid:stmt = stmt.where(ProjectContextSettings.conversation_id == cid)
    elif pid:stmt = stmt.where(ProjectContextSettings.project_id == pid)
    else:return
    session.execute(stmt)
