"""Immutable acceptance examples for the self-maintained stack selection policy."""
import importlib.util
import json
from pathlib import Path

CASES = [
    ('Сделай лендинг кофейни', 'static'),
    ('Создай сайт-портфолио без фреймворков', 'static'),
    ('Build a landing page in vanilla HTML', 'static'),
    ('Создай личный кабинет клиента', 'react'),
    ('Разработай приложение для учёта расходов', 'react'),
    ('Create a dashboard app for a small team', 'react'),
    ('Создай интернет-магазин с SEO и каталогом', 'next'),
    ('Разработай SaaS приложение', 'next'),
    ('Сделай сайт на Next.js', 'next'),
    ('Создай блог', 'astro'),
    ('Сделай сайт документации', 'astro'),
    ('Build a blog website using Astro', 'astro'),
    ('Создай Telegram бота', 'python'),
    ('Напиши приложение на Python FastAPI', 'python'),
    ('Create a bot for reminders', 'python'),
    ('Сделай сайт на React', 'react'),
    ('Создай приложение на Node.js', 'node'),
    ('Build an Express application', 'node'),
]
CLASSIFICATION = [
    ('Создай сайт для пекарни', True), ('Разработай приложение для заметок', True),
    ('Build a website for a painter', True), ('Создай Telegram бота', True),
    ('Какой сайт удобнее?', False), ('Прочитай README и выпиши команды', False),
    ('Исправь опечатку в заголовке сайта', False), ('Что такое React?', False),
    ('Сравни приложения конкурентов', False), ('Переведи текст сайта', False),
    ('Создай личный кабинет', True), ('Создай блог', True), ('Create a reminder bot', True),
    ('Объясни, как создать сайт', False), ('Explain how to create an app', False),
]


def evaluate(path=None):
    if path:
        spec = importlib.util.spec_from_file_location('candidate_strategy', Path(path))
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
    else:
        from app.services import product_strategy as policy
    results = []
    for brief, expected in CASES:
        actual = policy.select_stack(brief)
        results.append({'case': brief, 'expected': expected, 'actual': actual, 'passed': actual == expected})
    for brief, expected in CLASSIFICATION:
        actual = policy.is_product_request(brief)
        results.append({'case': brief, 'expected': expected, 'actual': actual, 'passed': actual == expected})
    return {'passed': sum(item['passed'] for item in results), 'total': len(results), 'cases': results}


if __name__ == '__main__':
    import sys
    print(json.dumps(evaluate(sys.argv[1] if len(sys.argv) > 1 else None), ensure_ascii=False))
