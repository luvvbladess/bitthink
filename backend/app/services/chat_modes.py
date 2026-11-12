"""Public product modes for BitClient; provider choices remain server-owned."""
from app.billing.plans import LEGACY_MODEL_ALIASES, allowed_models

PUBLIC_CHAT_MODES = (
    ('auto', 'Экспресс'), ('gpt-6-sol', 'Исследование'),
    ('docgen', 'Документы'), ('director', 'Оркестратор'),
)
PUBLIC_CHAT_MODE_IDS = frozenset(key for key, _ in PUBLIC_CHAT_MODES)
# Conversation choices only. gpt-6-astra stays an orchestrator employee for CAD.
RETIRED_CHAT_MODES = {'search': 'auto', 'gpt-6-astra': 'auto'}


def retire_chat_mode(value):
    """Map a removed conversation mode onto Express. Other model ids stay."""
    value = LEGACY_MODEL_ALIASES.get(value, value)
    return RETIRED_CHAT_MODES.get(value, value)


def normalize_chat_mode(value):
    value = retire_chat_mode(value)
    return value if value in PUBLIC_CHAT_MODE_IDS else 'auto'


def public_chat_modes(tier):
    allowed = allowed_models(tier)
    return [{'id': key, 'label': label, 'available': key in allowed} for key, label in PUBLIC_CHAT_MODES]
