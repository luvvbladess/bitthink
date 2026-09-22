"""Approximate API dollar cost from UsageRecord rows. For Creator self-tracking."""

from __future__ import annotations

from typing import Any

# USD per 1M tokens. Images: USD per picture. Estimates of vendor list prices,
# not a provider invoice. Unknown models use Luna rates so spend is not silent.
MODEL_USD: dict[str, dict[str, float]] = {
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5.6-luna": {"input": 0.25, "output": 2.00},
    "gpt-6-luna": {"input": 0.10, "output": 0.50},
    "gpt-5.6-terra": {"input": 1.25, "output": 10.00},
    "gpt-5.6-sol": {"input": 1.75, "output": 14.00},
    "gpt-5.6-sol-pro": {"input": 1.75, "output": 14.00},
    "gpt-6-sol": {"input": 2.00, "output": 10.00},
    "gpt-6-astra": {"input": 10.00, "output": 50.00},
    "kimi-k2.6": {"input": 0.60, "output": 2.50},
    "deepseek-v4-pro": {"input": 0.55, "output": 2.19},
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
    "gpt-image-2.5-sunburst": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-2.5-flare": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-2": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-1.5": {"input": 0.0, "output": 0.0, "image": 0.08},
    "gpt-image-1": {"input": 0.0, "output": 0.0, "image": 0.04},
}

_DEFAULT = {"input": 0.10, "output": 0.50, "image": 0.0}


def model_cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    images: int = 0,
    cached_input_tokens: int = 0,
) -> float:
    """List-price estimate. Cached prompt hits are billed at 10% of the input rate."""
    rates = MODEL_USD.get(model) or _DEFAULT
    fresh_input = max(0, int(input_tokens or 0))
    cached = min(max(0, int(cached_input_tokens or 0)), fresh_input)
    fresh_input -= cached
    usd = 0.0
    input_rate = float(rates.get("input", _DEFAULT["input"]))
    usd += fresh_input / 1_000_000 * input_rate
    usd += cached / 1_000_000 * input_rate * 0.1
    usd += max(0, int(output_tokens or 0)) / 1_000_000 * float(rates.get("output", _DEFAULT["output"]))
    usd += max(0, int(images or 0)) * float(rates.get("image", 0.0))
    return usd


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
        usd = model_cost_usd(model, inp, out, images, cached_input_tokens=cached)
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
            }
        )
    models.sort(key=lambda item: (-float(item["usd"]), str(item["model"])))
    return {"usd": round(total, 4), "models": models}
