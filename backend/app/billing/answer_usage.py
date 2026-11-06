"""Content-free, per-answer receipts; no wallet deltas or prompt storage."""
from contextlib import contextmanager
from contextvars import ContextVar

QUERY = '__answer_usage__'
current = ContextVar('answer_usage', default=None)


class AnswerUsage:
    def __init__(self):
        self.models = {}
        self.closed = False

    def record(self, model, counts, charged_units, *, retained=False):
        if self.closed:
            return
        if model not in self.models and len(self.models) >= 31:
            model = 'other'
        row = self.models.setdefault(model, dict(model=model, calls=0, input=0, output=0,
            cached=0, cache_write=0, units=0, retained=0, unknown_tokens=0, unknown_units=0))
        row['calls'] += 1
        if counts is None:
            row['unknown_tokens'] += 1
        else:
            for key, value in zip(('input', 'output', 'cached', 'cache_write'), counts):
                row[key] += max(0, int(value))
        if charged_units is None:
            row['unknown_units'] += 1
        else:
            row['units'] += max(0, int(charged_units))
            if retained:
                row['retained'] += max(0, int(charged_units))

    def snapshot(self):
        return {'version': 1, 'models': [dict(row) for row in self.models.values()]}


@contextmanager
def collect_usage():
    receipt = AnswerUsage()
    token = current.set(receipt)
    try:
        yield receipt
    finally:
        receipt.closed = True
        current.reset(token)
