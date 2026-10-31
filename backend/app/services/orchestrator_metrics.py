"""Content-free per-turn model telemetry; no account IDs, prompts or tool arguments."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import json
import logging
import time
import uuid

logger = logging.getLogger(__name__)
trace = ContextVar('orchestrator_model_trace', default=None)
phase = ContextVar('orchestrator_model_phase', default='director')


def model_phase(name):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            token = phase.set(name)
            try:
                return await fn(*args, **kwargs)
            finally:
                phase.reset(token)
        return wrapped
    return decorate


@contextmanager
def model_trace(surface):
    state = {'run': uuid.uuid4().hex, 'surface': surface, 'started': time.monotonic(),
             'calls': 0, 'input': 0, 'output': 0, 'cached': 0, 'reasoning': 0,
             'estimated_text_usd': 0.0, 'errors': 0}
    state.update({'accepted': None, 'artifacts': 0, 'task_errors': 0})
    token = trace.set(state)
    completed = False
    try:
        from app.services.orchestrator_budget import run_budget
        with run_budget(surface) as budget:
            try:
                yield state
                completed = True
            finally:
                state.update(budget.summary())
    finally:
        try:
            logger.info('orchestrator_summary %s', json.dumps({k: v for k, v in state.items() if k != 'started'} | {
                'returned': completed, 'elapsed_ms': round((time.monotonic()-state['started'])*1000)}, sort_keys=True))
        finally:
            trace.reset(token)


def trace_director(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        from app.services.desktop_context import desktop_executor
        with model_trace('desktop' if desktop_executor.get() is not None else 'web'):
            return await fn(*args, **kwargs)
    return wrapped


def mark_outcome(*, accepted=None, artifacts=None, errors=None):
    state = trace.get()
    if state is not None:
        for key, value in [('accepted', accepted), ('artifacts', artifacts), ('task_errors', errors)]:
            if value is not None:
                state[key] = value


def observe(model, usage, seconds, completed):
    state = trace.get()
    if state is None:
        return
    try:
        from app.billing.call_budget import token_counts
        from app.billing.costs import model_cost_usd, MODEL_USD, provider_cost_usd
        inp, out, cached, writes = token_counts(usage) if usage else (0, 0, 0, 0)
        details = (usage.get('output_tokens_details') or usage.get('completion_tokens_details') or {}) if isinstance(usage, dict) else getattr(usage, 'output_tokens_details', None) or getattr(usage, 'completion_tokens_details', None)
        reasoning = int((details.get('reasoning_tokens', 0) if isinstance(details, dict) else getattr(details, 'reasoning_tokens', 0)) or 0)
        cost = provider_cost_usd(usage)
        cost_source = 'provider' if cost is not None else 'estimate'
        if cost is None:
            cost = model_cost_usd(model, inp, out, cached_input_tokens=cached, cache_write_tokens=writes)
        rates = MODEL_USD.get(model)
        metadata = usage if isinstance(usage, dict) else {}
        state['calls'] += 1
        for key, value in [('input',inp), ('output',out), ('cached',cached), ('reasoning',reasoning)]:
            state[key] += value
        state['estimated_text_usd'] += cost
        state['errors'] += int(not completed)
        logger.info('orchestrator_call %s', json.dumps({
            'run':state['run'], 'surface':state['surface'], 'phase':phase.get(),
            'model':model, 'completed':completed, 'usage_known':bool(usage), 'rates_known':bool(rates),
            'cost_source':cost_source, 'provider':metadata.get('provider', ''),
            'api_model':metadata.get('model', ''), 'generation_id':metadata.get('generation_id', ''),
            'ms':round(seconds*1000), 'input':inp, 'output':out, 'cached':cached,
            'cache_writes':writes, 'reasoning':reasoning, 'estimated_text_usd':round(cost,8)}, sort_keys=True))
    except Exception:
        # Observability must never alter billing, retry a tool or fail a user task.
        logger.warning('orchestrator_metrics_unavailable')
