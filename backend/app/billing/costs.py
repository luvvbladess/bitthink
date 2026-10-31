"""Approximate API dollar cost from UsageRecord rows. For Creator self-tracking."""

from __future__ import annotations

from typing import Any
import math
from app.services.model_registry import MODELS, model_spec

# USD per 1M tokens. Images: USD per picture. Estimates of vendor list prices,
# not a provider invoice. Unknown models use Luna rates so spend is not silent.
MODEL_USD: dict[str, dict[str, float]] = {
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5.6-luna": {"input": 0.25, "output": 2.00},
    "gpt-6-luna": {"input": 0.10, "output": 0.50, "cached": 0.01},
    "gpt-5.6-terra": {"input": 1.25, "output": 10.00},
    "gpt-5.6-sol": {"input": 1.75, "output": 14.00},
    "gpt-5.6-sol-pro": {"input": 1.75, "output": 14.00},
    "gpt-6-sol": {"input": 2.00, "output": 10.00, "cached": 0.10},
    # API id of Sol. Usage is normally stored as gpt-6-sol; this alias keeps a
    # row written under the provider name on the same list price.
    "gpt-6.1-sol": {"input": 2.00, "output": 10.00, "cached": 0.10},
    "gpt-6.1-terra": {"input": 1.00, "output": 5.00, "cached": 0.05},
    "gpt-6-astra": {"input": 10.00, "output": 50.00, "cached": 1.00},
    "claude-haiku-5.5": {"input": 0.10, "output": 0.50, "cached": 0.01},
    "claude-sonnet-5.5": {"input": 2.00, "output": 10.00, "cached": 0.10},
    "claude-opus-5.5": {"input": 4.00, "output": 20.00, "cached": 0.20},
    "kimi-k2.6": {"input": 0.95, "output": 4.00, "cached": 0.16},
    # DeepSeek bills peak (UTC 01-04, 06-10 on weekdays) at twice the off-peak
    # rate. Mid-point of the two, weighted toward Russian working hours.
    "deepseek-v4-pro": {"input": 0.92, "output": 2.77, "cached": 0.03},
    "deepseek-v4-flash": {"input": 0.21, "output": 0.84, "cached": 0.005},
    "gpt-image-2.5-sunburst": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-2.5-flare": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-2": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-1.5": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-1": {"input": 0.0, "output": 0.0, "image": 0.04},
}

_DEFAULT = {"input": 0.10, "output": 0.50, "image": 0.0}

for _name, _spec in MODELS.items():
    MODEL_USD[_name] = {'input': _spec.input_price, 'output': _spec.output_price, 'cached': _spec.cached_price}


def model_cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    images: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
    *,
    apply_tiers: bool = True,
) -> float:
    """List-price estimate. Cached prompt hits use the model's own cached rate, else 10% of input."""
    from app.billing.plans import canonical_billing_model

    model = canonical_billing_model(model)
    rates = MODEL_USD.get(model) or _DEFAULT
    spec = model_spec(model)
    inp_rate, out_rate, cached_rate = spec.rates(int(input_tokens or 0), apply_tiers=apply_tiers) if spec else (
        rates['input'], rates['output'], rates.get('cached', rates['input'] * .1))
    fresh_input = max(0, int(input_tokens or 0))
    cached = min(max(0, int(cached_input_tokens or 0)), fresh_input)
    fresh_input -= cached
    usd = 0.0
    writes = min(max(0, int(cache_write_tokens or 0)), fresh_input)
    usd += (fresh_input + writes * .25) / 1_000_000 * inp_rate
    usd += cached / 1_000_000 * cached_rate
    usd += max(0, int(output_tokens or 0)) / 1_000_000 * out_rate
    usd += max(0, int(images or 0)) * float(rates.get("image", 0.0))
    return usd


def provider_cost_usd(usage):
    """OpenRouter reports inference cost in usage; zero is a valid cached charge."""
    value = usage.get('cost') if isinstance(usage, dict) else getattr(usage, 'cost', None)
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def usage_row_usd(model, row):
    """Never apply a per-request threshold to day/month aggregate tokens."""
    stored = row.get('usd')
    if stored is not None:
        return float(stored)
    return model_cost_usd(model, row.get('input', 0), row.get('output', 0), row.get('images', 0),
                          row.get('cached', 0), apply_tiers=False)


def add_usage_cost(record, *, input_tokens=0, output_tokens=0, cached=0, writes=0, images=0, actual_usd=None):
    if record.estimated_usd is None:
        old = {'input': record.input_tokens or 0, 'output': record.output_tokens or 0,
               'cached': record.cached_input_tokens or 0, 'images': record.images or 0}
        record.estimated_usd = usage_row_usd(record.model, old)
        record.cost_is_complete = not any(old.values())
    record.estimated_usd += actual_usd if actual_usd is not None else model_cost_usd(
        record.model, input_tokens, output_tokens, images, cached, writes)


def merge_usage(parts):
    result = {}
    for part in parts:
        for model, row in (part or {}).items():
            if not isinstance(row, dict):
                continue
            target = result.setdefault(model, {'input': 0, 'output': 0, 'images': 0, 'calls': 0,
                                                'cached': 0, 'usd': 0., 'cost_complete': True})
            for field in ('input', 'output', 'images', 'calls', 'cached'):
                target[field] += int(row.get(field) or 0)
            target['usd'] += usage_row_usd(model, row)
            target['cost_complete'] = target['cost_complete'] and bool(row.get('cost_complete', False))
    return result


def spend_summary(usage: dict[str, Any] | None) -> dict[str, Any]:
    models: list[dict[str, Any]] = []
    total = 0.0
    for model, row in (usage or {}).items():
        if not isinstance(row, dict):
            continue
        inp = int(row.get("input") or 0)
        out = int(row.get("output") or 0)
        images = int(row.get("images") or 0)
        cached = int(row.get("cached") or 0)
        usd = usage_row_usd(model, row)
        if usd <= 0 and inp <= 0 and out <= 0 and images <= 0:
            continue
        total += usd
        models.append(
            {
                "model": model,
                "usd": round(usd, 4),
                "input": inp,
                "output": out,
                "images": images,
                "cost_complete": bool(row.get('cost_complete', False)),
            }
        )
    models.sort(key=lambda item: (-float(item["usd"]), str(item["model"])))
    return {"usd": round(total, 4), "models": models,
            "cost_complete": all(item['cost_complete'] for item in models)}
