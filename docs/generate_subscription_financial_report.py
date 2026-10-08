"""Build an internal Bit-Think subscription economics report."""
from pathlib import Path
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, Flowable,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.billing.plans import PLAN_CATALOG

OUT = ROOT / "output" / "pdf" / "bitthink-subscription-economics-2026-10-08.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

FONT_DIR = Path("C:/Windows/Fonts")
for name, file in [("BT-Regular", "segoeui.ttf"), ("BT-Medium", "segoeuisl.ttf"), ("BT-Bold", "segoeuib.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
pdfmetrics.registerFontFamily("BT-Regular", normal="BT-Regular", bold="BT-Bold", italic="BT-Regular", boldItalic="BT-Bold")

W, H = A4
NAVY = colors.HexColor("#102C3A")
CYAN = colors.HexColor("#159FCB")
MUTED = colors.HexColor("#627985")
PALE = colors.HexColor("#EAF5FA")
PAPER = colors.HexColor("#F4F8FA")
LINE = colors.HexColor("#D7E3E9")
WHITE = colors.white
GREEN = colors.HexColor("#167A68")
RED = colors.HexColor("#B44E50")

FX = 85.4811  # CBR RUB/USD rate dated 2026-10-08, as recorded in the audit.
FEE = 0.085   # Planning assumption only; live checkout is not enabled.
SERVER = 400  # One shared monthly cost for the entire application.
INPUT_SHARE = 0.8
OUTPUT_SHARE = 0.2
GPT_RATES = {"input": 0.10, "output": 0.50}  # GPT-6 Luna standard, USD / 1M tokens.
PLANS = ["pro", "proplus", "ultra"]


def rub(value, decimals=0):
    n = f"{value:,.{decimals}f}".replace(",", " ")
    return n + " ₽"


def nfmt(value, decimals=0):
    return f"{value:,.{decimals}f}".replace(",", " ")


def money_cost(units_m, output_share=OUTPUT_SHARE):
    usd_per_m = GPT_RATES["input"] * (1 - output_share) + GPT_RATES["output"] * output_share
    return units_m * usd_per_m * FX


def plan_data(tier):
    p = PLAN_CATALOG[tier]
    units_m = (p["chat_tokens"] + p["computer_tokens"]) / 1_000_000
    monthly_cost = money_cost(units_m)
    month_net = p["price_rub"] * (1 - FEE)
    year_net_month = p["price_year_rub"] / 12 * (1 - FEE)
    return {
        **p,
        "units_m": units_m,
        "monthly_cost": monthly_cost,
        "month_net": month_net,
        "month_contribution": month_net - monthly_cost,
        "year_net_month": year_net_month,
        "year_contribution": year_net_month - monthly_cost,
        "cost_50": money_cost(units_m, 0.5),
        "cost_output": money_cost(units_m, 1.0),
    }


DATA = {p: plan_data(p) for p in PLANS}


def styles():
    return {
        "title": ParagraphStyle("title", fontName="BT-Medium", fontSize=27, leading=32, textColor=NAVY, spaceAfter=5),
        "subtitle": ParagraphStyle("subtitle", fontName="BT-Regular", fontSize=10, leading=15, textColor=MUTED),
        "h1": ParagraphStyle("h1", fontName="BT-Medium", fontSize=19, leading=24, textColor=NAVY, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName="BT-Medium", fontSize=12, leading=16, textColor=NAVY, spaceBefore=3, spaceAfter=5),
        "body": ParagraphStyle("body", fontName="BT-Regular", fontSize=9.3, leading=13.5, textColor=NAVY),
        "small": ParagraphStyle("small", fontName="BT-Regular", fontSize=7.8, leading=10.5, textColor=MUTED),
        "tiny": ParagraphStyle("tiny", fontName="BT-Regular", fontSize=7.0, leading=9.2, textColor=MUTED),
        "cardlabel": ParagraphStyle("cardlabel", fontName="BT-Regular", fontSize=8, leading=11, textColor=MUTED),
        "cardvalue": ParagraphStyle("cardvalue", fontName="BT-Bold", fontSize=18, leading=22, textColor=NAVY),
        "cell": ParagraphStyle("cell", fontName="BT-Regular", fontSize=8, leading=10.5, textColor=NAVY),
        "cellbold": ParagraphStyle("cellbold", fontName="BT-Medium", fontSize=8.2, leading=10.5, textColor=NAVY),
        "source": ParagraphStyle("source", fontName="BT-Regular", fontSize=7.4, leading=10.2, textColor=MUTED, splitLongWords=True),
    }


S = styles()


class KpiRow(Flowable):
    def __init__(self, cards, height=66):
        super().__init__()
        self.cards = cards
        self.height = height

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return availWidth, self.height

    def draw(self):
        gap = 8
        cw = (self.width - gap * (len(self.cards) - 1)) / len(self.cards)
        for i, (label, value, note) in enumerate(self.cards):
            x = i * (cw + gap)
            self.canv.setFillColor(PAPER if i else PALE)
            self.canv.roundRect(x, 0, cw, self.height, 9, fill=1, stroke=0)
            self.canv.setFillColor(MUTED)
            self.canv.setFont("BT-Regular", 7.5)
            self.canv.drawString(x + 11, self.height - 16, label)
            self.canv.setFillColor(NAVY)
            self.canv.setFont("BT-Bold", 15)
            self.canv.drawString(x + 11, self.height - 37, value)
            self.canv.setFillColor(MUTED)
            self.canv.setFont("BT-Regular", 6.8)
            self.canv.drawString(x + 11, 9, note)


class MarginBars(Flowable):
    def __init__(self, width=480, height=115):
        super().__init__()
        self.width, self.height = width, height

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return self.width, self.height

    def draw(self):
        labels = [("Pro", DATA["pro"]), ("Pro+", DATA["proplus"]), ("Ultra", DATA["ultra"])]
        left, top, bar_w, gap = 58, self.height - 17, self.width - 155, 31
        maxval = max(d["month_net"] for _, d in labels)
        for i, (label, d) in enumerate(labels):
            y = top - i * gap
            self.canv.setFillColor(MUTED)
            self.canv.setFont("BT-Medium", 8)
            self.canv.drawRightString(left - 9, y + 2, label)
            self.canv.setFillColor(PALE)
            self.canv.roundRect(left, y - 2, bar_w, 14, 6, fill=1, stroke=0)
            self.canv.setFillColor(CYAN)
            self.canv.roundRect(left, y - 2, bar_w * d["month_net"] / maxval, 14, 6, fill=1, stroke=0)
            self.canv.setFillColor(NAVY)
            self.canv.setFont("BT-Medium", 8)
            self.canv.drawString(left + bar_w + 9, y + 1, f"выручка после комиссии {rub(d['month_net'])}")


def P(text, style="body"):
    return Paragraph(text, S[style])


def table(rows, widths, header=True, font_size=8, aligns=None, padding=6):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), PALE), ("TEXTCOLOR", (0, 0), (-1, 0), NAVY)]
    start = 1 if header else 0
    for row in range(start, len(rows)):
        if (row - start) % 2 == 1:
            cmds.append(("BACKGROUND", (0, row), (-1, row), PAPER))
    if aligns:
        for col, align in enumerate(aligns):
            cmds.append(("ALIGN", (col, start), (col, -1), align))
    t.setStyle(TableStyle(cmds))
    return t


def page_chrome(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(WHITE)
    canvas.rect(0, 0, W, H, stroke=0, fill=1)
    canvas.drawImage(str(ROOT / "logo medium.png"), 17 * mm, H - 24 * mm, width=9 * mm, height=8.7 * mm, mask="auto")
    canvas.setFillColor(NAVY)
    canvas.setFont("BT-Medium", 10)
    canvas.drawString(29 * mm, H - 19.7 * mm, "Bit-Think | внутренняя экономика")
    canvas.setFillColor(CYAN)
    canvas.setFont("BT-Medium", 7)
    canvas.drawRightString(W - 17 * mm, H - 19.5 * mm, "РАСЧЁТНАЯ МОДЕЛЬ · 08.10.2026")
    canvas.setStrokeColor(LINE)
    canvas.line(17 * mm, H - 27 * mm, W - 17 * mm, H - 27 * mm)
    canvas.line(17 * mm, 15 * mm, W - 17 * mm, 15 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("BT-Regular", 7)
    canvas.drawString(17 * mm, 10.5 * mm, "Внутренний документ · не бухгалтерская отчётность · налоги не включены")
    canvas.drawRightString(W - 17 * mm, 10.5 * mm, f"{doc.page}")
    canvas.restoreState()


doc = BaseDocTemplate(
    str(OUT), pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm,
    topMargin=33 * mm, bottomMargin=21 * mm, title="Bit-Think - внутренняя экономика подписок",
    author="Bit-Think", subject="Выручка, модельная себестоимость и сценарии маржи",
)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates([PageTemplate(id="report", frames=frame, onPage=page_chrome)])
story = []

# Page 1: executive overview.
story += [P("Экономика подписок", "title"),
          P("Выручка, API-себестоимость и запас тарифов при полном использовании текстовых квот.", "subtitle"),
          Spacer(1, 12),
          KpiRow([
              ("Выручка: по одному Pro / Pro+ / Ultra", rub(sum(DATA[p]["price_rub"] for p in PLANS)), "3 активные месячные подписки"),
              ("API-текст при полном лимите", rub(sum(DATA[p]["monthly_cost"] for p in PLANS)), "сценарий 80% входа / 20% ответа"),
              ("Маржа до прочих затрат", rub(sum(DATA[p]["month_contribution"] for p in PLANS)), "после комиссии 8,5%, до общего сервера"),
          ]), Spacer(1, 13),
          P("Что показывает модель", "h2"),
          P("При стандартной смеси текста 80/20 модельные лимиты выглядят положительно: один подписчик каждого платного плана даёт около <b>" + rub(sum(DATA[p]["month_contribution"] for p in PLANS)) + "</b> вклада после условной комиссии и API-текста. После единственного общего расхода сервера 400 ₽ остаётся около <b>" + rub(sum(DATA[p]["month_contribution"] for p in PLANS) - SERVER) + "</b> до изображений, поиска, бесплатных/пробных аккаунтов и остальных расходов."),
          Spacer(1, 9), MarginBars(), Spacer(1, 5),
          P("Это не фактическая прибыль", "h2"),
          P("Платежи на сайте пока не подключены, а число реальных подписчиков и потребление API по пользователям неизвестны. Поэтому здесь показаны сценарная выручка и вклад на основе тарифных цен и лимитов, а не подтверждённые продажи или бухгалтерская прибыль. Налоги исключены по просьбе владельца.", "body"),
          Spacer(1, 10),
          P("Параметры модели", "h2")]
assumptions = [
    [P("Параметр", "cellbold"), P("Принято в расчёте", "cellbold"), P("Как трактовать", "cellbold")],
    [P("Модели и квоты", "cell"), P("Текущие лимиты Pro / Pro+ / Ultra", "cell"), P("В коде: Sol добавлен в Pro, Astra в Pro+; лимиты прежние.", "cell")],
    [P("Текстовая смесь", "cell"), P("80% входных / 20% выходных токенов", "cell"), P("Базовый сценарий; рядом показана чувствительность к 50/50 и ответам.", "cell")],
    [P("Комиссия оплаты", "cell"), P("8,5% от цены", "cell"), P("Условное допущение, не тариф подтверждённого провайдера.", "cell")],
    [P("Общий сервер", "cell"), P("400 ₽ в месяц", "cell"), P("Один раз на всё приложение, не на каждого подписчика.", "cell")],
]
story += [table(assumptions, [38 * mm, 58 * mm, 72 * mm], padding=5),
          Spacer(1, 8),
          P("Модель переводит лимит кошелька в денежную стоимость по стандартным ставкам GPT-6 Luna: $0,10 за 1 млн входных и $0,50 за 1 млн выходных токенов. Коэффициенты Sol ×20 и Astra ×100 делают базовую текстовую себестоимость на одну единицу кошелька примерно одинаковой. Курс для пересчёта: 85,4811 ₽/$ по ЦБ на дату аудита.", "small"),
          PageBreak()]

# Page 2: unit economics per plan.
story += [P("Вклад одного подписчика", "h1"),
          P("Сумма «лимиты» включает месячный кошелёк чата и отдельный кошелёк Оркестратора. Себестоимость предполагает полный расход обоих кошельков за месяц.", "subtitle"),
          Spacer(1, 10)]
unit_rows = [[P(v, "cellbold") for v in ["Тариф", "Цена / мес.", "Цена / год", "Квоты, млн ед.", "API-текст / мес.", "Вклад / мес."]]]
for tier in PLANS:
    d = DATA[tier]
    unit_rows.append([
        P(d["name"], "cellbold"), P(rub(d["price_rub"]), "cell"), P(rub(d["price_year_rub"]), "cell"),
        P(nfmt(d["units_m"], 0), "cell"), P(rub(d["monthly_cost"]), "cell"), P(rub(d["month_contribution"]), "cellbold"),
    ])
story += [table(unit_rows, [22 * mm, 27 * mm, 27 * mm, 29 * mm, 30 * mm, 33 * mm], aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"], padding=6),
          Spacer(1, 12), P("Месячная и годовая оплата", "h2")]
annual_rows = [[P(v, "cellbold") for v in ["План", "После условной комиссии / мес.", "API-текст при полном лимите", "Остаток до прочих затрат"]]]
for tier in PLANS:
    d = DATA[tier]
    annual_rows.append([
        P(d["name"], "cellbold"), P(rub(d["year_net_month"]), "cell"), P(rub(d["monthly_cost"]), "cell"), P(rub(d["year_contribution"]), "cellbold")
    ])
story += [table(annual_rows, [28 * mm, 49 * mm, 48 * mm, 43 * mm], padding=6), Spacer(1, 8),
          P("Годовая цена равна десяти месячным платежам. Поэтому средняя выручка за месяц по годовому плану ниже месячного плана: 19 900 / 39 900 / 129 900 ₽ вносится авансом, а при сравнении с расходом каждый месяц предполагается полная ежемесячная квота все 12 месяцев. По этой модели годовой план оставляет меньше запаса, особенно на Pro и Pro+.", "small"),
          Spacer(1, 12), P("Чувствительность к структуре токенов", "h2")]
sens_rows = [[P(v, "cellbold") for v in ["Тариф", "Вклад после комиссии при 80/20", "При 50/50", "Если весь расход - ответы"]]]
for tier in PLANS:
    d = DATA[tier]
    sens_rows.append([
        P(d["name"], "cellbold"), P(rub(d["month_contribution"]), "cell"),
        P(rub(d["month_net"] - d["cost_50"]), "cellbold"), P(rub(d["month_net"] - d["cost_output"]), "cellbold"),
    ])
story += [table(sens_rows, [25 * mm, 48 * mm, 47 * mm, 48 * mm], padding=6),
          Spacer(1, 8),
          P("50/50 оставляет примерно " + " / ".join(rub(DATA[p]["month_net"] - DATA[p]["cost_50"]) for p in PLANS) + " на покрытие всех прочих затрат. Если кошелёк в основном расходуется на длинные ответы, одни только текстовые API могут превысить выручку после комиссии. При полном контексте свыше 272 тыс. токенов код удваивает списание; это частично защищает от повышенных long-context ставок.", "small"),
          PageBreak()]

# Page 3: revenue examples and decision support.
story += [P("Выручка и покрытие расходов", "h1"),
          P("Примеры масштаба при одинаковом числе месячных подписок каждого платного тарифа.", "subtitle"), Spacer(1, 10)]
mix_rows = [[P(v, "cellbold") for v in ["Подписчиков каждого плана", "Валовая выручка", "После комиссии 8,5%", "Текстовый API", "После API и сервера"]]]
for count in [1, 10, 100]:
    gross = count * sum(DATA[p]["price_rub"] for p in PLANS)
    post_fee = gross * (1 - FEE)
    llm = count * sum(DATA[p]["monthly_cost"] for p in PLANS)
    after = post_fee - llm - SERVER
    mix_rows.append([
        P(str(count), "cellbold"), P(rub(gross), "cell"), P(rub(post_fee), "cell"), P(rub(llm), "cell"), P(rub(after), "cellbold")
    ])
story += [table(mix_rows, [35 * mm, 35 * mm, 38 * mm, 34 * mm, 36 * mm], aligns=["CENTER", "RIGHT", "RIGHT", "RIGHT", "RIGHT"], padding=6),
          Spacer(1, 6),
          P("Строка «после API и сервера» всё ещё не является прибылью: в ней не учтены изображения, web-search, Kimi Search/Fetch, нагрузка Free / Trial / Creator, конвертация валюты, поддержка, хранение, комиссии сверх сценарных 8,5% и прочие расходы.", "small"),
          Spacer(1, 12), P("Что критично для решения по лимитам", "h2")]
bullet_style = ParagraphStyle("bullet", parent=S["body"], leftIndent=10, firstLineIndent=-8, spaceAfter=4)
story += [Paragraph("• <b>Не увеличивать лимиты по одной только модели.</b> При сохранении кошелька доступ к Sol/Astra меняет расход фактических токенов, но не базовую стоимость единицы в сценарии GPT.", bullet_style),
          Paragraph("• <b>Годовые планы требуют осторожности.</b> При полном расходе квот 50/50 годовой Pro и Pro+ почти не имеют запаса или становятся отрицательными до изображений и бесплатной нагрузки.", bullet_style),
          Paragraph("• <b>Сервер вычитается из общего портфеля.</b> В базовом сценарии одного Pro до прочих расходов остаётся ~" + rub(DATA["pro"]["month_contribution"]) + "; поэтому один Pro покрывает сервер только в модельной части. Реальный порог выше из-за Free и других затрат.", bullet_style),
          Paragraph("• <b>Резерв бюджета снижает риск превышения кошелька.</b> Он резервирует максимум до запроса и ограничивает генерацию ответом, но не ограничивает расходы на изображения и отдельные инструменты.", bullet_style),
          Spacer(1, 8), P("Что собирать для фактической маржи", "h2")]
measure_rows = [
    [P("Показатель", "cellbold"), P("Зачем", "cellbold")],
    [P("Подписки по планам; месячные / годовые оплаты", "cell"), P("Реальная выручка и скидка за годовую оплату", "cell")],
    [P("API usage и стоимость по каждому user_id / model_id", "cell"), P("Фактическая модельная себестоимость, в т.ч. кэш и длинный контекст", "cell")],
    [P("Генерации и правки изображений: параметры + usage", "cell"), P("Себестоимость картинки зависит от размера, качества и количества image tokens", "cell")],
    [P("Поиск, бесплатные, пробные и Creator пользователи", "cell"), P("Расходы, распределяемые на платную базу", "cell")],
]
story += [table(measure_rows, [78 * mm, 100 * mm], padding=5), Spacer(1, 8), P("Формула: операционный результат = валовая выручка − комиссии платежей − все API и инструменты − 400 ₽ общего сервера − прочие расходы. Налоги = 0 в этой модели по указанию владельца.", "small"),
          Spacer(1, 10), P("Источники и границы", "h2"),
          P("Тарифы и лимиты взяты из текущего каталога Bit-Think. Стандартные ставки GPT-6, web-search и image tokens сверены с официальным прайсом OpenAI; ставки и коэффициенты других поставщиков в этой сценарной модели не используются как универсальная себестоимость, поскольку их usage зависит от фактического состава запросов.", "small"),
          P('<link href="https://developers.openai.com/api/docs/pricing" color="#159FCB">OpenAI API Pricing</link> · '
            '<link href="https://developers.openai.com/api/docs/models" color="#159FCB">OpenAI Models</link> · '
            '<link href="https://developers.openai.com/api/docs/guides/image-generation" color="#159FCB">Image Generation</link> · '
            '<link href="https://www.cbr.ru/currency_base/daily/" color="#159FCB">Банк России: курсы валют</link>', "source")]

doc.build(story)
print(OUT)
