"""A shared, request-local retrieval budget, including parallel and fallback calls."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import asyncio
import copy
import re
import json


@dataclass
class SearchBudget:
    searches: int = 2
    reads: int = 3
    queries: set = field(default_factory=set)
    pages: set = field(default_factory=set)
    pending: dict = field(default_factory=dict, repr=False)

    @property
    def search_left(self):
        return max(0, self.searches - len(self.queries))

    @property
    def read_left(self):
        return max(0, self.reads - len(self.pages))

    def evidence_text(self):
        """A reserve model reuses observations, rather than searching again."""
        found = []
        seen = set()
        remaining = 9000
        for task in self.pending.values():
            if not task.done() or task.cancelled() or task.exception() is not None:
                continue
            result = task.result()
            rows = result.get('results', []) if isinstance(result, dict) else result if isinstance(result, list) else [result]
            for row in rows:
                if isinstance(row, dict):
                    row = {key: row[key] for key in ('title', 'url', 'snippet', 'content', 'text') if key in row}
                text = json.dumps(row, ensure_ascii=False) if isinstance(row, dict) else str(row)
                text = text[:3000]
                if not text or text in seen or remaining <= 0:
                    continue
                seen.add(text)
                found.append(text[:remaining])
                remaining -= len(found[-1])
        return '\n'.join(found)


current_search_budget = ContextVar('search_budget', default=None)
_active_lookup = ContextVar('active_search_lookup', default=None)
LIMIT_NOTE = 'Лимит поиска для этого ответа достигнут. Заверши ответ по уже полученным данным; кратко укажи конкретные пробелы.'
SEARCH_PLAN = ('Ищи экономно: сначала один точный запрос с названием объекта, задачей и важными '
               'ограничениями (бюджет, регион, период). Не добавляй текущий год автоматически. '
               'Используй полученные фрагменты сразу. Второй запрос — только по конкретному пробелу, '
               'без синонимичного повторения успешного поиска. Открывай лишь нужные страницы; '
               'для изменений оформления и уже приложенных данных поиск не нужен. '
               'После получения достаточных данных сразу дай результат.')


def search_turn(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        if current_search_budget.get() is not None:
            return await function(*args, **kwargs)
        budget = SearchBudget(4, 6) if kwargs.get('research') else SearchBudget()
        token = current_search_budget.set(budget)
        try:
            return await function(*args, **kwargs)
        finally:
            # No references to page contents or in-flight requests survive a turn.
            for task in budget.pending.values():
                if not task.done():
                    task.cancel()
            if budget.pending:
                await asyncio.gather(*budget.pending.values(), return_exceptions=True)
            current_search_budget.reset(token)
    return wrapped


def limited_search(empty):
    def decorate(function):
        @wraps(function)
        async def wrapped(query, *args, **kwargs):
            budget = current_search_budget.get()
            if budget is None:
                return await function(query, *args, **kwargs)
            # Preserve word order, quoted phrases and negations: they change intent.
            normalized = ' '.join(str(query).casefold().split())
            sites = kwargs.get('sites') or (args[0] if args and isinstance(args[0], list) else [])
            key = (normalized, tuple(sorted(str(x).casefold() for x in sites)))
            if _active_lookup.get() == key:
                return await function(query, *args, **kwargs)
            cache_key = (function.__module__, function.__name__, key)
            if cache_key in budget.pending:
                return copy.deepcopy(await budget.pending[cache_key])
            if key not in budget.queries:
                if not budget.search_left:
                    return empty()
                # Reserve before awaiting, so parallel calls share the ceiling.
                budget.queries.add(key)
            async def execute():
                token = _active_lookup.set(key)
                try:
                    return await function(query, *args, **kwargs)
                finally:
                    _active_lookup.reset(token)
            task = asyncio.create_task(execute())
            budget.pending[cache_key] = task
            return copy.deepcopy(await task)
        return wrapped
    return decorate


def search_tools_allowed(name):
    budget = current_search_budget.get()
    if budget is None:
        return True
    if name in {'web_search', '$web_search', 'server_search'}:
        return bool(budget.search_left)
    if name in {'browse_page', 'browse_visual'}:
        return bool(budget.read_left)
    return True
