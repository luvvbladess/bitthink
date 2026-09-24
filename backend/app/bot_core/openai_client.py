"""
Клиент для работы с OpenAI API (Responses API)
"""

import base64
import json
import logging
import re
import unicodedata
from typing import List, Optional, Tuple, Dict, Any

from openai import AsyncOpenAI
import asyncio

from conversations import conversation_manager
from config import (
    OPENAI_API_KEY,
    DEFAULT_MODEL,
    OPENAI_VISION_MODEL,
    IMAGE_MODEL,
    MAX_TOKENS,
    SYSTEM_PROMPT,
    ASTRA_AGENT_PROMPT,
)


logger = logging.getLogger(__name__)

# Инициализация клиента OpenAI
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ============================================================
# Схема visualize_data для Responses API (поля на верхнем уровне)
# ============================================================
VISUALIZE_TOOL_RESPONSES = {
    "type": "function",
    "name": "visualize_data",
    "description": (
        "Встроить график в ответ. Вызывай, когда человек просит диаграмму "
        "или когда форма данных яснее картинкой, чем абзацем (тренд, сравнение величин). "
        "Не для коротких списков, определений и отказа. Минимум 2 точки. "
        "Не объясняй выбор инструмента вслух."
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

# Нативный поиск Responses API (OpenAI сам выполняет — callback не нужен)
WEB_SEARCH_TOOL = {"type": "web_search"}


_XHIGH_CAPABLE_MODELS = ("gpt-6-sol", "gpt-6-astra")
_MAX_CAPABLE_MODELS = ("gpt-6-astra",)


def _get_reasoning_config(model: str, user_effort: Optional[str] = None) -> dict:
    """Возвращает конфиг reasoning в зависимости от модели и пользовательской настройки.

    user_effort, если задан, переопределяет дефолт модели.
    API Sol и Luna принимают none…max. В продукте max остаётся у Astra,
    xhigh — у Sol и Astra, остальным понижается до high.
    """
    effort = (user_effort or "").strip().lower()
    if effort in {"", "none"}:
        effort = ""
    if effort:
        if effort == "max" and model not in _MAX_CAPABLE_MODELS:
            effort = "xhigh" if model in _XHIGH_CAPABLE_MODELS else "high"
        elif effort == "xhigh" and model not in _XHIGH_CAPABLE_MODELS:
            effort = "high"
        return {"effort": effort}
    if model == "gpt-6-astra":
        return {"effort": "high"}
    if model == "gpt-6-sol":
        return {"effort": "high"}
    if model in ("gpt-5-nano", "gpt-6-luna"):
        return {"effort": "low"}
    return {"effort": "medium"}


# Старые id линейки GPT-5.6 больше не вызываются. Если где-то остались —
# уходят в актуальную модель того же класса.
_MODEL_API_ALIASES = {
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5.6-terra": "gpt-6-sol",
    "gpt-5.6-sol": "gpt-6-sol",
    "gpt-5.6-sol-pro": "gpt-6-sol",
}


def _resolve_api_model(model: str) -> str:
    """Переводит внутренний ID модели бота в реальную строку модели API OpenAI."""
    return _MODEL_API_ALIASES.get(model, model)


def _with_astra_agent_prompt(messages: List[dict]) -> List[dict]:
    """Second system item: keeps the shared SYSTEM_PROMPT cacheable."""
    if any(
        isinstance(msg.get("content"), str) and msg.get("content") == ASTRA_AGENT_PROMPT
        for msg in messages
    ):
        return messages
    out = list(messages)
    insert_at = 0
    for i, msg in enumerate(out):
        if msg.get("role") == "system":
            insert_at = i + 1
            break
    out.insert(insert_at, {"role": "system", "content": ASTRA_AGENT_PROMPT})
    return out


def _astra_unavailable(err: str) -> bool:
    """True when gpt-6-astra is missing from the key, not yet rolled out, or 404s."""
    text = (err or "").lower()
    if "model_not_found" in text:
        return True
    if "gpt-6-astra" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "not found",
            "does not exist",
            "not exist",
            "no access",
            "not available",
            "unknown model",
            "invalid model",
        )
    )


def _usage_token_counts(usage: Any) -> Tuple[int, int, int, int]:
    """(input, output, cached_hits, cache_writes) from a Responses usage object."""
    if not usage:
        return 0, 0, 0, 0

    def _details_map(details: Any) -> tuple[int, int]:
        if not details:
            return 0, 0
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens") or 0)
            writes = int(
                details.get("cache_write_tokens")
                or details.get("cache_creation_input_tokens")
                or 0
            )
            return cached, writes
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        writes = int(
            getattr(details, "cache_write_tokens", 0)
            or getattr(details, "cache_creation_input_tokens", 0)
            or 0
        )
        return cached, writes

    if isinstance(usage, dict):
        inp = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        cached, writes = _details_map(usage.get("input_tokens_details") or usage.get("prompt_tokens_details"))
        return inp, out, cached, writes
    inp = int(getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0)
    cached, writes = _details_map(
        getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
    )
    return inp, out, cached, writes


def _strip_thought_tags(text: str) -> str:
    """Удаляет <thought>...</thought> теги и их содержимое из ответа модели."""
    if not text:
        return text
    # Удаляем блоки <thought>...</thought> (включая переносы строк)
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    # Убираем лишние пустые строки в начале, которые могут остаться после удаления
    text = text.lstrip()
    return text


def _clean_snippet(snippet: str) -> str:
    """Убирает служебные маркеры цитирования OpenAI из сниппета."""
    if not snippet:
        return snippet
    snippet = re.sub(r"[^]*", "", snippet)
    snippet = re.sub(r"\[[a-z]+:\s*[^\]]*\]", "", snippet)
    snippet = re.sub(r"(Crawled|Published|Content type|Source|Total chunks):\s*[^;]*;?\s*", "", snippet, flags=re.IGNORECASE)
    return snippet.strip()


def _sanitize_text(text: Any) -> str:
    """Очищает текст от null-байтов и непечатных символов."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace('\x00', '')
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text


def _build_responses_input(
    messages: List[Dict[str, Any]],
    image_base64: Optional[str] = None,
    image_mime_type: str = "image/jpeg"
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Разделяет messages на instructions (system) и input (user/assistant).
    Первый system – стабильный префикс для кэша OpenAI.
    Документы, память и прочие system-блоки – в input, чтобы не сбивать префикс.
    Если есть image_base64 – встраивает в последнее user-сообщение
    в формате Responses API (input_text / input_image).
    """
    static_parts: List[str] = []
    extra_system: List[str] = []
    input_items = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str) and content:
                text = _sanitize_text(content)
                if text:
                    if not static_parts:
                        static_parts.append(text)
                    else:
                        extra_system.append(text)
            continue

        # Для user/assistant — копируем как есть (text)
        if isinstance(content, list):
            # Уже содержит составной контент (например, от предыдущего vision-запроса)
            clean_parts = []
            for part in content:
                if part.get("type") == "text":
                    clean_parts.append({"type": "input_text", "text": _sanitize_text(part.get("text", ""))})
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    clean_parts.append({"type": "input_image", "image_url": url})
                elif part.get("type") in ("input_text", "input_image"):
                    clean_parts.append(part)
            input_items.append({"role": role, "content": clean_parts})
        else:
            input_items.append({"role": role, "content": _sanitize_text(content)})

    # Встраиваем изображение в последнее user-сообщение
    if image_base64:
        img_url = f"data:{image_mime_type};base64,{image_base64}"
        # Ищем последнее user-сообщение
        for i in reversed(range(len(input_items))):
            if input_items[i].get("role") == "user":
                existing = input_items[i]["content"]
                text = existing if isinstance(existing, str) else ""
                if not text:
                    text = "Опиши это изображение подробно."
                input_items[i]["content"] = [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": img_url}
                ]
                break

    instructions = "\n\n".join(static_parts) if static_parts else None
    prefix = [{"role": "system", "content": text} for text in extra_system]
    return instructions, prefix + input_items


async def transcribe_audio(audio_bytes: bytes, file_format: str = "ogg") -> str:
    """Транскрибирует аудио в текст с помощью Whisper."""
    try:
        import io
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = f"audio.{file_format}"
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ru"
        )
        return response.text
    except Exception as e:
        logger.error(f"Whisper error: {e}")
        return f"❌ Ошибка распознавания: {str(e)}"




async def get_chat_response(
    messages: List[dict],
    model: str = None,
    image_base64: Optional[str] = None,
    image_mime_type: str = "image/jpeg",
    user_id: Optional[int] = None,
    use_tools: bool = True,
    reasoning_effort: Optional[str] = None,
    on_reasoning_delta: Optional[Any] = None,
    force_web_search: bool = False,
    use_skills: bool = True,
    max_tool_loops: Optional[int] = None,
    chat_tools: bool = False,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """
    Получает ответ от OpenAI через Responses API, потоково (stream=True).

    chat_tools=True вместе с use_tools даёт не весь набор Computer, а только
    поиск, графики, страницы и файлы чата – для обычного режима Авто.

    max_tool_loops — сколько ходов с вызовами инструментов разрешено. По
    умолчанию 6 (Astra — 12). Сотруднику Пилота, собирающему комплект файлов,
    передаётся больше: шесть ходов кончались на первом же документе.
    Поддерживает: нативный web_search, reasoning, visualize_data, vision.

    on_reasoning_delta(text: str), если передан, вызывается на каждый кусочек
    reasoning summary сразу по мере прихода — для живого отображения в UI.
    Финальные данные для дальнейшей обработки (текст, tool calls) берутся из
    события response.completed — оно несёт тот же объект response, что и в
    нестриминговом вызове, так что вся логика ниже не меняется.

    use_skills=False отключает автоподбор скилов по тексту последнего user-сообщения.
    Нужно для внутренних служебных вызовов (JSON-планирование Пилота, сборка
    финального ответа, суммаризация документов в Map-Reduce) — там "user"-сообщение
    это не реальный вопрос человека, а собранный самим кодом промпт, и ключевые слова
    в нём (например, шаблонные фразы про "сравни", "договор", "фото") раньше случайно
    подбирали не относящийся к делу скил с инструкциями звать инструменты, которых
    у этого вызова вообще нет (use_tools=False) — путало модель и портило ответ.

    Возвращает (текст_ответа, сгенерированные_файлы, текст_размышлений, результаты_поиска).
    """
    try:
        use_model = model or DEFAULT_MODEL
        is_astra = use_model == "gpt-6-astra"

        # Astra takes images natively. Other routes still upgrade to the vision model.
        if image_base64 and not is_astra:
            use_model = OPENAI_VISION_MODEL

        # Reasoning config считаем ДО перевода старых id в строку API.
        reasoning_cfg = _get_reasoning_config(use_model, reasoning_effort)
        window_model = use_model
        use_model = _resolve_api_model(use_model)

        from model_context import max_output_tokens as model_max_output
        from runtime_context import with_runtime_context

        attach_tools = bool(use_tools or is_astra)
        # Astra is the sandbox agent: never drop computer tools for a web-only hop.
        force_web = bool(force_web_search and not is_astra)
        chat_only = bool(chat_tools and not is_astra)
        sandbox = bool(is_astra or (attach_tools and not force_web and not chat_only))

        messages = with_runtime_context(
            messages,
            use_skills=use_skills,
            skill_limit=3 if is_astra else 2,
            user_id=user_id,
            sandbox=sandbox,
        )
        if is_astra:
            messages = _with_astra_agent_prompt(messages)
        instructions, input_items = _build_responses_input(
            messages, image_base64, image_mime_type
        )

        # Инструменты: web_search, графики, Computer. Список стабилен – иначе OpenAI сбрасывает кэш префикса.
        tools: List[Dict] = [WEB_SEARCH_TOOL] if force_web else ([WEB_SEARCH_TOOL, VISUALIZE_TOOL_RESPONSES] if attach_tools else [])
        if attach_tools and not force_web:
            from computer_tools import CHAT_TOOLS_RESPONSES, COMPUTER_TOOLS_RESPONSES
            tools = tools + (CHAT_TOOLS_RESPONSES if chat_only else COMPUTER_TOOLS_RESPONSES)
        offered_tools = {tool.get("name") for tool in tools if tool.get("name")}

        generated_files: List[Dict[str, Any]] = []
        reasoning_parts: List[str] = []
        search_results: List[Dict[str, str]] = []
        current_input = input_items
        full_text = ""
        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0
        total_cache_write_tokens = 0

        max_loops = 12 if is_astra else 6
        if max_tool_loops:
            max_loops = max(max_loops, min(int(max_tool_loops), 30))
        search_count = 0
        MAX_SEARCHES = 6
        for loop_i in range(max_loops):
            logger.info(f"Responses API call #{loop_i + 1}, model={use_model}")

            request = {
                "model": use_model,
                "input": current_input,
                "instructions": instructions,
                "truncation": "auto",
                "max_output_tokens": model_max_output(window_model),
                "reasoning": reasoning_cfg
            }
            if tools:
                request["tools"] = tools
                # Ask OpenAI to include raw web search results so we can show them in the UI.
                request["include"] = ["web_search_call.results", "web_search_call.action.sources"]
            if user_id is not None:
                # Один ключ на пользователя держит стабильный system-префикс на одном сервере кэша.
                request["prompt_cache_key"] = f"web-{user_id}"[:64]
            if force_web:
                # With tool_choice="auto" search is optional. Explicit search
                # mode and volatile Auto queries must never silently skip it.
                request["tool_choice"] = "required"
            response = None

            async def _consume_stream(stream):
                nonlocal response
                async for event in stream:
                    etype = getattr(event, "type", "") or ""
                    if "reasoning" in etype and "delta" in etype:
                        delta_text = getattr(event, "delta", None)
                        if delta_text and on_reasoning_delta:
                            await on_reasoning_delta(delta_text)
                    elif etype == "response.completed":
                        response = getattr(event, "response", None)
                    elif "web_search" in etype and ("in_progress" in etype or "searching" in etype or etype.endswith(".added")):
                        try:
                            from status_feed import push_status
                            await push_status("search", "ищу в интернете")
                        except Exception:
                            pass

            try:
                stream = await client.responses.create(**request, stream=True)
                await asyncio.wait_for(_consume_stream(stream), timeout=420)
            except asyncio.TimeoutError:
                raise RuntimeError("Модель не ответила за 420 секунд (таймаут)")
            if response is None:
                # Стрим завершился без response.completed — считаем это сбоем API,
                # а не тихо продолжаем с пустым ответом.
                raise RuntimeError("Модель прервала поток без завершающего ответа")
            usage = getattr(response, "usage", None)
            if usage:
                inp, out, cached, writes = _usage_token_counts(usage)
                total_input_tokens += inp
                total_output_tokens += out
                total_cached_tokens += cached
                total_cache_write_tokens += writes
                if cached:
                    logger.info("Responses API prompt cache hit: %s input tokens", cached)

            # Парсим вывод
            text_this_turn = ""
            function_calls = []

            for item in response.output:
                item_type = getattr(item, "type", None)

                if item_type == "message":
                    for ci in getattr(item, "content", []):
                        if getattr(ci, "type", None) == "output_text":
                            txt = getattr(ci, "text", "")
                            text_this_turn += txt

                            # Источники из нативного web_search теперь приходят в annotations
                            # (ResponseFunctionWebSearch.results часто пуст), поэтому извлекаем
                            # url_citation-аннотации и показываем их в панели «Веб-поиск».
                            for ann in getattr(ci, "annotations", []) or []:
                                if getattr(ann, "type", None) != "url_citation":
                                    continue
                                url = getattr(ann, "url", "") or ""
                                if not url:
                                    continue
                                if any(s.get("summary", "").startswith(url) for s in search_results):
                                    continue
                                title = getattr(ann, "title", "") or ""
                                search_results.append({
                                    "query": title or "Веб-поиск",
                                    "summary": f"{url}\n{title}".strip(),
                                })

                            # Если есть мысли в этом ходу — можно логгировать или использовать иначе
                            if "<thought>" in txt:
                                try:
                                    thought_part = txt.split("<thought>")[1].split("</thought>")[0]
                                    # logger.info(f"Thought: {thought_part}")
                                except: pass

                elif item_type == "function_call":
                    function_calls.append(item)

                elif item_type == "reasoning":
                    # Реальная reasoning-трасса из Responses API (summary включён через reasoning.summary="auto").
                    # Разбор защищён от неизвестной формы ответа: пробуем список объектов
                    # с .text, plain-строку и dict-представление по очереди, а не полагаемся
                    # на одну гипотезу о структуре — API может отличаться версией/моделью.
                    summary = getattr(item, "summary", None)
                    found_any = False
                    if isinstance(summary, str) and summary.strip():
                        reasoning_parts.append(summary)
                        found_any = True
                    elif summary:
                        for s in summary:
                            s_text = getattr(s, "text", None)
                            if s_text is None and isinstance(s, dict):
                                s_text = s.get("text")
                            if isinstance(s, str):
                                s_text = s
                            if s_text:
                                reasoning_parts.append(s_text)
                                found_any = True
                    if not found_any:
                        logger.info(f"Reasoning item present but no extractable summary text; raw item: {item!r}")

                elif item_type == "web_search_call":
                    # Нативный web_search — OpenAI выполняет сам. С include=["web_search_call.results"]
                    # получаем title/url/snippet найденных страниц и показываем их в UI как источники.
                    action = getattr(item, "action", None)
                    queries = []
                    if action:
                        queries = getattr(action, "queries", None) or []
                        if not queries and getattr(action, "query", None):
                            queries = [action.query]

                    results = list(getattr(item, "results", None) or [])
                    action_sources = list(getattr(action, "sources", None) or []) if action else []
                    for r in results + action_sources:
                        if len(search_results) >= 24:
                            break
                        if isinstance(r, dict):
                            title = r.get("title") or ""
                            url = r.get("url") or ""
                            snippet = _clean_snippet(r.get("content") or r.get("snippet") or "")
                        else:
                            title = getattr(r, "title", None) or ""
                            url = getattr(r, "url", None) or ""
                            snippet = _clean_snippet(getattr(r, "content", None) or getattr(r, "snippet", None) or "")
                        if url and not any(s.get("summary", "").startswith(url) for s in search_results):
                            search_results.append({"query": title or "Веб-поиск", "summary": f"{url}\n{snippet}".strip()})

                    try:
                        from status_feed import host_from_url, push_status
                        for q in queries[:3]:
                            await push_status("search", str(q))
                        seen_hosts = set()
                        for r in (results + action_sources)[:5]:
                            url = r.get("url") if isinstance(r, dict) else (getattr(r, "url", None) or "")
                            host = host_from_url(url or "")
                            if host and host not in seen_hosts:
                                seen_hosts.add(host)
                                await push_status("browse", host)
                    except Exception:
                        pass

            full_text += text_this_turn

            # Нет function calls → ответ готов
            if not function_calls:
                cleaned_text = _strip_thought_tags(full_text)
                logger.info(f"Done. Total text: {len(full_text)} chars, files: {len(generated_files)}")
                if user_id:
                    await asyncio.to_thread(
                        conversation_manager.track_tokens,
                        user_id,
                        use_model,
                        total_input_tokens,
                        total_output_tokens,
                        total_cached_tokens,
                        total_cache_write_tokens,
                    )
                return cleaned_text or "Нет ответа от модели", generated_files, "\n\n".join(reasoning_parts), search_results

            # Есть function calls → добавляем output текущего ответа в input и выполняем
            next_input = list(current_input)

            # Добавляем все output items этого ответа (assistant turn)
            for item in response.output:
                if hasattr(item, "model_dump"):
                    dumped = item.model_dump(exclude_none=True)
                    next_input.append(dumped)
                else:
                    next_input.append(item)

            # Выполняем каждый function call
            for fc in function_calls:
                call_id = getattr(fc, "call_id", getattr(fc, "id", ""))
                fc_name = getattr(fc, "name", "")
                fc_args_str = getattr(fc, "arguments", "{}")
                try:
                    from status_feed import announce_tool
                    try:
                        _args = json.loads(fc_args_str or "{}")
                    except json.JSONDecodeError:
                        _args = {}
                    await announce_tool(fc_name, _args)
                except Exception:
                    pass

                if fc_name == "visualize_data":
                    try:
                        args = json.loads(fc_args_str)
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
                elif fc_name == "web_search":
                    try:
                        args = json.loads(fc_args_str)
                        query = args.get("query", "")
                        if query:
                            from search_engine import smart_web_search
                            tool_result = await smart_web_search(query)
                            search_count += 1
                            search_results.append({"query": query, "summary": (tool_result or "")[:500]})
                        else:
                            tool_result = "❌ Ошибка: Пустой поисковой запрос."
                    except Exception as e:
                        logger.error(f"Web search error: {e}")
                        tool_result = f"❌ Ошибка поиска: {str(e)}"
                else:
                    from computer_tools import COMPUTER_TOOL_NAMES, run_computer_tool
                    # Only what this call offered: Auto must not reach mail or SSH by name.
                    if fc_name in COMPUTER_TOOL_NAMES and fc_name in offered_tools:
                        try:
                            args = json.loads(fc_args_str or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        tool_result = await run_computer_tool(fc_name, args, user_id)
                        if fc_name in ("browse_page", "connector_browse", "site_login") and args.get("url"):
                            search_results.append({"query": args.get("url", ""), "summary": (tool_result or "")[:500]})
                    else:
                        tool_result = "Инструмент не найден."

                next_input.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": tool_result
                })

            current_input = next_input

        # Вышли из цикла — возвращаем накопленный текст
        logger.warning("Responses API: exhausted max loops")
        if user_id:
            await asyncio.to_thread(
                conversation_manager.track_tokens,
                user_id,
                use_model,
                total_input_tokens,
                total_output_tokens,
                total_cached_tokens,
                total_cache_write_tokens,
            )
        return _strip_thought_tags(full_text) or "Нет ответа от модели", generated_files, "\n\n".join(reasoning_parts), search_results

    except Exception as e:
        err = str(e)
        logger.error(f"OpenAI Responses API error: {e}")
        requested = (model or DEFAULT_MODEL)
        if requested == "gpt-6-astra" and _astra_unavailable(err):
            logger.warning("gpt-6-astra unavailable, falling back to gpt-6-sol")
            return await get_chat_response(
                messages,
                model="gpt-6-sol",
                image_base64=image_base64,
                image_mime_type=image_mime_type,
                user_id=user_id,
                use_tools=use_tools,
                reasoning_effort="high" if reasoning_effort in {None, "none", "max"} else reasoning_effort,
                on_reasoning_delta=on_reasoning_delta,
                force_web_search=force_web_search,
            )
        return f"❌ Ошибка OpenAI: {str(e)}", [], "", []


async def get_simple_response(user_message: str, model: str = None) -> Tuple[str, List[Dict[str, Any]]]:
    """Получает простой ответ без истории."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]
    text, files, _, _ = await get_chat_response(messages, model=model)
    return text, files


def _image_generate_kwargs(prompt: str, size: str = "auto", quality: str = "auto") -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": IMAGE_MODEL, "prompt": prompt, "n": 1}
    if size and size != "auto":
        kwargs["size"] = size
    if quality and quality != "auto":
        kwargs["quality"] = quality
    return kwargs


async def generate_image(prompt: str, size: str = "auto", quality: str = "auto") -> Tuple[Optional[str], Optional[str]]:
    """Генерирует изображение через GPT Image 2.5. Не передаём response_format: GPT Image всегда отдаёт b64."""
    try:
        response = await asyncio.wait_for(
            client.images.generate(**_image_generate_kwargs(prompt, size, quality)),
            timeout=180,
        )
        if response.data and len(response.data) > 0:
            b64_data = response.data[0].b64_json
            revised_prompt = response.data[0].revised_prompt
            if b64_data:
                return f"data:image/png;base64,{b64_data}", revised_prompt
            elif response.data[0].url:
                return response.data[0].url, revised_prompt
            return None, "API не вернул ни URL, ни данные изображения."
        return None, "Не удалось сгенерировать изображение"
    except asyncio.TimeoutError:
        logger.error("Image generation timed out after 180s")
        return None, "Таймаут: генерация заняла слишком много времени. Попробуйте упростить описание."
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Image generation error: {error_msg}")
        if "safety system" in error_msg or "moderation_blocked" in error_msg or "safety" in error_msg.lower():
            return None, "Запрос отклонен системой безопасности. Измените описание."
        return None, f"Ошибка генерации: {error_msg[:200]}"


def encode_image_to_base64(image_data: bytes) -> str:
    """Кодирует изображение в base64."""
    return base64.b64encode(image_data).decode('utf-8')


def _image_upload(image_bytes: bytes, index: int = 0):
    import io
    buf = io.BytesIO(image_bytes)
    buf.name = f"image-{index}.png"
    return buf


async def edit_image(
    image_bytes: bytes | list[bytes],
    prompt: str,
    size: str = "auto",
    quality: str = "auto",
) -> Tuple[Optional[str], Optional[str]]:
    """Правка или генерация по референсам через images.edit (GPT Image 2.5)."""
    sources = image_bytes if isinstance(image_bytes, list) else [image_bytes]
    sources = [item for item in sources if item]
    if not sources:
        return None, "Нет изображения для правки"
    try:
        files = [_image_upload(item, index) for index, item in enumerate(sources[:16])]
        kwargs: dict[str, Any] = {
            "model": IMAGE_MODEL,
            "image": files if len(files) > 1 else files[0],
            "prompt": prompt,
            "n": 1,
        }
        if size and size != "auto":
            kwargs["size"] = size
        if quality and quality != "auto":
            kwargs["quality"] = quality
        # GPT Image 2.5 processes image inputs at high fidelity; the optional flag is rejected.
        response = await asyncio.wait_for(client.images.edit(**kwargs), timeout=180)
        if response.data and len(response.data) > 0:
            b64_data = response.data[0].b64_json
            if b64_data:
                return f"data:image/png;base64,{b64_data}", prompt
            elif response.data[0].url:
                return response.data[0].url, prompt
        return None, "Не удалось отредактировать изображение"
    except asyncio.TimeoutError:
        logger.error("Image edit timed out after 180s")
        return None, "Таймаут: правка заняла слишком много времени. Попробуйте упростить описание."
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Image edit error: {error_msg}")
        if "safety system" in error_msg or "moderation_blocked" in error_msg or "safety" in error_msg.lower():
            return None, "Запрос отклонен системой безопасности. Измените описание."
        return None, f"Ошибка правки: {error_msg[:200]}"


async def edit_image_with_dalle(
    image_bytes: bytes,
    prompt: str,
    size: str = "auto",
) -> Tuple[Optional[str], Optional[str]]:
    return await edit_image(image_bytes, prompt, size=size)
