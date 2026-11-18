import asyncio
import json

import pytest

from app.services import cad_plate


REQUEST = 'Создай 3D-модель крепёжной пластины 120×80×6 мм. Четыре одинаковых сквозных отверстия Ø8 мм по углам, отступ 12 мм.'
DIMS = dict(length_mm=120, width_mm=80, thickness_mm=6, hole_diameter_mm=8, edge_inset_mm=12)


def test_plate_route_is_opt_in_and_requires_explicit_model_creation(monkeypatch):
    monkeypatch.delenv('BITTHINK_CAD_ENABLED', raising=False)
    assert not cad_plate.plate_request(REQUEST)
    monkeypatch.setenv('BITTHINK_CAD_ENABLED', '1')
    assert cad_plate.plate_request(REQUEST)
    assert cad_plate.plate_request('Создай STEP пластины с четырьмя отверстиями Ø8.')
    assert not cad_plate.plate_request('Создай промпт для 3D-модели пластины.')
    assert not cad_plate.plate_request('Объясни, как сделать STEP-модель пластины.')
    assert not cad_plate.plate_request('Создай 3D-модель пластины с пазом.')


@pytest.mark.parametrize('response, expected', [
    (DIMS, 'Построил пластину'),
    ({**DIMS, 'edge_inset_mm': None}, 'укажите'),
    ({**DIMS, 'edge_inset_mm': 3}, 'пересекаются'),
    ({**DIMS, 'length_mm': True}, 'Укажите размеры'),
    ({'unsupported': True}, None),
])
def test_cad_build_requires_all_dimensions_and_valid_geometry(monkeypatch, response, expected):
    import openai_client
    from conversations import conversation_manager

    calls = []
    async def fake_model(*args, **kwargs):
        return json.dumps(response), [], '', []
    async def build(dimensions):
        calls.append(dimensions)
        return [{'filename': name, 'bytes': b'file'} for name in cad_plate.FILENAMES]

    monkeypatch.setattr(openai_client, 'get_chat_response', fake_model)
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    monkeypatch.setattr(cad_plate, '_build', build)
    result = asyncio.run(cad_plate.respond(REQUEST, 92001))
    if expected is None:
        assert result is None and not calls
        return
    answer, files, _, _ = result
    assert expected in answer
    assert calls == ([DIMS] if response is DIMS else [])
    assert bool(files) == (response is DIMS)
