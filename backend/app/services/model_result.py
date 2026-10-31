"""Tuple-compatible result metadata for adapters without changing chat callers."""


class ModelResult(tuple):
    def __new__(cls, text, files=None, reasoning='', sources=None, *,
                error_kind='', retryable=False, actions_executed=0):
        result = super().__new__(cls, (text, files or [], reasoning, sources or []))
        result.error_kind = error_kind
        result.retryable = retryable
        result.actions_executed = actions_executed
        return result

