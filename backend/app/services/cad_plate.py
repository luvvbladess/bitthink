"""Web Orchestrator entry point for the internal FreeCAD MCP pilot."""
import asyncio
import base64
import json
import logging
import os
import re

from app.services.answer_format import normalize_answer_format


logger = logging.getLogger(__name__)
DIMENSIONS = {
    'length_mm': 'длина', 'width_mm': 'ширина', 'thickness_mm': 'толщина',
    'hole_diameter_mm': 'диаметр отверстий', 'edge_inset_mm': 'отступ центра отверстия от края',
}
FILENAMES = ('mounting-plate.FCStd', 'mounting-plate.step', 'mounting-plate.html')


def plate_request(text):
    return (os.environ.get('BITTHINK_CAD_ENABLED') == '1'
            and len(text) <= 1200
            and bool(re.match(r'(?i)^\s*(?:пожалуйста[, ]+)?(?:сделай|создай|построй|смоделируй|собери)\b', text))
            and bool(re.search(r'(?i)\b(?:пластин\w*|плит\w*)\b', text))
            and bool(re.search(r'(?i)\b(?:четыре|четырьмя|4)\s+(?:\w+\s+){0,3}отверсти\w*\b|\bотверсти\w*\s+по\s+углам\b', text))
            and bool(re.search(r'(?i)\b3d\b|тр[её]хмерн|модел|freecad|\bstep\b|\bfcstd\b', text))
            and not re.search(r'(?i)\b(?:промпт|доклад|инструкци\w*|черт[её]ж\w*)\b', text))


async def _build(dimensions):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with asyncio.timeout(30):
        async with streamablehttp_client('http://cad:8091/mcp') as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('create_mounting_plate', dimensions)
    if result.isError:
        return None
    payload = result.structuredContent or {}
    if payload.get('step_verified') is not True or payload.get('dimensions_mm') != dimensions:
        return None
    artifacts = payload.get('files') or {}
    files = []
    for name in FILENAMES:
        encoded = artifacts.get(name)
        if not isinstance(encoded, str) or len(encoded) > 1_400_000:
            return None
        data = base64.b64decode(encoded, validate=True)
        if not 0 < len(data) <= 1024 * 1024:
            return None
        files.append({'filename': name, 'bytes': data, **({'canvas': True} if name.endswith('.html') else {})})
    return files


async def respond(text, user_id):
    from openai_client import get_chat_response
    from conversations import conversation_manager
    from app.billing.plans import clamp_model

    tier = conversation_manager.get_subscription(user_id).get('tier')
    answer, _, _, _ = await get_chat_response(
        [{'role': 'system', 'content':
          'Извлеки размеры прямоугольной пластины с четырьмя одинаковыми сквозными отверстиями по углам. '
          'Верни только JSON с ключами length_mm, width_mm, thickness_mm, hole_diameter_mm, edge_inset_mm. '
          'Переведи размеры в мм. edge_inset_mm — одинаковое расстояние от центра отверстия до обоих ближайших краёв. '
          'Пропущенный размер — null. Для другой геометрии, числа отверстий, разных отступов, фасок, резьбы '
          'или иных дополнительных операций верни {"unsupported":true}. Размеры и особенности не угадывай.'},
         {'role': 'user', 'content': text}],
        model=clamp_model(tier, 'gpt-6-luna'), user_id=user_id, use_tools=False,
        use_skills=False, reasoning_effort='low',
    )
    try:
        dimensions = json.loads(normalize_answer_format(answer, 'Только JSON'))
    except (TypeError, ValueError):
        dimensions = {}
    if not isinstance(dimensions, dict):
        dimensions = {}
    if dimensions.get('unsupported') is True:
        return None
    missing = [label for key, label in DIMENSIONS.items() if dimensions.get(key) is None]
    if missing:
        return 'Для построения укажите: ' + ', '.join(missing) + '.', [], '', []
    if any(type(dimensions[key]) not in (int, float) or not 0.1 <= dimensions[key] <= 1000 for key in DIMENSIONS):
        return 'Укажите размеры от 0,1 до 1000 мм.', [], '', []
    dimensions = {key: dimensions[key] for key in DIMENSIONS}
    length, width, thickness, diameter, inset = dimensions.values()
    if inset <= diameter / 2 or min(length, width) - 2 * inset <= diameter:
        return 'Отверстия пересекаются или выходят за края пластины. Уточните диаметр или отступ.', [], '', []
    try:
        files = await _build(dimensions)
    except Exception as exc:
        logger.warning('FreeCAD MCP failed: %s', type(exc).__name__)
        files = None
    if not files:
        return 'FreeCAD не подтвердил построение. Проверьте размеры или повторите запрос.', [], '', []
    return (
        f'Построил пластину {length:g} × {width:g} × {thickness:g} мм с четырьмя сквозными отверстиями Ø{diameter:g} мм. '
        f'Центры отверстий отстоят от краёв на {inset:g} мм. Геометрия STEP проверена после повторного открытия.\n\n'
        'В холсте можно повернуть модель и воспроизвести этапы построения. Редактируемая модель FreeCAD и STEP приложены.',
        files, '', [],
    )
