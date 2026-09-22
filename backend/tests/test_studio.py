import re
import zipfile
from io import BytesIO

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from studio.build import build_studio_artifact
from studio.images import collect_image_jobs
from studio.quality import prune_weak_slides, wants_minimal
from studio.schema import StudioSpecError, normalize_deck, normalize_spec


def test_deck_schema_rejects_unknown_layout():
    try:
        normalize_deck({"theme_id": "quiet_teal", "slides": [{"layout_id": "neon_glass", "title": "x"}]})
        assert False, "expected error"
    except StudioSpecError as exc:
        assert "layout" in str(exc).lower() or "layout_id" in str(exc).lower()


def test_rejects_empty_two_column_placeholders():
    try:
        normalize_deck(
            {
                "theme_id": "quiet_teal",
                "slides": [
                    {
                        "layout_id": "two_column",
                        "title": "Стек",
                        "left_title": "Слева",
                        "right_title": "Справа",
                        "left_body": "",
                        "right_body": "",
                    }
                ],
            }
        )
        assert False, "expected error"
    except StudioSpecError:
        pass


def test_rejects_empty_comparison():
    try:
        normalize_deck(
            {
                "theme_id": "quiet_teal",
                "slides": [
                    {
                        "layout_id": "comparison",
                        "title": "Подходы",
                        "left_label": "A",
                        "right_label": "B",
                        "left_items": [],
                        "right_items": [],
                    }
                ],
            }
        )
        assert False, "expected error"
    except StudioSpecError:
        pass


def test_prune_weak_and_minimal():
    assert wants_minimal("\u0441\u0434\u0435\u043b\u0430\u0439 \u0441\u0442\u0438\u043b\u044c\u043d\u0443\u044e \u043f\u0440\u0435\u0437\u0435\u043d\u0442\u0430\u0446\u0438\u044e \u0431\u0435\u0437 \u043b\u0438\u0448\u043d\u0435\u0433\u043e \u0442\u0435\u043a\u0441\u0442\u0430")
    assert wants_minimal("stylish minimal deck without fluff")
    spec = {
        "kind": "deck",
        "theme_id": "quiet_teal",
        "title": "t",
        "slides": [
            {"layout_id": "title", "title": "Python Backend", "subtitle": "x", "footer": ""},
            {"layout_id": "section", "title": "Section", "subtitle": "", "eyebrow": ""},
            {
                "layout_id": "two_column",
                "title": "Stack",
                "left_title": "\u0421\u043b\u0435\u0432\u0430",
                "left_body": "",
                "right_title": "\u0421\u043f\u0440\u0430\u0432\u0430",
                "right_body": "",
            },
            {
                "layout_id": "bullets_focus",
                "title": "Key",
                "bullets": ["FastAPI", "Postgres", "Redis"],
            },
            {"layout_id": "closing", "title": "Next", "subtitle": "", "cta": ""},
        ],
    }
    pruned = prune_weak_slides(spec, max_slides=8)
    layouts = [s["layout_id"] for s in pruned["slides"]]
    assert "section" not in layouts
    assert "two_column" not in layouts
    assert "bullets_focus" in layouts


def test_deck_render_smoke():
    spec = normalize_spec(
        {
            "kind": "deck",
            "theme_id": "quiet_teal",
            "title": "Smoke Deck",
            "slides": [
                {"layout_id": "title", "title": "Заголовок", "subtitle": "Подзаголовок", "footer": "Bit-Think"},
                {
                    "layout_id": "bullets_focus",
                    "title": "Пункты",
                    "bullets": ["Один", "Два", "Три"],
                },
                {"layout_id": "closing", "title": "Итог", "subtitle": "Дальше", "cta": "Скачать"},
            ],
        }
    )
    files = build_studio_artifact(spec, with_previews=True)
    assert files
    pptx = next(item for item in files if str(item["filename"]).endswith(".pptx"))
    assert len(pptx["bytes"]) > 10_000
    with zipfile.ZipFile(BytesIO(pptx["bytes"])) as archive:
        assert any(name.startswith("ppt/slides/") for name in archive.namelist())


def test_board_render_smoke():
    spec = normalize_spec(
        {
            "kind": "infographic",
            "theme_id": "clean_light",
            "layout_id": "kpi_strip",
            "orientation": "landscape",
            "headline": "Метрики квартала",
            "subhead": "Короткий кадр",
            "footnote": "внутренние данные",
            "kpis": [
                {"value": "18%", "label": "Рост выручки"},
                {"value": "42", "label": "Новых клиентов"},
                {"value": "4.8", "label": "NPS"},
            ],
        }
    )
    files = build_studio_artifact(spec)
    assert len(files) == 1
    assert files[0]["filename"].endswith(".png")
    assert len(files[0]["bytes"]) > 10_000
    assert files[0]["bytes"][:8] == b"\x89PNG\r\n\x1a\n"


def test_composed_deck_and_image_jobs():
    raw = {
        "kind": "deck",
        "theme_id": "quiet_teal",
        "title": "Composed",
        "slides": [
            {
                "layout_id": "visual",
                "title": "Hero",
                "subtitle": "Mood",
                "image_prompt": "editorial abstract teal geometry, no text",
            },
            {
                "layout_id": "composed",
                "elements": [
                    {"type": "text", "x": 8, "y": 12, "w": 50, "h": 18, "style": "display", "text": "Свой шаблон"},
                    {"type": "bullets", "x": 8, "y": 40, "w": 40, "h": 40, "items": ["А", "Б", "В"]},
                    {"type": "image", "x": 55, "y": 20, "w": 38, "h": 60, "prompt": "clean desk product photo mood"},
                ],
            },
        ],
    }
    spec = normalize_spec(raw)
    jobs = collect_image_jobs(spec)
    assert len(jobs) == 2
    assert jobs[0][0] == "slide-0"
    files = build_studio_artifact(spec, with_previews=False, already_normalized=True)
    assert any(str(item["filename"]).endswith(".pptx") for item in files)


def test_composed_board_render():
    spec = normalize_spec(
        {
            "kind": "infographic",
            "theme_id": "data_dark",
            "layout_id": "composed",
            "orientation": "landscape",
            "headline": "Board",
            "elements": [
                {"type": "text", "x": 6, "y": 8, "w": 70, "h": 12, "style": "display", "text": "Свой кадр"},
                {"type": "card", "x": 6, "y": 30, "w": 40, "h": 40, "title": "Блок", "body": "Короткий текст"},
                {"type": "accent_bar", "x": 0, "y": 0, "w": 1, "h": 100, "fill": "accent"},
            ],
        }
    )
    files = build_studio_artifact(spec, already_normalized=True)
    assert files[0]["bytes"][:8] == b"\x89PNG\r\n\x1a\n"


def test_statement_stack_render():
    spec = normalize_spec(
        {
            "kind": "deck",
            "theme_id": "noir",
            "title": "Stylish",
            "slides": [
                {
                    "layout_id": "statement",
                    "title": "Backend is the contract between clients, data, and latency.",
                },
                {
                    "layout_id": "stack",
                    "title": "Stack",
                    "items": ["FastAPI", "Postgres", "Redis", "Docker"],
                },
                {"layout_id": "closing", "title": "Next", "subtitle": "Ship", "cta": "Go"},
            ],
        }
    )
    files = build_studio_artifact(spec, with_previews=False)
    assert any(str(item["filename"]).endswith(".pptx") for item in files)


def test_meta_cta_stripped():
    from studio.quality import is_meta_cta, sanitize_closing_slide

    assert is_meta_cta("\u041e\u043f\u0438\u0448\u0438\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443")
    assert is_meta_cta("\u041d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0434\u0435\u0442\u0430\u043b\u0438 \u0432 \u0447\u0430\u0442")
    assert not is_meta_cta("First endpoint this sprint")
    slide = sanitize_closing_slide(
        {
            "layout_id": "closing",
            "title": "Go",
            "subtitle": "Ship",
            "cta": "\u041e\u043f\u0438\u0448\u0438\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443",
        }
    )
    assert "cta" not in slide
    spec = normalize_spec(
        {
            "kind": "deck",
            "theme_id": "noir",
            "title": "t",
            "slides": [
                {"layout_id": "title", "title": "T", "subtitle": "", "footer": ""},
                {
                    "layout_id": "closing",
                    "title": "Next",
                    "subtitle": "Ship",
                    "cta": "\u041e\u043f\u0438\u0448\u0438\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443",
                },
            ],
        }
    )
    assert "cta" not in spec["slides"][-1]


def test_studio_in_plans():
    from app.billing.plans import allowed_models, clamp_model

    assert "studio" not in allowed_models("free")
    assert "studio" in allowed_models("pro")
    assert clamp_model("free", "studio") == "gpt-6-luna"
    assert clamp_model("pro", "studio") == "studio"


def test_direction_varies_and_clarify_is_thin_only():
    from studio.direction import brief_is_thin, pick_direction
    from studio_router import _needs_clarify

    coffee = pick_direction("сделай слайды про кофейню в центре")
    assert coffee["theme"]["bg"].startswith("#")
    assert coffee["vibe"]
    data = pick_direction("kpi отчёт банка за квартал")
    assert data["theme_id"] == "data_dark"
    assert not brief_is_thin("слайды про кофейню")
    assert not _needs_clarify("слайды про кофейню")
    assert _needs_clarify("сделай презентацию")
    assert _needs_clarify("инфографика")
    packed = (
        "Пользователь предоставил документ для контекста: ТЗ.docx\n\nСодержание:\n"
        + ("Структура питча, аудитория, оффер и три доказательства. " * 8)
    )
    assert not _needs_clarify("сделай презентацию", packed)
    assert not _needs_clarify("сделай презентацию", has_files=True)
    assert not _needs_clarify("сделай презентацию", history_text="x" * 400)
    short_doc = "Пользователь предоставил документ для контекста: ТЗ.docx\n\nСодержание:\n" + ("питч " * 20)
    assert not _needs_clarify("сделай презентацию", short_doc)


def test_poster_mosaic_metric_and_new_composed_elements():
    spec = normalize_spec(
        {
            "kind": "deck",
            "theme_id": "custom",
            "theme": {
                "bg": "#1A0C10",
                "surface": "#26141A",
                "text": "#F7EFE8",
                "muted": "#B59A90",
                "accent": "#E0B56A",
                "line": "#3A2228",
                "title_font": "Georgia",
            },
            "title": "Кофейня",
            "slides": [
                {
                    "layout_id": "poster",
                    "title": "Утро на Петровке",
                    "subtitle": "Зерно, пар, очередь",
                    "anchor": "bottom-left",
                    "image_prompt": "espresso bar morning steam, no text",
                },
                {
                    "layout_id": "mosaic",
                    "title": "Три кадра",
                    "tiles": [
                        {"image_prompt": "coffee bean macro, no text", "caption": "Зерно"},
                        {"image_prompt": "cup on oak table, no text", "caption": "Чашка"},
                    ],
                },
                {
                    "layout_id": "metric_row",
                    "title": "Ориентир запуска",
                    "kpis": [
                        {"value": "40", "label": "посадочных"},
                        {"value": "7–11", "label": "часы пик"},
                    ],
                },
                {
                    "layout_id": "composed",
                    "elements": [
                        {"type": "ellipse", "x": 70, "y": 10, "w": 18, "h": 24, "fill": "accent"},
                        {"type": "number", "x": 8, "y": 20, "w": 30, "h": 20, "text": "01"},
                        {"type": "text", "x": 8, "y": 48, "w": 50, "h": 20, "style": "display", "text": "Свой ритм"},
                        {"type": "rule", "x": 8, "y": 44, "w": 12, "h": 1, "fill": "accent"},
                    ],
                },
            ],
        }
    )
    layouts = [s["layout_id"] for s in spec["slides"]]
    assert layouts == ["poster", "mosaic", "metric_row", "composed"]
    jobs = collect_image_jobs(spec)
    assert any(job_id == "slide-0" for job_id, _ in jobs)
    assert any("tile" in job_id for job_id, _ in jobs)
    files = build_studio_artifact(spec, with_previews=True, already_normalized=True)
    assert any(str(item["filename"]).endswith(".pptx") for item in files)
    previews = [item for item in files if str(item["filename"]).startswith("preview-")]
    assert previews
    assert all(item["bytes"][:8] == b"\x89PNG\r\n\x1a\n" for item in previews)


def test_html_canvas_extract_sanitize_and_kind():
    from studio.html_canvas import (
        apply_ai_images,
        collect_ai_image_prompts,
        detect_kind,
        ensure_slide_runtime,
        extract_html,
        fallback_html,
        prepare_artifact,
        sanitize_html,
        should_iterate,
        title_from_html,
        wants_pptx_file,
    )

    fenced = extract_html("ok\n```html\n<!DOCTYPE html><html><head><title>Кофе</title></head><body><h1>Кофе</h1></body></html>\n```")
    assert fenced and "<html" in fenced.lower()
    assert title_from_html(fenced) == "Кофе"
    dirty = sanitize_html('<html><body><script src="https://evil.example/x.js"></script><script src=https://evil.example/y.js></script><a href="javascript:alert(1)">x</a><img data-ai="steam espresso" alt="bar"></body></html>')
    assert "evil.example" not in dirty
    assert "javascript:" not in dirty.lower()
    assert detect_kind("слайды про кофейню") == "slides"
    assert detect_kind("сделай презентацию") == "slides"
    assert detect_kind("лендинг кофейни") == "landing"
    assert detect_kind("дашборд подписки") == "dashboard"
    assert detect_kind("инфографика путь зерна") == "infographic"
    assert detect_kind("нарисуй рыжего кота на крыше") == "image"
    assert detect_kind("сделай картинку заката над морем") == "image"
    assert detect_kind("нарисуй инфографику пути зерна") == "infographic"
    assert wants_pptx_file("скачай powerpoint про кофейню")
    assert not wants_pptx_file("слайды про кофейню")
    prev = "<!DOCTYPE html><html><body><section class='slide'>x</section></body></html>"
    assert should_iterate("сделай шапку темнее", prev)
    assert not should_iterate("сделай с нуля лендинг чая", prev)
    assert not should_iterate("сделай шапку темнее", "")
    html = prepare_artifact(
        '<section class="slide"><div class="slide-inner"><h1>Hi</h1></div></section>',
        kind="slides",
    )
    assert 'class="slide"' in html
    with_nav = ensure_slide_runtime(
        '<html><body><section class="slide">a</section><section class="slide">b</section>'
        '<script>window.evilNav=1</script></body></html>'
    )
    assert "data-studio-nav" in with_nav
    assert "scroll-snap-type:y" not in with_nav
    assert "overflow:hidden" in with_nav
    assert "evilNav" not in with_nav
    assert with_nav.lower().count("<script") == 1
    slide_rule = re.search(r"\.slide\{([^}]+)\}", with_nav)
    assert slide_rule and "display:flex" not in slide_rule.group(1)
    from studio.html_canvas import (
        image_canvas_html,
        is_image_canvas,
        extract_embedded_image_bytes,
        resolve_studio_job,
    )
    picture = image_canvas_html("data:image/png;base64,QQ==", "Кот")
    assert is_image_canvas(picture)
    assert extract_embedded_image_bytes(picture) == b"A"
    landing = "<!DOCTYPE html><html><body><h1>Сайт</h1></body></html>"
    kind, prev, iterating = resolve_studio_job("темнее", picture)
    assert kind == "image" and iterating and prev == picture
    kind, prev, iterating = resolve_studio_job("сделай слайды про кофе", picture)
    assert kind == "slides" and not iterating and prev == ""
    kind, prev, iterating = resolve_studio_job("лендинг кофейни", picture)
    assert kind == "landing" and not iterating and prev == ""
    kind, prev, iterating = resolve_studio_job("нарисуй рыжего кота", landing)
    assert kind == "image" and not iterating and prev == ""
    kind, prev, iterating = resolve_studio_job("сделай шапку темнее", landing)
    assert kind == "landing" and iterating and prev == landing
    prompts = collect_ai_image_prompts('<img data-ai="steam espresso bar, no text" alt="x">')
    assert prompts == ["steam espresso bar, no text"]
    filled = apply_ai_images('<img data-ai="steam espresso bar, no text" alt="x">', {"steam espresso bar, no text": "data:image/png;base64,aaa"})
    assert 'src="data:image/png;base64,aaa"' in filled
    fb = fallback_html("кофейня", "slides", {"vibe": "editorial paper", "theme": {"bg": "#111", "text": "#eee", "accent": "#c00"}})
    assert "slide" in fb and "кофейня" in fb


def test_studio_reads_style_sample_and_rejects_empty_slides():
    from studio.briefing import attached_deck_sample, format_studio_documents, theme_from_documents, wants_slides_from_documents
    from studio.html_canvas import assert_slide_density
    from studio.pptx_style import extract_pptx_visual_brief

    packed = (
        "Пользователь предоставил документ для контекста: пример_BITSHIP.pptx\n\nСодержание:\n"
        "--- Визуальный стиль образца ---\nФон: #F7F6F3\nТекст: #111111\nАкцент: #C45C26\n"
        "Шрифт заголовков: Segoe UI\n\n--- Слайд 1 ---\nТитул\n\n"
        "Пользователь предоставил документ для контекста: ТЗ_питч.docx\n\nСодержание:\n"
        "Слайд 1: оффер. Слайд 2: рынок. Слайд 3: продукт."
    )
    formatted = format_studio_documents(packed)
    assert "ОБРАЗЕЦ СТИЛЯ" in formatted
    assert "ТЗ / СОДЕРЖАНИЕ" in formatted
    assert attached_deck_sample(packed)
    theme = theme_from_documents(packed)
    assert theme and theme["bg"] == "#F7F6F3" and theme["accent"] == "#C45C26"

    pdf_pair = (
        "Пользователь предоставил документ для контекста: Импакт про 2.pdf\n\nСодержание:\n"
        "Тёмный фон, тонкая инженерная сетка, акцент electric blue.\n\n"
        "Пользователь предоставил документ для контекста: Битшип_Абхазия.docx\n\nСодержание:\n"
        "Слайд 1: ГЭС. Слайд 2: СЭС. Три направления – одна стратегия."
    )
    pdf_formatted = format_studio_documents(pdf_pair)
    assert "ОБРАЗЕЦ СТИЛЯ" in pdf_formatted
    assert "Импакт про" in pdf_formatted
    assert "ТЗ / СОДЕРЖАНИЕ" in pdf_formatted
    assert attached_deck_sample(pdf_pair)
    assert wants_slides_from_documents(pdf_pair)

    empty = """<!DOCTYPE html><html><body>
    <section class="slide"><h1>Титул</h1><p>Есть текст на первом кадре и ещё немного фактов.</p></section>
    <section class="slide"></section>
    <section class="slide"><h2>x</h2></section>
    <section class="slide"><h2>y</h2></section>
    </body></html>"""
    try:
        assert_slide_density(empty, kind="slides")
        assert False, "expected empty slides to fail"
    except ValueError as exc:
        assert "пустые" in str(exc).lower() or "кадр" in str(exc).lower()

    dense = "".join(
        f'<section class="slide"><h1>Кадр {i}</h1>'
        f"<p>Факт из ТЗ номер {i}: рынок, оффер и следующий шаг для зрителя.</p>"
        f"<p>Вторая мысль, чтобы кадр не был постером без копирайта.</p></section>"
        for i in range(1, 7)
    )
    assert_slide_density(f"<!DOCTYPE html><html><body>{dense}</body></html>", kind="slides")

    import zipfile
    from io import BytesIO
    from xml.etree.ElementTree import Element, SubElement, tostring

    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    theme = Element(f"{{{ns}}}theme")
    elements = SubElement(theme, f"{{{ns}}}themeElements")
    scheme = SubElement(elements, f"{{{ns}}}clrScheme", {"name": "Bitship"})
    for name, hex_value in (("dk1", "1A1A1A"), ("lt1", "FFFFFF"), ("dk2", "111111"), ("accent1", "C45C26")):
        node = SubElement(scheme, f"{{{ns}}}{name}")
        SubElement(node, f"{{{ns}}}srgbClr", {"val": hex_value})
    fonts = SubElement(elements, f"{{{ns}}}fontScheme", {"name": "Bitship"})
    major = SubElement(fonts, f"{{{ns}}}majorFont")
    SubElement(major, f"{{{ns}}}latin", {"typeface": "Segoe UI"})
    minor = SubElement(fonts, f"{{{ns}}}minorFont")
    SubElement(minor, f"{{{ns}}}latin", {"typeface": "Calibri"})
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("ppt/theme/theme1.xml", tostring(theme))
        archive.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><a:t>Оффер</a:t></p:sld>")
    brief = extract_pptx_visual_brief(buf.getvalue())
    assert "Фон: #1A1A1A" in brief
    assert "Акцент: #C45C26" in brief
    assert "Segoe UI" in brief


def test_infographic_composed_default_fallback_shape():
    from studio_router import _fallback_board

    board = normalize_spec(_fallback_board("путь зерна", "noir"))
    assert board["layout_id"] == "composed"
    assert board.get("theme")
    assert len(board["elements"]) >= 2


def test_studio_does_not_spend_astra_on_canvas():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "bot_core" / "studio_router.py").read_text(encoding="utf-8")
    assert "gpt-6-astra" not in source
    assert '"gpt-6-sol"' in source
