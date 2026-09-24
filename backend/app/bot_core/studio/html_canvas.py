"""Live HTML canvas for Studio: Claude Design analog (one file, iterate, preview)."""

from __future__ import annotations

import html as html_lib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_HTML_CHARS = 220_000
MAX_PREV_HTML_CHARS = 70_000
MAX_AI_IMAGES = 4

_HTML_FENCE = re.compile(r"```(?:html|HTML)?\s*([\s\S]*?)```")
_DOCTYPE = re.compile(r"<!doctype\s+html", re.I)
_SCRIPT_SRC = re.compile(
    r"<script\b[^>]*\bsrc\s*=\s*(?:['\"][^'\"]+['\"]|[^\s>]+)[^>]*>[\s\S]*?</script>",
    re.I,
)
_IFRAME = re.compile(r"<iframe\b[\s\S]*?</iframe>", re.I)
_OBJECT = re.compile(r"<(object|embed|applet)\b[\s\S]*?</\1>", re.I)
_JS_URL = re.compile(r"\s+(href|src)\s*=\s*['\"]\s*javascript:[^'\"]*['\"]", re.I)
_ON_ATTR = re.compile(r"\s+on[a-z]+\s*=\s*('[\s\S]*?'|\"[\s\S]*?\")", re.I)
_META_REFRESH = re.compile(r"<meta\b[^>]*http-equiv\s*=\s*['\"]refresh['\"][^>]*>", re.I)
_BAD_LINK = re.compile(
    r"<link\b[^>]*href\s*=\s*['\"](?!https://fonts\.(?:googleapis|gstatic)\.com)[^'\"]+['\"][^>]*>",
    re.I,
)
_AI_IMG = re.compile(
    r"<img\b([^>]*?)\bdata-ai\s*=\s*[\"']([^\"']+)[\"']([^>]*)>",
    re.I,
)
_TITLE = re.compile(r"<title>([^<]+)</title>", re.I)
_H1 = re.compile(r"<h1\b[^>]*>([\s\S]*?)</h1>", re.I)
_TAGS = re.compile(r"<[^>]+>")

_SLIDE_HINT = re.compile(
    r"(?i)\b(презентац\w*|pptx|powerpoint|слайд\w*|питч\w*|pitch|decks?|выступлен\w*|keynote)\b"
)
_PPTX_FILE = re.compile(r"(?i)\b(pptx|powerpoint|power\s*point|\.ppt)\b")
_INFO_HINT = re.compile(
    r"(?i)\b(инфографик\w*|infographic|одноэкран\w*|воронк\w*|таймлайн\w*|timeline|kpi[\s-]?strip)\b"
)
_LANDING_HINT = re.compile(
    r"(?i)\b(лендинг\w*|landing|сайт\w*|страниц\w*|промо|hero|маркетинг\w*)\b"
)
_DASH_HINT = re.compile(
    r"(?i)\b(дашборд\w*|dashboard|кабинет\w*|аналитик\w*|панель\w*|метрики)\b"
)
_APP_HINT = re.compile(
    r"(?i)\b(прототип\w*|интерфейс\w*|ui[\s-]?kit|экран прило|мобильн\w*|app ui|макет приложения)\b"
)
_IMAGE_NOUN = (
    r"(?:картин\w*|изображен\w*|фото(?!отч)\w*|фотк\w*|арт\b|арты\b|обложк\w*|аватар\w*|иллюстрац\w*|"
    r"рисун\w*|постер\w*|плакат\w*|логотип\w*|лого\b|баннер\w*|стикер\w*|обои\b|открытк\w*|"
    r"портрет\w*|пейзаж\w*|image|picture|illustration|photo|artwork|poster|logo)"
)
_IMAGE_HINT = re.compile(
    r"(?i)(?:"
    r"\bнарису\w*|\bдорису\w*|\bперерису\w*|\bизобрази\w*|"
    r"\bdraw\b|\bpaint\b|"
    # «сгенерируй мне, пожалуйста, картинку», «сделай красивую обложку»
    r"\b(?:сгенериру\w*|генериру\w*|созда\w*|сдела\w*|хочу|нуж\w*|покажи|придумай|generate|create|make)"
    r"(?:\s+[\w,.-]+){0,4}?\s+" + _IMAGE_NOUN +
    # «картинку кота», «фото собаки в стиле аниме» — существительное первым словом
    r"|^\s*" + _IMAGE_NOUN +
    r")"
)
# Правка фото/картинки: «убери фон», «сделай его рыжим», «поменяй цвет».
_IMAGE_EDIT_HINT = re.compile(
    r"(?i)\b(?:фон\w*|стил\w*|цвет\w*|убери\w*|удали\w*|добав\w*|замени\w*|поменя\w*|измени\w*|"
    r"отредактир\w*|отретушир\w*|ретуш\w*|дорису\w*|перерису\w*|сделай\s+(?:его|её|ее|их|это|фото|картинк\w*)|"
    r"улучш\w*|раскрас\w*|обрежь|кадрир\w*|свет\w*|тёмн\w*|темн\w*|ярч\w*)"
)
_NEW_WORK = re.compile(
    r"(?i)\b(с нуля|заново|другая тема|новый (сайт|лендинг|проект|макет|питч)|вместо этого)\b"
)
_EDIT_HINT = re.compile(
    r"(?i)\b(поправ|измени|темнее|светлее|шрифт|цвет|шапк|кнопк|подвинь|убери|добавь|замени|ужест|мягче)\b"
)
_DATA_IMG = re.compile(
    r"src\s*=\s*[\"'](data:image/[^;]+;base64,([A-Za-z0-9+/=\s]+))[\"']",
    re.I,
)
STUDIO_IMAGE_MARK = "data-studio-image"


_HTML_KINDS = frozenset({"slides", "landing", "infographic", "dashboard", "app", "pptx"})


def detect_kind_explicit(user_text: str) -> str | None:
    text = user_text or ""
    if _PPTX_FILE.search(text) and not _EDIT_HINT.search(text):
        return "pptx"
    if _INFO_HINT.search(text) and not _SLIDE_HINT.search(text):
        return "infographic"
    if _DASH_HINT.search(text) and not _SLIDE_HINT.search(text):
        return "dashboard"
    if _APP_HINT.search(text) and not _SLIDE_HINT.search(text):
        return "app"
    if _LANDING_HINT.search(text) and not _SLIDE_HINT.search(text):
        return "landing"
    if _SLIDE_HINT.search(text):
        return "slides"
    if _IMAGE_HINT.search(text):
        return "image"
    return None


def detect_kind(user_text: str) -> str:
    return detect_kind_explicit(user_text) or "landing"


def wants_image_edit(user_text: str) -> bool:
    return bool(_IMAGE_EDIT_HINT.search(user_text or "") or _IMAGE_HINT.search(user_text or ""))


HTML_KINDS = _HTML_KINDS


def resolve_studio_job(user_text: str, previous_html: str | None) -> tuple[str, str, bool]:
    """Pick canvas kind and whether to iterate the previous HTML file."""
    prev = previous_html or ""
    iterating = should_iterate(user_text, prev)
    explicit = detect_kind_explicit(user_text)
    kind = explicit or "landing"

    if prev and is_image_canvas(prev):
        if explicit in _HTML_KINDS:
            return explicit, "", False
        if not iterating:
            return kind, "", False
        return "image", prev, True

    if kind == "image":
        return "image", "", False

    return kind, prev if iterating else "", iterating


def is_image_canvas(html: str) -> bool:
    return STUDIO_IMAGE_MARK in (html or "")


def image_canvas_html(src: str, title: str) -> str:
    safe_title = html_lib.escape((title or "Картинка").strip()[:80] or "Картинка")
    safe_src = (src or "").replace("\0", "").replace('"', "").strip()
    if not (safe_src.startswith("data:image/") or safe_src.startswith("https://") or safe_src.startswith("/")):
        safe_src = ""
    return (
        f'<!DOCTYPE html><html lang="ru" {STUDIO_IMAGE_MARK}="1">'
        "<head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{safe_title}</title>"
        "<style>html,body{margin:0;height:100%;background:#111}img{display:block;width:100%;height:100%;"
        "object-fit:contain;background:#111}</style></head><body>"
        f'<img src="{safe_src}" alt="{safe_title}">'
        "</body></html>"
    )


def extract_embedded_image_bytes(html: str) -> bytes | None:
    match = _DATA_IMG.search(html or "")
    if not match:
        return None
    import base64

    try:
        payload = re.sub(r"\s+", "", match.group(2))
        payload += "=" * ((4 - len(payload) % 4) % 4)
        return base64.b64decode(payload)
    except Exception:
        return None


def wants_pptx_file(user_text: str) -> bool:
    return bool(_PPTX_FILE.search(user_text or ""))


def should_iterate(user_text: str, previous_html: str | None) -> bool:
    if not (previous_html or "").strip():
        return False
    if _NEW_WORK.search(user_text or ""):
        return False
    return True


def extract_html(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = _HTML_FENCE.search(raw)
    if fenced:
        candidate = fenced.group(1).strip()
        wrapped = wrap_if_needed(candidate)
        if _looks_like_html(wrapped):
            return wrapped
    lowered = raw.lower()
    start = -1
    doc = _DOCTYPE.search(raw)
    if doc:
        start = doc.start()
    else:
        start = lowered.find("<html")
    if start < 0:
        if "<section" in lowered or "class=\"slide\"" in lowered or "class='slide'" in lowered:
            return wrap_if_needed(raw)
        return None
    end = lowered.rfind("</html>")
    body = raw[start : end + 7] if end > start else raw[start:]
    wrapped = wrap_if_needed(body)
    return wrapped if _looks_like_html(wrapped) else None


def _looks_like_html(text: str) -> bool:
    low = (text or "").lower()
    return "<html" in low or "<!doctype html" in low


def wrap_if_needed(html: str) -> str:
    text = (html or "").strip()
    if not text:
        return text
    low = text.lower()
    if "<html" in low or "<!doctype html" in low:
        if "<html" in low and "<!doctype" not in low:
            return "<!DOCTYPE html>\n" + text
        return text
    return (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Макет</title></head><body>\n"
        f"{text}\n</body></html>"
    )


def sanitize_html(html: str) -> str:
    text = wrap_if_needed(html or "")
    text = _SCRIPT_SRC.sub("", text)
    text = _IFRAME.sub("", text)
    text = _OBJECT.sub("", text)
    text = _META_REFRESH.sub("", text)
    text = _BAD_LINK.sub("", text)
    text = _JS_URL.sub("", text)
    # Keep inline scripts for slide nav; strip DOM0 handlers that are easy XSS.
    text = _ON_ATTR.sub("", text)
    if len(text) > MAX_HTML_CHARS:
        text = text[:MAX_HTML_CHARS] + "\n</body></html>"
    return text


def title_from_html(html: str, fallback: str = "Макет") -> str:
    match = _TITLE.search(html or "")
    if match:
        title = _TAGS.sub("", match.group(1)).strip()
        if title:
            return title[:80]
    match = _H1.search(html or "")
    if match:
        title = _TAGS.sub("", match.group(1)).strip()
        if title:
            return title[:80]
    return fallback[:80] or "Макет"


def safe_html_filename(title: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", (title or "maket").strip(), flags=re.U).strip("_") or "maket"
    return f"{stem[:48]}.html"


def clip_previous_html(html: str) -> str:
    text = html or ""
    if len(text) <= MAX_PREV_HTML_CHARS:
        return text
    keep_head = int(MAX_PREV_HTML_CHARS * 0.72)
    keep_tail = MAX_PREV_HTML_CHARS - keep_head
    return text[:keep_head] + "\n<!-- … середина обрезана … -->\n" + text[-keep_tail:]


_SLIDE_RUNTIME_MARK = "data-studio-nav"

_SLIDE_CSS = """
html,body{height:100%;margin:0;overflow:hidden;overscroll-behavior:none;touch-action:none}
html{scroll-snap-type:none!important;scroll-behavior:auto!important}
.slide{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;
overflow:hidden;box-sizing:border-box;visibility:hidden;pointer-events:none;z-index:0}
.slide.is-on{visibility:visible;pointer-events:auto;z-index:1}
.slide>.slide-inner{height:100%;min-height:0;display:flex;flex-direction:column;justify-content:center;
overflow:hidden;padding:clamp(1.25rem,4vw,4.5rem);box-sizing:border-box}
.nav,.counter,[data-deck-ui]{display:none!important}
""".strip()

_SLIDE_JS = """
(() => {
  if (window.__btDeck) return;
  window.__btDeck = 1;
  const slides = [...document.querySelectorAll('.slide')];
  if (!slides.length) return;
  const index = () => {
    const at = slides.findIndex((slide) => slide.classList.contains('is-on'));
    return at < 0 ? 0 : at;
  };
  const ping = (at) => {
    try { parent.postMessage({ type: 'bt-deck-at', index: at }, '*'); } catch (e) {}
  };
  const show = (n) => {
    const next = Math.max(0, Math.min(slides.length - 1, n | 0));
    slides.forEach((slide, i) => slide.classList.toggle('is-on', i === next));
    ping(next);
  };
  show(index() || 0);
  window.addEventListener('message', (e) => {
    if (!e.data || e.data.type !== 'bt-deck') return;
    if (typeof e.data.index === 'number') show(e.data.index);
    if (e.data.step === 1) show(index() + 1);
    if (e.data.step === -1) show(index() - 1);
  });
  window.addEventListener('keydown', (e) => {
    if (['ArrowDown','PageDown','ArrowRight',' '].includes(e.key)) { e.preventDefault(); show(index() + 1); }
    if (['ArrowUp','PageUp','ArrowLeft'].includes(e.key)) { e.preventDefault(); show(index() - 1); }
    if (e.key === 'Home') { e.preventDefault(); show(0); }
    if (e.key === 'End') { e.preventDefault(); show(slides.length - 1); }
  }, true);
  let lock = 0;
  let ignoreWheelUntil = 0;
  const step = (dir) => {
    const now = Date.now();
    if (now < lock) return;
    lock = now + 520;
    show(index() + dir);
  };
  window.addEventListener('wheel', (e) => {
    if (e.ctrlKey || e.metaKey) return;
    if (Date.now() < ignoreWheelUntil) { e.preventDefault(); return; }
    const dy = e.deltaY;
    const dx = e.deltaX;
    if (Math.abs(dy) < 12 || Math.abs(dy) < Math.abs(dx)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    step(dy > 0 ? 1 : -1);
  }, { passive: false, capture: true });
  let touchY = 0;
  let touchX = 0;
  window.addEventListener('touchstart', (e) => {
    touchY = e.changedTouches[0].clientY;
    touchX = e.changedTouches[0].clientX;
  }, { passive: true, capture: true });
  window.addEventListener('touchend', (e) => {
    const dy = touchY - e.changedTouches[0].clientY;
    const dx = touchX - e.changedTouches[0].clientX;
    if (Math.abs(dy) < 48 || Math.abs(dy) < Math.abs(dx) * 1.15) return;
    ignoreWheelUntil = Date.now() + 700;
    e.preventDefault();
    step(dy > 0 ? 1 : -1);
  }, { passive: false, capture: true });
})();
""".strip()


def ensure_slide_runtime(html: str) -> str:
    text = html or ""
    if ".slide" not in text and 'class="slide"' not in text and "class='slide'" not in text:
        return text
    text = re.sub(r"<script\b[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(rf"<style[^>]*{_SLIDE_RUNTIME_MARK}[^>]*>[\s\S]*?</style>", "", text, flags=re.I)
    css = f"<style {_SLIDE_RUNTIME_MARK}=\"css\">{_SLIDE_CSS}</style>"
    js = f"<script {_SLIDE_RUNTIME_MARK}=\"js\">{_SLIDE_JS}</script>"
    if re.search(r"</head>", text, re.I):
        text = re.sub(r"</head>", css + "\n</head>", text, count=1, flags=re.I)
    else:
        text = css + text
    if re.search(r"</body>", text, re.I):
        text = re.sub(r"</body>", js + "\n</body>", text, count=1, flags=re.I)
    else:
        text = text + js
    return text


def collect_ai_image_prompts(html: str) -> list[str]:
    prompts: list[str] = []
    seen: set[str] = set()
    for match in _AI_IMG.finditer(html or ""):
        prompt = " ".join(match.group(2).split()).strip()
        if not prompt or prompt in seen:
            continue
        seen.add(prompt)
        prompts.append(prompt)
        if len(prompts) >= MAX_AI_IMAGES:
            break
    return prompts


def apply_ai_images(html: str, images: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        pre, prompt, post = match.group(1), match.group(2), match.group(3)
        key = " ".join(prompt.split()).strip()
        data_url = images.get(key)
        attrs = f"{pre} {post}"
        attrs = re.sub(r"\ssrc\s*=\s*['\"][^'\"]*['\"]", "", attrs, flags=re.I)
        if data_url:
            return f'<img{attrs} src="{data_url}">'
        return f"<img{attrs}>"

    return _AI_IMG.sub(repl, html or "")


def load_previous_html(user_id: int) -> str | None:
    try:
        from conversations import conversation_manager

        conv = conversation_manager.conversation_for_turn(user_id)
    except Exception:
        logger.debug("Studio canvas: no active conversation", exc_info=True)
        return None
    if not conv:
        return None
    messages = list(getattr(conv, "messages", None) or [])
    for message in reversed(messages):
        attachment = getattr(message, "attachment", None)
        if isinstance(message, dict):
            attachment = message.get("attachment")
        if not isinstance(attachment, dict):
            continue
        items = [attachment]
        extra = attachment.get("files")
        if isinstance(extra, list):
            items.extend(item for item in extra if isinstance(item, dict))
        for item in items:
            name = str(item.get("name") or "")
            url = str(item.get("url") or "")
            if not (
                item.get("canvas")
                or name.lower().endswith((".html", ".htm"))
                or url.lower().endswith((".html", ".htm"))
            ):
                continue
            try:
                path = conversation_manager._attachment_disk_path(item)
            except Exception:
                path = None
            if not path:
                continue
            candidate = Path(path)
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if _looks_like_html(text):
                return text
    return None


def fallback_html(user_text: str, kind: str, direction: dict[str, Any] | None = None) -> str:
    direction = direction or {}
    theme = direction.get("theme") or {}
    bg = theme.get("bg") or "#111111"
    surface = theme.get("surface") or "#1c1c1c"
    text = theme.get("text") or "#f4f0e8"
    muted = theme.get("muted") or "#9a9086"
    accent = theme.get("accent") or "#e0b56a"
    topic = (user_text or "Тема").strip()
    if len(topic) > 72:
        topic = topic[:71] + "…"
    safe_topic = html_lib.escape(topic)
    vibe = html_lib.escape(str(direction.get("vibe") or "editorial"))
    if kind == "slides":
        return ensure_slide_runtime(
            f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_topic}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Manrope:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:{bg};--surface:{surface};--text:{text};--muted:{muted};--accent:{accent};}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Manrope,sans-serif}}
.slide{{background:var(--bg)}}
.kicker{{letter-spacing:.22em;text-transform:uppercase;font-size:11px;color:var(--muted);margin:0 0 1rem}}
h1,h2{{font-family:Fraunces,Georgia,serif;font-weight:500;letter-spacing:-.03em;margin:0;line-height:1.05}}
h1{{font-size:clamp(2.2rem,7vw,5.4rem)}}
h2{{font-size:clamp(1.6rem,4vw,3rem)}}
p{{color:var(--muted);max-width:34ch;line-height:1.45}}
.rule{{width:3.5rem;height:2px;background:var(--accent);margin:1.4rem 0}}
</style>
</head>
<body>
<section class="slide"><div class="slide-inner">
<p class="kicker">{vibe}</p>
<h1>{safe_topic}</h1>
<div class="rule"></div>
<p>Первый кадр. Напишите в чате, что усилить: цвет, ритм, кадры.</p>
</div></section>
<section class="slide"><div class="slide-inner">
<p class="kicker">01</p>
<h2>Одна мысль на кадр</h2>
<div class="rule"></div>
<p>Дальше Студия допишет живой макет под ваш бриф, а не шаблон слайдов.</p>
</div></section>
<section class="slide"><div class="slide-inner">
<p class="kicker">Дальше</p>
<h2>Скажите, что поменять</h2>
</div></section>
</body></html>"""
        )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_topic}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Manrope:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:{bg};--surface:{surface};--text:{text};--muted:{muted};--accent:{accent};}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100dvh;background:var(--bg);color:var(--text);font-family:Manrope,sans-serif;display:flex;align-items:center;padding:8vw}}
main{{max-width:18rem}}
.kicker{{letter-spacing:.2em;text-transform:uppercase;font-size:11px;color:var(--muted)}}
h1{{font-family:Fraunces,Georgia,serif;font-size:clamp(2.4rem,8vw,4.8rem);line-height:.95;letter-spacing:-.04em;margin:.8rem 0 1.2rem;font-weight:600}}
p{{color:var(--muted);line-height:1.5;max-width:36ch}}
.bar{{width:3rem;height:2px;background:var(--accent);margin:1.2rem 0}}
</style>
</head>
<body>
<main>
<p class="kicker">{vibe}</p>
<h1>{safe_topic}</h1>
<div class="bar"></div>
<p>Черновик на холсте. Напишите, что собрать: лендинг, слайды, дашборд или инфографику.</p>
</main>
</body></html>"""


_SLIDE_BLOCK = re.compile(
    r"<(section|div)\b([^>]*\bclass\s*=\s*[\"'][^\"']*\bslide\b[^\"']*[\"'][^>]*)>([\s\S]*?)</\1>",
    re.I,
)


def slide_copy_lengths(html: str) -> list[int]:
    lengths: list[int] = []
    for match in _SLIDE_BLOCK.finditer(html or ""):
        chunk = match.group(3)
        text = re.sub(r"<style[\s\S]*?</style>", " ", chunk, flags=re.I)
        text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", html_lib.unescape(text)).strip()
        lengths.append(len(text))
    return lengths


def assert_slide_density(html: str, *, kind: str) -> None:
    if kind != "slides":
        return
    lengths = slide_copy_lengths(html)
    if len(lengths) < 4:
        raise ValueError("Нужно 6–10 слайдов с живым текстом. Сейчас мало кадров.")
    empty = [index for index, count in enumerate(lengths, 1) if count < 48]
    thin = [index for index, count in enumerate(lengths, 1) if count < 90]
    if empty or len(thin) > max(1, len(lengths) // 4):
        raise ValueError(
            "Есть пустые кадры. На каждом слайде нужен заголовок и 2–4 предложения "
            "или список фактов из ТЗ. Запрещены чёрный фон без текста, opacity:0 "
            "и анимация, без которой копирайт не виден."
        )


def prepare_artifact(html: str, *, kind: str = "landing") -> str:
    text = sanitize_html(extract_html(html) or html)
    if kind == "slides":
        text = ensure_slide_runtime(text)
    return text


async def fill_ai_images(html: str, user_id: int | None) -> tuple[str, int, str]:
    """Replace data-ai img tags with generated data URLs. Returns html, count, skip note."""
    prompts = collect_ai_image_prompts(html)
    if not prompts:
        return html, 0, ""
    if user_id:
        try:
            from app.billing.quota import assert_can_generate_image

            assert_can_generate_image(int(user_id))
        except Exception as exc:
            logger.info("Studio canvas images skipped: %s", exc)
            return html, 0, "картинки пропущены: лимит генерации"
    from openai_client import generate_image
    import asyncio

    mapping: dict[str, str] = {}
    sem = asyncio.Semaphore(2)
    quota_lock = asyncio.Lock()
    quota_ok = True

    async def _one(prompt: str) -> tuple[str, str] | None:
        nonlocal quota_ok
        if user_id:
            async with quota_lock:
                if not quota_ok:
                    return None
                try:
                    from app.billing.quota import assert_can_generate_image

                    assert_can_generate_image(int(user_id))
                except Exception:
                    quota_ok = False
                    return None
        async with sem:
            data_url, err = await generate_image(
                f"{prompt}. Photoreal or refined editorial still, no text letters logos watermarks, no purple neon.",
                size="1024x1024",
                quality="medium",
            )
        if not data_url or not data_url.startswith("data:image"):
            logger.warning("Canvas image failed: %s", err)
            return None
        if user_id:
            try:
                from app.billing.quota import debit_images

                debit_images(int(user_id), 1)
            except Exception:
                logger.exception("Failed to debit canvas image")
        return prompt, data_url

    results = await asyncio.gather(*[_one(prompt) for prompt in prompts], return_exceptions=True)
    for item in results:
        if isinstance(item, tuple) and len(item) == 2:
            mapping[item[0]] = item[1]
    return apply_ai_images(html, mapping), len(mapping), ""
