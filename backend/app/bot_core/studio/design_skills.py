"""Pinned, offline upstream design guidance, bounded before reaching the model."""
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / 'computer_skills'


@lru_cache(maxsize=1)
def _search_engine():
    spec = importlib.util.spec_from_file_location('bitthink_uipro_bm25', ROOT / 'ui_ux_pro_max/vendor/scripts/core.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sections(text, names, limit):
    parts = re.split(r'(?m)^## ', text)
    chosen = [part for part in parts[1:] if part.splitlines()[0].strip() in names]
    return '\n\n'.join('## ' + part[:1200] for part in chosen)[:limit]


def design_guidance(user_text: str, kind: str, user_id: int | None = None) -> str:
    from computer_skills.loader import load_skill, disabled_builtin_names
    disabled = disabled_builtin_names(user_id)
    chunks = []
    if 'ui_ux_pro_max' not in disabled:
        chunks.append(load_skill('ui_ux_pro_max', user_id))
        engine = _search_engine()
        context = {'deck': 'presentation editorial storytelling', 'board': 'infographic hierarchy chart data', 'slides': 'presentation editorial storytelling', 'landing': 'landing page responsive clear call to action',
                   'app': 'app interface interaction forms navigation', 'dashboard': 'dashboard data visualization',
                   'infographic': 'infographic hierarchy chart data'}.get(kind, 'interface responsive')
        query = context + ' ' + (user_text or '')[:500]
        domains = ['product', 'style', 'typography', 'ux', 'chart' if kind in {'dashboard', 'infographic'} else 'landing']
        rows = {domain: engine.search(query, domain=domain, max_results=1).get('results', []) for domain in domains}
        chunks.append('UI UX Pro Max: локальные рекомендации, не замена брифу:\n' + json.dumps(rows, ensure_ascii=False)[:5500])
    if 'emil_design_eng' not in disabled:
        chunks.append(load_skill('emil_design_eng', user_id))
        original = (ROOT / 'emil_design_eng/references/upstream.md').read_text(encoding='utf-8')
        names = {'Component Building Principles', 'Accessibility', 'Performance Rules'}
        if kind in {'app', 'dashboard', 'landing'}:
            names.add('The Animation Decision Framework')
        chunks.append('Emil Kowalski: выбранные разделы оригинального навыка:\n' + _sections(original, names, 5000))
    return '\n\n'.join(chunks)
