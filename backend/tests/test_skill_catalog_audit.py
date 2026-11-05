import hashlib
import json
from pathlib import Path

import pytest
from app.config import get_settings  # noqa: F401
from computer_skills import loader
from computer_skills.adaptations import canonical_name, read_builtin_resource, registry


@pytest.mark.parametrize('legacy,target', [
    ('wf_search','research'), ('wf_browser_workflow','browser'),
    ('wf_artifacts','workspace'), ('wf_warehouses','sql'),
    ('wf_design','impeccable'), ('wf_routing','wf_capabilities'),
])
def test_consolidated_names_are_loadable_but_not_duplicated_in_catalog(legacy,target):
    assert canonical_name(legacy)==target
    assert canonical_name(legacy,follow_alias=False)==legacy
    assert legacy in loader.builtin_names()
    assert legacy not in {r['name'] for r in loader.catalog()}
    assert loader.load_skill(legacy).startswith('# '+target+'\n')
    assert read_builtin_resource(legacy,'references/contract.md',None)


def test_disabled_legacy_source_alias_stays_disabled(monkeypatch):
    monkeypatch.setattr(loader,'disabled_builtin_names',lambda uid:frozenset({'wf_browser_workflow'}))
    assert 'выключен' in loader.load_skill('browser-use',123)
    assert read_builtin_resource('browser-use','references/contract.md',123) is None
    assert loader.match_skills('load_skill browser-use',user_id=123)==[]


def test_disabling_canonical_target_also_blocks_legacy_access(monkeypatch):
    monkeypatch.setattr(loader,'disabled_builtin_names',lambda uid:frozenset({'research'}))
    assert 'выключен' in loader.load_skill('wf_search',123)
    assert read_builtin_resource('wf_search','references/contract.md',123) is None
    assert 'research' not in loader.match_skills('load_skill wf_search',user_id=123)


def test_personal_skill_wins_over_a_foreign_source_alias(monkeypatch):
    monkeypatch.setattr(loader,'_user_skill_rows',lambda uid:[{'name':'browser_use','body':'Личная инструкция владельца'}])
    monkeypatch.setattr(loader,'disabled_builtin_names',lambda uid:frozenset({'wf_browser_workflow'}))
    assert 'Личная инструкция владельца' in loader.load_skill('browser-use',123,shared=False)


@pytest.mark.parametrize('query',[
    'Напиши README.md для проекта', 'Обнови документацию API по исходникам',
    'Создай runbook развёртывания', 'Перепиши инструкцию запуска',
])
def test_document_authoring_matches_the_actual_job(query):
    assert 'technical_docs' in loader.match_skills(query)


@pytest.mark.parametrize('query',[
    'Найди документацию Python 3.14', 'Что такое README?',
    'Объясни, что такое React', 'Привет, как дела?', 'Сравни три рации',
])
def test_document_authoring_and_frameworks_do_not_capture_ordinary_questions(query):
    names=loader.match_skills(query)
    assert 'technical_docs' not in names
    if query=='Объясни, что такое React':assert 'code' not in names


def test_design_autoload_respects_limit_without_removing_studio_resources():
    assert loader.match_skills('Сделай сайт завода',limit=2)==['impeccable']
    for limit in [1,2]:assert len(loader.match_skills('Сделай лендинг с анимацией',limit=limit))<=limit
    assert 'emil_design_eng' in loader.match_skills('Сделай сайт с анимацией',limit=2)
    assert 'ui_ux_pro_max' in loader.builtin_names()
    assert 'visual_system' in loader.builtin_names()


def test_pinned_github_references_match_manifest():
    root=Path(loader.__file__).parent
    for name in ['code','debug']:
        manifest=json.loads((root/name/'SOURCE.json').read_text(encoding='utf8'))
        for row in manifest['sources']:
            assert len(row['commit'])==40
            content=(root/row['dest']).read_bytes().replace(b'\r\n',b'\n')
            assert hashlib.sha256(content).hexdigest()==row['sha256']
        assert manifest['license']=='MIT'
    assert all(row.get('alias_of') in loader.builtin_names() for row in registry().values() if row.get('alias_of'))


def test_source_names_inside_code_do_not_override_the_actual_task():
    names=loader.match_skills('Почини Python модуль models.py, ошибка импорта класса Order')
    assert 'code' in names
    assert 'wf_capabilities' not in names and 'wf_routing' not in names


def test_incidental_readme_does_not_displace_project_tools():
    assert 'technical_docs' not in loader.match_skills('Напиши сервис на Python, тесты, README и ZIP проекта')
