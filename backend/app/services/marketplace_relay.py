"""Bounded API-owned jobs for an outbound-only home browser worker.

The production backend runs one Uvicorn worker. Jobs intentionally contain only
public marketplace URLs, never a chat, user credentials or model API keys.
Generation workers reach the API's queue through its authenticated protocol.
"""
import asyncio
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx

from app.config import get_settings

MAX_CONTENT = 80_000
JOB_TIMEOUT = 60.0
ONLINE_WINDOW = 45.0
# Only generation-worker tasks use HTTP. API/background tasks retain the local
# queue to which the home browser actually sends its heartbeats and results.
reader_api: ContextVar[str | None] = ContextVar('marketplace_reader_api', default=None)


async def _remote_request(path: str, *, data: dict | None = None) -> dict | None:
    base, token = reader_api.get(), get_settings().HOME_RELAY_TOKEN
    if not base or not token:
        return None
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                timeout=JOB_TIMEOUT + 5 if data is not None else 3) as client:
            response = await client.request('POST' if data is not None else 'GET',
                base.rstrip('/') + path, json=data,
                headers={'Authorization': 'Bearer ' + token})
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


@dataclass
class Job:
    id: str
    url: str
    deadline: float
    future: asyncio.Future
    claimed: bool = False
    mode: str = "full"


class HomeRelay:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=12)
        self.jobs: dict[str, Job] = {}
        self.last_seen = 0.0
        self.reader_version: str | None = None
        self.recent_reads: list[dict] = []

    @property
    def online(self) -> bool:
        return self.last_seen > 0 and time.monotonic() - self.last_seen < ONLINE_WINDOW

    async def available(self) -> bool:
        if reader_api.get():
            return (await _remote_request('/status') or {}).get('online') is True
        return self.online

    def heartbeat(self):
        self.last_seen = time.monotonic()

    def disconnect(self):
        self.last_seen = 0.0
        for job in self.jobs.values():
            if not job.future.done():
                job.future.set_result(None)
        while not self.queue.empty():
            self.queue.get_nowait()

    async def fetch(self, url: str, *, mode: str | None = None) -> dict | None:
        from web_scraper import is_ru_marketplace

        from turn_scope import reader_snapshots, reader_mode

        mode = mode or reader_mode()
        if mode not in {"overview", "full"}:
            raise ValueError("Unknown reader mode")
        cache_key = url if mode == "full" else "overview:" + url
        snapshots = reader_snapshots()
        cached = snapshots.get(cache_key) if snapshots is not None else None
        if cached and time.monotonic() - cached[0] < 180:
            return dict(cached[1])
        parsed = urlparse(url)
        if (not get_settings().HOME_RELAY_TOKEN or not is_ru_marketplace(url)
                or parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username or parsed.password):
            return None
        if reader_api.get():
            from marketplace_verification import public_shop_url
            found = public_shop_url(url)
            if not found or found[0] not in {'card', 'short', 'listing'}:
                return None
            response = await _remote_request('/inspect', data={'url': found[1], 'mode': mode})
            result = (response or {}).get('result')
            if not isinstance(result, dict) or not isinstance(result.get('text', ''), str) or len(result.get('text', '')) > MAX_CONTENT:
                return None
            if snapshots is not None and result.get('status') == 'ok' and len(snapshots) < 32:
                snapshots[cache_key] = (time.monotonic(), dict(result))
            return result
        if not self.online:
            return None
        loop = asyncio.get_running_loop()
        job = Job(secrets.token_urlsafe(24), url, time.monotonic() + JOB_TIMEOUT, loop.create_future())
        job.mode = mode
        try:
            self.queue.put_nowait(job)
        except asyncio.QueueFull:
            return None
        self.jobs[job.id] = job
        try:
            result = await asyncio.wait_for(job.future, JOB_TIMEOUT)
            if snapshots is not None and result and result.get("status") == "ok" and len(snapshots) < 32:
                snapshots[cache_key] = (time.monotonic(),dict(result))
                if result.get("url"):
                    resolved_key = result["url"] if mode == "full" else "overview:" + result["url"]
                    snapshots[resolved_key] = snapshots[cache_key]
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            self.jobs.pop(job.id, None)

    async def pull(self, wait: float = 20.0) -> dict | None:
        self.heartbeat()
        until = time.monotonic() + wait
        while True:
            try:
                job = await asyncio.wait_for(self.queue.get(), max(0.01, until - time.monotonic()))
            except asyncio.TimeoutError:
                self.heartbeat()
                return None
            if job.id in self.jobs and not job.future.done() and job.deadline > time.monotonic():
                job.claimed = True
                return {"id": job.id, "url": job.url, "mode": job.mode}
            if time.monotonic() >= until:
                return None

    def complete(self, job_id: str, result: dict) -> bool:
        self.heartbeat()
        job = self.jobs.get(job_id)
        if not job or not job.claimed or job.future.done() or time.monotonic() >= job.deadline:
            return False
        self.recent_reads.append({'path':urlparse(result.get('url',job.url)).path,'status':result.get('status'),
            'reader_version':result.get('reader_version'), 'reader_source':result.get('reader_source'),
            'error_code':result.get('error_code'), 'reviews':result.get('review_diagnostics')})
        self.recent_reads=self.recent_reads[-12:]
        job.future.set_result(result)
        return True


home_relay = HomeRelay()
