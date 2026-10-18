"""Real page layout names must not erase articles, numbers or currency tables."""
from app.config import get_settings  # noqa: F401
from web_scraper import _clean_html


def test_navigation_named_wrapper_preserves_article_and_editorial_banner():
    text = _clean_html('''<html><body class="python about"><div id="touchnav-wrapper">
    <nav>Navigation links which should not become page evidence.</nav>
    <div class="about-banner"><h1>About Python</h1><p>Python is a programming language
    that lets you work quickly and integrate systems more effectively.</p></div>
    <main><article><p>Python can be used for web development, scientific computing,
    and automation. This is the primary article rather than a navigation control.</p>
    <div class="medium-widget"><p>More examples of actual applications are described here.</p></div>
    </article></main></div></body></html>''')
    assert "About Python" in text and "scientific computing" in text and "actual applications" in text
    assert "Navigation links" not in text


def test_header_spacing_class_preserves_currency_table_and_short_numbers():
    text = _clean_html('''<html><body><div class="header_margin-left"><main>
    <h1>Курсы валют</h1><table><tr><td>USD</td><td>1</td><td>90,1234</td></tr>
    <tr><td>JPY</td><td>100</td><td>60,4321</td></tr></table>
    <p>Курс устанавливается на указанную дату. Номинал обязателен для корректного сравнения.</p>
    </main></div></body></html>''')
    assert "USD\n1\n90,1234" in text and "JPY\n100\n60,4321" in text


def test_menu_container_cannot_remove_main_and_boilerplate_controls_are_removed():
    text = _clean_html('''<body><div class="menu-wrapper"><main><h1>Тариф</h1>
    <p>Основная информация о тарифе: стоимость, условия и дата начала действия.</p>
    </main></div><div class="cookie-banner">Посторонний текст cookie-плашки</div>
    <script>secretScript()</script><div class="social-links">Посторонние соцсети</div></body>''')
    assert "Основная информация" in text and "стоимость" in text
    assert "Посторонний" not in text and "secretScript" not in text


def test_stats_table_outside_article_keeps_headers_names_numbers_and_guide_links():
    text = _clean_html('''<body><article><h1>Hero guide</h1><p>''' + 'Introduction ' * 30 + '''</p>
    <a href="/hero/skills">Skills and combos</a><a href="javascript:alert(1)">Bad link</a></article>
    <table><tr><th><button>Hero</button></th><th><button>Win rate</button></th><th>Matches</th></tr>
    <tr><td><img alt="Example Hero" src="a.png"></td><td>54.20%</td><td>12400</td></tr></table></body>''', 'https://stats.example/heroes')
    assert 'Hero | Win rate | Matches' in text
    assert 'Example Hero | 54.20% | 12400' in text
    assert 'Skills and combos (https://stats.example/hero/skills)' in text
    assert 'javascript:' not in text


def test_long_intro_does_not_hide_table_before_read_budget():
    text = _clean_html('<main><p>' + 'intro ' * 3000 + '</p><table><tr><th>Model</th><th>Score</th></tr><tr><td>Item</td><td>42</td></tr></table></main>')
    assert 'Item | 42' in text[:6500]


def test_reader_accepts_large_but_bounded_security_headers():
    import asyncio
    from aiohttp import web
    from web_scraper import _fetch_url_content_local
    async def run():
        async def page(request):
            return web.Response(text='<main>Public pricing page with plans and usage limits. ' * 8 + '</main>', content_type='text/html', headers={'Content-Security-Policy':"default-src 'self'; " + 'https://cdn.example ' * 550})
        app = web.Application(); app.router.add_get('/', page)
        runner = web.AppRunner(app); await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
        try:
            port = site._server.sockets[0].getsockname()[1]
            _, text = await _fetch_url_content_local(f'http://127.0.0.1:{port}/')
            assert 'Public pricing page' in text and not text.startswith('[Ошибка')
        finally: await runner.cleanup()
    asyncio.run(run())
