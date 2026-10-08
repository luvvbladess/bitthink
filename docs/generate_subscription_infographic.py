"""Customer-facing PDF. Run with ReportLab; values come from the live plan catalog."""
from pathlib import Path
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.billing.plans import PLAN_CATALOG, allowed_models

OUT = ROOT / "output" / "pdf" / "bitthink-tariffs.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)
FONT_DIR = Path("C:/Windows/Fonts")
for name, file in [("Regular", "segoeui.ttf"), ("Medium", "segoeuisb.ttf"), ("Bold", "segoeuib.ttf"), ("Light", "segoeuil.ttf")]:
    if not (FONT_DIR / file).exists():
        file = "segoeuib.ttf" if name in {"Medium", "Bold"} else "segoeui.ttf"
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
pdfmetrics.registerFontFamily("Regular", normal="Regular", bold="Bold", italic="Regular", boldItalic="Bold")

W, H = A4
M = 38
CW = W - M * 2
INK = colors.HexColor("#102C3A")
MUTED = colors.HexColor("#607682")
CYAN = colors.HexColor("#219FCD")
PALE = colors.HexColor("#EAF5FA")
PAPER = colors.HexColor("#F5F8FA")
LINE = colors.HexColor("#D8E4EA")
WHITE = colors.white

c = canvas.Canvas(str(OUT), pagesize=A4, pageCompression=1)
c.setTitle("Bit-Think: тарифы и возможности")
c.setAuthor("Bit-Think")
c.setSubject("Pro, Pro+, Ultra и Базовый: цены, модели и лимиты")


def text(s, x, top, size=11, font="Regular", color=INK, align="left"):
    c.setFillColor(color)
    c.setFont(font, size)
    baseline = H - top - size * .78
    fn = c.drawRightString if align == "right" else c.drawCentredString if align == "center" else c.drawString
    fn(x, baseline, s)


def rule(x1, x2, top, color=LINE, width=.6):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(x1, H - top, x2, H - top)


def box(x, top, w, h, fill=WHITE, stroke=None, radius=12):
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.setLineWidth(.6)
    c.roundRect(x, H - top - h, w, h, radius, fill=1, stroke=bool(stroke))


def para(s, x, top, w, size=10, color=MUTED, leading=None, font="Regular"):
    style = ParagraphStyle("body", fontName=font, fontSize=size, leading=leading or size * 1.45, textColor=color)
    p = Paragraph(s, style)
    _, h = p.wrap(w, H)
    p.drawOn(c, x, H - top - h)
    return h


def check(x, top, enabled=True):
    if not enabled:
        rule(x - 4, x + 4, top + 5, MUTED, 1)
        return
    c.setStrokeColor(CYAN)
    c.setLineWidth(1.7)
    p = c.beginPath()
    p.moveTo(x - 5, H - top - 5)
    p.lineTo(x - 1, H - top - 9)
    p.lineTo(x + 6, H - top - 1)
    c.drawPath(p)


def rub(v):
    return f"{v:,}".replace(",", " ") + " ₽"


def millions(v):
    return f"{v / 1_000_000:g}".replace(".", ",") + " млн"


def header(page):
    c.setFillColor(PAPER if page == 1 else WHITE)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.drawImage(str(ROOT / "logo medium.png"), M, H - 68, width=33, height=32, mask="auto")
    text("Bit-Think", M + 44, 40, 22, "Medium")
    text("ТАРИФЫ 2026", W - M, 46, 9, "Medium", CYAN, "right")
    rule(M, W - M, 84)


def footer(page):
    rule(M, W - M, 809)
    text("Цены и условия на 08.10.2026", M, 820, 8.2, color=MUTED)
    text(f"{page} / 2", W - M, 820, 8.2, color=MUTED, align="right")


def plan_card(tier, top, dark=False):
    p = PLAN_CATALOG[tier]
    bg = INK if dark else WHITE
    fg = WHITE if dark else INK
    secondary = colors.HexColor("#BDD4DF") if dark else MUTED
    box(M, top, CW, 143, bg, None if dark else LINE)
    c.setFillColor(CYAN)
    c.roundRect(M, H - top - 143, 4, 143, 2, fill=1, stroke=0)
    text(p["name"], M + 19, top + 16, 22, "Medium", fg)
    price = rub(p["price_rub"])
    text(price, M + 19, top + 54, 25, "Bold", fg)
    price_w = pdfmetrics.stringWidth(price, "Bold", 25)
    text("/ месяц", M + 25 + price_w, top + 65, 8.7, color=secondary)
    text(rub(p["price_year_rub"]) + " / год", M + 19, top + 92, 10, color=secondary)
    captions = {"pro": "На каждый день", "proplus": "Для сложных задач", "ultra": "Для интенсивной работы"}
    text(captions[tier], M + 19, top + 122, 9, color=secondary)
    split = M + 182
    c.setStrokeColor(colors.HexColor("#37505E") if dark else LINE)
    c.setLineWidth(.6)
    c.line(split, H - top - 18, split, H - top - 126)
    start = split + 20
    metric_w = (CW - 220) / 3
    for i, (label, value) in enumerate([
        ("Чат", millions(p["chat_tokens"])),
        ("Оркестратор", millions(p["computer_tokens"])),
        ("Изображения", str(p["images"])),
    ]):
        x = start + i * metric_w
        text(label, x, top + 23, 9.3, color=secondary)
        text(value, x, top + 45, 22, "Medium", fg)
    rule(start, W - M - 20, top + 82, colors.HexColor("#37505E") if dark else LINE)
    model_line = {
        "pro": "GPT-6.1 Sol + Исследование",
        "proplus": "GPT-6 Astra + всё из Pro",
        "ultra": "Sol, Astra и самые большие лимиты",
    }
    text(model_line[tier], start, top + 95, 11.6, "Medium", WHITE if dark else CYAN)
    text("Поиск с источниками · файлы · Студия", start, top + 118, 9.4, color=secondary)


header(1)
text("Больше возможностей.", M, 105, 32, "Medium")
text("Ваш масштаб.", M, 145, 32, "Medium", CYAN)
text("Сильные модели и рабочие инструменты в одном чате.", M, 191, 11, color=MUTED)
text("Бюджеты указаны в единицах. Правила расхода - на странице 2.", M, 207, 8.4, color=MUTED)
plan_card("pro", 222)
plan_card("proplus", 378, dark=True)
plan_card("ultra", 534)

box(M, 693, CW, 76, PALE)
text("Базовый", M + 19, 708, 16, "Medium")
text("Бесплатно", W - M - 19, 711, 12, "Medium", CYAN, "right")
text("30 ответов в день  ·  5 поисков в день  ·  3 изображения в месяц", M + 19, 738, 10.2)
text("Подключение тарифов - через администратора.", M, 785, 8.5, color=MUTED)
text("bit-think.space", W - M, 784, 10, "Medium", CYAN, "right")
c.linkURL("https://bit-think.space", (W - M - 82, H - 798, W - M, H - 780), relative=0)
footer(1)
c.showPage()

header(2)
text("Что входит в тариф", M, 107, 27, "Medium")
text("Общие модели платных планов: Nano · Luna · Kimi · DeepSeek", M, 145, 9.8, color=MUTED)

tiers = ["free", "pro", "proplus", "ultra"]
label_w = 219
value_w = (CW - label_w) / 4
table_top = 173
box(M, table_top, CW, 40, INK, radius=8)
text("Возможность", M + 14, table_top + 14, 10.2, "Medium", WHITE)
for i, tier in enumerate(tiers):
    text(PLAN_CATALOG[tier]["name"], M + label_w + value_w * (i + .5), table_top + 14,
         10.2 if tier == "free" else 12, "Medium", WHITE, "center")

rows = [
    ("Чат / месяц", ["30 / день"] + [millions(PLAN_CATALOG[t]["chat_tokens"]) for t in tiers[1:]]),
    ("Оркестратор / месяц", [None] + [millions(PLAN_CATALOG[t]["computer_tokens"]) for t in tiers[1:]]),
    ("Изображения / месяц", [str(PLAN_CATALOG[t]["images"]) for t in tiers]),
    ("GPT-6.1 Sol и Исследование", ["gpt-6-sol" in allowed_models(t) for t in tiers]),
    ("GPT-6 Astra", ["gpt-6-astra" in allowed_models(t) for t in tiers]),
    ("Студия", ["studio" in allowed_models(t) for t in tiers]),
    ("Поиск с источниками", ["5 / день", "Да", "Да", "Да"]),
    ("Отдельный режим «Документы»", ["docgen" in allowed_models(t) for t in tiers]),
    ("Безлимит", [False, False, False, False]),
]
row_h = 26
for r, (label, vals) in enumerate(rows):
    y = table_top + 40 + r * row_h
    if r % 2 == 0:
        c.setFillColor(PAPER)
        c.rect(M, H - y - row_h, CW, row_h, stroke=0, fill=1)
    text(label, M + 14, y + 8, 10)
    for i, val in enumerate(vals):
        x = M + label_w + value_w * (i + .5)
        if val is None or isinstance(val, bool):
            check(x, y + 7, bool(val))
        else:
            text(val, x, y + 8, 10, "Medium", INK, "center")

text("Как расходуется лимит", M, 466, 17, "Medium")
para("Миллионы в тарифах - внутренние <b>единицы бюджета</b>. Дорогие модели расходуют их быстрее: "
     "Luna и Nano ×1, Kimi ×9, DeepSeek Pro ×9 / Flash ×2, Sol ×20, Astra ×100. "
     "Вход, ответ и контекст входят в расход; кэш может уменьшать списание. "
     "Для чата и Оркестратора предусмотрены отдельные кошельки.",
     M, 492, CW, 10.2, MUTED, 14.4)

text("Окна использования", M, 570, 17, "Medium")
text("Месячные квоты дополнительно ограничены окнами на 5 часов и неделю.", M, 596, 9.5, color=MUTED)
window_top = 619
rule(M, W - M, window_top)
for i, tier in enumerate(tiers[1:]):
    x = M + 219 + ((CW - 219) / 3) * (i + .5)
    text(PLAN_CATALOG[tier]["name"], x, window_top + 9, 10, "Medium", CYAN, "center")
window_rows = [("Чат / 5 часов", "chat_session"), ("Чат / неделя", "chat_week"),
               ("Оркестратор / 5 часов", "computer_session"), ("Оркестратор / неделя", "computer_week")]
for r, (label, key) in enumerate(window_rows):
    y = window_top + 29 + r * 21
    text(label, M, y, 9.5, color=MUTED)
    for i, tier in enumerate(tiers[1:]):
        x = M + 219 + ((CW - 219) / 3) * (i + .5)
        text(millions(PLAN_CATALOG[tier][key]), x, y, 10, "Medium", INK, "center")
rule(M, W - M, 733)
para("Лимиты обновляются по московскому времени. Месячный бюджет - по календарному месяцу, "
     "недельный - в понедельник. Остатки не переносятся. Квота изображений общая для генерации и правок. "
     "Работа с файлами в чате входит в платные тарифы; отдельный режим «Документы» и безлимит в них не входят.",
     M, 746, CW, 9.2, MUTED, 13.2)
footer(2)
c.save()
print(OUT)
