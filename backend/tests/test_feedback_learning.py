import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import uuid

import pytest
from sqlalchemy import delete
from app.config import get_settings
from app.db.engine import SyncSessionLocal
from app.db.models import Conversation, Message, Connector
from app.services import improvement_journal as journal
from app.services import daily_feedback as daily
from app.services.feedback_repair import validate


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'DATA_DIR', tmp_path)
    return tmp_path / 'autonomy/improvements.sqlite3'


def test_journal_deduplicates_and_reopens_verified_issue(ledger):
    kwargs = dict(category='response', title='Теряется контекст', detail='Используется не последний вопрос', target='response', cluster='lost_context')
    iid = journal.record('m1', account='customer-one', **kwargs)
    assert journal.record('m1', account='customer-one', **kwargs) == iid
    journal.record('m2', account='customer-two', **kwargs)
    assert journal.issue(iid)['occurrences'] == 2
    assert journal.issues()[0]['affected_accounts'] == 2
    with pytest.raises(ValueError):
        journal.transition(iid, 'resolved')
    journal.transition(iid, 'monitoring', 'Проверено', verified=True)
    journal.record('m3', account='customer-two', **kwargs)
    assert journal.issue(iid)['status'] == 'new'
    assert any(event['state'] == 'reopened' for event in journal.issue(iid)['events'])


def test_error_log_never_stores_exception_payload_or_contacts(ledger):
    iid = journal.capture_error('provider.openai', 'TimeoutError', account='private@example.com', event_key='attempt-1')
    journal.capture_error('provider.openai', 'TimeoutError', account='private@example.com', event_key='attempt-1')
    assert journal.issue(iid)['occurrences'] == 1
    text = journal.scrub('email user@example.com пароль: SecretValue99 sk-secretvalue123456 https://private.example/doc 79991234567')
    for secret in ('user@example.com', 'SecretValue99', 'sk-secretvalue', 'private.example', '79991234567'):
        assert secret not in text
    assert b'private@example.com' not in ledger.read_bytes()


def test_failed_journal_does_not_break_original_error_handler(monkeypatch):
    def broken():
        raise OSError('disk unavailable')
    monkeypatch.setattr(journal, 'connection', broken)
    assert journal.capture_error('tool.test', 'ValueError') is None


def payload_item():
    return {'ref': 'message-ref', 'conversation': 'chat-ref', 'role': 'user', 'text': 'Не сохранился контекст', '_id': 10, '_account': 12}


def answer(item):
    return {'conversations': [{'conversation': item['conversation'], 'summary': 'Жалоба на потерю контекста ответа',
        'findings': [{'message_ref': item['ref'], 'kind': 'defect', 'category': 'response', 'cluster': 'lost_context',
            'title': 'Теряется контекст', 'detail': 'При уточнении меняется тема ответа', 'target': 'response', 'severity': 2}]}]}


def test_analysis_requires_real_user_evidence_and_preserves_unsupported_features(ledger):
    item = payload_item()
    good = answer(item)
    summaries, findings = daily.validate_review(good, [item])
    assert summaries and findings[0]['account'] == 12
    good['conversations'][0]['findings'][0]['target'] = 'backend/app/auth.py'
    _, findings = daily.validate_review(good, [item])
    iid = journal.record(**findings[0])
    assert journal.issue(iid)['target'] is None and journal.issue(iid)['status'] == 'needs_review'
    bad = answer(item)
    bad['conversations'][0]['findings'][0]['message_ref'] = 'invented'
    with pytest.raises(ValueError):
        daily.validate_review(bad, [item])
    with pytest.raises(ValueError):
        daily.validate_review(answer(item), [{**item, 'role': 'assistant'}])
    with pytest.raises(ValueError):
        daily.validate_review({'conversations': []}, [item])


def test_successful_daily_review_commits_receipts_and_failure_does_not_advance(ledger, monkeypatch):
    item = payload_item()
    monkeypatch.setattr(daily, 'require_owner', lambda uid: None)
    monkeypatch.setattr(daily, 'collect', lambda now: ([item], 0, False))
    async def analyse(uid, items):
        return answer(items[0])
    monkeypatch.setattr(daily, 'analyse', analyse)
    report = asyncio.run(daily.review_daily(1))
    assert report['messages_reviewed'] == 1 and journal.checkpoint() == 10
    assert item['ref'] in journal.was_reviewed([item['ref']])
    assert journal.reports()[0]['summaries'][0]['summary']
    async def broken(uid, items):
        raise ValueError('invalid JSON')
    monkeypatch.setattr(daily, 'analyse', broken)
    with pytest.raises(ValueError):
        asyncio.run(daily.review_daily(1))
    assert journal.checkpoint() == 10 and len(journal.reports()) == 1


def test_daily_model_never_receives_account_ids(ledger, monkeypatch):
    import openai_client as oc
    item = payload_item()
    async def model(messages, **kwargs):
        sent = json.loads(messages[-1]['content'])
        assert not {'_id', '_account', 'account'} & set(sent['messages'][0])
        assert kwargs['use_tools'] is False
        return json.dumps(answer(item)), [], '', []
    monkeypatch.setattr(oc, 'get_chat_response', model)
    assert asyncio.run(daily.analyse(1, [item]))['conversations']


@pytest.fixture
def conversations(ledger, monkeypatch):
    cid = 'review-' + uuid.uuid4().hex
    uid = 9817029
    base = 1_500_000_000
    now = datetime.now(timezone.utc)
    with SyncSessionLocal.begin() as db:
        db.add(Conversation(id=cid, user_id=uid, title='Sensitive project title'))
        db.flush()
        db.add_all([Message(id=base, conversation_id=cid, role='assistant', content='Ответ с неверным итогом', created_at=now-timedelta(minutes=10)),
                    Message(id=base+1, conversation_id=cid, role='user', content='Снова неверно. Почта private@example.com пароль: abcABC12345', created_at=now-timedelta(minutes=9))])
    monkeypatch.setattr(journal, 'checkpoint', lambda: base)
    from app.services import chat_access
    monkeypatch.setattr(chat_access, 'redact_for_user', lambda uid, text: text)
    try:
        yield cid, uid, now, base
    finally:
        with SyncSessionLocal.begin() as db:
            db.execute(delete(Message).where(Message.conversation_id == cid))
            db.execute(delete(Conversation).where(Conversation.id == cid))
            db.execute(delete(Connector).where(Connector.user_id == uid))


def test_collection_scrubs_text_and_omits_attachments(conversations):
    cid, uid, now, base = conversations
    items, cursor, backlog = daily.collect(now)
    user = next(item for item in items if item['_id'] == base+1)
    assert 'private@example.com' not in user['text'] and 'abcABC12345' not in user['text']
    assert 'Sensitive project title' not in json.dumps(items)
    assert 'attachment' not in user


def test_deleted_or_personal_integration_conversations_are_not_reviewed(conversations):
    cid, uid, now, base = conversations
    with SyncSessionLocal.begin() as db:
        db.add(Connector(user_id=uid, type='google', name='Private', payload_encrypted='do-not-decrypt'))
    items, _, _ = daily.collect(now)
    assert all(item.get('_excluded') for item in items if item['_id'] >= base)
    with SyncSessionLocal.begin() as db:
        db.get(Conversation, cid).deleted_at = int(now.timestamp())
    items, _, _ = daily.collect(now)
    assert not any(item['_id'] >= base for item in items)


def proposal_for(path):
    source = Path(__file__).parents[1].joinpath(path.removeprefix('backend/')).read_text(encoding='utf-8')
    module = path.removeprefix('backend/').removesuffix('.py').replace('/', '.')
    test = f'import unittest\nimport {module} as policy\nclass Behavior(unittest.TestCase):\n    def test_behavior(self):\n        self.assertTrue(callable(policy.is_product_request))\n'
    return source, {'path': path, 'base_sha256': hashlib.sha256(source.encode()).hexdigest(), 'source': source, 'test': test}


def test_repair_policy_rejects_privilege_expansion_and_fake_tests():
    source, proposal = proposal_for('backend/app/services/product_strategy.py')
    assert validate(source, proposal)
    for patch in [dict(proposal, path='backend/app/auth.py'), dict(proposal, source=source+'\nimport os\n'),
                  dict(proposal, source=source+'\nx=getattr(select_stack,"__globals__")\n'),
                  dict(proposal, source=source+'\nx="{0.__dict__}".format(re)\n'),
                  dict(proposal, test=proposal['test']+'\nimport unittest.mock\n')]:
        with pytest.raises(ValueError):
            validate(source, patch)


def test_repair_policy_accepts_equivalent_target_imports_only():
    source, proposal = proposal_for('backend/app/services/product_strategy.py')
    test = proposal['test'].replace('import app.services.product_strategy as policy', 'from app.services import product_strategy as policy')
    assert validate(source, dict(proposal, test=test))
    with pytest.raises(ValueError):
        validate(source, dict(proposal, test=test.replace('import product_strategy as policy', 'import product_strategy as policy, daily_feedback')))
    with pytest.raises(ValueError):
        validate(source, dict(proposal, test=test.replace('from app.services', 'from .app.services')))


def test_repair_policy_cannot_remove_user_search_prohibition():
    source, proposal = proposal_for('backend/app/services/request_intent.py')
    changed = source.replace('def forbids_web(text: str) -> bool:', 'def forbids_web(text: str) -> bool:\n    return False')
    with pytest.raises(ValueError):
        validate(source, dict(proposal, source=changed))
