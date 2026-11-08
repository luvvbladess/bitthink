import asyncio
from types import SimpleNamespace
import time
import pytest
from app.services.read_batches import read_batch, PARALLEL_READS
from app.services.run_protocol import RunRecord, current_run


def calls(*names):
    return [SimpleNamespace(name=name, arguments='{"index":%d}' % i) for i, name in enumerate(names)]


def test_identical_reads_share_one_execution():
    seen = []
    async def read(call):
        seen.append(call.name)
        await asyncio.sleep(.01)
        return 'page'
    repeated = [SimpleNamespace(name='browse_page', arguments='{"url":"https://example.com"}') for _ in range(3)]
    assert asyncio.run(read_batch(repeated, PARALLEL_READS, read)) == ['page'] * 3
    assert seen == ['browse_page']


def test_parallel_reads_are_bounded_and_failing_sibling_isolated():
    active = peak = 0
    async def read(call):
        nonlocal active, peak
        active += 1; peak = max(peak, active)
        await asyncio.sleep(.06)
        active -= 1
        if call.name == 'project_read': raise RuntimeError('private-token')
        return call.name
    started = time.monotonic()
    result = asyncio.run(read_batch(calls('workspace_read', 'workspace_glob', 'project_read', 'workspace_grep'), PARALLEL_READS, read))
    assert peak == 3 and active == 0
    assert time.monotonic() - started < .23
    assert result[0] == 'workspace_read' and result[3] == 'workspace_grep'
    assert 'Ошибка' in result[2] and 'private-token' not in result[2]


def test_mutations_and_unoffered_tools_never_preexecute():
    async def forbidden(call): raise AssertionError('must stay in sequential executor')
    assert asyncio.run(read_batch(calls('workspace_read', 'workspace_write'), PARALLEL_READS, forbidden)) is None
    assert asyncio.run(read_batch(calls('browse_page', 'server_search'), {'browse_page'}, forbidden)) is None


def test_pricing_prefetch_reads_both_sides_once_and_keeps_partial_result(monkeypatch):
    import computer_tools
    import search_engine
    from app.services.pricing_prefetch import pricing_context

    record = RunRecord()
    active = 0
    both_started = asyncio.Event()

    async def browse(name, args, user_id):
        nonlocal active
        assert name == 'browse_page'
        active += 1
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 1)
        url = args['url']
        text = ('Pro\n$10 per month\nFor everyday coding with agents. Includes autocomplete.'
                if 'github' in url else '[Ошибка: сайт недоступен]')
        result = f'URL: {url}\n\n{text}'
        record.observe_page(result)
        return result

    async def search(*args, **kwargs):
        raise AssertionError('Known official pages need no discovery')

    monkeypatch.setattr(computer_tools, 'run_computer_tool', browse)
    monkeypatch.setattr(search_engine, 'search_web', search)
    context = asyncio.run(pricing_context('В чем разница тарифов Cursor и Copilot?', 1, record))
    assert '$10' in context and 'cursor: цена на странице тарифов не подтверждена' in context
    assert not asyncio.run(pricing_context('Сравни цены на G435 в Ozon и DNS', 1, record))
    assert active == 2


def test_cancelled_batch_drains_children():
    active = 0
    async def read(call):
        nonlocal active
        active += 1
        try: await asyncio.sleep(30)
        finally: active -= 1
    async def run():
        job = asyncio.create_task(read_batch(calls('browse_page', 'server_search'), PARALLEL_READS, read))
        await asyncio.sleep(.01)
        job.cancel()
        with pytest.raises(asyncio.CancelledError): await job
    asyncio.run(run())
    assert active == 0


def test_linked_excerpt_is_exact_observation_and_not_search_snippet():
    record = RunRecord()
    text = 'Вступление без фактов. ' * 80 + '\nLogitech G435: цена 4282 рубля, комплектация LIGHTSPEED.\n' + 'Другие сведения. ' * 60
    record.observe_page('URL: https://example.com/g435\n\n' + text)
    record.observe_search([{'url': 'https://example.com/search', 'snippet': 'Logitech G435 999 рублей'}], '2026-10-14T00:00:00Z')
    record.link_excerpts('[Logitech G435](https://example.com/g435): цена 4282 рубля, комплектация LIGHTSPEED.')
    rows = record.enrich_sources([])
    assert '4282' in rows[0]['answer_excerpt'] and rows[0]['answer_excerpt'] in text
    assert 'Logitech G435' in rows[0]['answer_context']
    assert not rows[1]['answer_excerpt']
    record.observe_page('URL: https://example.com/g435\n\n[Ошибка загрузки]')
    record.link_excerpts('[Logitech G435](https://example.com/g435): цена 4282 рубля.')
    assert not record.enrich_sources([])[0]['answer_excerpt']


def test_repeated_failed_read_guard_is_turn_scoped(monkeypatch):
    import computer_tools
    from app.services import computer_hooks
    seen = []
    monkeypatch.setattr(computer_hooks, 'blocked_tool', lambda *args: False)
    monkeypatch.setattr(computer_hooks, 'output_limit', lambda *args: 12000)
    async def fetch(name, args, uid):
        seen.append(name)
        return 'URL: https://example.com/broken\n\n[Сайт защищён от автоматического чтения]'
    monkeypatch.setattr(computer_tools, '_run_computer_tool', fetch)
    async def run():
        record = RunRecord(); token = current_run.set(record)
        try:
            for _ in range(2): await computer_tools.run_computer_tool('browse_page', {'url': 'https://example.com/broken'}, 1)
            result = await computer_tools.run_computer_tool('browse_page', {'url': 'https://example.com/broken'}, 1)
            assert 'Повтор остановлен' in result and len(seen) == 2
            assert len(record.timings) == 2
        finally: current_run.reset(token)
        token = current_run.set(RunRecord())
        try: await computer_tools.run_computer_tool('browse_page', {'url': 'https://example.com/broken'}, 1)
        finally: current_run.reset(token)
    asyncio.run(run())
    assert len(seen) == 3
