"""
Дешёвый режим генерации больших документов (docgen).
Строит план документа, пишет разделы параллельно дешёвой моделью
с эскалацией по сложности, собирает единый .docx.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from config import DEEPSEEK_API_KEY
from openai_client import get_chat_response

logger = logging.getLogger(__name__)

# Not unlimited by design: a planner that returns a runaway outline (tens of
# thousands of sections) would otherwise start a run lasting days with no way
# back. 5000 sections is ~7500 pages, which covers the 5-7 thousand page
# requirement with margin.
MAX_SECTIONS = 5000
# Batches (not a global semaphore) so previous_tail continuity and progress
# reporting stay simple; the trade-off is each batch waits for its slowest
# member. Acceptable at this concurrency — do not "fix" this into a semaphore
# without re-checking that trade-off still holds.
MAX_PARALLEL_SECTIONS = 12
CHUNK_TARGET_CHARS = 3000
TOP_K_CHUNKS = 6
MAX_CHUNK_CHARS_PER_SECTION = 12000

# Raising the per-file extraction caps (document_parser.MAX_*_EXTENDED) removes
# the only thing that used to keep the total corpus small by accident. Measured
# with the new caps: 50 files x 900 pages = 118 MB of text -> 57 500 chunks,
# 21.8s, 420MB RAM. That's fine; 200 such files would be ~1.7GB, which is not.
# This is the deliberate ceiling that replaces that accident.
MAX_SOURCE_CHARS_TOTAL = 150_000_000

# Measured on 149 files across 5 archives: unbounded previews + catalog reached
# ~300 000 chars (~120 000 tokens) in the planner call, which is supposed to be
# the cheap one, and grows linearly with file count. These two caps bound it.
PLANNER_PREVIEW_BUDGET = 60_000   # chars of preview bodies (headers extra)
# Previews are per archive, not per file, so these two give a real ceiling
# instead of a slower linear growth: at most PLANNER_PREVIEW_GROUPS previews no
# matter how many files those archives hold, archives beyond it listed by name
# only. Measured whole-block ceiling including headers and name lists: ~70k
# chars, flat from ~1000 files up to 5000 (it was 346k at 1000 before).
PLANNER_PREVIEW_GROUPS = 40
_NAMES_SHOWN_PER_GROUP = 8        # file names listed per archive before "… и ещё N"
PLANNER_CATALOG_CHUNKS = 400      # chunk titles shown, was an unbounded 2000

PLANNER_MODEL = "gpt-5.6-terra"
DEFAULT_WRITER_MODEL = "gpt-5.6-luna"
ESCALATED_WRITER_MODEL = "gpt-5.6-terra"

# Transient failures (429, provider timeout, dropped connection) are certain
# at thousands of calls. Bounded, no jitter/backoff growth: this is a bulk
# job, not a latency-sensitive path.
SECTION_ATTEMPTS = 3
SECTION_RETRY_DELAYS = (2, 8)  # seconds before attempts 2 and 3

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")
_PAGE_MARKER = re.compile(r"\n---\s*Страница\s+\d+\s*---\n")
_SECTION_FAILED_PREFIX = "[Не удалось сгенерировать раздел"
# Число в маркере обязательно: без него подстрока может встретиться в самом
# тексте документа и оболгать его как усечённый.
_PAGES_TRUNCATED_RE = re.compile(r"Прочитал первые \d+")

# Confirmation chip labels (Task 12). Phase two matches these exact strings in
# the clarify reply text to detect the user's choice — a literal retyped
# elsewhere instead of importing these constants would silently break that.
_CONFIRM_START = "Да, начинай"
_CONFIRM_CANCEL = "Нет, отменить"
_TEMPLATE_CONFIRMED = "Да"
_TEMPLATE_NONE = "Шаблона нет, всё это база знаний"
_TEMPLATE_WRONG = "Нет, шаблон другой файл"


@dataclass
class Chunk:
    id: int
    doc_name: str
    title: str
    text: str
    tokens: frozenset = field(default_factory=frozenset)
    title_tokens: frozenset = field(default_factory=frozenset)


@dataclass
class Section:
    id: int
    title: str
    brief: str
    complexity: str  # "simple" | "complex"


def _tokenize(text: str) -> set:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _split_into_chunks(doc_name: str, text: str, start_id: int) -> List[Chunk]:
    pieces = [p.strip() for p in _PAGE_MARKER.split(text) if p.strip()]
    chunks: List[Chunk] = []
    cid = start_id
    for piece in pieces:
        for i in range(0, len(piece), CHUNK_TARGET_CHARS):
            slice_text = piece[i:i + CHUNK_TARGET_CHARS].strip()
            if not slice_text:
                continue
            title = slice_text.splitlines()[0][:120]
            chunks.append(Chunk(
                id=cid, doc_name=doc_name, title=title, text=slice_text,
                tokens=frozenset(_tokenize(slice_text)),
                title_tokens=frozenset(_tokenize(title)),
            ))
            cid += 1
    return chunks


def _extract_source_chunks(user_id: int) -> Tuple[List[Chunk], List[str], List[str]]:
    """Чанки всех документов беседы, имена тех, что прочитаны не целиком, и
    имена тех, что не поместились в общий потолок MAX_SOURCE_CHARS_TOTAL.

    Усечение ищется в целом тексте документа, до нарезки: маркер длиной в
    десятки символов легко попадает на границу чанков, и тогда ни в одном
    чанке целиком не находится.

    Про сами усечения: повышенные лимиты извлечения включаются, только если
    режим «Документы» уже выбран в момент загрузки файла. Если человек сначала
    приложил файлы и только потом переключил режим, большой исходник уже
    усечён, и без предупреждения он выглядит как полный документ.

    Про общий потолок: документ, который вместе с уже накопленными не
    поместится в MAX_SOURCE_CHARS_TOTAL, пропускается — но следующие, меньшие
    по размеру, всё ещё проверяются и могут поместиться. Имя пропущенного
    документа обязательно возвращается вызывающему: документ, молча
    исчезнувший из генерации на 5000 страниц, — ровно тот отказ, от которого
    этот режим и защищали все предыдущие лимиты.
    """
    from conversations import conversation_manager
    from document_parser import TEXT_TRUNCATED_NOTICE

    docs = conversation_manager.get_documents(int(user_id))
    chunks: List[Chunk] = []
    truncated: List[str] = []
    skipped: List[str] = []
    total_chars = 0
    for doc in docs:
        name = str(doc.get("filename") or "документ")
        body = str(doc.get("content") or "")
        if not body:
            continue
        if total_chars + len(body) > MAX_SOURCE_CHARS_TOTAL:
            skipped.append(name)
            continue
        total_chars += len(body)
        if TEXT_TRUNCATED_NOTICE.strip() in body or _PAGES_TRUNCATED_RE.search(body):
            truncated.append(name)
        chunks.extend(_split_into_chunks(name, body, len(chunks)))
    return chunks, truncated, skipped


def _select_relevant_chunks(
    section_title: str, section_brief: str, chunks: List[Chunk], top_k: int = TOP_K_CHUNKS
) -> List[Chunk]:
    if not chunks:
        return []
    query_tokens = _tokenize(f"{section_title} {section_brief}")
    if not query_tokens:
        return chunks[:top_k]
    scored = []
    for chunk in chunks:
        overlap = len(query_tokens & chunk.tokens)
        # title_tokens is precomputed by _split_into_chunks; a Chunk built by hand
        # elsewhere still gets the title bonus instead of silently losing it.
        title_tokens = chunk.title_tokens or _tokenize(chunk.title)
        title_overlap = len(query_tokens & title_tokens)
        score = overlap + title_overlap * 3
        if score > 0:
            scored.append((score, chunk))
    if not scored:
        return chunks[:top_k]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def _join_labeled(chunks: List[Chunk], budget: int) -> str:
    parts = []
    remaining = budget
    for chunk in chunks:
        if remaining <= 0:
            break
        piece = chunk.text[:remaining]
        parts.append(f"[{chunk.doc_name}] {piece}")
        remaining -= len(piece)
    return "\n\n".join(parts)


def _build_context_block(chunks: List[Chunk], budget: int, template_names: Optional[Set[str]] = None) -> str:
    if not chunks:
        return ""
    if not template_names:
        return _join_labeled(chunks, budget)
    template_chunks = [c for c in chunks if c.doc_name in template_names]
    knowledge_chunks = [c for c in chunks if c.doc_name not in template_names]
    if not knowledge_chunks:
        return f"Формат по шаблону:\n{_join_labeled(template_chunks, budget)}"
    if not template_chunks:
        return f"Факты из базы знаний:\n{_join_labeled(knowledge_chunks, budget)}"
    half = budget // 2
    template_block = _join_labeled(template_chunks, half)
    knowledge_block = _join_labeled(knowledge_chunks, budget - len(template_block))
    return f"Формат по шаблону:\n{template_block}\n\nФакты из базы знаний:\n{knowledge_block}"


_TEMPLATE_NAME_RE = re.compile(r"(?i)(шаблон|образец|форма|бланк|пример|template|form|sample)")


def _classify_documents_hint(chunks: List[Chunk]) -> str:
    """Дешёвая подсказка планировщику по именам файлов —
    что похоже на шаблон оформления, а что на базу знаний. Планировщик
    вправе проигнорировать её, если пользователь в запросе явно называет
    другой файл шаблоном — это только эвристика на случай, когда
    пользователь не сказал прямо."""
    seen: List[str] = []
    for c in chunks:
        if c.doc_name not in seen:
            seen.append(c.doc_name)
    template_like = [n for n in seen if _TEMPLATE_NAME_RE.search(n)]
    if not template_like:
        return ""
    knowledge_like = [n for n in seen if n not in template_like]
    return (
        f"По именам файлов похоже на шаблон оформления: {', '.join(template_like)}. "
        f"Остальное похоже на базу знаний: {', '.join(knowledge_like) or '(нет других файлов)'}. "
        "Это только подсказка по имени файла — если пользователь в запросе прямо называет "
        "другой файл шаблоном, доверяй запросу, а не этой подсказке."
    )


def _folder_of(doc_name: str) -> str:
    """The containing folder — everything before the LAST '/', or the bare
    name when there is none. extract_zip_archive names nested archive members
    f"{archive}/{dir}/{inner}", so a file two folders deep groups with its own
    folder, not with the archive as a whole — that's what lets a planner tell
    "arhiv.zip/shablony" (templates) apart from "arhiv.zip/baza" (knowledge)."""
    return doc_name.rsplit("/", 1)[0] if "/" in doc_name else doc_name


def _group_by_folder(names: List[str]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for name in names:
        groups.setdefault(_folder_of(name), []).append(name)
    return groups


def _document_previews(chunks: List[Chunk], budget_per_doc: int = 1500) -> str:
    """Одно превью на папку (архив или папку внутри него), а не на каждый
    файл, плюс список имён внутри.

    Превью на файл не ограничивало ничего: пол в 300 символов побеждал деление
    бюджета, и блок снова рос линейно — замерено 66 878 символов уже на 150
    файлах и 346 028 на 1000, то есть хуже исходной проблемы. Папок же в
    беседе единицы, поэтому бюджет на папку даёт настоящий потолок:
    PLANNER_PREVIEW_GROUPS × budget_per_doc, независимо от числа файлов.

    Файлы внутри одной папки обычно однотипны (формы, тома одного
    справочника), так что для распознавания шаблона хватает начала первого из
    них; остальные планировщик видит по именам — они дешёвые, и именно их он
    возвращает.
    """
    order: List[str] = []
    bodies: Dict[str, str] = {}
    for c in chunks:
        if c.doc_name not in bodies:
            order.append(c.doc_name)
            bodies[c.doc_name] = ""
        if len(bodies[c.doc_name]) < budget_per_doc:
            bodies[c.doc_name] += c.text

    groups = _group_by_folder(order)
    previewed = list(groups.items())[:PLANNER_PREVIEW_GROUPS]
    per_group_budget = max(300, min(budget_per_doc, PLANNER_PREVIEW_BUDGET // max(1, len(previewed))))

    def _listed(names: List[str]) -> str:
        shown = ", ".join(names[:_NAMES_SHOWN_PER_GROUP])
        if len(names) > _NAMES_SHOWN_PER_GROUP:
            shown += f", … и ещё {len(names) - _NAMES_SHOWN_PER_GROUP}"
        return shown

    parts: List[str] = []
    for folder, members in previewed:
        head = members[0]
        if len(members) > 1:
            parts.append(
                f"=== Группа {folder}: {len(members)} файлов ({_listed(members)}) ===\n"
                f"--- начало файла {head} ---\n{bodies[head][:per_group_budget]}"
            )
        else:
            parts.append(f"--- {head} (начало файла) ---\n{bodies[head][:per_group_budget]}")

    hidden = list(groups)[PLANNER_PREVIEW_GROUPS:]
    if hidden:
        parts.append(f"=== Ещё источники без превью ({len(hidden)}): {_listed(hidden)} ===")
    return "\n\n".join(parts)


def _parse_outline_response(response_text: str) -> Tuple[List[Section], List[str]]:
    cleaned = (response_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        return [], []
    if not isinstance(raw, dict):
        return [], []
    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list):
        return [], []
    sections: List[Section] = []
    for i, item in enumerate(raw_sections):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        complexity = item.get("complexity") if item.get("complexity") in ("simple", "complex") else "simple"
        sections.append(Section(
            id=i,
            title=str(item["title"])[:200],
            brief=str(item.get("brief", ""))[:500],
            complexity=complexity,
        ))
    raw_templates = raw.get("template_documents")
    # A planner that answers with the old singular shape (a bare string) must
    # not silently produce "no template" — wrap it instead of dropping it.
    if isinstance(raw_templates, str):
        raw_templates = [raw_templates]
    if not isinstance(raw_templates, list):
        raw_templates = []
    template_names = [str(n).strip() for n in raw_templates if str(n).strip()]
    return sections[:MAX_SECTIONS], template_names


def _expand_template_names(names: List[str], chunks: List[Chunk]) -> Set[str]:
    """Resolves planner-named templates to the set of document names they
    select. An exact match selects that document; a name matching an archive
    prefix (some document starts with f"{name}/") selects every member of
    that archive; unknown names are dropped. A name that is both a real file
    and a prefix of others selects the union of both — nothing named by the
    planner is silently lost."""
    all_docs: List[str] = []
    doc_set: Set[str] = set()
    for c in chunks:
        if c.doc_name not in doc_set:
            doc_set.add(c.doc_name)
            all_docs.append(c.doc_name)

    resolved: Set[str] = set()
    for raw in names:
        # Планировщик вполне может назвать архив с хвостовым слэшем
        # ("shablony.zip/"); без нормализации такое имя не совпадёт ни с чем,
        # и шаблоны молча окажутся пустыми.
        name = raw.strip().rstrip("/")
        if not name:
            continue
        if name in doc_set:
            resolved.add(name)
        prefix = f"{name}/"
        resolved.update(d for d in all_docs if d.startswith(prefix))
    return resolved


async def _plan_outline(
    user_text: str, chunks: List[Chunk], user_id: int, extra_instruction: str = ""
) -> Tuple[List[Section], Set[str], bool]:
    """Разделы, набор файлов-шаблонов (может быть пустым) и флаг «план
    построить не удалось».

    Флаг нужен, чтобы молчаливый откат на один раздел «Документ» был виден
    пользователю: без него сбой планировщика выглядит как обычный короткий
    документ, и человек не понимает, почему структура не та, что он просил.
    """
    if chunks:
        catalog = "\n".join(f"{c.id}: {c.title}" for c in chunks[:PLANNER_CATALOG_CHUNKS])
    else:
        catalog = "(исходники не найдены — опирайся только на запрос пользователя)"

    classification_hint = _classify_documents_hint(chunks)
    document_previews = _document_previews(chunks)

    prompt = (
        "Построй план большого документа по запросу пользователя.\n"
        "Верни СТРОГО JSON-объект без markdown-обёрток и без пояснений, в формате:\n"
        '{"template_documents": ["точное имя файла или имя архива из списка ниже", ...] (можно пустой список), '
        '"sections": [{"title": "Название раздела", "brief": "Что должно быть в разделе, 1-3 предложения", '
        '"complexity": "simple" | "complex"}, ...]}.\n'
        "complexity=complex — для расчётов, таблиц с цифрами, юридических формулировок, "
        "технических требований с точными значениями. Остальное — simple.\n\n"
        f"Запрос пользователя:\n{user_text}\n\n"
        + (f"Уточнения пользователя: {extra_instruction}\n\n" if extra_instruction else "")
        + f"Заголовки доступных фрагментов исходников (id: заголовок):\n{catalog}\n\n"
        "template_documents — точные имена документов ниже (можно несколько), ТОЛЬКО если запрос\n"
        "пользователя или подсказка ниже указывают, что это шаблон оформления (пример структуры для\n"
        "итогового документа). Вместо перечисления всех файлов можно указать имя целого архива, имя\n"
        "папки внутри архива (например, \"архив.zip/папка\") или имя одного файла — тогда шаблоном\n"
        "станут все файлы этого архива, все файлы этой папки или один этот файл.\n"
        "Слова пользователя в запросе всегда важнее подсказки по имени файла.\n"
        "Если ничто не указывает на шаблон, верни template_documents: []. Если template_documents\n"
        "задан, построй список разделов, максимально повторяя структуру (заголовки, их порядок) этих\n"
        "документов, а не придумывай новую; иначе строй план свободно по сути запроса и остальных\n"
        "материалов.\n\n"
        f"{classification_hint}\n\n"
        f"Начало каждого документа (для распознавания шаблона):\n{document_previews}"
    )
    messages = [
        {"role": "system", "content": "Ты планировщик документов. Отвечаешь только валидным JSON-объектом."},
        {"role": "user", "content": prompt},
    ]
    try:
        response_text, _, _, _ = await get_chat_response(
            messages, model=PLANNER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
        )
        sections, template_names_raw = _parse_outline_response(response_text)
        if sections:
            return sections, _expand_template_names(template_names_raw, chunks), False
        logger.error("docgen outline planning returned no sections: %s", (response_text or "")[:300])
    except Exception as e:
        logger.error(f"docgen outline planning failed: {e}", exc_info=True)
    return [Section(id=0, title="Документ", brief=user_text[:500], complexity="complex")], set(), True


def _section_context(
    section: Section, chunks: List[Chunk], template_names: Optional[Set[str]]
) -> str:
    relevant = _select_relevant_chunks(section.title, section.brief, chunks)
    return _build_context_block(relevant, MAX_CHUNK_CHARS_PER_SECTION, template_names)


async def _write_section(
    section: Section, chunks: List[Chunk], previous_tail: str, user_id: int,
    template_names: Optional[Set[str]] = None,
) -> str:
    # Selecting chunks + building the context block tokenizes/scans the whole
    # corpus per section; at 12 concurrent writers that's real CPU time on the
    # (shared) event loop, so it runs in a thread instead.
    context_block = await asyncio.to_thread(
        _section_context, section, chunks, template_names
    )

    prompt_parts = [f"Раздел документа: {section.title}", f"Задача раздела: {section.brief}"]
    if context_block:
        prompt_parts.append(f"Релевантные фрагменты исходников:\n{context_block}")
    if previous_tail:
        prompt_parts.append(
            "Конец предыдущего раздела (для согласованности терминов и стиля, не повторяй "
            f"его содержание):\n{previous_tail}"
        )
    prompt_parts.append(
        "Напиши текст ТОЛЬКО этого раздела в Markdown, без заголовка раздела (его добавят "
        "отдельно), без вступлений вида «в этом разделе» и без итоговых выводов в конце. "
        "Не выдумывай цифры и факты, которых нет в исходниках или в задаче раздела."
    )
    prompt = "\n\n".join(prompt_parts)

    messages = [
        {"role": "system", "content": "Ты технический писатель. Пишешь один раздел документа, по существу, без воды."},
        {"role": "user", "content": prompt},
    ]

    # asyncio.CancelledError is a BaseException, not an Exception, so it is
    # never caught below — it passes straight through the retry loop and out
    # of this function. That is required: it's how the user's stop button
    # (generation_hub.hub.cancel) reaches a running job. Do not widen this
    # except clause.
    last_error: Optional[Exception] = None
    for attempt in range(1, SECTION_ATTEMPTS + 1):
        try:
            if section.complexity == "complex":
                if DEEPSEEK_API_KEY:
                    from deepseek_client import get_deepseek_response
                    text, _, _, _ = await asyncio.wait_for(
                        get_deepseek_response(
                            messages, model="deepseek-v4-pro", user_id=user_id, use_tools=False,
                        ),
                        timeout=120,
                    )
                else:
                    text, _, _, _ = await asyncio.wait_for(
                        get_chat_response(
                            messages, model=ESCALATED_WRITER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
                        ),
                        timeout=120,
                    )
            else:
                text, _, _, _ = await asyncio.wait_for(
                    get_chat_response(
                        messages, model=DEFAULT_WRITER_MODEL, user_id=user_id, use_tools=False, use_skills=False,
                    ),
                    timeout=120,
                )
            return text.strip()
        except Exception as e:
            last_error = e
            if attempt < SECTION_ATTEMPTS:
                logger.warning(
                    "docgen section '%s' attempt %d/%d failed, retrying: %s",
                    section.title, attempt, SECTION_ATTEMPTS, e,
                )
                # Clamped, not indexed directly: raising SECTION_ATTEMPTS without
                # extending the delays tuple would otherwise IndexError here — in
                # the one code path whose whole job is surviving failures.
                await asyncio.sleep(SECTION_RETRY_DELAYS[min(attempt, len(SECTION_RETRY_DELAYS)) - 1])
            else:
                logger.error(
                    f"docgen section '{section.title}' failed after {SECTION_ATTEMPTS} attempts: {e}",
                    exc_info=True,
                )
    return f"{_SECTION_FAILED_PREFIX}: {str(last_error)[:200]}]"


async def _update_status(status_msg: Any, text: str) -> None:
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.debug(f"Failed to edit docgen status message: {e}")


async def get_docgen_response(
    messages: List[Dict[str, Any]],
    user_text: str,
    user_id: int,
    status_msg: Any,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Two-phase entry (Task 12): a first turn plans and asks for confirmation
    before any writer call runs; only a clarify reply on a later turn actually
    generates. At up to 5000 sections a run is thousands of model calls and
    hours of wall time, so starting one on the wrong knowledge base or the
    wrong template file by mistake is expensive — this makes that mistake
    cheap to catch before it burns anything."""
    from app.billing.quota import billing_pool
    from clarify import is_clarify_reply

    token = billing_pool.set("computer")
    try:
        if not is_clarify_reply(user_text):
            return await _confirm_before_generating(user_text, user_id, status_msg)
        return await _run_docgen_after_confirmation(messages, user_text, user_id, status_msg)
    finally:
        billing_pool.reset(token)


def _recover_original_request(messages: List[Dict[str, Any]], user_text: str) -> str:
    """The last user message that isn't itself a clarify reply — i.e. the
    request from before the confirmation question was asked. Falls back to
    user_text so a conversation that somehow starts with a clarify reply
    doesn't crash."""
    from clarify import is_clarify_reply

    for message in reversed(messages or []):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if is_clarify_reply(content):
            continue
        return content
    return user_text


def _format_grouped_names(names: List[str], max_members: int = 5) -> str:
    """Names grouped by containing folder for the confirmation text, which has
    no length limit — unlike the clarify chip prompts. Each group's member
    list is truncated after max_members with "… и ещё N" so a 200-file base
    stays readable instead of listing every file."""
    if not names:
        return ""
    parts = []
    for folder, members in _group_by_folder(names).items():
        if len(members) == 1 and members[0] == folder:
            parts.append(folder)
            continue
        prefix = f"{folder}/"
        shown = [m[len(prefix):] if m.startswith(prefix) else m for m in members[:max_members]]
        suffix = f", … и ещё {len(members) - max_members}" if len(members) > max_members else ""
        parts.append(f"{folder} ({len(members)} файл(ов): {', '.join(shown)}{suffix})")
    return "; ".join(parts)


async def _confirm_before_generating(
    user_text: str, user_id: int, status_msg: Any
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Phase one: plan, then ask — never write a single section. One planner
    call is cheap next to the thousands of writer calls it would otherwise
    green-light blindly, and it buys precise numbers for the question instead
    of a blind "are you sure?"."""
    from clarify import normalize_questions, pack_search

    await _update_status(status_msg, "📄 Читаю исходники и строю план документа...")
    chunks, truncated_sources, skipped_sources = await asyncio.to_thread(_extract_source_chunks, user_id)
    outline, template_names, planning_failed = await _plan_outline(user_text, chunks, user_id)

    total = len(outline)
    approx_pages = max(1, total * CHUNK_TARGET_CHARS // 2000)

    doc_names: List[str] = []
    for chunk in chunks:
        if chunk.doc_name not in doc_names:
            doc_names.append(chunk.doc_name)
    knowledge_names = [n for n in doc_names if n not in template_names] if template_names else doc_names

    lines = [f"Разделов: {total}, примерно {approx_pages} стр."]
    if template_names:
        lines.append(
            f"Шаблон оформления ({len(template_names)} файл(ов)): "
            f"{_format_grouped_names(sorted(template_names))}."
        )
    else:
        lines.append("Шаблон оформления не определён.")
    lines.append(
        f"База знаний: {_format_grouped_names(knowledge_names)}." if knowledge_names
        else "База знаний: файлы не найдены."
    )
    if truncated_sources:
        lines.append(
            f"Прочитаны не целиком: {', '.join(truncated_sources)}. Загрузите их заново в режиме «Документы»."
        )
    if skipped_sources:
        lines.append(
            f"Не поместились в общий лимит базы знаний ({MAX_SOURCE_CHARS_TOTAL // 1_000_000} млн символов) "
            f"и не читались вовсе: {', '.join(skipped_sources)}."
        )
    if planning_failed:
        lines.append("План построить не удалось — запасной вариант: один раздел на весь документ.")
    text = "\n".join(lines)

    questions_raw = [
        {
            "prompt": f"Начинать генерацию? Разделов: {total}, примерно {approx_pages} страниц",
            "options": [_CONFIRM_START, _CONFIRM_CANCEL],
        }
    ]
    if template_names:
        questions_raw.append({
            # Count-based, not name-based: a chip prompt over 160 chars is
            # silently dropped by clarify.normalize_questions, and naming
            # dozens of template files here would do exactly that. The detail
            # goes in `text` above instead, which has no limit.
            "prompt": f"Шаблоны определены верно? Файлов: {len(template_names)}",
            "options": [_TEMPLATE_CONFIRMED, _TEMPLATE_NONE, _TEMPLATE_WRONG],
        })
    questions = normalize_questions(questions_raw)
    return text, [], "", pack_search(questions)


async def _run_docgen_after_confirmation(
    messages: List[Dict[str, Any]], user_text: str, user_id: int, status_msg: Any
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Phase two: honour the answers. Anything short of an explicit start exits
    before anything is loaded or planned; otherwise the original request is
    recovered and the reply itself is threaded into planning so an answer like
    "шаблон другой файл" actually changes the plan instead of being asked for
    and then ignored.

    The gate requires _CONFIRM_START rather than merely the absence of
    _CONFIRM_CANCEL, because the clarify card is a shared component with a
    "Пропустить" button bound to Enter: skipping every question sends
    "Уточнения пропущены…", which is a clarify reply containing neither label.
    Treating that as consent would launch thousands of model calls on one
    accidental keypress — exactly what this confirmation exists to prevent.
    """
    if _CONFIRM_START not in user_text:
        if _CONFIRM_CANCEL in user_text:
            return "Отменил, ничего не генерировал.", [], "", []
        return (
            "Не начинаю: подтверждение не получено. Нажмите «"
            f"{_CONFIRM_START}», если документ нужно сгенерировать.",
            [], "", [],
        )
    original_request = _recover_original_request(messages, user_text)
    return await _run_docgen(original_request, user_id, status_msg, extra_instruction=user_text)


async def _run_docgen(
    user_text: str,
    user_id: int,
    status_msg: Any,
    extra_instruction: str = "",
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """Режим Документы: план -> параллельная генерация разделов -> сборка в .docx."""
    await _update_status(status_msg, "📄 Читаю исходники и строю план документа...")
    # Синхронный запрос к БД плюс токенизация всего корпуса: на тысячах страниц
    # это секунды CPU, которые нельзя держать в event loop — он общий на всех.
    chunks, truncated_sources, skipped_sources = await asyncio.to_thread(_extract_source_chunks, user_id)
    no_sources = not chunks
    outline, template_names, planning_failed = await _plan_outline(user_text, chunks, user_id, extra_instruction)

    total = len(outline)
    if planning_failed:
        plan_status = "📄 План построить не удалось — пишу документ одним разделом..."
    else:
        plan_status = f"📄 План готов: {total} раздел(ов). Пишу текст..."
        if no_sources:
            plan_status += " Исходники не найдены — пишу по одному промпту."
    await _update_status(status_msg, plan_status)

    section_texts: List[str] = [""] * total
    previous_tail = ""
    done = 0
    for batch_start in range(0, total, MAX_PARALLEL_SECTIONS):
        batch = outline[batch_start:batch_start + MAX_PARALLEL_SECTIONS]
        jobs = [
            _write_section(section, chunks, previous_tail, user_id, template_names)
            for section in batch
        ]
        results = await asyncio.gather(*jobs)
        for offset, text in enumerate(results):
            section_texts[batch_start + offset] = text
        if results and results[-1] and not results[-1].startswith(_SECTION_FAILED_PREFIX):
            previous_tail = results[-1][-500:]
        done += len(batch)
        await _update_status(status_msg, f"📄 Раздел {done} из {total}...")

    await _update_status(status_msg, "📄 Собираю итоговый .docx...")
    full_markdown = "\n\n".join(
        f"## {section.title}\n\n{text}" for section, text in zip(outline, section_texts)
    )

    from docx_generator import convert_markdown_to_docx
    try:
        docx_bytes = await asyncio.to_thread(convert_markdown_to_docx, full_markdown)
    except Exception as e:
        logger.error(f"docgen docx assembly failed: {e}", exc_info=True)
        return f"Не удалось собрать документ: {str(e)[:200]}", [], "", []

    summary = f"Готово. Документ из {total} раздел(ов) собран в .docx — файл во вложении."
    if no_sources:
        summary += " Исходники не найдены — документ написан по одному промпту."
    if planning_failed:
        summary += " План разделов построить не удалось, поэтому документ написан одним разделом."
    failed_sections = sum(1 for text in section_texts if text.startswith(_SECTION_FAILED_PREFIX))
    if failed_sections:
        summary += f" Не удалось сгенерировать разделов: {failed_sections} из {total} — они помечены в тексте."
    if truncated_sources:
        summary += (
            f" Прочитаны не целиком: {', '.join(truncated_sources)}. "
            "Загрузите эти файлы заново, уже в режиме «Документы» — тогда они будут прочитаны полностью."
        )
    if skipped_sources:
        summary += (
            f" Не поместились в общий лимит базы знаний и не читались вовсе: {', '.join(skipped_sources)}."
        )
    files = [{"filename": "Документ.docx", "bytes": docx_bytes}]
    return summary, files, "", []
