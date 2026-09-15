"""
Модуль оркестрации для гибридного авто-режима (Auto Mode)
Декомпозирует запросы, выполняет подзадачи параллельно и объединяет результаты
"""

import json
import logging
import asyncio
import re
from typing import List, Dict, Any, Tuple

from config import DEEPSEEK_API_KEY, KIMI_API_KEY
from openai_client import get_chat_response
from search_engine import smart_web_search

logger = logging.getLogger(__name__)

# Единые ограничения форматирования для всех выдач Auto/Корреспондента
_FORMATTING_RULES = (
    "Важно: не используй длинное тире «—», только среднее «–»; "
    "не используй HTML-теги и LaTeX (\\textbf{}, \\textit{}, \\texttt{}); "
    "формулы – обычный текст с Unicode: ×, ÷, ±, √, ², ³, ≈, ≤, ≥ (пример: S = a × b), "
    "запрещена LaTeX-нотация формул (доллары, скобки после обратного слэша вроде \\[ \\] или \\( \\), "
    "\\frac{}{}, \\cdot, \\text{} и другие команды с обратным слэшем); "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО оборачивать что-либо в угловые скобки << >> или использовать их как плейсхолдер — "
    "такая запись ломается в документе. Если значение неизвестно — напиши об этом словами."
)


async def _update_status(status_msg: Any, text: str) -> None:
    """Безопасно обновляет сообщение статуса (лоадер), избегая циклических импортов"""
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"Failed to edit status message: {e}")


def _clean_json_response(text: str) -> str:
    """Очищает ответ модели от markdown-разметки кода, оставляя только сырой JSON"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\n', '', cleaned)
        cleaned = re.sub(r'\n```$', '', cleaned)
    return cleaned.strip()


def _format_chat_history(messages: List[Dict[str, Any]]) -> str:
    """История для планировщика и синтеза: pin ранних вопросов + длинный хвост."""
    from model_context import format_chat_history_for_prompt

    return format_chat_history_for_prompt(messages)


async def split_query_into_tasks(user_text: str, user_id: int = None, history_text: str = "") -> List[Dict[str, Any]]:
    """
    Разбивает сложный пользовательский запрос на подзадачи с помощью быстрой модели.
    Учитывает историю диалога, чтобы follow-up запросы не теряли контекст.
    """
    history_block = f"\n\nКонтекст предыдущей переписки:\n{history_text}\n" if history_text else ""

    prompt = (
        "Разбери запрос пользователя на отдельные логические подзадачи.\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "1. Если запрос пользователя простой, короткий или представляет собой один вопрос/команду (например: 'о чем тут', 'напиши код на python', 'что это значит', 'как дела'), НЕ разбивай его на части. Опиши его как СТРОГО одну подзадачу.\n"
        "2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО анализировать или объяснять значение самих разговорных фраз пользователя (например, расписывать значение фраз 'о чем тут', 'сделай ревью', 'объясни'). Сосредоточься на сути намерения пользователя (например: 'Проанализировать загруженный документ и кратко описать его содержание').\n"
        "3. Для каждой подзадачи определи её сложность и необходимость веб-поиска:\n"
        "   - 'simple': если это легкий вопрос, написание стиха/короткого текста, перевод слов, приветствие, простые расчеты.\n"
        "   - 'complex': если это программирование, математика, логические загадки, глубокая аналитика, детальное сравнение, анализ кода.\n\n"
        "Верни СТРОГО JSON-массив объектов без лишнего текста, заголовков и markdown-оберток.\n"
        "Пример формата ответа для простого запроса:\n"
        "[\n"
        "  {\"task\": \"Проанализировать загруженный документ и кратко описать его содержание\", \"complexity\": \"complex\", \"search_required\": false}\n"
        "]\n\n"
        f"Запрос пользователя: \"{user_text}\""
        f"{history_block}"
    )

    try:
        messages = [
            {"role": "system", "content": "Ты системный планировщик задач. Отвечаешь только валидным JSON-массивом."},
            {"role": "user", "content": prompt}
        ]
        # Используем gpt-5.6-luna как быстрый и точный роутер
        response_text, _, _, _ = await get_chat_response(messages, model="gpt-5.6-luna", user_id=user_id)
        
        cleaned_json = _clean_json_response(response_text)
        tasks = json.loads(cleaned_json)
        if isinstance(tasks, list) and len(tasks) > 0:
            logger.info(f"Successfully decomposed query into {len(tasks)} tasks.")
            return tasks
    except Exception as e:
        logger.error(f"Decomposition failed: {e}. Falling back to single task.", exc_info=True)
    
    # Резервный вариант: весь запрос как одна сложная задача
    return [{"task": user_text, "complexity": "complex", "search_required": False}]


async def summarize_scraped_content(task: str, raw_content: str, user_id: int = None) -> str:
    """
    Быстро сжимает сырой скрапленный текст через мини-модель до выжимки фактов.
    """
    if not raw_content or len(raw_content) < 100:
        return raw_content

    prompt = (
        f"Проанализируй предоставленный сырой текст и выдели из него ТОЛЬКО факты, цифры и информацию, "
        f"непосредственно относящиеся к вопросу: \"{task}\".\n"
        "Сделай это кратко, сухо и тезисно, убрав весь мусор и рекламу.\n\n"
        f"Текст для анализа:\n{raw_content}"
    )

    try:
        messages = [
            {"role": "system", "content": f"Ты аналитик данных. Выделяешь только факты без вступлений и выводов. {_FORMATTING_RULES}"},
            {"role": "user", "content": prompt}
        ]
        summary, _, _, _ = await get_chat_response(messages, model="gpt-5.6-luna", user_id=user_id)
        return summary
    except Exception as e:
        logger.error(f"Summarization of scraped content failed: {e}")
        return raw_content[:3000]  # Безопасная обрезка при сбое


async def execute_subtask(
    task: Dict[str, Any],
    history: List[Dict[str, Any]],
    user_id: int
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """
    Выполняет отдельную подзадачу с использованием оптимальной модели и инструментов.
    """
    task_text = task.get("task", "")
    complexity = task.get("complexity", "simple")
    search_required = task.get("search_required", False)

    # 1. Выполняем поиск, если он требуется. Приоритет — встроенный $web_search у Kimi;
    # если KIMI_API_KEY не задан, используем резервный поиск через DuckDuckGo.
    facts = ""
    if search_required:
        try:
            if KIMI_API_KEY:
                logger.info(f"Running Kimi web search for subtask: '{task_text[:30]}'")
                from kimi_client import get_kimi_search_brief
                facts = await get_kimi_search_brief(history, task_text, user_id=user_id)
            else:
                logger.info(f"Running DuckDuckGo web search for subtask: '{task_text[:30]}'")
                raw_search_results = await smart_web_search(task_text)
                facts = await summarize_scraped_content(task_text, raw_search_results, user_id=user_id)
        except Exception as e:
            logger.error(f"Search failed for subtask {task_text}: {e}")
            facts = "[Ошибка поиска информации в интернете]"

    # 2. Формируем промпт для исполнителя
    if facts:
        prompt_content = (
            f"Задача: {task_text}\n\n"
            f"Найденные факты из интернета:\n{facts}\n\n"
            "Ответь на задачу, основываясь на предоставленных фактах.\n\n"
            f"{_FORMATTING_RULES}"
        )
    else:
        prompt_content = f"{task_text}\n\n{_FORMATTING_RULES}"

    # Строим историю с новой подзадачей
    subtask_messages = list(history)
    subtask_messages.append({"role": "user", "content": prompt_content})

    # 3. Выбираем модель
    if complexity == "complex":
        # Сложные задачи отдаем DeepSeek (если настроен) или GPT-5.5 (как резерв)
        if DEEPSEEK_API_KEY:
            from deepseek_client import get_deepseek_response
            logger.info(f"Routing complex subtask to DeepSeek V4 Pro")
            answer, files, reasoning, search = await get_deepseek_response(subtask_messages, model="deepseek-v4-pro", user_id=user_id)
        else:
            logger.info(f"Routing complex subtask to GPT-5.5 (DeepSeek key missing)")
            answer, files, reasoning, search = await get_chat_response(subtask_messages, model="gpt-5.6-sol", user_id=user_id)
    else:
        # Простые задачи — в GPT-5.4 Mini
        logger.info(f"Routing simple subtask to GPT-5.4 Mini")
        answer, files, reasoning, search = await get_chat_response(subtask_messages, model="gpt-5.6-luna", user_id=user_id)

    # 4. Прикрепляем к результатам подзадачи факты из первоначального поиска,
    #    чтобы они отображались в панели «Веб-поиск» в веб-интерфейсе.
    if facts:
        search = [{"query": task_text, "summary": facts[:800]}] + list(search or [])
    return answer, files, reasoning, search


async def synthesize_final_answer(
    original_query: str, task_results: List[Dict[str, Any]], user_id: int = None, history_text: str = ""
) -> Tuple[str, str]:
    """
    Объединяет результаты выполнения подзадач в единый качественный ответ.
    Учитывает историю диалога, чтобы финальный ответ не выпадал из контекста беседы.
    """
    formatted_results = ""
    for i, res in enumerate(task_results):
        formatted_results += f"### Подзадача {i+1}: {res['task']}\nИсполнитель: {res['model']}\nОтвет:\n{res['answer']}\n\n"

    history_block = f"\n\nКонтекст предыдущей переписки:\n{history_text}\n" if history_text else ""

    prompt = (
        "Объедини ответы от разных ИИ-моделей на подзадачи в один красивый, структурированный и логичный ответ на русском языке.\n"
        f"Оригинальный запрос пользователя: \"{original_query}\"\n\n"
        f"Результаты выполнения подзадач:\n{formatted_results}\n"
        f"{history_block}"
        "Сформируй финальный ответ. Используй качественную Markdown-разметку (жирный текст для главного, списки, таблицы).\n"
        "Убери любые повторяющиеся приветствия, прощания или вводные фразы от разных моделей, сделай текст цельным."
    )

    try:
        messages = [
            {"role": "system", "content": f"Ты профессиональный редактор текстов. Объединяешь информацию без потери деталей в чистый Markdown. {_FORMATTING_RULES}"},
            {"role": "user", "content": prompt}
        ]
        # Для сборки используем флагманскую GPT-5.5
        final_answer, _, synthesis_reasoning, _ = await get_chat_response(messages, model="gpt-5.6-sol", user_id=user_id)
        return final_answer, synthesis_reasoning
    except Exception as e:
        logger.error(f"Synthesis failed: {e}", exc_info=True)
        # Если склейка упала, отдаем сырую склейку
        raw_output = "### Результаты выполнения запроса:\n\n"
        for res in task_results:
            raw_output += f"**Задание:** {res['task']}\n{res['answer']}\n\n"
        return raw_output, ""


async def get_hybrid_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """
    Основная управляющая функция авто-режима (Auto Mode).
    """
    await _update_status(status_msg, "🧩 **Auto**: Анализирую структуру вопроса...")

    # История диалога для планировщика и синтеза (пользователь/ассистент, без системных сообщений)
    chat_history = _format_chat_history(messages)

    # 1. Разбиваем запрос на задачи
    tasks = await split_query_into_tasks(user_text, user_id=user_id, history_text=chat_history)
    
    # Проверяем, нужен ли поиск хотя бы в одной задаче, чтобы обновить статус
    has_search = any(t.get("search_required", False) for t in tasks)
    if has_search:
         await _update_status(status_msg, "🔍 **Auto**: Ищу информацию в интернете и читаю сайты...")
    else:
         await _update_status(status_msg, "🧠 **Auto**: Решаю задачи и пишу код...")

    # Вытаскиваем историю переписки, сохраняя документы (системные сообщения о них),
    # но пропуская основной системный промпт (первое системное сообщение) для чистоты контекста подзадач.
    history_context = []
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            content = m.get("content", "")
            if "документ для контекста" in content or "предоставил документ" in content:
                history_context.append(m)
        else:
            history_context.append(m)

    # 2. Выполняем подзадачи параллельно
    jobs = [execute_subtask(task, history_context, user_id) for task in tasks]
    results = await asyncio.gather(*jobs, return_exceptions=True)

    task_results = []
    generated_files = []
    reasoning_sections: List[str] = []
    search_results: List[Dict[str, str]] = []

    for i, task in enumerate(tasks):
        res = results[i]
        task_text = task.get("task", "")
        complexity = task.get("complexity", "simple")

        # Определяем, какая модель должна была выполнять
        if complexity == "complex":
            model_used = "DeepSeek V4 Pro" if DEEPSEEK_API_KEY else "GPT-5.5"
        else:
            model_used = "GPT-5.4 Mini"

        if isinstance(res, Exception):
            logger.error(f"Task {i+1} failed during execution: {res}")
            answer = f"❌ [Ошибка при выполнении этой части запроса: {str(res)[:100]}]"
        else:
            answer, files, sub_reasoning, sub_search = res
            if files:
                generated_files.extend(files)
            if sub_reasoning:
                reasoning_sections.append(f"### Подзадача: {task_text}\n{sub_reasoning}")
            search_results.extend(sub_search)

        task_results.append({
            "task": task_text,
            "model": model_used,
            "answer": answer
        })

    # 3. Собираем финальный ответ
    await _update_status(status_msg, "✨ **Auto**: Объединяю ответы и форматирую текст...")
    final_response, synthesis_reasoning = await synthesize_final_answer(user_text, task_results, user_id=user_id, history_text=chat_history)
    if synthesis_reasoning:
        reasoning_sections.append(f"### Финальная сборка\n{synthesis_reasoning}")

    return final_response, generated_files, "\n\n".join(reasoning_sections), search_results


async def get_correspondent_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Режим корреспондента: правовой анализ через GPT, источники через Kimi, финальный ответ через DeepSeek."""
    await _update_status(status_msg, "🗞 **Корреспондент**: ищу внешние источники через Kimi...")
    from kimi_client import get_kimi_search_brief
    kimi_brief = await get_kimi_search_brief(messages, user_text, user_id=user_id)
    search_results: List[Dict[str, str]] = [{"query": "Внешние источники (Kimi)", "summary": (kimi_brief or "")[:500]}]

    await _update_status(status_msg, "🧠 **Корреспондент**: анализирую правовую позицию через GPT...")
    analysis_prompt = (
        f"Запрос пользователя:\n{user_text}\n\n"
        f"Внешняя информация и источники от Kimi:\n{kimi_brief}\n\n"
        "Ты выступаешь как сильный российский юрист по официальной переписке с государственными органами, "
        "контролирующими ведомствами, работодателями, судами, инспекциями, контрагентами и иными структурами.\n\n"
        f"{_FORMATTING_RULES}\n\n"
        "Сделай только правовой анализ без финального письма.\n"
        "Определи:\n"
        "1. Правовую суть обращения и позицию отправителя.\n"
        "2. Какие отрасли права затронуты: налоговое, трудовое, административное, гражданское, процессуальное или иные.\n"
        "3. Какие нормы законодательства РФ и какая правоприменительная логика могут быть релевантны.\n"
        "4. Какие доводы наиболее сильные для ответа.\n"
        "5. Какие риски, слабые места, недостающие факты или документы есть в ситуации.\n"
        "6. Какую линию ответа выбрать: возражение, разъяснение, частичное согласие, запрос уточнений, подтверждение исполнения или иную.\n\n"
        "Правила:\n"
        "- не выдумывай нормы, судебные акты, письма ведомств и факты;\n"
        "- если данных недостаточно, прямо укажи, чего не хватает;\n"
        "- опирайся только на предоставленные материалы и внешние сведения выше;\n"
        "- не оформляй финальный текст ответа, дай именно структурированный юридический анализ."
    )
    gpt_messages = list(messages) + [{"role": "user", "content": analysis_prompt}]
    gpt_analysis, generated_files, analysis_reasoning, _ = await get_chat_response(
        gpt_messages, model="gpt-5.6-terra", user_id=user_id, use_tools=False
    )
    reasoning_sections = [f"### Правовой анализ\n{analysis_reasoning}"] if analysis_reasoning else []

    await _update_status(status_msg, "✍️ **Корреспондент**: оформляю финальный ответ через DeepSeek...")
    formatter_prompt = (
        "Ты - специалист по официальной юридической переписке и правовому анализу в Российской Федерации.\n"
        "Твоя задача - подготовить юридически корректный, уверенный, официальный ответ на письмо, запрос, претензию, уведомление "
        "или иное обращение, основываясь на нормах права Российской Федерации в актуальной редакции и на предоставленных материалах.\n\n"
        f"Запрос пользователя:\n{user_text}\n\n"
        f"Логика и анализ GPT:\n{gpt_analysis}\n\n"
        f"Факты и источники Kimi:\n{kimi_brief}\n\n"
        "Требования к ответу:\n"
        "- пиши на русском языке в официальном, деловом, уверенном и уважительном стиле;\n"
        "- не пиши как журналист, обозреватель или автор статьи;\n"
        "- не добавляй факты, нормы, судебные акты, даты и выводы, которых нет в материалах или которые не следуют из них;\n"
        "- если данных недостаточно, сначала кратко укажи, что нужно уточнить, а затем дай осторожный проект ответа;\n"
        "- если правовая позиция спорная, покажи это юридически корректно и без лишней эмоциональности;\n"
        "- если применимы нормы права, указывай конкретные статьи или акты только когда они действительно релевантны;\n"
        "- особое внимание уделяй вопросам налогового, трудового и административного права, а также официальной переписке с органами и структурами;\n"
        "- итог должен выглядеть как проект письма, подготовленный сильным юристом-практиком.\n\n"
        "Предпочтительный формат:\n"
        "1. Краткая правовая суть обращения.\n"
        "2. Юридическая оценка.\n"
        "3. Проект официального ответа.\n"
        "4. При необходимости: какие документы приложить, что уточнить, какие есть риски.\n\n"
        "Если пользователь просит именно ответ на письмо, основной акцент сделай на готовом тексте ответа, пригодном для отправки почти без доработки.\n\n"
        f"{_FORMATTING_RULES}\n\n"
        "Технические правила: сохрани ссылки на источники, если они есть в материалах; пиши чистым Markdown; без длинного тире - используй -."
    )

    # Передаём историю диалога, чтобы финальный ответ помнил предыдущие вопросы и ответы
    formatter_messages = list(messages) + [{"role": "user", "content": formatter_prompt}]

    if DEEPSEEK_API_KEY:
        from deepseek_client import get_deepseek_response
        final_answer, files, final_reasoning, final_search = await get_deepseek_response(
            formatter_messages,
            model="deepseek-v4-pro",
            user_id=user_id,
            use_tools=False,
        )
    else:
        final_answer, files, final_reasoning, final_search = await get_chat_response(
            formatter_messages,
            model="gpt-5.6-luna",
            user_id=user_id,
            use_tools=False,
        )

    if final_reasoning:
        reasoning_sections.append(f"### Финальный ответ\n{final_reasoning}")
    search_results.extend(final_search)
    return final_answer, generated_files + files, "\n\n".join(reasoning_sections), search_results
