import asyncio

from app.services.search_budget import (
    current_search_budget, limited_search, search_turn, search_tools_allowed,
)


def test_parallel_searches_share_limit_and_duplicate_work():
    seen = []
    @limited_search(list)
    async def search(query):
        seen.append(query)
        await asyncio.sleep(.01)
        return [{'title': query}]
    @search_turn
    async def run():
        result = await asyncio.gather(search('Phone Camera'), search(' phone  camera '),
                                      search('Phone battery'), search('Phone price'), search('Phone reviews'))
        assert len(seen) == 2
        assert result[0] == result[1] and result[2] and not result[3] and not result[4]
        result[0][0]['title'] = 'changed'
        assert result[1][0]['title'] != 'changed'
        assert not search_tools_allowed('web_search')
        assert search_tools_allowed('workspace_read')
    asyncio.run(run())
    assert current_search_budget.get() is None


def test_nested_adapters_count_once_and_research_has_explicit_ceiling():
    @limited_search(list)
    async def low(query, sites=None):
        return [query]
    @limited_search(list)
    async def high(query, *, sites=None):
        return await low(query, sites or [])
    @search_turn
    async def run(**kwargs):
        results = [await high(str(index), sites=['example.com']) for index in range(6)]
        assert sum(bool(x) for x in results) == (4 if kwargs.get('research') else 2)
    asyncio.run(run())
    asyncio.run(run(research=True))


def test_fallback_and_nested_composition_cannot_reset_the_budget():
    seen = []
    @limited_search(list)
    async def search(query):
        seen.append(query)
        return [query]
    @search_turn
    async def fallback():
        assert 'first' in current_search_budget.get().evidence_text() or not current_search_budget.get().queries
        return await search('third')
    @search_turn
    async def main():
        await search('first'); await search('second')
        assert not await fallback()
    asyncio.run(main())
    assert seen == ['first', 'second']
    asyncio.run(fallback())
    assert seen[-1] == 'third'  # A new user turn gets its own allowance.


def test_opposite_queries_and_quoted_phrases_do_not_share_cache():
    @limited_search(list)
    async def search(query):
        return [query]
    @search_turn
    async def run():
        assert await search('convert USD to RUB') != await search('convert RUB to USD')
        assert len(current_search_budget.get().queries) == 2
    asyncio.run(run())


def test_parallel_page_reads_are_cached_and_bounded_without_counting_project_files(monkeypatch):
    import computer_tools
    seen = []
    async def read(name, args, uid):
        seen.append((name, args))
        await asyncio.sleep(.01)
        return 'URL: ' + str(args.get('url', 'local'))
    monkeypatch.setattr(computer_tools, '_run_budgeted_computer_tool', read)
    @search_turn
    async def run():
        urls = ['https://example.com/a', 'https://example.com/a', 'https://example.com/b',
                'https://example.com/c', 'https://example.com/d']
        result = await asyncio.gather(*(computer_tools.run_computer_tool('browse_page', {'url': url}, None) for url in urls))
        assert result[0] == result[1] and len(seen) == 3
        assert 'Лимит поиска' in result[-1]
        assert not search_tools_allowed('browse_page')
        await computer_tools.run_computer_tool('project_read', {'id': 'local'}, None)
        assert len(seen) == 4
    asyncio.run(run())


def test_budget_scope_cleans_up_after_cancellation():
    @limited_search(list)
    async def search(query):
        await asyncio.sleep(30)
    @search_turn
    async def main():
        await search('query')
    async def run():
        task = asyncio.create_task(main())
        await asyncio.sleep(.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert current_search_budget.get() is None
    asyncio.run(run())
