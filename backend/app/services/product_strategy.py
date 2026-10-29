"""Small, deterministic defaults; the architect may choose a better supported stack."""
import re

STACKS = {
    'static': 'HTML/CSS/JavaScript; Node test runner; static hosting',
    'react': 'React + TypeScript + Vite; npm build/test; static hosting or API',
    'next': 'Next.js + TypeScript; npm build/test; Node hosting',
    'astro': 'Astro + TypeScript; npm build/test; content/static hosting',
    'python': 'Python; requirements.txt; unittest; container hosting',
    'node': 'Node.js + TypeScript; npm build/test; container hosting',
}
_CREATE = re.compile(r'(?i)созда[йт]|сдела[йт]|собери|собрать|разработ|реализ|построй|напиши|build|create|develop|implement')
_PRODUCT = re.compile(r'(?i)сайт|лендинг|приложен|веб.?сервис|интернет.?магазин|блог|личный кабинет|дашборд|\bбот[а-я]*\b|\bwebsite\b|\blanding\b|\bapp\b|\bapplication\b|\bsaas\b|\bweb ?app\b|\bbot\b|\bdashboard\b|\bblog\b|\bapi\s+service\b')
_EXPLAIN = re.compile(r'(?i)^\s*(объясни|расскажи|как\b|почему\b|сколько\b|хочу (?:узнать|понять)|explain\b|how\b|tell me)')


def is_product_request(text):
    return bool(not _EXPLAIN.search(text or '') and _CREATE.search(text or '') and _PRODUCT.search(text or ''))


def select_stack(brief):
    text = (brief or '').lower()
    # Explicit choices take precedence over inferred defaults.
    for key, pattern in [('next', r'next\.?js'), ('astro', r'\bastro\b'),
                         ('react', r'\breact\b'), ('python', r'\bpython\b|fastapi|django'),
                         ('node', r'node\.?js|express'), ('static', r'чист\w* html|без фреймворк|vanilla')]:
        if re.search(pattern, text):
            return key
    if re.search(r'\bбот|\bbot\b|api.?сервис|обработк\w* данных', text):
        return 'python'
    if re.search(r'магазин|каталог|\bseo\b|маркетплейс|\bsaas\b', text):
        return 'next'
    if re.search(r'приложен|дашборд|личный кабинет|dashboard|application|\bapp\b', text):
        return 'react'
    if re.search(r'блог|документац|медиа|\bblog\b', text):
        return 'astro'
    return 'static'
