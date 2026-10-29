"""WebSocket transport over durable snapshots/events; no model execution here."""
import asyncio
import base64
import logging
import time
import uuid
from dataclasses import fields
from app.services import generation_store as store

log = logging.getLogger(__name__)


def persistent_hub(base, job_type):
    class DurableHub(base):
        def __init__(self):
            super().__init__()
            self.publisher = uuid.uuid4().hex
            self.cursors = {}
            self.pump_task = None

        async def start(self):
            if not self.pump_task or self.pump_task.done():
                self.pump_task = asyncio.create_task(self.pump())

        async def stop(self):
            if self.pump_task:
                self.pump_task.cancel()
                await asyncio.gather(self.pump_task, return_exceptions=True)
            self._sockets.clear()
            self.cursors.clear()

        def snapshots(self, user):
            return store.subscription(user)[0]

        def running_count(self, user):
            return store.count(user)

        def has_pending(self, user):
            return store.running(user)

        def is_running(self, user, cid):
            return store.running(user, cid)

        def mark_busy(self, user, cid):
            store.reserve(user, cid, owner=self.publisher)

        def clear_busy(self, user, cid):
            store.finish(user, cid, owner=self.publisher)

        def get_job(self, user, cid):
            data = store.snapshot(user, cid)
            return job_type(**{key: value for key, value in data.items() if key in {f.name for f in fields(job_type)}}) if data else None

        def upsert_job(self, user, cid, **values):
            if not store.running(user, cid):
                store.reserve(user, cid, owner=self.publisher)
            store.patch(user, cid, values)
            return self.get_job(user, cid)

        def finish_job(self, user, cid):
            store.finish(user, cid, owner=self.publisher)

        def cancel(self, user, cid=None):
            local = super().cancel(user, cid)
            return store.cancel(user, cid) or local

        async def subscribe(self, user, websocket):
            jobs, cursor = await asyncio.to_thread(store.subscription, user)
            async with self._lock:
                self.cursors[websocket] = cursor
                self._sockets.setdefault(user, set()).add(websocket)
            return jobs

        async def unsubscribe(self, user, websocket):
            await super().unsubscribe(user, websocket)
            self.cursors.pop(websocket, None)

        async def broadcast(self, user, message):
            await asyncio.to_thread(store.emit, user, self.publisher, message)

        def bind(self, user, cid, job_key=None, generation_id=None):
            return DurableSenders(self, user, cid, generation_id)

        async def pump(self):
            renewed = 0
            while True:
                try:
                    if time.monotonic() - renewed > 10:
                        await asyncio.to_thread(store.renew, self.publisher)
                        renewed = time.monotonic()
                    if self.cursors:
                        records = await asyncio.to_thread(store.events, min(self.cursors.values()), list(self._sockets))
                        async def deliver(user, socket):
                            try:
                                for sequence, owner, message in records:
                                    if socket not in self.cursors:
                                        return
                                    if owner == user and sequence > self.cursors.get(socket, sequence):
                                        await asyncio.wait_for(socket.send_json(message), timeout=15)
                                    if socket in self.cursors:
                                        self.cursors[socket] = max(self.cursors[socket], sequence)
                            except Exception:
                                # Leave the browser socket open and it keeps "Думаю"
                                # forever: the server has stopped sending, the client
                                # still believes the connection is live.
                                close = getattr(socket, 'close', None)
                                if close:
                                    try:
                                        await close()
                                    except Exception:
                                        pass
                                await self.unsubscribe(user, socket)
                        await asyncio.gather(*(deliver(user, socket) for user, sockets in list(self._sockets.items()) for socket in list(sockets)))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception('Generation event delivery failed; retrying')
                await asyncio.sleep(.1)

    return DurableHub()


class DurableSenders:
    def __init__(self, hub, user, cid, generation_id=None):
        self.hub, self.user_id = hub, user
        self.conversation_id, self.generation_id = cid, generation_id

    async def _emit(self, kind, payload):
        if self.conversation_id:
            payload = {**payload, 'conversation_id': self.conversation_id}
        await asyncio.to_thread(store.emit, self.user_id, self.hub.publisher,
            {'type': kind, 'payload': payload}, self.generation_id)

    async def send_thinking(self):
        await self._emit('thinking', {'started': True})

    async def send_status(self, text):
        await self._emit('status', {'text': text})

    async def send_chunk(self, text):
        for offset in range(0, len(text or ''), 800):
            await self._emit('chunk', {'text': text[offset:offset + 800], 'done': offset + 800 >= len(text)})

    async def send_file(self, filename, data, url=''):
        await self._emit('file', {'filename': filename, 'data': '' if url else base64.b64encode(data or b'').decode(),
            **({'url': url} if url else {}), 'canvas': bool(url or filename.lower().endswith(('.html', '.htm')))})

    async def send_meta(self, conv_id, replaces=None):
        self.conversation_id = conv_id
        await self._emit('meta', {'conversation_id': conv_id, **({'replaces': replaces} if replaces else {})})

    async def send_extras(self, reasoning, search_results):
        await self._emit('extras', {'reasoning': reasoning or '', 'search': search_results or []})

    async def send_reasoning_delta(self, text):
        await self._emit('reasoning_delta', {'text': text})
