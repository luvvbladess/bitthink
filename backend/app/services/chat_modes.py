"""Public product modes for BitClient; provider choices remain server-owned."""
from app.billing.plans import LEGACY_MODEL_ALIASES, allowed_models

PUBLIC_CHAT_MODES = (
    ('auto', 'Экспресс'), ('search', 'Поиск'), ('gpt-6-sol', 'Исследование'),
    ('gpt-6-astra', 'Astra'), ('docgen', 'Документы'), ('director', 'Оркестратор'),
)
PUBLIC_CHAT_MODE_IDS = frozenset(key for key, _ in PUBLIC_CHAT_MODES)


def normalize_chat_mode(value):
    value = LEGACY_MODEL_ALIASES.get(value, value)
    return value if value in PUBLIC_CHAT_MODE_IDS else 'auto'


def public_chat_modes(tier):
    allowed = allowed_models(tier)
    return [{'id': key, 'label': label, 'available': key in allowed} for key, label in PUBLIC_CHAT_MODES]
