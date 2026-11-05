"""Retired provider ids must not leak through unlimited plans or saved chats."""
import asyncio
import os

os.environ.setdefault('OPENAI_API_KEY','test-key')

from app.config import get_settings  # noqa: F401
from app.billing.plans import allowed_models, clamp_model, computer_models, canonical_billing_model


def test_kimi_is_unavailable_even_for_creator_and_saved_chats_migrate():
    import config
    for tier in ('free','trial','pro','proplus','ultra','creator'):
        assert 'kimi-k2.6' not in allowed_models(tier)
        assert 'kimi-k2.6' not in computer_models(tier)
        assert clamp_model(tier,'kimi-k2.6') == 'search'
        assert 'search' in allowed_models(tier)
    assert 'kimi-k2.6' not in config.AVAILABLE_MODELS
    assert not config.KIMI_API_KEY
    # Historical bills must keep their original price.
    assert canonical_billing_model('kimi-k2.6') == 'kimi-k2.6'


def test_models_payload_never_advertises_retired_provider(monkeypatch):
    from app.api import models_router as api
    stored=[]
    async def subscription(_): return {'tier':'creator'}
    async def selected(_): return 'kimi-k2.6'
    async def set_selected(_,model): stored.append(model)
    async def effort(_): return 'none'
    async def quality(_): return 'high'
    monkeypatch.setattr(api.repo,'get_subscription',subscription)
    monkeypatch.setattr(api.repo,'get_user_model',selected)
    monkeypatch.setattr(api.repo,'set_user_model',set_selected)
    monkeypatch.setattr(api.repo,'get_user_reasoning_effort',effort)
    monkeypatch.setattr(api.repo,'get_user_image_quality',quality)
    payload=asyncio.run(api.list_models('synthetic'))
    import json
    assert 'kimi' not in json.dumps(payload).lower()
    assert payload['selected']=='search'
    assert payload['searchAvailable']
    assert stored==['search']


def test_search_uses_luna_and_shared_tools(monkeypatch):
    from handlers import core
    from app.services.request_intent import classify_request
    # Exercise routing through the real entry point; no hosted provider is used.
    monkeypatch.setattr(core.conversation_manager,'get_user_model',lambda _: 'search')
    monkeypatch.setattr(core.conversation_manager,'get_user_reasoning_effort',lambda _: 'none')
    monkeypatch.setattr(core.conversation_manager,'get_subscription',lambda _: {'tier':'pro'})
    calls=[]
    async def fake(messages,**kwargs):
        calls.append(kwargs)
        return 'Проверено [по источнику](https://example.com).',[], '',[]
    monkeypatch.setattr(core,'get_chat_response',fake)
    import web_scraper
    async def nothing(*_,**__): return ''
    monkeypatch.setattr(web_scraper,'walled_links_context',nothing)
    result=asyncio.run(core.get_smart_response(998831,'Объясни, что такое HTTP',[],None))
    assert calls and calls[-1]['model']=='gpt-6-luna'
    assert calls[-1]['force_web_search'] is True
    assert not result[0].startswith('❌')
