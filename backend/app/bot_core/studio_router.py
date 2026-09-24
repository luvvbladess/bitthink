"""Studio mode: presentations and infographics via structured specs + render engine."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_INFO_HINT = re.compile(
    r"(?i)\b(инфографик|infographic|одноэкран|воронк|таймлайн|timeline|kpi[\s-]?strip|stories)\b"
)
_DECK_HINT = re.compile(
    r"(?i)\b(презентац|pptx|powerpoint|слайд|питч|pitch|deck|выступлен)\b"
)


def _extract_json_object(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    match = _JSON_BLOCK.search(raw)
    if match:
        raw = match.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _wants_infographic(user_text: str) -> bool:
    text = user_text or ""
    if _INFO_HINT.search(text) and not _DECK_HINT.search(text):
        return True
    if _INFO_HINT.search(text):
        return True
    return False


_DOC_SUFFIX = (".pdf", ".docx", ".doc", ".pptx", ".ppt", ".odp", ".txt", ".md", ".rtf")


def _messages_have_docs(messages: List[Dict[str, Any]] | None) -> bool:
    for message in messages or []:
        content = str(message.get("content") or "")
        if message.get("role") == "system" and (
            "документ для контекста" in content or "предоставил документ" in content
        ):
            return True
        attachment = message.get("attachment") if isinstance(message.get("attachment"), dict) else {}
        name = str((attachment or {}).get("name") or "").lower()
        if name.endswith(_DOC_SUFFIX):
            return True
    return False


def _needs_clarify(
    user_text: str,
    document_context: str = "",
    *,
    has_files: bool = False,
    history_text: str = "",
) -> bool:
    if has_files:
        return False
    if (document_context or "").strip() and len(document_context.strip()) >= 80:
        return False
    if len((history_text or "").strip()) >= 400:
        return False
    text = (user_text or "").strip()
    if not text:
        return True
    try:
        from clarify import is_clarify_reply

        if is_clarify_reply(text):
            return False
    except Exception:
        pass
    from studio.direction import brief_is_thin

    return brief_is_thin(text)


def _studio_skills_blurb(*, html_canvas: bool = True) -> str:
    try:
        from computer_skills.loader import load_skill

        if html_canvas:
            chunks = [load_skill("visual_system"), load_skill("canvas")]
        else:
            chunks = [
                load_skill("visual_system"),
                load_skill("deck"),
                load_skill("infographic"),
                load_skill("studio_render"),
            ]
        return "\n\n".join(chunk for chunk in chunks if chunk)
    except Exception:
        if html_canvas:
            return (
                "Выдай один самодостаточный HTML-файл на холст. "
                "Слайды: секции .slide на 100dvh. Лендинг и дашборд – одна страница. "
                "Фото через <img data-ai=\"english prompt, no text\">. Без внешних скриптов."
            )
        return (
            "Изобретай визуальный язык под бриф. custom theme с hex. "
            "Слайды: poster, visual, mosaic, composed, statement, stack, metric_row, split_visual, closing. "
            "Не копируй один layout дважды подряд. Картинки – материал дизайна, не украшение."
        )


def _default_clarify_questions(user_text: str) -> list[dict[str, Any]]:
    from studio.html_canvas import detect_kind

    kind = detect_kind(user_text)
    if kind == "infographic":
        return [
            {
                "prompt": "О чём инфографика?",
                "options": ["Процесс", "Цифры и KPI", "Сравнение", "Таймлайн", "Другое"],
            }
        ]
    if kind in {"landing", "dashboard", "app"}:
        return [
            {
                "prompt": "Что сделать?",
                "options": ["Картинка", "Лендинг", "Дашборд", "Прототип экранов", "Слайды"],
            }
        ]
    return [
        {
            "prompt": "О чём презентация?",
            "options": ["Продукт или запуск", "Отчёт", "Обучение", "Пичч", "Другое"],
        }
    ]


async def _update_status(status_msg: Any, text: str) -> None:
    if status_msg is None:
        return
    try:
        from status_feed import push_status

        await push_status("think", text)
    except Exception:
        pass
    try:
        await status_msg.edit_text(text)
    except Exception:
        pass


def _theme_from_clarify(text: str) -> str:
    from studio.direction import pick_direction

    return str(pick_direction(text).get("theme_id") or "noir")


async def _compose_spec(
    user_text: str,
    *,
    kind: str,
    theme_id: str,
    document_context: str,
    history_text: str,
    user_id: int,
    repair_hint: str = "",
    direction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from openai_client import get_chat_response
    from studio.briefing import format_studio_documents
    from studio.direction import pick_direction
    from studio.quality import target_slide_count

    direction = direction or pick_direction(user_text, infographic=(kind == "infographic"))
    skills = _studio_skills_blurb(html_canvas=False)
    doc_block = format_studio_documents(document_context)
    hist_block = f"\n\nИстория:\n{history_text}" if history_text else ""
    repair_block = f"\n\nИсправь прошлую ошибку схемы: {repair_hint}" if repair_hint else ""
    vibe = direction.get("vibe")
    vibe_brief = direction.get("brief")
    spine = direction.get("spine")
    theme = direction.get("theme") or {}
    if kind == "infographic":
        schema_hint = (
            '{"kind":"infographic","theme_id":"custom","theme":{"bg":"#...","surface":"#...","text":"#...",'
            '"muted":"#...","accent":"#...","line":"#...","title_font":"Georgia|Segoe UI"},'
            '"layout_id":"composed","orientation":"landscape","headline":"...","subhead":"...","footnote":"...",'
            '"image_prompt":"cinematic background still, no text",'
            '"elements":[{"type":"text|number|card|image|rounded|ellipse|rule|bullets","x":6,"y":8,"w":40,"h":18,'
            '"style":"display_xl|display|title|body|caption|kpi","text":"...","prompt":"...","fill":"accent|surface"}]}'
        )
        task = (
            "Собери ОДИН кадр инфографики как арт-директор, не как шаблон дашборда. "
            "По умолчанию layout_id composed: уникальная сетка в % координатах, не ряд одинаковых карточек. "
            "Обязателен image_prompt фона по теме. 1–3 type:image с разными кадрами. "
            "Headline конкретный. Без emoji, без фиолетового неона, без «шаг 1/2/3» в одинаковых прямоугольниках, "
            "если можно рассказать ритмом, цифрой и фото."
        )
    else:
        lo, hi = target_slide_count(user_text)
        schema_hint = (
            '{"kind":"deck","title":"...","theme_id":"custom","theme":{"bg":"#...","surface":"#...","text":"#...",'
            '"muted":"#...","accent":"#...","line":"#...","title_font":"Georgia|Segoe UI"},"slides":['
            '{"layout_id":"poster|visual|mosaic|composed|statement|stack|metric_row|split_visual|closing",'
            '"anchor":"bottom-left|center|top-left|bottom-right","image_prompt":"...",'
            '"title":"...","subtitle":"...","items":[],"kpis":[{"value":"...","label":"..."}],'
            '"tiles":[{"image_prompt":"...","caption":"..."}],'
            '"elements":[{"type":"text|number|image|card|rounded|ellipse|rule|bullets","x":8,"y":12,"w":40,"h":20,'
            '"style":"display_xl|display|title|body|caption|kpi","text":"...","prompt":"..."}]}]}'
        )
        task = (
            f"Собери презентацию PPTX как дизайнер, не пустой постер. "
            f"Объём {lo}–{hi} слайдов. Каждый слайд – новый кадр: нельзя два одинаковых layout подряд. "
            "История кадрами, не оглавление. Минимум 4 слайда с image_prompt (poster/visual/mosaic/composed). "
            "Хотя бы 2 composed с уникальными координатами. Хотя бы 1 mosaic или metric_row, если есть что показать. "
            "На КАЖДОМ слайде живой title и subtitle или items/bullets из ТЗ — пустой кадр запрещён. "
            "Если есть образец стиля, палитра и шрифты из него, не случайный noir. "
            "Текст конкретный, по брифу. image_prompt на английском, сцена по теме, без букв на картинке. "
            "Запрещено: bullets_focus на каждом слайде, section-разделители, «Слева/Справа», Bit-Think в футере, "
            "cta «напишите в чат», фиолетовый неон, абстрактный teal blob вместо места/предмета из брифа."
        )

    prompt = (
        f"{skills}\n\n"
        f"Визуальный закон этого брифа (обязателен, не тихий teal по умолчанию):\n"
        f"Вайб: {vibe}. {vibe_brief}\n"
        f"Повествование: {spine}\n"
        f"Стартовая палитра (можно уточнить hex под бриф, но держи этот мир): {theme}\n\n"
        f"{task}\nОтветь ТОЛЬКО одним JSON-объектом.\n"
        f"Схема: {schema_hint}\n"
        f"Бриф:\n{user_text}"
        f"{doc_block}{hist_block}{repair_block}"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Ты арт-директор Студии Bit-Think, уровень Claude Design: придумываешь кадры, а не заполняешь макеты. "
                "Каждый бриф получает свой визуальный мир. Строгий JSON, без markdown вокруг. "
                "Не выдумывай KPI, если в брифе нет цифр – тогда метрики не ставь или помечай как ориентир словом «оценка». "
                "Картинки только через image_prompt / tiles / elements.prompt – движок сгенерирует. "
                "Пустой слайд без title и тела — брак. Если есть образец PPTX, повтори его стиль."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    async def _call(model: str, effort: str) -> str:
        text, _, _, _ = await get_chat_response(
            messages,
            model=model,
            user_id=user_id,
            use_tools=False,
            reasoning_effort=effort,
        )
        return text

    try:
        text = await _call("gpt-6-sol", "medium" if kind == "deck" else "low")
    except Exception:
        logger.info("Studio sol compose failed, falling back to luna")
        text = await _call("gpt-6-luna", "medium")
    data = _extract_json_object(text)
    if not data:
        raise ValueError("Модель не вернула JSON-спецификацию")
    data.setdefault("kind", kind)
    if not data.get("theme"):
        data["theme"] = theme
        data["theme_id"] = "custom"
    else:
        data.setdefault("theme_id", "custom")
    return data


_HTML_SYSTEM = (
    "Ты дизайнер Студии Bit-Think. Ты собираешь живой HTML-макет на холст: "
    "один самодостаточный файл, человек правит следующим сообщением. "
    "Отвечай только HTML. Без markdown-пояснений вокруг, без JSON-спеки, без PPTX. "
    "Не выдумывай KPI. Не ставь Bit-Think в футер. Не используй Inter, Roboto, фиолетовый неон. "
    "Если приложен образец презентации — повтори его визуальный язык. Если приложено ТЗ — "
    "заполни слайды фактами из ТЗ, не оставляй чёрные кадры без текста."
)

_KIND_TASK = {
    "slides": (
        "Собери HTML-презентацию: секции class=\"slide\" плюс свой класс сетки (.s1, .s2), "
        "каждый кадр 16:9 на весь экран, без скролла внутри. 6–10 кадров. "
        "Сетку (grid/flex) вешай на .s1/.s2, не на голый .slide. Навигацию, .nav, .counter и transform-колоду не пиши. "
        "Не ломай 16:9 через @media max-width:900 — холст узкий, кадр всё равно широкий. "
        "ПУСТОЙ КАДР — брак: на каждом слайде видимый заголовок (h1 или h2) и 2–4 предложения "
        "или 3–5 фактов списком из ТЗ/брифа. Текст статичен: без opacity:0, без анимации, "
        "без которой копирайт не появляется. Контраст заголовка к фону высокий; на фото — тёмный "
        "scrim под текстом. Если есть образец стиля — повтори ЕГО палитру, шрифты и сетку, "
        "не уходи в чёрный кинематограф. Один постер-титул можно сделать просторнее, остальные кадры плотные."
    ),
    "infographic": (
        "Собери одноэкранную или короткую HTML-инфографику. Уникальная сетка, "
        "не ряд одинаковых карточек. Цифры только из брифа."
    ),
    "dashboard": (
        "Собери HTML-дашборд: рабочий каркас, воздух, внятная иерархия. "
        "Цифры только из брифа, иначе подпись «оценка»."
    ),
    "app": (
        "Собери HTML-прототип интерфейса: несколько состояний в одном файле, без бэкенда."
    ),
    "landing": (
        "Собери HTML-лендинг или промо-страницу: hero, ритм секций, асимметрия, воздух."
    ),
}


async def _compose_html(
    user_text: str,
    *,
    kind: str,
    document_context: str,
    history_text: str,
    user_id: int,
    direction: dict[str, Any],
    previous_html: str = "",
    repair_hint: str = "",
) -> str:
    from openai_client import get_chat_response
    from studio.briefing import format_studio_documents
    from studio.html_canvas import assert_slide_density, clip_previous_html, extract_html, prepare_artifact

    skills = _studio_skills_blurb(html_canvas=True)
    theme = direction.get("theme") or {}
    task = _KIND_TASK.get(kind) or _KIND_TASK["landing"]
    doc_block = format_studio_documents(document_context)
    hist_block = f"\n\nИстория чата:\n{history_text}" if history_text else ""
    repair_block = f"\n\nПрошлый HTML был битый. Исправь: {repair_hint}" if repair_hint else ""
    prev_block = ""
    if previous_html:
        prev_block = (
            "\n\nПредыдущий HTML на холсте – правь его, сохрани вайб, "
            "не пересобирай с нуля:\n```html\n"
            + clip_previous_html(previous_html)
            + "\n```"
        )
    prompt = (
        f"{skills}\n\n"
        f"Визуальный закон: вайб {direction.get('vibe')}. {direction.get('brief')}\n"
        f"Повествование: {direction.get('spine')}\n"
        f"Палитра (держи этот мир, hex можно уточнить): {theme}\n"
        f"Тип макета: {kind}. {task}\n"
        f"Фото только через <img data-ai=\"english prompt, no text no logos\" alt=\"...\"> без src, максимум 4.\n"
        f"Бриф:\n{user_text}"
        f"{doc_block}{hist_block}{prev_block}{repair_block}\n"
        "Верни один полный HTML-документ."
    )
    messages = [
        {"role": "system", "content": _HTML_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    async def _call(model: str, effort: str) -> str:
        text, _, _, _ = await get_chat_response(
            messages,
            model=model,
            user_id=user_id,
            use_tools=False,
            reasoning_effort=effort,
        )
        return text

    effort = "low" if previous_html else ("medium" if kind == "slides" else "low")
    try:
        text = await _call("gpt-6-sol", effort)
    except Exception:
        logger.info("Studio HTML sol compose failed, falling back to luna")
        text = await _call("gpt-6-luna", "medium")
    html = extract_html(text)
    if not html:
        raise ValueError("Модель не вернула HTML")
    html = prepare_artifact(html, kind=kind)
    assert_slide_density(html, kind=kind)
    return html


def _fallback_deck(user_text: str, theme_id: str, direction: dict[str, Any] | None = None) -> dict[str, Any]:
    from studio.direction import pick_direction

    direction = direction or pick_direction(user_text)
    topic = (user_text or "Тема").strip()
    if len(topic) > 56:
        topic = topic[:55] + "…"
    scene = f"cinematic still of {topic}, specific place or object, no text no logos"
    return {
        "kind": "deck",
        "theme_id": "custom",
        "theme": direction.get("theme"),
        "title": topic or "Презентация",
        "slides": [
            {
                "layout_id": "poster",
                "title": topic or "Презентация",
                "subtitle": str(direction.get("vibe") or ""),
                "anchor": "bottom-left",
                "image_prompt": scene,
            },
            {
                "layout_id": "statement",
                "title": "Один кадр – одна мысль. Предмет из брифа, не шаблон.",
            },
            {
                "layout_id": "mosaic",
                "title": "Три взгляда",
                "tiles": [
                    {"image_prompt": f"detail crop related to {topic}, no text", "caption": "Деталь"},
                    {"image_prompt": f"wide environmental frame for {topic}, no text", "caption": "Место"},
                    {"image_prompt": f"hands or tool still life for {topic}, no text", "caption": "Жест"},
                ],
            },
            {
                "layout_id": "closing",
                "title": "Дальше собираем живой контур",
                "subtitle": "Первый кадр уже задаёт тон",
            },
        ],
    }


def _fallback_board(user_text: str, theme_id: str, direction: dict[str, Any] | None = None) -> dict[str, Any]:
    from studio.direction import pick_direction

    direction = direction or pick_direction(user_text, infographic=True)
    topic = (user_text or "Процесс").strip()
    if len(topic) > 56:
        topic = topic[:55] + "…"
    return {
        "kind": "infographic",
        "theme_id": "custom",
        "theme": direction.get("theme"),
        "layout_id": "composed",
        "orientation": "landscape",
        "headline": topic or "Инфографика",
        "image_prompt": f"atmospheric background still for {topic}, no text",
        "elements": [
            {"type": "text", "x": 6, "y": 8, "w": 70, "h": 14, "style": "display", "text": topic or "Кадр"},
            {"type": "number", "x": 6, "y": 32, "w": 24, "h": 18, "text": "01"},
            {"type": "card", "x": 6, "y": 54, "w": 28, "h": 32, "title": "Суть", "body": "Один экран, свой ритм"},
            {"type": "card", "x": 36, "y": 54, "w": 28, "h": 32, "title": "Материал", "body": "Фото и тип, не клипарт"},
            {"type": "card", "x": 66, "y": 54, "w": 28, "h": 32, "title": "Вывод", "body": "Что сделать дальше"},
        ],
    }


async def get_studio_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    from app.billing.quota import billing_pool

    token = billing_pool.set("computer")
    try:
        return await _run_studio(messages, user_text, user_id, status_msg)
    finally:
        billing_pool.reset(token)


def _chat_image_bytes(user_id: int, *, current_turn_only: bool) -> list[bytes]:
    """Фото, загруженные в беседу: только этого хода или последние из всей беседы."""
    try:
        from conversations import conversation_manager

        conv = conversation_manager.conversation_for_turn(int(user_id))
    except Exception:
        logger.debug("Studio: no conversation for chat images", exc_info=True)
        return []
    messages = list(getattr(conv, "messages", None) or []) if conv else []
    start = 0
    if current_turn_only:
        last_assistant = max(
            (index for index, message in enumerate(messages) if getattr(message, "role", "") == "assistant"),
            default=-1,
        )
        start = last_assistant + 1
    found: list[bytes] = []
    for message in messages[start:]:
        attachment = getattr(message, "attachment", None) or {}
        if not conversation_manager._is_image_attachment(attachment):
            continue
        path = conversation_manager._attachment_disk_path(attachment)
        try:
            if path and path.is_file():
                found.append(path.read_bytes())
        except OSError:
            logger.warning("Studio: cannot read chat image %s", path)
    return found[-4:]


async def _run_studio(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    from studio.html_canvas import (
        HTML_KINDS,
        detect_kind_explicit,
        is_image_canvas,
        load_previous_html,
        resolve_studio_job,
        wants_image_edit,
        wants_pptx_file,
    )

    previous_html = load_previous_html(user_id)
    had_canvas = bool(previous_html)
    explicit = detect_kind_explicit(user_text)

    # Ответ на уточнение «Что сделать? – Картинка»: рисуем по исходной просьбе.
    from clarify import is_clarify_reply

    if is_clarify_reply(user_text) and re.search(r"[–-]\s*Картинка\b", user_text):
        original = ""
        for message in reversed(messages or []):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip() and not is_clarify_reply(content):
                original = content.strip()
                break
        return await _run_image_studio(messages, original or user_text, user_id, status_msg)
    html_canvas_open = bool(previous_html) and not is_image_canvas(previous_html)

    # Фото, приложенное к этому сообщению: «убери фон», «сделай в стиле аниме».
    # Раньше оно уходило в сборку лендинга, и Студия отвечала макетом вместо правки.
    if explicit not in HTML_KINDS and (not html_canvas_open or explicit == "image" or wants_image_edit(user_text)):
        turn_images = _chat_image_bytes(user_id, current_turn_only=True)
        if turn_images:
            return await _run_image_studio(
                messages, user_text, user_id, status_msg, source_images=turn_images,
            )

    kind, previous_html, iterating = resolve_studio_job(user_text, previous_html)
    if wants_pptx_file(user_text) and not iterating:
        return await _run_pptx_studio(messages, user_text, user_id, status_msg)

    # Фото из беседы без открытого холста: правка по словам «фон», «цвет», «убери».
    if kind != "image" and explicit is None and not had_canvas and wants_image_edit(user_text):
        older_images = _chat_image_bytes(user_id, current_turn_only=False)
        if older_images:
            return await _run_image_studio(
                messages, user_text, user_id, status_msg, source_images=older_images[-1:],
            )

    if kind == "image":
        return await _run_image_studio(
            messages,
            user_text,
            user_id,
            status_msg,
            previous_html=previous_html if iterating else "",
        )
    return await _run_html_studio(
        messages,
        user_text,
        user_id,
        status_msg,
        previous_html=previous_html if iterating else "",
    )


async def _run_image_studio(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
    *,
    previous_html: str = "",
    source_images: list[bytes] | None = None,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    from handlers.core import sanitize_response_text
    from studio.html_canvas import (
        extract_embedded_image_bytes,
        image_canvas_html,
        is_image_canvas,
        safe_html_filename,
        title_from_html,
    )

    iterating = bool(previous_html and is_image_canvas(previous_html))
    editing = iterating or bool(source_images)
    await _update_status(status_msg, "Правлю изображение" if editing else "Рисую изображение")
    debit_images = None
    try:
        from app.billing.quota import QuotaError, assert_can_generate_image, debit_images as _debit_images

        debit_images = _debit_images
        assert_can_generate_image(int(user_id))
    except QuotaError as exc:
        return sanitize_response_text(str(exc) or "Лимит картинок на сегодня исчерпан."), [], "", []
    except Exception:
        logger.exception("Studio image quota check failed")

    from openai_client import edit_image, generate_image

    data_url: str | None = None
    err: str | None = None
    if source_images:
        data_url, err = await edit_image(source_images, user_text, size="1024x1024", quality="high")
    elif iterating:
        raw = extract_embedded_image_bytes(previous_html)
        if raw:
            data_url, err = await edit_image(raw, user_text, size="1024x1024", quality="high")
    if not data_url and not source_images:
        data_url, err = await generate_image(user_text, size="1024x1024", quality="high")
    if not data_url or not (
        data_url.startswith("data:image/") or data_url.startswith("https://") or data_url.startswith("/")
    ):
        return sanitize_response_text(err or "Не удалось нарисовать картинку. Попробуйте другое описание."), [], "", []

    if debit_images:
        try:
            debit_images(int(user_id), 1)
        except Exception:
            logger.exception("Failed to debit studio image")

    title = (user_text or "Картинка").strip()[:48] or "Картинка"
    html = image_canvas_html(data_url, title)
    title = title_from_html(html, fallback=title)
    files = [
        {
            "filename": safe_html_filename(title),
            "bytes": html.encode("utf-8"),
            "caption": title,
            "mime_type": "text/html",
            "canvas": True,
        }
    ]
    if editing:
        answer = f"Картинка «{title}» обновлена на холсте. Напишите, что ещё поменять, или скачайте PNG."
    else:
        answer = f"Картинка «{title}» на холсте справа. Правится следующим сообщением, скачивается как PNG."
    return sanitize_response_text(answer), files, "", []


async def _run_html_studio(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
    *,
    previous_html: str = "",
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    from director_router import _extract_document_context, _format_chat_history
    from handlers.core import sanitize_response_text
    from studio.briefing import attached_deck_sample, theme_from_documents, wants_slides_from_documents
    from studio.direction import pick_direction
    from studio.html_canvas import (
        collect_ai_image_prompts,
        detect_kind,
        fallback_html,
        fill_ai_images,
        safe_html_filename,
        title_from_html,
    )

    document_context = _extract_document_context(messages)
    history_text = _format_chat_history(messages)
    iterating = bool(previous_html)
    has_files = bool((document_context or "").strip()) or _messages_have_docs(messages)

    await _update_status(status_msg, "Читаю бриф")

    if not iterating and _needs_clarify(
        user_text, document_context, has_files=has_files, history_text=history_text
    ):
        from clarify import normalize_questions, pack_search

        questions = normalize_questions(_default_clarify_questions(user_text))
        await _update_status(status_msg, "Уточняю тему")
        return questions[0]["prompt"], [], "", pack_search(questions)

    kind = detect_kind(user_text)
    if iterating and ".slide" in previous_html and kind == "landing":
        kind = "slides"
    elif not iterating and kind == "landing" and (
        attached_deck_sample(document_context) or wants_slides_from_documents(document_context)
    ):
        kind = "slides"
    direction = pick_direction(user_text, infographic=(kind == "infographic"))
    sample_theme = theme_from_documents(document_context)
    if sample_theme:
        direction = {
            **direction,
            "theme": sample_theme,
            "theme_id": "custom",
            "vibe": "по образцу заказчика",
            "brief": (
                "Повтори визуальный язык приложенного образца: те же цвета, шрифты, сетка и плотность текста. "
                "Не уходи в чёрный кинематограф, если образец другой."
            ),
        }

    await _update_status(
        status_msg,
        "Правлю макет" if iterating else "Собираю макет",
    )

    html = ""
    last_exc: Exception | None = None
    repair_hint = ""
    for attempt in range(3):
        try:
            html = await _compose_html(
                user_text,
                kind=kind,
                document_context=document_context,
                history_text=history_text,
                user_id=user_id,
                direction=direction,
                previous_html=previous_html,
                repair_hint=repair_hint,
            )
            break
        except Exception as exc:
            last_exc = exc
            repair_hint = str(exc)[:280]
            logger.info("Studio HTML compose attempt %s failed: %s", attempt + 1, exc)
    if not html:
        logger.info("Studio HTML falling back: %s", last_exc)
        html = fallback_html(user_text, kind, direction)

    prompts = collect_ai_image_prompts(html)
    skip_note = ""
    img_n = 0
    if prompts:
        await _update_status(status_msg, f"Рисую кадры ({len(prompts)})")
        try:
            html, img_n, skip_note = await fill_ai_images(html, user_id)
        except Exception:
            logger.exception("Studio canvas images failed")

    title = title_from_html(html, fallback=(user_text or "Макет").strip()[:48] or "Макет")
    filename = safe_html_filename(title)
    files = [
        {
            "filename": filename,
            "bytes": html.encode("utf-8"),
            "caption": title,
            "mime_type": "text/html",
            "canvas": True,
        }
    ]
    img_note = f", AI-картинок: {img_n}" if img_n else ""
    if skip_note and prompts and not img_n:
        img_note = f" ({skip_note})"
    vibe = direction.get("vibe") or "свой"
    kind_label = {
        "slides": "Презентация",
        "infographic": "Инфографика",
        "dashboard": "Дашборд",
        "app": "Прототип",
        "landing": "Макет",
        "image": "Картинка",
    }.get(kind, "Макет")
    if iterating:
        answer = (
            f"На холсте справа обновлён макет «{title}», язык «{vibe}»{img_note}. "
            f"Напишите, что ещё поменять: слайд, цвет, факты. Не нужно собирать заново."
        )
    else:
        answer = (
            f"{kind_label} «{title}», язык «{vibe}»{img_note} – справа на холсте. "
            f"Готовый макет правится следующим сообщением (темнее шапка, другой стиль, поправить слайд). "
            f"Скачивается как PPTX, PDF или PNG."
        )
    return sanitize_response_text(answer), files, "", []


async def _run_pptx_studio(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    from director_router import _extract_document_context, _format_chat_history
    from handlers.core import sanitize_response_text
    from studio.build import build_studio_artifact
    from studio.briefing import theme_from_documents
    from studio.images import collect_image_jobs, resolve_studio_images

    from studio.direction import pick_direction

    document_context = _extract_document_context(messages)
    history_text = _format_chat_history(messages)
    has_files = bool((document_context or "").strip()) or _messages_have_docs(messages)

    await _update_status(status_msg, "Читаю бриф")

    if _needs_clarify(user_text, document_context, has_files=has_files, history_text=history_text):
        from clarify import normalize_questions, pack_search

        questions = normalize_questions(_default_clarify_questions(user_text))
        await _update_status(status_msg, "Уточняю тему")
        return questions[0]["prompt"], [], "", pack_search(questions)

    kind = "infographic" if _wants_infographic(user_text) else "deck"
    direction = pick_direction(user_text, infographic=(kind == "infographic"))
    sample_theme = theme_from_documents(document_context)
    if sample_theme:
        direction = {
            **direction,
            "theme": sample_theme,
            "theme_id": "custom",
            "vibe": "по образцу заказчика",
            "brief": "Повтори палитру, шрифты и плотность образца. Пустой слайд запрещён.",
        }
    theme_id = str(direction.get("theme_id") or "noir")

    await _update_status(status_msg, "Придумываю визуальный язык")
    from studio.quality import prune_weak_slides, strip_excess_classic_images, target_slide_count
    from studio.schema import StudioSpecError, normalize_spec

    _, max_slides = target_slide_count(user_text)
    repair_hint = ""
    spec: dict[str, Any] | None = None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            raw_spec = await _compose_spec(
                user_text,
                kind=kind,
                theme_id=theme_id,
                document_context=document_context,
                history_text=history_text,
                user_id=user_id,
                repair_hint=repair_hint,
                direction=direction,
            )
            spec = normalize_spec(raw_spec)
            break
        except (StudioSpecError, ValueError) as exc:
            last_exc = exc
            repair_hint = str(exc)[:280]
            logger.info("Studio compose attempt %s failed: %s", attempt + 1, exc)
        except Exception as exc:
            last_exc = exc
            logger.info("Studio compose failed (%s), using fallback", exc)
            break

    if spec is None:
        logger.info("Studio falling back after compose errors: %s", last_exc)
        raw_spec = _fallback_board(user_text, theme_id, direction) if kind == "infographic" else _fallback_deck(user_text, theme_id, direction)
        spec = normalize_spec(raw_spec)

    if spec.get("kind") == "deck":
        spec = prune_weak_slides(spec, max_slides=max_slides)
        spec = strip_excess_classic_images(spec, keep=8)

    image_jobs = collect_image_jobs(spec)
    if image_jobs:
        await _update_status(status_msg, f"Рисую кадры ({len(image_jobs)})")
        try:
            spec = await resolve_studio_images(spec, user_id)
        except Exception:
            logger.exception("Studio image resolve failed; continue without images")

    await _update_status(status_msg, "Собираю макеты")
    try:
        files = build_studio_artifact(spec, with_previews=True, already_normalized=True)
    except Exception:
        logger.exception("Studio render failed")
        return "Не удалось собрать файл Студии. Уточните бриф и попробуйте ещё раз.", [], "", []

    img_n = len(spec.get("_images") or {})
    img_note = f", AI-картинок: {img_n}" if img_n else ""
    if spec.get("_images_skipped") and image_jobs and not img_n:
        img_note = " (картинки пропущены: лимит генерации)"

    vibe = (spec.get("theme") or {}).get("label") or direction.get("vibe") or spec.get("theme_id")
    if spec["kind"] == "deck":
        n = len(spec.get("slides") or [])
        answer = (
            f"Готова презентация «{spec.get('title') or 'Deck'}»: {n} слайдов, визуальный язык «{vibe}»{img_note}. "
            f"PPTX и превью прикреплены – скачайте кнопкой в чате."
        )
    else:
        answer = (
            f"Готова инфографика «{spec.get('headline') or 'Board'}», "
            f"язык «{vibe}»{img_note}. PNG прикреплён – скачайте кнопкой в чате."
        )
    return sanitize_response_text(answer), files, "", []
