import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from conversations import conversation_manager
from openai_client import get_chat_response

from .state import USER_TASKS

logger = logging.getLogger(__name__)


def _with_web_context(messages: List[dict], context: str) -> List[dict]:
    if not context:
        return messages
    grounded = list(messages)
    instruction = {
        "role": "system",
        "content": (
            "Ниже результаты актуального веб-поиска. Используй их при ответе, но не вставляй "
            "в текст ссылки, домены, номера источников или сноски: интерфейс покажет источники отдельно. "
            "Не выдумывай факты, которых нет в материалах.\n\n" + context
        ),
    }
    if grounded and grounded[-1].get("role") == "user":
        grounded.insert(-1, instruction)
    else:
        grounded.append(instruction)
    return grounded


def _merge_sources(
    primary: List[Dict[str, str]], extra: List[Dict[str, str]], limit: int = 12
) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for source in list(primary or []) + list(extra or []):
        key = source.get("summary", "").splitlines()[0] or source.get("query", "")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged[:limit]


async def cancel_user_task(user_id: int):
    """Отменяет текущую активную задачу пользователя, если она есть."""
    if user_id in USER_TASKS:
        task = USER_TASKS[user_id]
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        del USER_TASKS[user_id]


async def reduce_heavy_context(
    messages: List[dict],
    user_text: str,
    status_msg: Optional[Any] = None,
    user_id: Optional[int] = None,
    summarizer_model: str = "gpt-5.6-luna",
    model: str = "auto",
) -> List[dict]:
    """
    Map-Reduce для больших контекстов.
    Порог — доля официального окна текущего режима, а не фиксированные 700k символов:
    у режима Поиск (Kimi) 256k токенов, у Авто / Computer / Research / Luna / Terra — около миллиона.
    """
    from model_context import (
        estimate_message_tokens,
        estimate_messages_tokens,
        input_budget_tokens,
    )

    total_tokens = estimate_messages_tokens(messages)
    MAP_REDUCE_THRESHOLD = int(input_budget_tokens(model) * 0.72)

    if total_tokens < MAP_REDUCE_THRESHOLD:
        return messages

    logger.info(f"Triggering Map-Reduce: {total_tokens} tokens, {len(messages)} messages, model={model}")
    if status_msg:
        try:
            await status_msg.edit_text("Обнаружен большой объем данных. Анализирую документы по очереди...")
        except Exception:
            pass

    heavy_messages = []
    light_messages = []
    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        if not isinstance(content, str) or i >= len(messages) - 1:
            light_messages.append(msg)
            continue
        # Only Map-Reduce attached documents — never ordinary chat turns.
        is_document = msg.get("role") == "system" and (
            "документ для контекста" in content or "предоставил документ" in content
        )
        is_heavy = is_document and estimate_message_tokens(msg) > 2_000
        if is_heavy:
            heavy_messages.append(msg)
        else:
            light_messages.append(msg)

    if not heavy_messages:
        logger.info("No heavy messages found, skipping Map-Reduce")
        return messages

    if status_msg:
        try:
            await status_msg.edit_text(f"Разбираю {len(heavy_messages)} документов по частям...")
        except Exception:
            pass

    CHUNK_SIZE = 200000
    MAP_CONCURRENCY = 4

    tasks_meta: List[Tuple[int, int, int, str]] = []
    doc_names: Dict[int, str] = {}
    for doc_idx, doc_msg in enumerate(heavy_messages):
        doc_content = doc_msg.get("content", "")

        doc_name = "неизвестный документ"
        if "документ для контекста:" in doc_content:
            doc_name = doc_content.split("документ для контекста:")[1].split("\n")[0].strip()
        doc_names[doc_idx] = doc_name

        chunks = [doc_content[i:i + CHUNK_SIZE] for i in range(0, len(doc_content), CHUNK_SIZE)] or [""]
        for chunk_idx, chunk in enumerate(chunks):
            tasks_meta.append((doc_idx, chunk_idx, len(chunks), chunk))

    semaphore = asyncio.Semaphore(MAP_CONCURRENCY)
    completed = {"n": 0}

    async def _map_one(doc_idx: int, chunk_idx: int, total_chunks: int, chunk: str):
        async with semaphore:
            if status_msg and completed["n"] % 2 == 0:
                try:
                    await status_msg.edit_text(
                        f"Анализ документов: {completed['n'] + 1}/{len(tasks_meta)} "
                        f"({doc_names.get(doc_idx, 'файл')})"
                    )
                except Exception:
                    pass
            map_prompt = [
                {
                    "role": "system",
                    "content": (
                        f"Ты аналитик данных. Сожми фрагмент документа '{doc_names.get(doc_idx, 'документ')}' "
                        f"(часть {chunk_idx + 1}/{total_chunks}), сохранив всё важное для "
                        "ответа на вопрос пользователя: ключевые пункты, цифры, требования, возможные ошибки, "
                        "противоречия или неточности. НЕ пропускай и не отбрасывай фрагмент, даже если он не "
                        "отвечает на вопрос напрямую - если пользователь просит проверить или проанализировать "
                        "документ целиком, важно сохранить содержание каждого фрагмента для дальнейшего анализа, "
                        "а не отфильтровать его как нерелевантное."
                    ),
                },
                {"role": "user", "content": f"Вопрос пользователя: {user_text}\n\nТекст для анализа:\n{chunk}"},
            ]
            try:
                result = await asyncio.wait_for(
                    get_chat_response(
                        map_prompt, model=summarizer_model, user_id=user_id, use_tools=False, use_skills=False
                    ),
                    timeout=120,
                )
            except Exception as exc:
                logger.error("Map-Reduce failed doc=%s chunk=%s: %s", doc_idx + 1, chunk_idx + 1, exc)
                result = exc
            completed["n"] += 1
            return result

    results = await asyncio.gather(
        *[_map_one(doc_idx, chunk_idx, total, chunk) for doc_idx, chunk_idx, total, chunk in tasks_meta]
    )

    doc_chunk_summaries: Dict[int, List[Tuple[int, str]]] = {}
    for (doc_idx, chunk_idx, total_chunks, _), res in zip(tasks_meta, results):
        if isinstance(res, Exception):
            logger.error(f"Error in Map-Reduce task doc={doc_idx + 1} chunk={chunk_idx + 1}/{total_chunks}: {res}")
            continue
        chunk_response, _, _, _ = res
        logger.info(f"Map-Reduce result doc={doc_idx + 1} chunk={chunk_idx + 1}/{total_chunks}: {len(chunk_response)} chars")
        if len(chunk_response) > 10:
            doc_chunk_summaries.setdefault(doc_idx, []).append((chunk_idx, chunk_response))

    summaries = []
    for doc_idx in sorted(doc_chunk_summaries.keys()):
        ordered_chunks = [text for _, text in sorted(doc_chunk_summaries[doc_idx])]
        summaries.append(
            f"=== Информация из документа {doc_idx + 1} ({doc_names[doc_idx]}) ===\n" + "\n\n".join(ordered_chunks)
        )

    if status_msg:
        try:
            await status_msg.edit_text("Формирую итоговый ответ...")
        except Exception:
            pass

    combined_context = (
        "\n\n".join(summaries)
        if summaries
        else "В проанализированных документах не найдено информации, прямо отвечающей на вопрос."
    )

    final_messages = [m for m in light_messages if m.get("role") == "system"]
    final_messages += [m for m in light_messages if m.get("role") != "system"]

    context_msg = {
        "role": "system",
        "content": (
            "Пользователь предоставил документ для контекста: краткий анализ больших документов\n\n"
            f"Содержание:\n{combined_context}\n\n"
            "Используй эти данные как дополнение к истории беседы для ответа на текущий вопрос."
        )
    }

    if final_messages and final_messages[-1].get("role") == "user":
        final_messages.insert(-1, context_msg)
    else:
        final_messages.append(context_msg)

    logger.info(f"Reduced context: {len(final_messages)} messages")
    return final_messages


async def get_smart_response(
    user_id: int,
    user_text: str,
    messages: List[dict],
    status_msg: Any,
    on_reasoning_delta: Optional[Any] = None,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Маршрутизация ответа по выбранной модели, с Map-Reduce для больших документов."""

    model = conversation_manager.get_user_model(user_id)
    reasoning_effort = conversation_manager.get_user_reasoning_effort(user_id)
    sub = conversation_manager.get_subscription(user_id)
    from app.billing.plans import clamp_model, canonical_tier, research_model
    from app.billing.quota import assert_can_use, usage_view

    tier = canonical_tier(sub.get("tier"))
    model = clamp_model(tier, model)
    pool = "computer" if model in {"director", "studio", "docgen"} else "chat"
    view = usage_view(sub)
    if (
        pool == "chat"
        and not view["unlimited"]
        and view["tier"] != "free"
        and view["chat"]["remaining"] is not None
        and view["chat"]["remaining"] <= 0
        and view["nano_cushion"]["used"] < view["nano_cushion"]["limit"]
    ):
        model = "gpt-5-nano"
    assert_can_use(user_id, pool, model)
    if view["tier"] == "free":
        if model == "kimi-k2.6":
            conversation_manager.update_subscription_limits(user_id, "daily_nano_mini", 1)
        elif model != "director":
            conversation_manager.update_subscription_limits(user_id, "daily_gpt54", 1)
    elif (
        pool == "chat"
        and not view["unlimited"]
        and view["chat"]["remaining"] is not None
        and view["chat"]["remaining"] <= 0
        and model == "gpt-5-nano"
    ):
        conversation_manager.increment_nano_cushion(user_id)

    if not user_text:
        logger.warning(f"Empty user_text in get_smart_response for user {user_id}")
        user_text = "Проанализируй предоставленные документы."

    if model == "docgen":
        # Работает по полному, не сжатому тексту исходников через собственный
        # отбор релевантных фрагментов — reduce_heavy_context/fit_for_mode
        # иначе обрежут или пересожмут именно те детали, ради которых и
        # существует этот режим.
        from docgen_router import get_docgen_response

        return await get_docgen_response(messages, user_text, user_id, status_msg)

    messages = await reduce_heavy_context(messages, user_text, status_msg, user_id=user_id, model=model)
    from model_context import fit_for_mode, search_hop_messages
    messages = await fit_for_mode(messages, model)

    total_chars_after = sum(len(m.get("content", "")) for m in messages)
    logger.info(
        f"Smart Context: user_id={user_id}, model={model}, reduced size={total_chars_after} chars, "
        f"user_text_len={len(user_text)}"
    )

    from search_engine import build_grounded_web_context
    from routing import current_turn_has_files, openai_tool_flags, packed_has_open_documents, turn_requires_web

    conv = conversation_manager.get_active_conversation(user_id)
    has_documents, has_images = current_turn_has_files(conv.messages if conv else [])
    if packed_has_open_documents(messages):
        has_documents = True

    research_mode = model in {"gpt-5.6-sol", "gpt-5.6-sol-pro"} or (
        model == "gpt-5.6-terra" and research_model(tier) == "gpt-5.6-terra"
    )
    # Files first only for this turn's uploads in Auto. Search/Research still
    # go to the web even if an older photo or PDF is sitting in the thread.
    web_required = turn_requires_web(
        user_text,
        model,
        research_mode=research_mode,
        has_documents=has_documents,
        has_images=has_images,
    )
    logger.info(
        "Web route: user_id=%s model=%s required=%s current_docs=%s current_images=%s",
        user_id, model, web_required, has_documents, has_images,
    )

    # Legacy DeepSeek routes use the shared Kimi-first retrieval layer. Public
    # Search/Auto/Research routes below use Kimi directly and validate its result.
    grounded_sources: List[Dict[str, str]] = []
    if web_required and "deepseek" in model:
        web_context, grounded_sources = await build_grounded_web_context(
            user_text, max_results=14, pages_to_read=6
        )
        messages = _with_web_context(messages, web_context)

    async def kimi_web_result(source_messages: List[dict], research: bool = False):
        from kimi_client import get_kimi_chat_response, kimi_result_is_grounded
        from status_feed import push_status

        await push_status("search", "Ищу ответ в интернете")
        try:
            candidate = await asyncio.wait_for(
                get_kimi_chat_response(
                    source_messages,
                    user_id=user_id,
                    on_reasoning_delta=None,
                    research=research,
                ),
                timeout=45 if research else 25,
            )
        except asyncio.TimeoutError:
            logger.warning("Kimi web search timed out research=%s", research)
            await push_status("think", "Поиск не успел вовремя, продолжаю без него")
            return None
        except Exception:
            logger.exception("Kimi web search failed")
            await push_status("think", "Поиск недоступен, продолжаю без него")
            return None
        minimum = 4 if research else 2
        if kimi_result_is_grounded(candidate[0], candidate[3], minimum_sources=minimum):
            await push_status("browse", f"Изучаю {len(candidate[3])} источников")
            return candidate
        await push_status("think", "Уточняю результаты поиска")
        return None

    result: Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]

    # Documents keep a quality-first route independent of the public cost mode.
    # Large files were already mapped above with Luna; Terra/Sol performs the final
    # cross-document analysis so economical chat never downgrades document quality.
    # Never await Kimi before reading attachments: that is what made Search /
    # Research / mixed image+PDF batches look frozen after a big upload.
    if has_documents and model != "director":
        from status_feed import push_status

        await push_status("think", "Разбираю загруженные документы")
        if model == "gpt-6-astra":
            document_model = "gpt-6-astra"
        elif model == "gpt-5.6-sol" or reasoning_effort in {"high", "xhigh", "max"}:
            document_model = "gpt-5.6-sol"
        else:
            document_model = "gpt-5.6-terra"
        document_model = clamp_model(tier, document_model)
        document_effort = reasoning_effort if reasoning_effort not in {None, "none"} else (
            "high" if model == "gpt-6-astra" or research_mode else "medium"
        )
        await push_status("think", "Разбираю документы в песочнице" if model == "gpt-6-astra" else "Собираю ответ по документам")
        doc_tools, doc_force_web = openai_tool_flags(model, web_required)
        result = await get_chat_response(
            messages,
            model=document_model,
            user_id=user_id,
            use_tools=doc_tools,
            reasoning_effort=document_effort,
            on_reasoning_delta=None if doc_force_web else on_reasoning_delta,
            force_web_search=doc_force_web,
        )
    elif has_images:
        # Multimodal turns always use a vision-capable OpenAI route. The images
        # are already resized on upload, so this remains materially cheaper than
        # repeatedly OCRing originals while preserving visual understanding.
        vision_model = "gpt-6-astra" if model == "gpt-6-astra" else "gpt-5.6-terra"
        vision_tools, vision_force_web = openai_tool_flags(model, web_required)
        result = await get_chat_response(
            messages,
            model=clamp_model(tier, vision_model),
            user_id=user_id,
            use_tools=vision_tools,
            reasoning_effort="high" if model == "gpt-6-astra" else ("medium" if has_documents else "low"),
            on_reasoning_delta=on_reasoning_delta,
            force_web_search=vision_force_web,
        )
    elif model == "auto":
        from status_feed import push_status
        if web_required:
            result = await kimi_web_result(search_hop_messages(messages, user_text))
            if result is None:
                result = await get_chat_response(
                    messages,
                    model="gpt-5.6-luna",
                    user_id=user_id,
                    use_tools=True,
                    reasoning_effort="low",
                    on_reasoning_delta=None,
                    force_web_search=True,
                )
        else:
            from config import DEEPSEEK_API_KEY
            from routing import best_route
            # Auto owns its effort decision. A stale manual toggle from another
            # mode must not make a short everyday prompt expensive.
            route, deep_thinking = best_route(user_text, "none", bool(DEEPSEEK_API_KEY))
            route = clamp_model(tier, route)
            label = "глубокий анализ" if deep_thinking else "быстрый точный ответ"
            await push_status("think", f"Выбрана оптимальная модель · {label}")
            if route.startswith("deepseek"):
                from deepseek_client import get_deepseek_response
                result = await get_deepseek_response(
                    messages,
                    model=route,
                    user_id=user_id,
                    use_tools=False,
                    reasoning_enabled=deep_thinking,
                    on_reasoning_delta=on_reasoning_delta,
                )
                if result[0].startswith("❌"):
                    await push_status("think", "Основной маршрут недоступен · переключаюсь на резервный")
                    fallback = clamp_model(tier, "gpt-5.6-terra" if route == "deepseek-v4-pro" else "gpt-5.6-luna")
                    result = await get_chat_response(
                        messages,
                        model=fallback,
                        user_id=user_id,
                        use_tools=False,
                        reasoning_effort="high" if deep_thinking else "none",
                        on_reasoning_delta=on_reasoning_delta,
                    )
            else:
                result = await get_chat_response(
                    messages,
                    model=clamp_model(tier, route),
                    user_id=user_id,
                    use_tools=False,
                    reasoning_effort="high" if deep_thinking else "none",
                    on_reasoning_delta=on_reasoning_delta,
                )
    elif model == "correspondent":
        from hybrid_router import get_correspondent_response
        result = await get_correspondent_response(messages, user_text, user_id, status_msg)
    elif model == "director":
        from director_router import get_director_response
        result = await get_director_response(messages, user_text, user_id, status_msg)
    elif model == "studio":
        from studio_router import get_studio_response

        result = await get_studio_response(messages, user_text, user_id, status_msg)
    elif model == "kimi-k2.6":
        result = await kimi_web_result(search_hop_messages(messages, user_text))
        if result is None:
            result = await get_chat_response(
                messages, model="gpt-5.6-luna", user_id=user_id, use_tools=True,
                reasoning_effort="low", on_reasoning_delta=None,
                force_web_search=True,
            )
    elif model in {"gpt-5.6-sol", "gpt-5.6-sol-pro"} or (
        model == "gpt-5.6-terra" and research_model(tier) == "gpt-5.6-terra"
    ):
        # Research: Kimi gathers sources, then Terra or Sol writes the report.
        synthesizer = clamp_model(tier, model if model != "gpt-5.6-sol-pro" else "gpt-5.6-sol")
        kimi_result = await kimi_web_result(search_hop_messages(messages, user_text), research=True)
        if kimi_result:
            grounded_sources = _merge_sources(grounded_sources, kimi_result[3], limit=28)
            result = await get_chat_response(
                _with_web_context(messages, kimi_result[0]),
                model=synthesizer,
                user_id=user_id,
                use_tools=False,
                reasoning_effort=reasoning_effort if reasoning_effort not in {None, "none"} else "high",
                on_reasoning_delta=None,
            )
        else:
            result = await get_chat_response(
                messages, model=synthesizer, user_id=user_id, use_tools=True,
                reasoning_effort="high", on_reasoning_delta=None,
                force_web_search=True,
            )
    elif "deepseek" in model:
        from deepseek_client import get_deepseek_response
        result = await get_deepseek_response(messages, model=model, user_id=user_id, use_tools=False, on_reasoning_delta=on_reasoning_delta)
    elif model == "gpt-6-astra":
        from status_feed import push_status
        await push_status("think", "Работаю в песочнице")
        astra_effort = reasoning_effort if reasoning_effort not in {None, "none"} else "high"
        result = await get_chat_response(
            messages,
            model="gpt-6-astra",
            user_id=user_id,
            use_tools=True,
            reasoning_effort=astra_effort,
            on_reasoning_delta=on_reasoning_delta,
            force_web_search=False,
        )
    else:
        result = await get_chat_response(
            messages, model=model, user_id=user_id, use_tools=web_required,
            reasoning_effort=reasoning_effort, on_reasoning_delta=None if web_required else on_reasoning_delta,
            force_web_search=web_required,
        )

    answer, files, reasoning, model_sources = result
    from status_feed import push_status
    await push_status("think", "Проверяю выводы и оформляю ответ")
    source_limit = 28 if model == "director" else (24 if model in {"gpt-5.6-sol", "gpt-5.6-sol-pro", "gpt-6-astra", "kimi-k2.6"} or (
        model == "gpt-5.6-terra" and research_model(tier) == "gpt-5.6-terra"
    ) else 18)
    sources = _merge_sources(grounded_sources, model_sources, limit=source_limit)
    if sources:
        from kimi_client import strip_source_links
        answer = strip_source_links(answer)
    else:
        from kimi_client import extract_domain_sources
        sources = extract_domain_sources(answer)[:source_limit]
        if sources:
            from kimi_client import strip_source_links
            answer = strip_source_links(answer)
    # Never expose raw provider chain-of-thought. The compact status feed is the
    # user-facing explanation of progress.
    return answer, files, "", sources


def sanitize_response_text(text: str) -> str:
    """
    Применяет к сырому тексту ключевые ограничения из SYSTEM_PROMPT:
    - заменяет длинное тире (em dash) на среднее (en dash);
    - удаляет сырые HTML-теги (кроме содержимого блоков кода);
    - убирает LaTeX-разметку \\textbf{}, \\textit{}, \\texttt{};
    - заменяет угловые скобки <<...>> на кавычки «...» (пустые <<>> — на [не указано]).
    """
    text = text.replace("—", "–")

    text = re.sub(r"\\textbf\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\textit\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\texttt\{([^{}]+)\}", r"\1", text)

    code_blocks: List[str] = []
    inline_codes: List[str] = []
    _PLACEHOLDER = ""

    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"{_PLACEHOLDER}CB{len(code_blocks) - 1}{_PLACEHOLDER}"

    def save_inline_code(match):
        inline_codes.append(match.group(0))
        return f"{_PLACEHOLDER}IC{len(inline_codes) - 1}{_PLACEHOLDER}"

    text = re.sub(r"```[\s\S]*?```", save_code_block, text)
    text = re.sub(r"`[^`]+`", save_inline_code, text)

    text = re.sub(
        r"<<([\s\S]*?)>>",
        lambda m: f"«{m.group(1)}»" if m.group(1).strip() else "[не указано]",
        text,
    )

    text = re.sub(r"</?[a-zA-Z][^>\n]{0,40}>", "", text)

    for i, block in enumerate(code_blocks):
        text = text.replace(f"{_PLACEHOLDER}CB{i}{_PLACEHOLDER}", block)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"{_PLACEHOLDER}IC{i}{_PLACEHOLDER}", code)

    from kimi_client import drop_empty_list_items

    return drop_empty_list_items(_strip_fake_download_links(text))


_FAKE_DOWNLOAD_LINK = re.compile(
    r"\[([^\]]+)\]\((?:file:|/?(?:workspaces|tmp|sandbox|mnt|opt)[^)]*|[^)\s]*\.(?:xlsx|xls|csv|docx|pdf|zip))\)",
    re.IGNORECASE,
)


def _strip_fake_download_links(text: str) -> str:
    """Models invent markdown download links to sandbox files that the chat cannot open."""
    cleaned = _FAKE_DOWNLOAD_LINK.sub(r"\1", text)
    return re.sub(r"\[([^\]]*(?:скачать|download)[^\]]*)\]\((?:#)?\)", r"\1", cleaned, flags=re.IGNORECASE)
