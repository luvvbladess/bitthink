"""
Клиент для работы с DeepSeek API (Chat Completions API)
"""

import asyncio
import logging
import json
from typing import List, Dict, Any, Tuple, Optional

from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY
from conversations import conversation_manager
from model_context import max_output_tokens
from search_engine import get_web_search_sources

logger = logging.getLogger(__name__)

# Инициализация клиента DeepSeek (совместим с OpenAI SDK)
if DEEPSEEK_API_KEY:
    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
else:
    client = None

# Схема visualize_data для Chat Completions API (вложена в function)
VISUALIZE_TOOL_DEEPSEEK = {
    "type": "function",
    "function": {
        "name": "visualize_data",
        "description": (
            "Построить график или диаграмму на основе данных. "
            "Используй этот инструмент, когда пользователь просит визуализировать данные, "
            "показать тренды или сравнить значения. "
            "ВСЕГДА проверяй, что данных достаточно для построения (минимум 2 точки)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Подпись (например, год или категория)"},
                            "value": {"type": "number", "description": "Значение (число)"}
                        },
                        "required": ["label", "value"]
                    },
                    "description": "Массив данных для графика"
                },
                "title": {"type": "string", "description": "Заголовок графика на русском языке"},
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie"],
                    "description": "Тип графика: bar (столбцы), line (линии), pie (круговая)"
                },
                "x_label": {"type": "string", "description": "Подпись оси X"},
                "y_label": {"type": "string", "description": "Подпись оси Y"},
                "caption": {"type": "string", "description": "Краткий вывод по графику (1-2 предложения)"}
            },
            "required": ["data", "title", "chart_type"]
        }
    }
}

# Схема web_search для Chat Completions API
WEB_SEARCH_TOOL_DEEPSEEK = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Поиск актуальной информации в интернете (новости, погода, курсы валют, факты). Используй этот инструмент, если запрос пользователя требует свежих данных.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос. Для техники, продуктов и международных фактов предпочтительно использовать английский язык."}
            },
            "required": ["query"]
        }
    }
}


async def get_deepseek_response(
    messages: List[Dict[str, Any]],
    model: str = "deepseek-v4-pro",
    user_id: Optional[int] = None,
    use_tools: bool = True,
    on_reasoning_delta: Optional[Any] = None,
    reasoning_enabled: bool = True,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """
    Получает ответ от DeepSeek через Chat Completions API, потоково (stream=True).
    Поддерживает: рассуждения (reasoning_content), визуализацию (visualize_data) и поиск (web_search).

    on_reasoning_delta(text: str), если передан, вызывается на каждый кусочек
    reasoning_content сразу по мере прихода — для живого отображения "мыслей"
    в UI, а не только после того, как весь ответ готов.

    Возвращает (текст_ответа, файлы, текст_размышлений, результаты_поиска).
    """
    global client
    # Ленивая инициализация на случай, если ключ был обновлен в рантайме в config.py
    if client is None and DEEPSEEK_API_KEY:
        client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    if not DEEPSEEK_API_KEY or client is None:
        logger.warning(f"Attempted DeepSeek call without API key for user {user_id}")
        return "❌ Пожалуйста, укажите DEEPSEEK_API_KEY в файле config.py для использования этой модели.", [], "", []

    from runtime_context import with_runtime_context

    messages = with_runtime_context(
        messages,
        use_skills=True,
        user_id=user_id,
        sandbox=bool(use_tools),
    )
    current_messages = []
    for msg in messages:
        # Убеждаемся, что передаем только стандартные поля (role, content, name, tool_calls и т.д.)
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # Очищаем content от null-байтов (как в openai_client.py)
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
            )
        if isinstance(content, str):
            content = content.replace('\x00', '')
        else:
            content = str(content or "")
            
        current_messages.append({
            "role": role,
            "content": content
        })

    generated_files: List[Dict[str, Any]] = []
    reasoning_parts: List[str] = []
    search_results: List[Dict[str, str]] = []
    max_loops = 6
    search_count = 0
    MAX_SEARCHES = 5
    last_text = ""
    total_input_tokens = 0
    total_output_tokens = 0

    for loop_i in range(max_loops):
        logger.info(f"DeepSeek API call #{loop_i + 1}, model={model}, user={user_id}")

        # После MAX_SEARCHES поисков убираем web_search из инструментов,
        # чтобы модель не зациклилась на поиске и вернула финальный ответ
        active_tools = [VISUALIZE_TOOL_DEEPSEEK] if use_tools else []
        if use_tools and search_count < MAX_SEARCHES:
            active_tools.append(WEB_SEARCH_TOOL_DEEPSEEK)
        if use_tools:
            from computer_tools import COMPUTER_TOOLS_CHAT
            active_tools = active_tools + COMPUTER_TOOLS_CHAT

        content_parts: List[str] = []
        loop_reasoning_parts: List[str] = []
        tool_call_chunks: Dict[int, Dict[str, str]] = {}
        stream_usage = None

        async def _consume_stream(stream):
            nonlocal stream_usage
            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    stream_usage = chunk_usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                delta_reasoning = getattr(delta, "reasoning_content", None)
                if delta_reasoning:
                    loop_reasoning_parts.append(delta_reasoning)
                    if on_reasoning_delta:
                        await on_reasoning_delta(delta_reasoning)
                if getattr(delta, "content", None):
                    content_parts.append(delta.content)
                delta_tool_calls = getattr(delta, "tool_calls", None)
                if delta_tool_calls:
                    for tc_delta in delta_tool_calls:
                        slot = tool_call_chunks.setdefault(tc_delta.index, {"id": "", "name": "", "arguments": ""})
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        func = getattr(tc_delta, "function", None)
                        if func and func.name:
                            slot["name"] += func.name
                        if func and func.arguments:
                            slot["arguments"] += func.arguments

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=current_messages,
                tools=active_tools or None,
                extra_body={"thinking": {"type": "enabled" if reasoning_enabled else "disabled"}},
                max_tokens=max_output_tokens(model),
                stream=True,
                stream_options={"include_usage": True},
            )
            await asyncio.wait_for(_consume_stream(stream), timeout=420)
        except asyncio.TimeoutError:
            logger.error("DeepSeek API call timed out after 420s")
            return "❌ Модель DeepSeek не ответила за 420 секунд (таймаут)", [], "\n\n".join(reasoning_parts), search_results
        except Exception as e:
            logger.error(f"DeepSeek API call failed: {e}", exc_info=True)
            return f"❌ Ошибка API DeepSeek: {str(e)}", [], "\n\n".join(reasoning_parts), search_results

        if stream_usage:
            total_input_tokens += getattr(stream_usage, "prompt_tokens", 0) or 0
            total_output_tokens += getattr(stream_usage, "completion_tokens", 0) or 0

        message_content = "".join(content_parts)
        loop_reasoning = "".join(loop_reasoning_parts)
        if loop_reasoning:
            reasoning_parts.append(loop_reasoning)
        elif loop_i == 0:
            logger.info(f"DeepSeek stream had no reasoning_content deltas for model={model}")

        if message_content:
            last_text = message_content

        tool_calls = None
        if tool_call_chunks:
            from types import SimpleNamespace
            tool_calls = [
                SimpleNamespace(
                    id=slot["id"],
                    type="function",
                    function=SimpleNamespace(name=slot["name"], arguments=slot["arguments"]),
                )
                for slot in tool_call_chunks.values()
            ]

        # Формируем сообщение ассистента для добавления в историю
        assistant_msg = {
            "role": "assistant",
            "content": message_content or ""
        }

        if tool_calls:
            # Для корректного продолжения диалога в Chat Completions нужно передать tool_calls
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in tool_calls
            ]

        current_messages.append(assistant_msg)

        # Если вызова функций нет — возвращаем итоговый ответ
        if not tool_calls:
            logger.info(f"DeepSeek completed successfully on loop {loop_i+1}")
            if user_id:
                conversation_manager.track_tokens(user_id, model, total_input_tokens, total_output_tokens)
            return message_content or "Нет ответа от модели", generated_files, "\n\n".join(reasoning_parts), search_results[:20]

        # Выполняем каждый tool call
        for tc in tool_calls:
            call_id = tc.id
            func_name = tc.function.name
            func_args_str = tc.function.arguments

            logger.info(f"Executing DeepSeek tool '{func_name}' for user {user_id}")
            try:
                from status_feed import announce_tool
                try:
                    _args = json.loads(func_args_str or "{}")
                except json.JSONDecodeError:
                    _args = {}
                await announce_tool(func_name, _args)
            except Exception:
                pass

            tool_result = ""
            if func_name == "visualize_data":
                try:
                    args = json.loads(func_args_str)
                    from chart_generator import generate_chart
                    chart_bytes = generate_chart(
                        data=args.get("data", []),
                        title=args.get("title", "График"),
                        chart_type=args.get("chart_type", "bar"),
                        x_label=args.get("x_label", ""),
                        y_label=args.get("y_label", "")
                    )
                    if chart_bytes:
                        caption = args.get("caption", "")
                        generated_files.append({"bytes": chart_bytes, "caption": caption})
                        tool_result = f"✅ График построен. Подпись: {caption}"
                    else:
                        tool_result = "❌ Ошибка при построении графика."
                except Exception as e:
                    logger.error(f"Chart generation error: {e}")
                    tool_result = f"❌ Ошибка графика: {str(e)}"
            elif func_name == "web_search":
                try:
                    args = json.loads(func_args_str)
                    query = args.get("query", "")
                    if query:
                        from search_engine import smart_web_search, get_web_search_sources
                        sources = await get_web_search_sources(query, max_results=12)
                        search_results.extend([
                            {"query": s.get("title", "Источник"), "summary": f"{s.get('url', '')}\n{s.get('snippet', '')}".strip()}
                            for s in sources[:12]
                        ])
                        tool_result = await smart_web_search(query, max_results=12)
                        search_count += 1
                    else:
                        tool_result = "❌ Ошибка: Пустой поисковой запрос."
                except Exception as e:
                    logger.error(f"Web search error: {e}")
                    tool_result = f"❌ Ошибка поиска: {str(e)}"
            else:
                from computer_tools import COMPUTER_TOOL_NAMES, run_computer_tool
                if func_name in COMPUTER_TOOL_NAMES:
                    try:
                        args = json.loads(func_args_str or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool_result = await run_computer_tool(func_name, args, user_id)
                    if func_name in ("browse_page", "connector_browse", "site_login") and args.get("url"):
                        search_results.append({"query": args.get("url", ""), "summary": (tool_result or "")[:500]})
                else:
                    tool_result = f"Инструмент {func_name} не найден."

            current_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_result
            })

    logger.warning("DeepSeek API: exhausted max loops")
    if user_id:
        conversation_manager.track_tokens(user_id, model, total_input_tokens, total_output_tokens)
    return last_text or "Нет ответа от модели", generated_files, "\n\n".join(reasoning_parts), search_results[:20]
