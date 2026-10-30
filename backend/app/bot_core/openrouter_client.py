"""OpenRouter chat-completions client for Claude Haiku, Sonnet and Opus.

Called by director_router (orchestrator employees) and handlers/core.py (Auto).
No database schema change. Billing stays on the product ids below.

User instruction: внеси изменения по моделям, затем проверь все и задеплой
и проверь на сервере. Качество должно улучшиться, цена вызовов желательно упасть.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from app.billing.quota import billing_scope
from app.services.search_budget import search_turn
from config import OPENROUTER_API_KEY
from model_context import cached_prompt_tokens, max_output_tokens

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-5.5"
SONNET_MODEL = "claude-sonnet-5.5"
OPUS_MODEL = "claude-opus-5.5"
OPENROUTER_MODELS = frozenset({HAIKU_MODEL, SONNET_MODEL, OPUS_MODEL})

_API_IDS = {
    HAIKU_MODEL: "anthropic/claude-haiku-5.5",
    SONNET_MODEL: "anthropic/claude-sonnet-5.5",
    OPUS_MODEL: "anthropic/claude-opus-5.5",
}
_DEFAULT_EFFORT = {HAIKU_MODEL: "medium", SONNET_MODEL: "medium", OPUS_MODEL: "medium"}

_client: AsyncOpenAI | None = None


def _client_or_none() -> AsyncOpenAI | None:
    global _client
    if _client is None and OPENROUTER_API_KEY:
        _client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
    return _client


def _effort(model: str, requested: Optional[str]) -> str:
    effort = (requested or _DEFAULT_EFFORT.get(model) or "low").strip().lower()
    if model == HAIKU_MODEL:
        return effort if effort in {"low", "medium"} else "medium"
    return effort if effort in {"low", "medium"} else "medium"


def _delta_field(delta: Any, key: str) -> Any:
    value = getattr(delta, key, None)
    if value:
        return value
    extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict) and extra.get(key):
        return extra[key]
    return None


@billing_scope
@search_turn
async def get_openrouter_response(
    messages: List[Dict[str, Any]],
    model: str = HAIKU_MODEL,
    user_id: Optional[int] = None,
    use_tools: bool = True,
    on_reasoning_delta: Optional[Any] = None,
    chat_tools: bool = False,
    use_skills: bool = True,
    max_tool_loops: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Same return shape as the DeepSeek and OpenAI clients."""
    client = _client_or_none()
    if model not in OPENROUTER_MODELS:
        model = HAIKU_MODEL
    if not OPENROUTER_API_KEY or client is None:
        return "❌ Ошибка OpenRouter: ключ не задан", [], "", []

    from runtime_context import with_runtime_context

    messages = with_runtime_context(
        messages,
        use_skills=use_skills,
        user_id=user_id,
        sandbox=bool(use_tools and not chat_tools),
    )
    from app.services.autonomy import attach_company
    messages = attach_company(messages)
    from computer_tools import COMPUTER_TOOLS_CHAT, SKILL_TOOL_NAMES, response_tool_names

    wanted = response_tool_names(
        attach_tools=bool(use_tools),
        chat_only=bool(chat_tools),
        force_web=False,
        skill_tools=bool(use_skills),
    )
    extra_tools = [tool for tool in COMPUTER_TOOLS_CHAT if tool["function"]["name"] in wanted]
    current_messages: List[Dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
            )
        if not isinstance(content, str):
            content = str(content or "")
        current_messages.append({"role": msg.get("role", "user"), "content": content.replace("\x00", "")})

    generated_files: List[Dict[str, Any]] = []
    reasoning_parts: List[str] = []
    search_results: List[Dict[str, str]] = []
    loops = max(1, int(max_tool_loops or (4 if chat_tools else 6)))
    search_count = 0
    effort = _effort(model, reasoning_effort)

    for loop_i in range(loops):
        from app.services.search_budget import search_tools_allowed

        from deepseek_client import VISUALIZE_TOOL_DEEPSEEK, WEB_SEARCH_TOOL_DEEPSEEK
        catalog = ([VISUALIZE_TOOL_DEEPSEEK] if use_tools else []) + ([WEB_SEARCH_TOOL_DEEPSEEK] if use_tools and search_count < 5 else []) + extra_tools
        active_tools = [tool for tool in catalog if search_tools_allowed(tool["function"]["name"])] if use_tools or use_skills else []
        final_pass = loop_i == loops - 1
        if final_pass:
            active_tools = []
            current_messages.append({
                "role": "system",
                "content": (
                    "Заверши работу готовым ответом по уже полученным данным. "
                    "Новые поиски не нужны. Если часть данных недоступна, назови конкретный пробел."
                ),
            })
        content_parts: List[str] = []
        loop_reasoning: List[str] = []
        tool_call_chunks: Dict[int, Dict[str, str]] = {}
        reasoning_details: Any = None
        stream_usage = None

        async def _consume(stream):
            nonlocal stream_usage, reasoning_details
            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    stream_usage = chunk_usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                details = _delta_field(delta, "reasoning_details")
                if details:
                    reasoning_details = details
                thought = _delta_field(delta, "reasoning") or getattr(delta, "reasoning_content", None)
                if isinstance(thought, str) and thought:
                    loop_reasoning.append(thought)
                    if on_reasoning_delta:
                        await on_reasoning_delta(thought)
                if getattr(delta, "content", None):
                    content_parts.append(delta.content)
                for tc_delta in getattr(delta, "tool_calls", None) or []:
                    slot = tool_call_chunks.setdefault(tc_delta.index, {"id": "", "name": "", "arguments": ""})
                    if tc_delta.id:
                        slot["id"] = tc_delta.id
                    func = getattr(tc_delta, "function", None)
                    if func and func.name:
                        slot["name"] += func.name
                    if func and func.arguments:
                        slot["arguments"] += func.arguments
            return stream_usage

        try:
            from app.billing.call_budget import model_call
            await model_call(client, {
                "model": _API_IDS[model],
                "messages": current_messages,
                "tools": active_tools or None,
                "extra_body": {"reasoning": {"effort": effort}},
                "max_tokens": max_output_tokens(model),
                "stream": True,
                "stream_options": {"include_usage": True},
            }, model=model, user_id=user_id, consume=_consume, usage_is_result=True)
        except asyncio.TimeoutError:
            return "❌ Ошибка OpenRouter: таймаут", [], "\n\n".join(reasoning_parts), search_results
        except Exception as exc:
            logger.error("OpenRouter call failed model=%s: %s", model, exc)
            return f"❌ Ошибка OpenRouter: {str(exc)[:300]}", [], "\n\n".join(reasoning_parts), search_results

        if stream_usage:
            cached_prompt_tokens(stream_usage)
        text = "".join(content_parts)
        if loop_reasoning:
            reasoning_parts.append("".join(loop_reasoning))
        assistant: Dict[str, Any] = {"role": "assistant", "content": text or ""}
        if reasoning_details:
            assistant["reasoning_details"] = reasoning_details
        tool_calls = [
            {"id": slot["id"] or f"call_{loop_i}_{index}", "type": "function",
             "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"}}
            for index, slot in sorted(tool_call_chunks.items())
            if slot["name"]
        ]
        if tool_calls:
            assistant["tool_calls"] = tool_calls
        current_messages.append(assistant)
        if not tool_calls:
            return text or "❌ Модель не вернула текст ответа.", generated_files, "\n\n".join(reasoning_parts), search_results[:20]
        if final_pass:
            return "❌ Модель не завершила ответ.", generated_files, "\n\n".join(reasoning_parts), search_results[:20]

        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                from status_feed import announce_tool
                await announce_tool(name, args if isinstance(args, dict) else {})
            except Exception:
                pass
            if name == "web_search" and isinstance(args, dict):
                query = str(args.get("query") or "")
                if not query:
                    tool_result = "❌ Ошибка: пустой поисковой запрос."
                else:
                    from search_engine import get_web_search_sources, smart_web_search
                    sources = await get_web_search_sources(query, max_results=12)
                    search_results.extend(
                        {"query": item.get("title", "Источник"), "summary": f"{item.get('url', '')}\n{item.get('snippet', '')}".strip()}
                        for item in sources[:12]
                    )
                    tool_result = await smart_web_search(query, max_results=12, sources=sources)
                    search_count += 1
            elif name in wanted and (use_tools or name in SKILL_TOOL_NAMES):
                from computer_tools import run_computer_tool
                tool_result = await run_computer_tool(name, args if isinstance(args, dict) else {}, user_id)
                if name in {"browse_page", "browse_visual", "connector_browse", "site_login"} and isinstance(args, dict) and args.get("url"):
                    search_results.append({"query": str(args.get("url")), "summary": (tool_result or "")[:500]})
            else:
                tool_result = f"Инструмент {name} не найден."
            current_messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(tool_result)[:20000]})

    return "❌ Модель не завершила ответ.", generated_files, "\n\n".join(reasoning_parts), search_results[:20]
