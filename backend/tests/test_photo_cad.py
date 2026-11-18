import asyncio

import pytest

from app.services import photo_cad


@pytest.mark.parametrize('text,expected', [
    ('можешь сделать модель вот такого станка. сделай по фото. сам прикинь габариты', True),
    ('Создай 3D-модель корпуса по этому изображению', True),
    ('мне нужно чтобы ты 3д модель этогт станка сделал. сам рассчитай примерные размеры', True),
    ('Объясни, как сделать 3D-модель по фото', False),
    ('Создай сайт и 3D-модель по фото', False),
])
def test_photo_build_is_selected_only_for_model_creation(text, expected):
    assert photo_cad.requested(text, True) is expected
    assert not photo_cad.requested(text, False)


def test_visual_review_allows_one_repair_and_keeps_its_exports(monkeypatch):
    from turn_scope import turn_conversation

    files, models, feedback = [], [], [(True, 'Add the visible spindle.'), (True, '')]

    async def execute(employee, attempt, history, user_id, **kwargs):
        models.append(employee['model'])
        if attempt == 2:
            assert 'Add the visible spindle.' in employee['task'] and len(history) == 1
        prefix = employee['task'].split('папке model-', 1)[1].split('/')[0]
        files[:] = [{'filename': f'model-{prefix}.obj', 'bytes': bytes([attempt])}]
        return {'status': 'ok', 'result': 'Model exported'}

    async def collect():
        return files

    async def review(*args):
        return feedback.pop(0)

    async def status(label):
        pass

    monkeypatch.setattr(photo_cad, 'review', review)
    with turn_conversation(None):
        answer, result, _, _ = asyncio.run(photo_cad.build_from_reference(
            'Сделай 3D-модель по фото', 1, [{}], ['gpt-6-luna', 'gpt-6-sol'], execute, collect, status,
        ))
    assert answer == 'Model exported' and result[0]['bytes'] == b'\x02'
    assert models == ['gpt-6-sol'] * 2 and not feedback
