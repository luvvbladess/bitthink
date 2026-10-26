"""Run with python -m app.workers.generations, separately from Uvicorn."""
import asyncio
import logging
import signal
import time
from app.config import get_settings
from app.services import generation_store as store
from app.services.generation_hub import hub
from app.services.chat_service import run_chat, regenerate_chat
from app.core.request_context import generation_preferences

log = logging.getLogger(__name__)


async def execute(row):
    try:
        from app.domains.experience import record
        await asyncio.to_thread(record, 'queue_wait', max(0, int(time.time()) - row.get('created_at', int(time.time()))) * 1000, 'server')
    except Exception:
        log.warning('Queue measurement unavailable')
    user = row['user']
    cid = None if row['cid'].startswith('pending:') else row['cid']
    senders = hub.bind(user, cid, generation_id=row['id'])
    status = 'completed'
    preference_token = generation_preferences.set(row['request'].get('preferences'))
    callbacks = {name: getattr(senders, name) for name in ('send_status', 'send_chunk', 'send_file', 'send_meta', 'send_extras', 'send_reasoning_delta')}
    try:
        if row['cancel']:
            raise asyncio.CancelledError
        await senders.send_thinking()
        if row['kind'] == 'regenerate':
            await regenerate_chat(user, cid, **callbacks)
        else:
            await run_chat(user, row['request']['content'], cid, **callbacks)
    except asyncio.CancelledError:
        cancelled = await asyncio.to_thread(store.cancellations, hub.publisher)
        status = 'stopped' if row['cancel'] or row['id'] in cancelled else 'interrupted'
        await senders._emit('stopped' if status == 'stopped' else 'error', {} if status == 'stopped' else {'message': store.INTERRUPTED})
        raise
    except Exception as exc:
        status = 'failed'
        log.exception('Generation failed id=%s', row['id'])
        from app.billing.quota import QuotaError
        message = str(exc) if isinstance(exc, QuotaError) else 'Нет доступа к этой беседе. Выберите другую.' if isinstance(exc, PermissionError) else 'Не удалось завершить ответ. История сохранена; попробуйте ещё раз.'
        await senders._emit('error', {'message': message})
    finally:
        try:
            await senders._emit('done', {})
            await asyncio.to_thread(store.finish, user, senders.conversation_id or row['cid'], status, row['id'])
        finally:
            generation_preferences.reset(preference_token)


async def serve(stop=None):
    get_settings()
    stop = stop or asyncio.Event()
    running = {}
    renewed = 0
    cleaned = 0
    try:
        while not stop.is_set():
            try:
                cancelled = await asyncio.to_thread(store.cancellations, hub.publisher)
                for task_id in cancelled:
                    if task_id in running and not running[task_id].cancelling():
                        running[task_id].cancel()
                if time.monotonic() - renewed > 10:
                    cancelled = await asyncio.to_thread(store.renew, hub.publisher, True)
                    for task_id in cancelled:
                        if task_id in running and not running[task_id].cancelling():
                            running[task_id].cancel()
                    await asyncio.to_thread(store.recover, hub.publisher)
                    renewed = time.monotonic()
                if time.monotonic() - cleaned > 600:
                    from app.domains.conversations import purge_expired
                    await asyncio.to_thread(purge_expired)
                    cleaned = time.monotonic()
                running = {key: task for key, task in running.items() if not task.done()}
                if len(running) < 4:
                    row = await asyncio.to_thread(store.claim, hub.publisher)
                    if row:
                        running[row['id']] = asyncio.create_task(execute(row))
                await asyncio.wait_for(stop.wait(), timeout=.2)
            except asyncio.TimeoutError:
                pass
            except Exception:
                log.exception('Generation worker iteration failed')
                await asyncio.sleep(1)
    finally:
        # A controlled stop interrupts, rather than silently replays, external
        # actions. A web-server restart does not touch this process.
        for task in running.values():
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*running.values(), return_exceptions=True)


async def main():
    from app.services.computer_tasks import worker
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(name, stop.set)
        except NotImplementedError:
            pass
    await worker.start()
    try:
        await serve(stop)
    finally:
        await worker.stop()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
