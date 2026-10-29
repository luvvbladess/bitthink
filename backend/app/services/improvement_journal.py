"""Private improvement ledger. No original conversations, credentials or attachments."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import logging
import re
import sqlite3
import time
import uuid

log = logging.getLogger(__name__)
CATEGORIES = {'product', 'response', 'search', 'files', 'ux', 'performance', 'provider', 'other'}
TARGETS = {
    'product': 'backend/app/services/product_strategy.py',
    'response': 'backend/app/services/request_intent.py',
    'search': 'backend/app/services/source_quality.py',
    'slides': 'backend/app/bot_core/studio/quality.py',
}


def ref(value):
    from app.config import get_settings
    return hmac.new(get_settings().SECRET_KEY.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:32]


def scrub(text, limit=1200):
    text = str(text or '')
    text = re.sub(r'```[\s\S]*?```', '[CODE OMITTED]', text)
    text = re.sub(r'-----BEGIN[\s\S]*?-----END[^\n]+', '[KEY OMITTED]', text)
    text = re.sub(r'(?i)(?:пароль|password|api[_ -]?key|secret|token|authorization|логин|login)\s*[:=]\s*[^\s,;]+', '[SECRET]', text)
    text = re.sub(r'(?i)\b(?:sk-|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}|\bBearer\s+\S+', '[SECRET]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[SECRET]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)
    text = re.sub(r'https?://[^\s<>]+', '[URL]', text)
    text = re.sub(r'(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)', '[NUMBER]', text)
    text = re.sub(r'(?i)\b[A-Z]:[\\/][^\n\s]+|/(?:home|workspaces|uploads|app/data|Users)/[^\s]+', '[PATH]', text)
    return text[:limit]


@contextmanager
def connection():
    from app.config import get_settings
    root = get_settings().DATA_DIR / 'autonomy'
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'improvements.sqlite3', timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS issues (
          id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
          category TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, cluster TEXT NOT NULL DEFAULT '',
          target TEXT, severity INTEGER NOT NULL, status TEXT NOT NULL,
          occurrences INTEGER NOT NULL DEFAULT 0, first_seen INTEGER NOT NULL,
          last_seen INTEGER NOT NULL, last_attempt INTEGER NOT NULL DEFAULT 0,
          applied_at INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS occurrences (
          event_key TEXT PRIMARY KEY, issue_id TEXT NOT NULL, account_ref TEXT NOT NULL,
          created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, issue_id TEXT NOT NULL, state TEXT NOT NULL,
          detail TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reports (
          id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviewed (message_ref TEXT PRIMARY KEY, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS cursors (name TEXT PRIMARY KEY, position INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS exclusions (conversation_ref TEXT PRIMARY KEY);
        ''')
        if 'cluster' not in {row[1] for row in db.execute('PRAGMA table_info(issues)')}:
            db.execute("ALTER TABLE issues ADD COLUMN cluster TEXT NOT NULL DEFAULT ''")
        with db:
            yield db
    finally:
        db.close()


def record(source, category, title, detail='', *, account='', kind='defect', target=None, severity=2, cluster=None):
    category = category if category in CATEGORIES else 'other'
    kind = kind if kind in {'defect', 'feature'} else 'defect'
    title, detail = scrub(title, 200), scrub(detail, 1200)
    target = TARGETS.get(target)
    cluster = re.sub(r'[^a-z0-9_-]', '_', str(cluster).lower())[:64] if cluster else ''
    fingerprint = ref(('issue', kind, category, cluster or title.lower()))
    if isinstance(account, str) and '@' in account:
        from sqlalchemy import select
        from app.db.engine import SyncSessionLocal
        from app.db.models import User
        with SyncSessionLocal() as session:
            account = session.scalar(select(User.bot_user_id).where(User.email == account.lower())) or account.lower()
    event_key, account_ref = ref(('event', source)), ref(('account', str(account))) if account else ''
    now = int(time.time())
    with connection() as db:
        old = db.execute('SELECT issue_id FROM occurrences WHERE event_key=?', (event_key,)).fetchone()
        if old:
            return old['issue_id']
        row = db.execute('SELECT id,status FROM issues WHERE fingerprint=?', (fingerprint,)).fetchone()
        iid = row['id'] if row else uuid.uuid4().hex
        if row is None:
            db.execute('INSERT INTO issues(id,fingerprint,kind,category,title,detail,cluster,target,severity,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (iid, fingerprint, kind, category, title, detail, cluster, target, max(1, min(3, int(severity))), 'new' if target else 'needs_review', now, now))
        db.execute('INSERT INTO occurrences VALUES(?,?,?,?)', (event_key, iid, account_ref, now))
        db.execute("UPDATE issues SET occurrences=occurrences+1,last_seen=?,status=CASE WHEN status IN ('resolved','monitoring') THEN 'new' ELSE status END WHERE id=?", (now, iid))
        db.execute('INSERT INTO events(issue_id,state,detail,created_at) VALUES(?,?,?,?)',
                   (iid, 'reopened' if row and row['status'] in {'resolved', 'monitoring'} else 'observed', detail[:400], now))
        return iid


def capture_error(component, error_type, *, account='', event_key=None, code=None):
    """Error handlers must never fail the user request or persist exception messages."""
    try:
        component = re.sub(r'[^a-zA-Z0-9_.-]', '', str(component))[:100]
        error_type = re.sub(r'[^a-zA-Z0-9_.-]', '', str(error_type))[:100]
        return record(event_key or uuid.uuid4().hex, 'provider' if component.startswith('provider') else 'other',
                      f'{component}: {error_type}', f'component={component}; type={error_type}; code={code if isinstance(code, int) else "unknown"}',
                      account=account, cluster=f'{component}:{error_type}:{code}')
    except Exception:
        log.warning('Improvement journal unavailable; original request continues')


def issues(limit=100):
    with connection() as db:
        return [dict(row) for row in db.execute('''SELECT i.*, (SELECT COUNT(DISTINCT account_ref) FROM occurrences o
            WHERE o.issue_id=i.id AND account_ref!='') AS affected_accounts FROM issues i
            ORDER BY CASE WHEN status='resolved' THEN 1 ELSE 0 END,severity,occurrences DESC,last_seen DESC LIMIT ?''', (max(1, min(limit, 200)),))]


def issue(iid):
    with connection() as db:
        row = db.execute('SELECT * FROM issues WHERE id=?', (iid,)).fetchone()
        if row is None:
            raise ValueError('Проблема не найдена.')
        return {**dict(row), 'events': [dict(event) for event in db.execute('SELECT state,detail,created_at FROM events WHERE issue_id=? ORDER BY id DESC LIMIT 50', (iid,))]}


def transition(iid, state, detail='', *, verified=False):
    if state not in {'reproducing', 'needs_review', 'rejected', 'verified_candidate', 'monitoring', 'resolved'}:
        raise ValueError('Неверное состояние.')
    if state in {'monitoring', 'resolved', 'verified_candidate'} and not verified:
        raise ValueError('Нет проверенного результата.')
    now = int(time.time())
    with connection() as db:
        if db.execute('SELECT id FROM issues WHERE id=?', (iid,)).fetchone() is None:
            raise ValueError('Проблема не найдена.')
        db.execute('UPDATE issues SET status=?,last_attempt=CASE WHEN ?="reproducing" THEN ? ELSE last_attempt END, applied_at=CASE WHEN ?="monitoring" THEN ? ELSE applied_at END, failures=failures+? WHERE id=?',
                   (state, state, now, state, now, int(state == 'rejected'), iid))
        db.execute('INSERT INTO events(issue_id,state,detail,created_at) VALUES(?,?,?,?)', (iid, state, scrub(detail, 800), now))


def next_issue(allow_resolve=True):
    now = int(time.time())
    with connection() as db:
        stale = [row[0] for row in db.execute("SELECT id FROM issues WHERE status='reproducing' AND last_attempt<?", (now - 3600,))]
        for iid in stale:
            db.execute("UPDATE issues SET status='rejected',failures=failures+1 WHERE id=?", (iid,))
            db.execute('INSERT INTO events(issue_id,state,detail,created_at) VALUES(?,?,?,?)', (iid, 'interrupted', 'Предыдущая попытка была прервана.', now))
        if allow_resolve:
            settled = [row[0] for row in db.execute("SELECT id FROM issues WHERE status='monitoring' AND applied_at<? AND last_seen<=applied_at", (now - 86400,))]
            for iid in settled:
                db.execute("UPDATE issues SET status='resolved' WHERE id=?", (iid,))
                db.execute('INSERT INTO events(issue_id,state,detail,created_at) VALUES(?,?,?,?)', (iid, 'resolved', 'Проверенный выпуск: сутки без наблюдавшихся повторений.', now))
        row = db.execute("SELECT * FROM issues WHERE target IS NOT NULL AND status IN ('new','rejected','verified_candidate') AND failures<3 AND last_attempt<? ORDER BY severity,occurrences DESC,first_seen LIMIT 1", (now - 86400,)).fetchone()
        return dict(row) if row else None


def reports():
    with connection() as db:
        return [json.loads(row['payload']) for row in db.execute('SELECT payload FROM reports ORDER BY created_at DESC LIMIT 30')]


def save_review(report, findings, message_refs, cursor):
    # Event ingestion is idempotent: a crash before this checkpoint only replays refs.
    for finding in findings:
        record(**finding)
    with connection() as db:
        for message_ref in message_refs:
            db.execute('INSERT OR IGNORE INTO reviewed VALUES(?,?)', (message_ref, int(time.time())))
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?)', ('messages', cursor))
        db.execute('INSERT INTO reports VALUES(?,?,?)', (report['id'], int(time.time()), json.dumps(report, ensure_ascii=False)))


def checkpoint():
    with connection() as db:
        row = db.execute("SELECT position FROM cursors WHERE name='messages'").fetchone()
        return row['position'] if row else None


def was_reviewed(message_refs):
    if not message_refs:
        return set()
    with connection() as db:
        return {row[0] for row in db.execute('SELECT message_ref FROM reviewed WHERE message_ref IN (' + ','.join('?' for _ in message_refs) + ')', message_refs)}


def exclude_current_conversation():
    from turn_scope import turn_conversation_id
    cid = turn_conversation_id()
    if not cid:
        return
    with connection() as db:
        db.execute('INSERT OR IGNORE INTO exclusions VALUES(?)', (ref(('conversation', cid)),))


def excluded():
    with connection() as db:
        return {row[0] for row in db.execute('SELECT conversation_ref FROM exclusions')}
