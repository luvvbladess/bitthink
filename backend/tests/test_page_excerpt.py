from app.services.page_excerpt import page_excerpt


def test_two_api_definitions_survive_repetitive_navigation():
    text = ('Python asyncio documentation Task coroutine\n' * 500
            + 'asyncio.create_task(coro)\nSchedules a coroutine in the event loop.\n' + 'A' * 5000
            + 'asyncio.to_thread(func, /, *args, **kwargs)\nRun function in a separate thread.\n' + 'B' * 5000)
    result = page_excerpt(text, 'asyncio.to_thread create_task documentation', budget=6500)
    assert 'Schedules a coroutine in the event loop.' in result
    assert 'Run function in a separate thread.' in result
    assert len(result) <= 6500


def test_anchor_targets_definition_later_in_page():
    text = 'intro ' * 2000 + 'asyncio.to_thread(func)\nSeparate thread definition.\n' + 'end ' * 2000
    assert 'Separate thread definition.' in page_excerpt(text, url='https://docs.example/a#asyncio.to_thread', budget=3000)


def test_excerpt_only_contains_actual_source_spans():
    text = 'first\n' * 4000 + 'UNIQUE evidence here\n' + 'last\n' * 4000
    result = page_excerpt(text, 'UNIQUE evidence', budget=2400)
    assert 'UNIQUE evidence here' in result
    assert 'из ' + str(len(text)) in result
    assert len(result) <= 2400


def test_small_sources_and_budgets():
    assert page_excerpt('complete source', 'query') == 'complete source'
    assert page_excerpt('x'*1000,budget=30) == 'x'*30
    assert page_excerpt('', 'anything') == ''


def test_cleaned_html_api_definitions_beat_repeated_link_mentions():
    text = 'module.gather() navigation module.TaskGroup\n' * 500
    text += '\nmodule.\ngather\nargs\nThe first failure propagates without cancelling siblings.\n' + 'padding ' * 500
    text += '\nmodule.\nTaskGroup\nargs\nAn ordinary failure cancels sibling tasks.\n' + 'padding ' * 500
    result = page_excerpt(text, 'module.gather module.TaskGroup gather_cancels_siblings taskgroup_cancels_siblings', budget=6500)
    assert 'without cancelling siblings' in result
    assert 'failure cancels sibling tasks' in result


def test_query_reader_fetches_late_definition_but_returns_small_excerpt(monkeypatch):
    import asyncio
    import web_scraper as ws
    import computer_tools as ct
    text = 'Introduction. ' * 3000 + '\nrare_function(x)\nThe actual definition is late in the source.\n' + 'End. ' * 2000
    async def fetch(session, url):
        return 200, '<html><body><article>' + text + '</article></body></html>'
    monkeypatch.setattr(ws, '_fetch_direct', fetch)
    monkeypatch.setattr(ct, '_assert_public_http_url', lambda url: url)
    result = asyncio.run(ct._browse_public('https://docs.example/large', 'rare_function definition'))
    assert 'The actual definition is late in the source.' in result
    assert len(result) < 8500
    assert ws.page_text_limit.get() == ws.MAX_CONTENT_PER_URL
    # The old plain-link contract stays bounded, independently of earlier reads.
    _, plain = asyncio.run(ws._fetch_url_content_local('https://docs.example/large'))
    assert 'The actual definition is late in the source.' not in plain
    assert len(plain) < 15100
