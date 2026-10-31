"""Per-run model spend envelope shared by concurrent employees.

All mutations are synchronous on the event-loop thread. A failed stream with
unknown usage keeps its hold as an unknown expense; it never reopens the run's
budget. User-wallet refunds are independent from this company spend envelope.
"""
from contextvars import ContextVar
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import os
import uuid

from app.billing.quota import QuotaError

current_budget = ContextVar('orchestrator_spend_budget', default=None)


class RunBudgetExceeded(QuotaError):
    pass


@dataclass
class RunBudget:
    limit: float
    spent: float = 0.
    unknown: float = 0.
    holds: dict = field(default_factory=dict)
    exhausted: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def reserve(self, model, input_tokens, output_cap):
        from app.billing.costs import model_cost_usd
        remaining = max(0., self.limit - self.spent - sum(self.holds.values()))
        base = model_cost_usd(model, input_tokens, cache_write_tokens=input_tokens)
        output_rate = model_cost_usd(model, input_tokens, 1) - model_cost_usd(model, input_tokens, 0)
        cap = min(output_cap, max(0, int((remaining - base) / max(output_rate, 1e-12))))
        if cap < min(1024, output_cap):
            self.exhausted = True
            raise RunBudgetExceeded('Достигнут бюджет работы моделей. Выполненные действия и файлы сохранены; готовность незавершённой части не подтверждена.')
        amount = model_cost_usd(model, input_tokens, cap, cache_write_tokens=input_tokens)
        hold = uuid.uuid4().hex
        self.holds[hold] = amount
        return hold, cap

    async def reserve_call(self, model, input_tokens, output_cap):
        while True:
            changed = self.changed
            try:
                return self.reserve(model, input_tokens, output_cap)
            except RunBudgetExceeded:
                if not self.holds:
                    raise
                # Another employee's maximum output is reserved, not spent.
                # Wait for its actual usage instead of prematurely ending the task.
                self.exhausted = False
                await changed.wait()

    def settle(self, hold, model, usage):
        amount = self.holds.pop(hold, 0.)
        if usage:
            from app.billing.call_budget import token_counts
            from app.billing.costs import model_cost_usd, provider_cost_usd
            inp, out, cached, writes = token_counts(usage)
            actual = provider_cost_usd(usage)
            self.spent += actual if actual is not None else model_cost_usd(
                model, inp, out, cached_input_tokens=cached, cache_write_tokens=writes)
        else:
            self.spent += amount
            self.unknown += amount
        changed, self.changed = self.changed, asyncio.Event()
        changed.set()

    def summary(self):
        return {'limit_usd': self.limit, 'spent_usd': round(self.spent, 8),
                'unknown_usd': round(self.unknown, 8), 'budget_exhausted': self.exhausted}


@contextmanager
def run_budget(surface):
    name = 'ORCHESTRATOR_DESKTOP_BUDGET_USD' if surface == 'desktop' else 'ORCHESTRATOR_MODEL_BUDGET_USD'
    default = 10. if surface == 'desktop' else 2.
    try:
        limit = float(os.getenv(name, str(default)))
        if not math.isfinite(limit) or limit <= 0:
            limit = default
    except ValueError:
        limit = default
    budget = RunBudget(limit)
    token = current_budget.set(budget)
    try:
        yield budget
    finally:
        current_budget.reset(token)
