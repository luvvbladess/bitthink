"""Bounded, in-process jobs for an outbound-only home browser worker.

The production backend runs one Uvicorn worker. Jobs intentionally contain only
public marketplace URLs, never a chat, user credentials or model API keys.
"""
import asyncio
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import get_settings

MAX_CONTENT = 80_000
JOB_TIMEOUT = 60.0
ONLINE_WINDOW = 45.0


@dataclass
class Job:
    id: str
    url: str
    deadline: float
    future: asyncio.Future
    claimed: bool = False


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

    def heartbeat(self):
        self.last_seen = time.monotonic()

    def disconnect(self):
        self.last_seen = 0.0
        for job in self.jobs.values():
            if not job.future.done():
                job.future.set_result(None)
        while not self.queue.empty():
            self.queue.get_nowait()

    async def fetch(self, url: str) -> dict | None:
        from web_scraper import is_ru_marketplace

        from turn_scope import reader_snapshots
        snapshots = reader_snapshots()
        cached = snapshots.get(url) if snapshots is not None else None
        if cached and time.monotonic() - cached[0] < 180:
            return dict(cached[1])
        parsed = urlparse(url)
        if (not get_settings().HOME_RELAY_TOKEN or not self.online or not is_ru_marketplace(url)
                or parsed.scheme != "https" or parsed.port not in (None, 443)):
            return None
        loop = asyncio.get_running_loop()
        job = Job(secrets.token_urlsafe(24), url, time.monotonic() + JOB_TIMEOUT, loop.create_future())
        try:
            self.queue.put_nowait(job)
        except asyncio.QueueFull:
            return None
        self.jobs[job.id] = job
        try:
            result = await asyncio.wait_for(job.future, JOB_TIMEOUT)
            if snapshots is not None and result and result.get("status") == "ok" and len(snapshots) < 32:
                snapshots[url] = (time.monotonic(),dict(result))
                if result.get("url"):
                    snapshots[result["url"]] = snapshots[url]
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
                return {"id": job.id, "url": job.url}
            if time.monotonic() >= until:
                return None

    def complete(self, job_id: str, result: dict) -> bool:
        self.heartbeat()
        job = self.jobs.get(job_id)
        if not job or not job.claimed or job.future.done() or time.monotonic() >= job.deadline:
            return False
        self.recent_reads.append({'path':urlparse(result.get('url',job.url)).path,'status':result.get('status'),
            'reader_version':result.get('reader_version'), 'reviews':result.get('review_diagnostics')})
        self.recent_reads=self.recent_reads[-12:]
        job.future.set_result(result)
        return True


home_relay = HomeRelay()
