"""Bounded optional retrieval; the source database remains the authority for access.

No provider call holds a DB transaction. Index jobs are bounded and disposable:
source chunk replacement invalidates their IDs. Query deadlines are wall-clock
deadlines, independent of HTTP read timeout. Saturated pools fall back immediately.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
import math
import re
import struct
import threading
import time

import httpx
from sqlalchemy import select, update, or_, func

from app.config import get_settings
from app.db.engine import SyncSessionLocal
from app.db.project_models import Project, ProjectEntry, ProjectChunk, ProjectRevision

logger = logging.getLogger(__name__)
MODEL = 'qwen/qwen3-embedding-8b'
MODEL_VERSION = MODEL + ':1024:v1'
DIMENSIONS = 1024
QUERY_DEADLINE = .8
THRESHOLD = .55
MAX_CHUNKS = 4096
INDEX_BATCH = 16
INDEX_JOB_CHUNKS = 128
QUERY_PREFIX = 'Instruct: Given a question, retrieve relevant passages that answer the question\nQuery: '
_queries = ThreadPoolExecutor(max_workers=4, thread_name_prefix='project-query')
_indexer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='project-index')
_query_slots = threading.BoundedSemaphore(4)
_lock = threading.Lock()
_pending = set()
_cooldown = OrderedDict()
_cache = OrderedDict()
_inflight = {}
_client = None


def enabled():
    from config import OPENROUTER_API_KEY
    return get_settings().PROJECT_EMBEDDINGS_ENABLED and bool(OPENROUTER_API_KEY)


def _http_client():
    global _client
    with _lock:
        if _client is None:
            _client = httpx.Client(timeout=httpx.Timeout(1.2, connect=.5, pool=.1),
                limits=httpx.Limits(max_connections=6, max_keepalive_connections=6))
        return _client


def normalize(vector):
    if len(vector) != DIMENSIONS or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
        raise ValueError('Invalid embedding')
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('Invalid embedding norm')
    return tuple(x / norm for x in vector)


def pack(vector):
    return struct.pack('<' + 'f' * DIMENSIONS, *normalize(vector))


def unpack(value):
    if not value or len(value) != DIMENSIONS * 4:
        raise ValueError('Invalid stored embedding')
    # pack() already stores unit vectors; renormalizing every row on every
    # search wastes several million Python operations in large projects.
    return struct.unpack('<' + 'f' * DIMENSIONS, value)


def embed(texts, *, indexing=False):
    from config import OPENROUTER_API_KEY
    if not texts or len(texts) > INDEX_BATCH:
        raise ValueError('Invalid embedding batch')
    response = _http_client().post('https://openrouter.ai/api/v1/embeddings',
        headers={'Authorization': 'Bearer ' + OPENROUTER_API_KEY},
        json={'model': MODEL, 'input': texts, 'dimensions': DIMENSIONS, 'encoding_format': 'float'},
        timeout=15 if indexing else httpx.Timeout(1.2, connect=.5, pool=.1))
    response.raise_for_status()
    payload = response.json()
    rows = sorted(payload['data'], key=lambda row: row['index'])
    if [row['index'] for row in rows] != list(range(len(texts))):
        raise ValueError('Incomplete embedding batch')
    vectors = [normalize(row['embedding']) for row in rows]
    usage = payload.get('usage') or {}
    # No source text, question, credentials or provider error body enters logs.
    logger.info('project_embedding_usage indexing=%s tokens=%s cost_usd=%s',
        indexing, usage.get('prompt_tokens', 0), usage.get('cost'))
    return vectors


def query_vector(uid, pid, query):
    key = (uid, pid, hashlib.sha256(query.encode()).hexdigest())
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            _cache.move_to_end(key)
            return cached[1]
        future = _inflight.get(key)
        if future is None:
            if not _query_slots.acquire(blocking=False):
                return None
            def run():
                try:
                    vector = embed([QUERY_PREFIX + query])[0]
                    with _lock:
                        _cache[key] = (time.monotonic() + 600, vector)
                        _cache.move_to_end(key)
                        while len(_cache) > 256:
                            _cache.popitem(last=False)
                    return vector
                finally:
                    _query_slots.release()
            try:
                future = _queries.submit(run)
            except Exception:
                _query_slots.release()
                return None
            _inflight[key] = future
    try:
        return future.result(timeout=QUERY_DEADLINE)
    except Exception as exc:
        logger.info('project_embedding_query_fallback reason=%s', type(exc).__name__)
        return None
    finally:
        # Register even when completion races the timeout; no stale Future leaks.
        def completed(_):
            with _lock:
                if _inflight.get(key) is future:
                    _inflight.pop(key, None)
        future.add_done_callback(completed)


def _eligible(uid, pid):
    return (Project.id == pid, Project.user_id == uid,
        ProjectEntry.kind.not_in(['suggestion', 'dismissed']))


def index_project(uid, pid, entry_ids):
    """One bounded background job. Stale IDs cannot attach to a new revision."""
    with SyncSessionLocal() as session:
        rows = list(session.execute(select(ProjectChunk.id, ProjectEntry.title, ProjectChunk.body)
            .join(ProjectEntry, ProjectEntry.id == ProjectChunk.entry_id)
            .join(Project, Project.id == ProjectEntry.project_id)
            .where(*_eligible(uid, pid), ProjectEntry.id.in_(entry_ids),
                or_(ProjectChunk.embedding.is_(None), ProjectChunk.embedding_model.is_(None),
                    ProjectChunk.embedding_model != MODEL_VERSION))
            .order_by(ProjectChunk.id).limit(INDEX_JOB_CHUNKS)).mappings())
    count = 0
    for offset in range(0, len(rows), INDEX_BATCH):
        batch = rows[offset:offset + INDEX_BATCH]
        vectors = embed([r['title'] + '\n' + r['body'] for r in batch], indexing=True)
        with SyncSessionLocal() as session:
            for row, vector in zip(batch, vectors):
                # Also verify project ownership at write time after the network wait.
                allowed = select(ProjectEntry.id).join(Project).where(*_eligible(uid, pid))
                result = session.execute(update(ProjectChunk).where(ProjectChunk.id == row['id'],
                    ProjectChunk.entry_id.in_(allowed)).values(embedding=pack(vector), embedding_model=MODEL_VERSION))
                count += result.rowcount
            session.commit()
    return count


def schedule(uid, pid, entry_ids):
    if not enabled() or not entry_ids:
        return
    key = (uid, pid)
    with _lock:
        if key in _pending or len(_pending) >= 32 or _cooldown.get(key, 0) > time.monotonic():
            return
        _pending.add(key)
    def run():
        try:
            index_project(uid, pid, tuple(entry_ids)[:1000])
        except Exception as exc:
            logger.info('project_embedding_index_deferred reason=%s', type(exc).__name__)
        finally:
            with _lock:
                _pending.discard(key)
                _cooldown[key] = time.monotonic() + 5
                _cooldown.move_to_end(key)
                while len(_cooldown) > 256:
                    _cooldown.popitem(last=False)
    try:
        _indexer.submit(run)
    except Exception:
        with _lock:
            _pending.discard(key)


def fuse(lexical, semantic, query, limit):
    scores, items = {}, {}
    for ranking in (lexical, semantic):
        for rank, item in enumerate(ranking):
            key = item['id']
            items.setdefault(key, item)
            scores[key] = scores.get(key, 0) + 1 / (21 + rank)
    identifiers = re.findall(r'\b(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9-]{2,}\b', query)
    pins = [key for key, item in items.items() if identifiers and all(
        token.casefold() in (item['title'] + '\n' + item['body']).casefold() for token in identifiers)]
    ordered = pins + [key for key in sorted(scores, key=lambda key: -scores[key]) if key not in pins]
    return [items[key] for key in ordered[:limit]]


def _current_lexical(uid, pid, lexical):
    """Discard snapshots edited/deleted while the optional API call was waiting."""
    from app.services.project_policy import filters
    with SyncSessionLocal() as session:
        rows = session.execute(select(ProjectEntry.id, func.max(ProjectRevision.number))
            .join(Project).outerjoin(ProjectRevision, ProjectRevision.entry_id == ProjectEntry.id)
            .where(*_eligible(uid, pid), *filters(pid), ProjectEntry.id.in_([r['id'] for r in lexical]))
            .group_by(ProjectEntry.id)).all()
    revisions = {key: revision or 1 for key, revision in rows}
    return [row for row in lexical if revisions.get(row['id']) == row['revision']]


def augment(uid, pid, query, lexical, limit):
    """Candidate rows are access-filtered before ranking and rechecked after API."""
    from app.services.project_policy import filters
    with SyncSessionLocal() as session:
        allowed_ids = list(session.scalars(select(ProjectEntry.id).join(Project)
            .where(*_eligible(uid, pid), *filters(pid)).limit(1000)))
        if not allowed_ids:
            return []
        vectors = list(session.execute(select(ProjectChunk.id, ProjectChunk.embedding)
            .where(ProjectChunk.entry_id.in_(allowed_ids), ProjectChunk.embedding.is_not(None),
                ProjectChunk.embedding_model == MODEL_VERSION)
            .order_by(ProjectChunk.id).limit(MAX_CHUNKS)).all())
    schedule(uid, pid, allowed_ids)
    if not vectors:
        return lexical[:limit]
    vector = query_vector(uid, pid, query[:500])
    lexical = _current_lexical(uid, pid, lexical)
    if vector is None:
        return lexical[:limit]
    ranked = []
    for chunk_id, value in vectors:
        try:
            similarity = sum(a * b for a, b in zip(unpack(value), vector))
        except ValueError:
            continue
        if math.isfinite(similarity) and similarity >= THRESHOLD:
            ranked.append((similarity, chunk_id))
    candidates = [chunk_id for _, chunk_id in sorted(ranked, reverse=True)[:50]]
    with SyncSessionLocal() as session:
        rows = list(session.execute(select(ProjectEntry.id, ProjectEntry.title, ProjectEntry.kind,
            ProjectEntry.source_url, ProjectEntry.updated_at, func.length(ProjectEntry.body).label('chars'),
            ProjectChunk.id.label('chunk_id'), ProjectChunk.body, ProjectChunk.position)
            .join(ProjectChunk).join(Project)
            .where(*_eligible(uid, pid), *filters(pid), ProjectChunk.id.in_(candidates))).mappings())
        by_chunk = {r['chunk_id']: r for r in rows}
        semantic, seen = [], set()
        for chunk_id in candidates:
            row = by_chunk.get(chunk_id)
            if row is None or row['id'] in seen:
                continue
            seen.add(row['id'])
            revision = session.scalar(select(func.max(ProjectRevision.number)).where(ProjectRevision.entry_id == row['id'])) or 1
            offset = row['position'] * 5700
            semantic.append({key: row[key] for key in ('id','title','kind','source_url','updated_at','chars')}
                | {'body':row['body'][:4000], 'passage':row['position']+1, 'offset':offset,
                    'revision':revision, 'citation_url':f"#project/{pid}/{row['id']}/{revision}/{offset}"})
    return fuse(lexical, semantic, query, limit)
