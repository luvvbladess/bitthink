import asyncio
import hashlib
import json
from pathlib import Path

from app.config import get_settings  # noqa: F401
from computer_skills.loader import builtin_names, load_skill
from studio.design_skills import ROOT, design_guidance


def test_author_skills_and_pinned_mit_resources_are_installed():
    assert {'ui_ux_pro_max', 'emil_design_eng'} <= set(builtin_names())
    for name in ['ui_ux_pro_max', 'emil_design_eng']:
        folder = ROOT / name
        source = json.loads((folder / 'SOURCE.json').read_text())
        assert source['license'] == 'MIT' and len(source['commit']) == 40
        assert 'Permission is hereby granted' in (folder / 'LICENSE.txt').read_text()
        for relative, expected in source['files'].items():
            assert hashlib.sha256((folder / relative).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == expected
        assert 'references/upstream.md' in load_skill(name)


def test_guidance_uses_real_offline_database_and_respects_disabled_skills(monkeypatch):
    from computer_skills import loader
    text = design_guidance('Create a clear finance dashboard', 'dashboard')
    assert 'UI UX Pro Max' in text and 'Emil Kowalski' in text
    assert '"chart": [{' in text and '"style": [{' in text
    assert len(text) < 16000
    monkeypatch.setattr(loader, 'disabled_builtin_names', lambda uid: frozenset({'ui_ux_pro_max', 'emil_design_eng'}))
    assert design_guidance('Create a clear finance dashboard', 'dashboard', 1) == ''


def test_actual_studio_composition_receives_design_skills_without_extra_model_calls(monkeypatch):
    import studio_router as sr
    import studio.research as research
    captured = []
    async def compose(messages, **kwargs):
        captured.extend(messages)
        return '<!doctype html><html><head><title>Design test</title></head><body><h1>Working interface</h1></body></html>'
    monkeypatch.setattr(research, 'compose_with_web', compose)
    html = asyncio.run(sr._compose_html('Build a small app', kind='app', document_context='', history_text='',
        user_id=1, direction={'vibe': 'minimal', 'theme': {}}))
    assert 'Working interface' in html
    prompt = '\n'.join(m['content'] for m in captured)
    assert 'UI UX Pro Max' in prompt and 'Emil Kowalski' in prompt
    assert '"product": [{' in prompt
