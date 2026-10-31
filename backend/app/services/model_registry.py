"""Reviewed model capabilities and per-request prices (USD / million tokens).

Do not auto-enable models from a remote catalogue. Experimental workers require
an explicit deployment flag, a compatible adapter and subscription permission.
Prices checked against vendor docs and OpenRouter's catalogue on 2026-10-31.
"""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class PriceTier:
    above: int
    input: float
    output: float
    cached: float


@dataclass(frozen=True)
class ModelSpec:
    api_id: str
    provider: str
    input_price: float
    output_price: float
    cached_price: float
    context: int = 1_000_000
    output_cap: int = 16_000
    efforts: tuple[str, ...] = ('low', 'medium', 'high', 'xhigh', 'max')
    default_effort: str = 'medium'
    tiers: tuple[PriceTier, ...] = ()
    explicit_cache: bool = False
    experimental: bool = False

    def rates(self, input_tokens=0, *, apply_tiers=True):
        rates = (self.input_price, self.output_price, self.cached_price)
        if apply_tiers:
            for tier in self.tiers:
                if input_tokens > tier.above:
                    rates = (tier.input, tier.output, tier.cached)
        return rates


MODELS = {
    'gpt-6-luna': ModelSpec('gpt-6-luna', 'openai', .10, .50, .01,
        context=1_050_000, tiers=(PriceTier(272_000, .20, .75, .02),)),
    'gpt-6.1-terra': ModelSpec('gpt-6.1-terra', 'openai', 1., 5., .05,
        context=1_050_000, tiers=(PriceTier(272_000, 2., 7.5, .10),)),
    'gpt-6-sol': ModelSpec('gpt-6.1-sol', 'openai', 2., 10., .10,
        context=1_050_000, output_cap=24_000, tiers=(PriceTier(272_000, 4., 15., .20),)),
    'gpt-6-astra': ModelSpec('gpt-6-astra', 'openai', 10., 50., 1.,
        context=1_050_000, output_cap=24_000, tiers=(PriceTier(272_000, 20., 75., 2.),)),
    'claude-haiku-5.5': ModelSpec('anthropic/claude-haiku-5.5', 'openrouter', .10, .50, .01,
        efforts=('none', 'low', 'medium', 'high', 'xhigh', 'max'),
        tiers=(PriceTier(100_000, .50, 2.50, .05),), explicit_cache=True),
    'claude-sonnet-5.5': ModelSpec('anthropic/claude-sonnet-5.5', 'openrouter', 2., 10., .10,
        output_cap=24_000, explicit_cache=True),
    'claude-opus-5.5': ModelSpec('anthropic/claude-opus-5.5', 'openrouter', 4., 20., .20,
        output_cap=24_000, explicit_cache=True),
    'glm-5.3-flash': ModelSpec('z-ai/glm-5.3-flash', 'openrouter', .10, .50, .02,
        context=1_048_576, efforts=('low', 'high', 'max'), default_effort='low'),
    # Conservative peak rate. The actual endpoint's usage.cost wins over this estimate.
    'minimax-m3.1-flash': ModelSpec('minimax/minimax-m3.1-flash', 'openrouter', .15, .60, .015,
        context=1_048_576, default_effort='low'),
}

MODEL_ALIASES = {spec.api_id: name for name, spec in MODELS.items()}


def model_spec(model):
    return MODELS.get(MODEL_ALIASES.get(model, model))


def openrouter_models(*, include_experimental=False):
    return {name: spec for name, spec in MODELS.items()
            if spec.provider == 'openrouter' and (include_experimental or not spec.experimental)}


def experimental_workers():
    requested = {item.strip() for item in os.getenv('ORCHESTRATOR_EXPERIMENTAL_MODELS', '').split(',')}
    return [name for name, spec in openrouter_models(include_experimental=True).items()
            if spec.experimental and name in requested]


def production_workers():
    requested = os.getenv('ORCHESTRATOR_ECONOMY_WORKERS', 'minimax-m3.1-flash,glm-5.3-flash')
    return [name for name in dict.fromkeys(item.strip() for item in requested.split(','))
            if name in {'minimax-m3.1-flash', 'glm-5.3-flash'}]

