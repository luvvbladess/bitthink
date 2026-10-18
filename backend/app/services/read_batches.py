"""Bounded parallel reads. Mixed or mutating batches retain their original order."""
import asyncio

PARALLEL_READS = frozenset({
    'server_search', 'browse_page', 'project_search', 'project_read',
    'read_chat_document', 'list_chat_files', 'get_capabilities',
})


async def read_batch(calls, offered, execute):
    if len(calls) < 2 or any(getattr(call, 'name', '') not in PARALLEL_READS
                             or getattr(call, 'name', '') not in offered for call in calls):
        return None
    limit = asyncio.Semaphore(3)

    async def one(call):
        async with limit:
            try:
                return await execute(call)
            except asyncio.CancelledError:
                raise
            except Exception:
                # One failing read must not discard successful siblings. No raw
                # exception text: it can include signed URLs or credentials.
                return 'Ошибка чтения источника. Используй доступные результаты; этот источник не подтверждён.'

    shared = {}
    jobs = []
    for call in calls:
        key = (call.name, str(getattr(call, 'arguments', '{}')))
        if key not in shared:
            shared[key] = asyncio.create_task(one(call))
        jobs.append(shared[key])
    try:
        return await asyncio.gather(*jobs)
    finally:
        for job in jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
