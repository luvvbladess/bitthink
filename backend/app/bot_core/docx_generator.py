"""
Модуль для генерации DOCX документов из Markdown/текста.

Сборка идёт напрямую через python-docx: Document(), add_heading(), абзацы,
нумерованные списки 1 / 1.1 / 1.1.1 / 1.1.1.1 и add_table(). Markdown модели остаётся
источником структуры, но в Word он не экспортируется через HTML — иначе
ломаются стили шаблона, таблицы и нумерация.
"""

import io
import re
import unicodedata
from typing import Optional
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, RGBColor
from docx.oxml.shared import OxmlElement
from docx.oxml.ns import qn
import logging

logger = logging.getLogger(__name__)

# Текст этого абзаца — признак того, что сборка DOCX сорвалась и в документ
# лёг сырой markdown. Вызывающий код ищет его, чтобы не выдать такой файл
# пользователю за готовый.
CONVERSION_FAILED_MARKER = "Ошибка при конвертации форматирования. Исходный текст:"

# hanging обязан быть шире номера («1.1.» ≈ 0.4"), иначе LibreOffice
# склеивает «1.1.подготовке». left > hanging, чтобы маркер не уезжал в поле.
LIST_NUMBERING_LEVELS = (
    (720, 400, "%1."),
    (1440, 720, "%1.%2."),
    (2160, 960, "%1.%2.%3."),
    (2880, 1200, "%1.%2.%3.%4."),
    (3600, 1440, "%1.%2.%3.%4.%5."),
)
MAX_LIST_ILVL = len(LIST_NUMBERING_LEVELS) - 1


def _numbering_root(doc):
    try:
        return doc.part.numbering_part.numbering_definitions._numbering
    except (NotImplementedError, AttributeError):
        return None


def _lvl_val(lvl, tag: str):
    el = lvl.find(qn(tag))
    return el.get(qn("w:val")) if el is not None else None


def _find_gost_abstract_id(root) -> Optional[int]:
    """AbstractNum шаблона, где уровни 0–3 — десятичные 1 / 1.1 / 1.1.1 / 1.1.1.1."""
    for absn in root.findall(qn("w:abstractNum")):
        texts = {}
        fmts = {}
        for lvl in absn.findall(qn("w:lvl")):
            ilvl = int(lvl.get(qn("w:ilvl")))
            texts[ilvl] = _lvl_val(lvl, "w:lvlText") or ""
            fmts[ilvl] = _lvl_val(lvl, "w:numFmt")
        if fmts.get(0) != "decimal":
            continue
        if texts.get(0, "").startswith("%1") and texts.get(1, "").startswith("%1.%2"):
            return int(absn.get(qn("w:abstractNumId")))
    return None


def _append_num_instance(root, abstract_id: int) -> int:
    current_ids = [int(n.get(qn("w:numId"))) for n in root.findall(qn("w:num"))]
    next_num_id = max(current_ids, default=0) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(next_num_id))
    abs_id = OxmlElement("w:abstractNumId")
    abs_id.set(qn("w:val"), str(abstract_id))
    num.append(abs_id)
    root.append(num)
    return next_num_id


def _create_gost_abstract(root) -> int:
    import random

    current_abs_ids = [int(a.get(qn("w:abstractNumId"))) for a in root.findall(qn("w:abstractNum"))]
    next_abs_id = max(current_abs_ids, default=-1) + 1
    abs_num = OxmlElement("w:abstractNum")
    abs_num.set(qn("w:abstractNumId"), str(next_abs_id))
    nsid = OxmlElement("w:nsid")
    nsid.set(qn("w:val"), "".join(random.choices("0123456789ABCDEF", k=8)))
    abs_num.append(nsid)
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "multilevel")
    abs_num.append(multi)
    for i, (left, hanging, text) in enumerate(LIST_NUMBERING_LEVELS):
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), str(i))
        start = OxmlElement("w:start")
        start.set(qn("w:val"), "1")
        lvl.append(start)
        num_fmt = OxmlElement("w:numFmt")
        num_fmt.set(qn("w:val"), "decimal")
        lvl.append(num_fmt)
        suff = OxmlElement("w:suff")
        suff.set(qn("w:val"), "space")
        lvl.append(suff)
        lvl_text = OxmlElement("w:lvlText")
        lvl_text.set(qn("w:val"), text)
        lvl.append(lvl_text)
        lvl_jc = OxmlElement("w:lvlJc")
        lvl_jc.set(qn("w:val"), "left")
        lvl.append(lvl_jc)
        pPr = OxmlElement("w:pPr")
        ind = OxmlElement("w:ind")
        ind.set(qn("w:left"), str(left))
        ind.set(qn("w:hanging"), str(hanging))
        pPr.append(ind)
        lvl.append(pPr)
        abs_num.append(lvl)
    nums = root.findall(qn("w:num"))
    if nums:
        nums[0].addprevious(abs_num)
    else:
        root.append(abs_num)
    return next_abs_id


def create_list_numbering(doc, is_bullet=False):
    """Новый Word-список 1 / 1.1 / 1.1.1 / 1.1.1.1 на своём abstractNum.

    Чужой abstractNum шаблона нельзя переиспользовать: Word ведёт один
    счётчик на abstract, и «1.3» раздела превращается в «5.1».
    """
    root = _numbering_root(doc)
    if root is None:
        return None
    return _append_num_instance(root, _create_gost_abstract(root))


def _clear_direct_indent(paragraph) -> None:
    """Прямой w:ind на абзаце перекрывает hanging нумерации — номер уезжает в поле."""
    pPr = paragraph._element.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is not None:
        pPr.remove(ind)

def remove_empty_list_items(doc):
    """
    Удаляет пустые пункты списков (пустые параграфы со стилем List Number или List Bullet).
    Это артефакты конвертации, когда ИИ оставляет пустые строки вида '1. ' или '- '.
    """
    from docx.oxml.text.paragraph import CT_P
    from docx.text.paragraph import Paragraph

    list_styles = {'List Number', 'List Bullet', 'List Paragraph'}
    to_remove = []
    
    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            p = Paragraph(child, doc)
            if p.style and p.style.name in list_styles and not p.text.strip():
                to_remove.append(child)
    
    for element in to_remove:
        element.getparent().remove(element)

def fix_numbered_lists(doc):
    """Донумеровывает списки без numPr. Уже расставленные Word-номера не трогает.

    Списки могут быть разными: новый numId — новый «1.». Склеивать всё в один
    список нельзя — под заголовком «2.» часто начинается свой перечень.
    """
    from docx.oxml.text.paragraph import CT_P
    from docx.text.paragraph import Paragraph

    current_num_id = None
    list_style_keywords = {'list', 'bullet', 'number', 'список'}

    for child in doc.element.body.iterchildren():
        if not isinstance(child, CT_P):
            current_num_id = None
            continue
        p = Paragraph(child, doc)
        style_name = ((p.style.name if p.style else "") or "").lower()
        is_empty = not p.text.strip()
        is_heading = style_name.startswith('heading') or style_name.startswith('title') or style_name.startswith('заголовок')

        has_num_pr = False
        existing_id = existing_ilvl = None
        try:
            pPr_elem = p._element.pPr
            if pPr_elem is not None and pPr_elem.numPr is not None:
                has_num_pr = True
                if pPr_elem.numPr.numId is not None:
                    existing_id = int(pPr_elem.numPr.numId.val)
                if pPr_elem.numPr.ilvl is not None:
                    existing_ilvl = int(pPr_elem.numPr.ilvl.val)
        except Exception:
            pass

        is_list_style = any(kw in style_name for kw in list_style_keywords)
        if is_heading:
            current_num_id = existing_id if has_num_pr else None
            continue
        if is_empty:
            continue
        if has_num_pr:
            current_num_id = existing_id
            _clear_direct_indent(p)
            continue
        if not is_list_style:
            current_num_id = None
            continue
        if current_num_id is None:
            current_num_id = create_list_numbering(doc, False)
        if current_num_id is not None:
            _apply_list_number(p, current_num_id, existing_ilvl or 0)

def add_table_borders(doc):
    """
    Добавляет видимые границы ко всем таблицам в документе.
    """
    from docx.oxml.ns import qn
    from docx.oxml.shared import OxmlElement
    
    def make_border_el(tag, val="single", sz="4", color="000000"):
        """Creates a border XML element."""
        el = OxmlElement(tag)
        el.set(qn('w:val'), val)
        el.set(qn('w:sz'), sz)
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color)
        return el
    
    for table in doc.tables:
        tbl = table._tbl
        # Находим или создаём tblPr
        tblPr = tbl.find(qn('w:tblPr'))
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr')
            tbl.insert(0, tblPr)
        
        # Удаляем старый tblBorders, если есть
        old_borders = tblPr.find(qn('w:tblBorders'))
        if old_borders is not None:
            tblPr.remove(old_borders)
        
        tblBorders = OxmlElement('w:tblBorders')
        for side in ('w:top', 'w:left', 'w:bottom', 'w:right', 'w:insideH', 'w:insideV'):
            tblBorders.append(make_border_el(side))
        tblPr.append(tblBorders)


def auto_size_table_columns(doc):
    """
    Перераспределяет ширину столбцов таблиц пропорционально содержимому.
    Числовые/короткие столбцы получают узкую ширину, текстовые — широкую.
    """
    section = doc.sections[0]
    page_width_dxa = max(int((section.page_width - section.left_margin - section.right_margin) / 635), 1)
    MIN_RATIO = 0.12
    MAX_RATIO = 0.50

    numeric_pattern = re.compile(r'^[\d\s.,+\-±%$€₽°×№#:\/\\()\[\]]+$')

    for table in doc.tables:
        num_rows = len(table.rows)
        if num_rows == 0:
            continue
        num_cols = len(table.columns)
        if num_cols <= 1:
            continue

        # Собираем текст по каждому столбцу
        col_texts = [[] for _ in range(num_cols)]
        for ri in range(num_rows):
            for ci in range(num_cols):
                try:
                    col_texts[ci].append(table.cell(ri, ci).text.strip())
                except Exception:
                    col_texts[ci].append("")

        # Вычисляем вес каждого столбца
        weights = []
        for ci, texts in enumerate(col_texts):
            if not texts:
                weights.append(4)
                continue
            lengths = [len(t) for t in texts]
            max_len = max(lengths)
            avg_len = sum(lengths) / len(lengths)

            # Данные без заголовка для определения типа столбца
            data = texts[1:] if len(texts) > 1 else texts
            numeric_count = sum(1 for t in data if t and numeric_pattern.match(t))
            is_numeric = data and numeric_count / len(data) > 0.5

            if is_numeric:
                weight = min(max(avg_len, max_len), 12)
            else:
                weight = max_len

            # Узкий столбец с длинным заголовком Word переносит по слогам:
            # «Версия/редакция» превращалось в «В ерсия/ редак ция». Столбец
            # обязан вмещать самое длинное слово своей шапки целиком.
            header = texts[0] if texts else ""
            longest_word = max(
                (len(w) for t in texts for w in re.split(r"[\s/]+", t) if w),
                default=0,
            )
            weights.append(max(weight, longest_word, len(header), 8))

        # Применяем ограничения min/max и нормализуем
        total = sum(weights)
        ratios = [max(min(w / total, MAX_RATIO), MIN_RATIO) for w in weights]
        total_r = sum(ratios)
        ratios = [r / total_r for r in ratios]

        # Ширины в dxa
        widths = [int(page_width_dxa * r) for r in ratios]
        widths[-1] += page_width_dxa - sum(widths)  # компенсация погрешности округления

        tbl = table._tbl
        table.autofit = False

        # Обновляем tblW (общая ширина таблицы)
        tblPr = tbl.find(qn('w:tblPr'))
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr')
            tbl.insert(0, tblPr)
        tblLayout = tblPr.find(qn('w:tblLayout'))
        if tblLayout is None:
            tblLayout = OxmlElement('w:tblLayout')
            tblPr.append(tblLayout)
        tblLayout.set(qn('w:type'), 'fixed')
        tblW = tblPr.find(qn('w:tblW'))
        if tblW is None:
            tblW = OxmlElement('w:tblW')
            tblPr.append(tblW)
        tblW.set(qn('w:w'), str(page_width_dxa))
        tblW.set(qn('w:type'), 'dxa')

        # Обновляем tblGrid
        old_grid = tbl.find(qn('w:tblGrid'))
        if old_grid is not None:
            tbl.remove(old_grid)
        tblGrid = OxmlElement('w:tblGrid')
        for w in widths:
            gc = OxmlElement('w:gridCol')
            gc.set(qn('w:w'), str(w))
            tblGrid.append(gc)
        tblPr.addnext(tblGrid)

        # Устанавливаем ширину ячеек в каждом столбце
        for ci in range(num_cols):
            for cell in table.columns[ci].cells:
                tc = cell._tc
                tcPr = tc.get_or_add_tcPr()
                tcW = tcPr.find(qn('w:tcW'))
                if tcW is None:
                    tcW = OxmlElement('w:tcW')
                    tcPr.append(tcW)
                tcW.set(qn('w:w'), str(widths[ci]))
                tcW.set(qn('w:type'), 'dxa')
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            if trPr.find(qn('w:cantSplit')) is None:
                trPr.append(OxmlElement('w:cantSplit'))


def fix_monospace_fonts(doc):
    """
    Защитный пост-процессинг: htmldocx форсирует моноширинный шрифт (Courier New и т.п.)
    для <code>/<pre> блоков. Если де-фенсинг на этапе Markdown не сработал (например,
    LLM указал язык у блока, хотя текст внутри не код), документ всё равно выглядит
    "рваным" по шрифтам. Здесь убираем явный moноширинный шрифт у runs, чтобы они
    наследовали обычный шрифт абзаца/стиля.

    Цвет текста всегда чёрный, в том числе при работе по шаблону. Исключение
    для шаблонов тут было, и оно ничего не защищало: обход идёт только по телу
    документа и ячейкам таблиц, а цветные элементы рамки ГОСТ живут в
    колонтитулах, куда эта функция не заходит вовсе. Зато без принудительного
    чёрного заголовки выходили синими — таким их определяет стандартный стиль
    Heading, и в деловом документе это брак.
    """
    MONOSPACE_FONTS = {"Courier New", "Consolas", "Lucida Console", "Courier", "Monaco", "Menlo"}

    def clear_run_font(run):
        rPr = run._element.find(qn('w:rPr'))
        if rPr is not None:
            rFonts = rPr.find(qn('w:rFonts'))
            if rFonts is not None:
                rPr.remove(rFonts)

    def process_paragraphs(paragraphs):
        for p in paragraphs:
            for r in p.runs:
                if re.fullmatch(r'```(?:text|txt|markdown|md)?', r.text.strip(), re.IGNORECASE):
                    r.text = ""
                    continue
                r.font.color.rgb = RGBColor(0, 0, 0)
                if r.font.name in MONOSPACE_FONTS:
                    clear_run_font(r)

    process_paragraphs(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                process_paragraphs(cell.paragraphs)


def apply_paragraph_formatting(doc):
    """
    Выравнивание текста документа:
    - Заголовки (Heading/Title) — по центру, без отступа первой строки.
    - Списки (нумерованные/маркированные) — по левому краю, без отступа.
    - Обычный текст — по ширине, с отступом первой строки (красная строка).
    Применяется только к основному телу документа, ячейки таблиц не трогаем —
    там выравнивание по центру/ширине и отступы выглядят неестественно.
    """
    LIST_STYLE_KEYWORDS = ('list', 'bullet', 'number', 'список')
    FIRST_LINE_INDENT = Cm(1.25)

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue

        style_name = (p.style.name if p.style else "") or ""
        style_lower = style_name.lower()
        is_heading = style_lower.startswith('heading') or style_lower.startswith('title')

        has_num_pr = False
        try:
            pPr = p._element.pPr
            has_num_pr = pPr is not None and pPr.numPr is not None
        except Exception:
            pass
        is_list = has_num_pr or any(kw in style_lower for kw in LIST_STYLE_KEYWORDS)

        is_short_label = text.endswith(":") and len(text) <= 80
        is_numbered_clause = bool(re.match(r"^\d+(\.\d+)*\.?\s", text))

        if is_heading:
            if has_num_pr or not (
                style_lower.startswith("heading 1") or style_lower.startswith("title")
            ):
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if has_num_pr:
                _clear_direct_indent(p)
            else:
                p.paragraph_format.first_line_indent = Cm(0)
        elif has_num_pr:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _clear_direct_indent(p)
        elif is_list or is_short_label or is_numbered_clause:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            indent = p.paragraph_format.first_line_indent
            if indent is None or indent >= 0:
                p.paragraph_format.first_line_indent = Cm(0)
        else:
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = FIRST_LINE_INDENT


def strip_blockquote_markers(markdown_text: str) -> str:
    """
    Технические тексты часто используют '>' как визуальное выделение, а не как
    цитату Markdown. Маркер убираем целиком — иначе в Word он остаётся буквальным
    символом на каждой строке.
    """
    parts = re.split(r'(```.*?```)', markdown_text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):  # чётные индексы - вне кода, нечётные - внутри ```...```
        lines = parts[i].split('\n')
        lines = [re.sub(r'^(\s*)>\s?', r'\1', line) for line in lines]
        parts[i] = '\n'.join(lines)
    return "".join(parts)


def escape_stray_angle_brackets(markdown_text: str) -> str:
    """
    LLM иногда пишет формулы или заметки в угловых скобках (например "<<S = a × b>>"),
    не подозревая, что конвертер markdown -> HTML интерпретирует '<'/'>' как начало
    HTML-тега и молча вырезает нераспознанное содержимое - в документе остаётся
    пустое "<<>>". Экранируем '<', '>' и '&' в HTML-сущности везде, КРОМЕ блоков кода
    (```...```), которые и так рендерятся отдельным, безопасным путём.
    """
    parts = re.split(r'(```.*?```)', markdown_text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):  # чётные индексы - вне кода, нечётные - внутри ```...```
        parts[i] = parts[i].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return "".join(parts)


_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*\S)\s*$')
_HR_RE = re.compile(r'^(?:-{3,}|\*{3,}|_{3,})$')
_TABLE_SEP_RE = re.compile(r'^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$')
_GOST_LIST_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<nums>\d+(?:\.\d+){0,4})\.?(?:\s+)(?P<body>\S.*)$'
)
_MD_LIST_RE = re.compile(r'^(?P<indent>[ \t]*)(?:[-*+]|\d+\.)\s+(?P<body>.+)$')
# 1.1 / 1.2.1 — пункты, не названия разделов. «1. Назначение» (один номер) сюда не входит.
_NUMBERED_CLAUSE_RE = re.compile(r'^\d+\.\d+')
_LEADING_NUMBER_RE = re.compile(r'^\d+(?:\.\d+){0,4}\.?\s+')
_UNIT_START_RE = re.compile(
    r'^(?:МПа|кПа|мм|см|км|кг|кВт|Вт|кВ|Гц|бар|об/мин|°C|°С|%)(?:\b|[ —–-]|$)',
    re.IGNORECASE,
)
_INLINE_RE = re.compile(
    r'\*\*(.+?)\*\*|__(.+?)__'
    r'|(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)'
    r'|(?<![A-Za-z0-9_])_(?!_)(.+?)(?<!_)_(?![A-Za-z0-9_])'
    r'|`([^`]+)`'
    r'|\[([^\]]+)\]\([^)]+\)'
    r'|!\[([^\]]*)\]\([^)]+\)'
)
_CODE_INDICATORS = (
    'def ', 'function ', 'class ', 'import ', 'const ', 'let ', 'var ', 'public ',
    'private ', 'void ', 'return ', '{', '}', ';', '=>', '<?php', '#include',
    'SELECT ', 'INSERT ', 'UPDATE ', 'CREATE TABLE', '<html', '<div', '</', '==', '!=',
)


def _looks_like_code(text: str) -> bool:
    return any(ind in text for ind in _CODE_INDICATORS)


def _add_formatted_runs(paragraph, text: str) -> None:
    """Пишет в абзац текст с **жирным**, *курсивом* и ссылками как видимым текстом."""
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos:match.start()])
        if match.group(1) is not None or match.group(2) is not None:
            run = paragraph.add_run(match.group(1) or match.group(2))
            run.bold = True
        elif match.group(3) is not None or match.group(4) is not None:
            run = paragraph.add_run(match.group(3) or match.group(4))
            run.italic = True
        elif match.group(5) is not None:
            paragraph.add_run(match.group(5))
        elif match.group(6) is not None:
            paragraph.add_run(match.group(6))
        else:
            paragraph.add_run(match.group(7) or "")
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])
    if not paragraph.runs:
        paragraph.add_run(text)


def _apply_list_number(paragraph, num_id, ilvl) -> None:
    if not num_id:
        return
    pPr = paragraph._element.get_or_add_pPr()
    numPr = pPr.get_or_add_numPr()
    numId_el = numPr.get_or_add_numId()
    numId_el.set(qn("w:val"), str(num_id))
    ilvl_el = numPr.get_or_add_ilvl()
    ilvl_el.set(qn("w:val"), str(_cap_ilvl(ilvl)))
    # Прямой firstLine/left на абзаце перекрывает hanging из numbering.xml —
    # именно так номера ИТТ уезжали в левое поле.
    _clear_direct_indent(paragraph)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT


def _strip_leading_number(text: str) -> str:
    return _LEADING_NUMBER_RE.sub("", text or "", count=1).strip()


def _cap_ilvl(ilvl: int, floor: int = 0) -> int:
    return min(max(int(ilvl), floor), MAX_LIST_ILVL)


def _parse_number_tuple(text: str):
    match = re.match(r"^(\d+(?:\.\d+){0,4})\.?\s+", (text or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _continues_list(prev, new, *, allow_repeat: bool = False) -> bool:
    """Тот же Word-список (ребёнок, сосед, дядя) или нет."""
    if not prev or not new:
        return False
    if len(new) == len(prev) + 1 and new[:-1] == prev:
        return True
    if len(new) == len(prev) and new[:-1] == prev[:-1]:
        if new[-1] > prev[-1]:
            return True
        # markdown часто пишет 1. 1. 1. — это один список, Word посчитает 1 2 3
        if allow_repeat and new[-1] == prev[-1]:
            return True
    if len(new) < len(prev):
        parent = prev[:len(new)]
        if new[:-1] == parent[:-1] and new[-1] > parent[-1]:
            return True
        if len(new) == 1 and new[0] > prev[0]:
            return True
    return False


def _body_attaches_to_heading(heading_tuple, body_tuple) -> bool:
    """1.1 после «1. Раздел» — продолжение того же контура."""
    if not heading_tuple or not body_tuple:
        return False
    return len(body_tuple) > len(heading_tuple) and body_tuple[:len(heading_tuple)] == heading_tuple


def _relative_to_heading(heading_tuple, body_tuple):
    """Писатель под разделом 2 снова пишет 1. / 1.1 / 2. — это 2.1 / 2.1.1 / 2.2."""
    if not body_tuple:
        return body_tuple
    if heading_tuple and _body_attaches_to_heading(heading_tuple, body_tuple):
        return body_tuple
    if heading_tuple:
        return tuple(heading_tuple) + tuple(body_tuple)
    return body_tuple


_DEF_DASH_RE = re.compile(r"\s[—–-]\s")


def _is_nested_list_item(text: str) -> bool:
    """Пункт вроде «договор…;» или «НИОКР — …» после фразы с двоеточием."""
    body = _strip_leading_number(text or "") or (text or "").strip()
    if not body:
        return False
    if body.endswith(";"):
        return True
    if _DEF_DASH_RE.search(body[:60]):
        return True
    return body[0].islower()


def _place_clause(heading_tuple, last, raw, indent: int = 0):
    """Куда в ГОСТ-контуре поставить пункт: абсолютный 2.1 или относительный 1. / 2.1."""
    if not raw:
        if heading_tuple:
            return last, _cap_ilvl(indent, 1)
        return last, _cap_ilvl(indent)
    if heading_tuple:
        if last == heading_tuple:
            if len(raw) == len(last) + 1 and raw[:-1] == last:
                return raw, _cap_ilvl(len(raw) - 1, 1)
            rebased = tuple(heading_tuple) + tuple(raw)
            return rebased, _cap_ilvl(len(rebased) - 1, 1)
        if last and len(raw) == len(last) + 1 and raw[:-1] == last:
            return raw, _cap_ilvl(len(raw) - 1, 1)
        # Под заголовком 1. затем 1.1 — это 1.1 / 1.1.1, не два соседа 1.1.
        # Сосед только если номер вырос: 1.1 затем 1.2.
        if last and len(raw) == len(last) and raw[:-1] == last[:-1] and raw[-1] > last[-1]:
            return raw, _cap_ilvl(len(raw) - 1, 1)
        if last and len(raw) < len(last):
            parent = last[:len(raw)]
            if (
                raw[:len(heading_tuple)] == heading_tuple
                and raw[:-1] == parent[:-1]
                and raw[-1] > parent[-1]
            ):
                return raw, _cap_ilvl(len(raw) - 1, 1)
        rebased = tuple(heading_tuple) + tuple(raw)
        return rebased, _cap_ilvl(len(rebased) - 1, 1)
    if last and len(raw) == len(last) + 1 and raw[:-1] == last:
        return raw, _cap_ilvl(len(raw) - 1)
    if last and len(raw) == len(last) and raw[:-1] == last[:-1] and raw[-1] >= last[-1]:
        return raw, _cap_ilvl(len(raw) - 1)
    if last and len(raw) < len(last):
        parent = last[:len(raw)]
        if raw[:-1] == parent[:-1] and raw[-1] > parent[-1]:
            return raw, _cap_ilvl(len(raw) - 1)
    return raw, _cap_ilvl(len(raw) - 1)


def _pick_body_list(doc, body_num_id, body_last, nt):
    """Один numId, если номера продолжают контур; новый — если это отдельный перечень."""
    if nt is None:
        if body_num_id is None:
            body_num_id = create_list_numbering(doc, False)
        return body_num_id, body_last
    if body_num_id is not None and _continues_list(body_last, nt, allow_repeat=True):
        return body_num_id, nt
    return create_list_numbering(doc, False), nt


def _add_numbered_body(doc, text: str, num_id, ilvl: int):
    body = _strip_leading_number(text) or text
    paragraph = doc.add_paragraph()
    _style_list_paragraph(doc, paragraph)
    _add_formatted_runs(paragraph, body)
    _apply_list_number(paragraph, num_id, ilvl)
    return paragraph


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _split_table_row(line: str) -> list:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _indent_level(line: str) -> int:
    expanded = line.replace("\t", "    ")
    spaces = len(expanded) - len(expanded.lstrip(" "))
    if spaces <= 0:
        return 0
    if spaces <= 4:
        return 1
    return min(spaces // 3, MAX_LIST_ILVL)


def _classify_line(line: str, in_list: bool = False):
    """clause | None. Номер в тексте — подсказка для Word, в абзац не копируется."""
    gost = _GOST_LIST_RE.match(line)
    if gost:
        if not gost.group("indent") and not in_list and _UNIT_START_RE.match(gost.group("body")):
            return None
        return "clause", _indent_level(line), line.strip()
    markdown_item = _MD_LIST_RE.match(line)
    if markdown_item:
        stripped = line.strip()
        if stripped[:1] in "-*+":
            return "clause", max(_indent_level(line), 1) if line[:1] in " \t" else 0, markdown_item.group("body")
        return "clause", _indent_level(line), stripped
    return None


def _peek_number_tuple(lines, start: int):
    j = start
    while j < len(lines):
        raw = lines[j]
        stripped = raw.strip()
        if not stripped:
            j += 1
            continue
        if stripped.startswith("```") or _is_table_line(raw) or _HR_RE.match(stripped):
            j += 1
            continue
        if _HEADING_RE.match(stripped):
            return None
        classified = _classify_line(raw)
        if classified:
            return _parse_number_tuple(classified[2])
        j += 1
    return None


def _add_heading_native(doc, text: str, level: int):
    level = max(1, min(int(level), 6))
    title = text.strip().rstrip("#").rstrip()
    try:
        paragraph = doc.add_heading("", level=level)
    except KeyError:
        paragraph = doc.add_paragraph()
        try:
            paragraph.style = f"Heading {level}"
        except Exception:
            pass
    _add_formatted_runs(paragraph, title)
    paragraph.paragraph_format.first_line_indent = Cm(0)
    if level <= 1:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    return paragraph


def _add_table_native(doc, rows: list) -> None:
    if not rows:
        return
    cols = max(len(row) for row in rows)
    if cols <= 0:
        return
    normalized = [row + [""] * (cols - len(row)) for row in rows]
    try:
        table = doc.add_table(rows=len(normalized), cols=cols, style="Table Grid")
    except Exception:
        table = doc.add_table(rows=len(normalized), cols=cols)
    for i, row in enumerate(normalized):
        for j, value in enumerate(row):
            paragraph = table.cell(i, j).paragraphs[0]
            paragraph.text = ""
            _add_formatted_runs(paragraph, value)


def _style_list_paragraph(doc, paragraph) -> None:
    # List Paragraph у python-docx держит left=720 без hanging. Вместе с
    # нумерацией это выталкивает маркер в поле страницы — как на скриншотах.
    # Стиль не ставим: номер и отступ задаёт только w:numPr.
    return


def _render_markdown_native(doc, markdown_text: str) -> None:
    """Заголовки 1 / 2 / 3 и пункты 2.1 / 2.2 — один Word-список.

    Писатель под каждым разделом часто начинает 1. 2. 3. заново. Это не новый
    перечень: под «## 2 …» это 2.1 / 2.2, иначе по документу снова и снова
    всплывают пункты 1 / 1.1 / 2.
    """
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    outline_id = None
    section_anchor = None
    body_num_id = None
    body_last = None
    nest_under = None
    nest_ilvl = 1

    def _outline():
        nonlocal outline_id
        if outline_id is None:
            outline_id = create_list_numbering(doc, False)
        return outline_id

    def _emit_section_clause(nt, indent, text: str) -> None:
        nonlocal body_last, body_num_id, nest_under, nest_ilvl
        body_num_id = _outline()
        nested = nest_under is not None and _is_nested_list_item(text)
        if indent and body_last and body_last != section_anchor:
            nested = True
            if nest_under is None:
                nest_under = body_last
                nest_ilvl = _cap_ilvl(len(body_last) - 1, 1)
        if nested and nest_under is not None:
            rel = nt
            if nt and body_last == nest_under and nt[0] == 1 and len(nt) > 1:
                rel = nt[1:]
            body_last, ilvl = _place_clause(nest_under, body_last, rel, indent)
            ilvl = _cap_ilvl(nest_ilvl + 1)
        else:
            nest_under = None
            body_last, ilvl = _place_clause(section_anchor, body_last, nt, indent)
        _add_numbered_body(doc, text, body_num_id, ilvl)
        plain = _strip_leading_number(text) or text
        if plain.rstrip().endswith(":"):
            nest_under = body_last
            nest_ilvl = ilvl

    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            block = []
            i += 1
            while i < n and lines[i].strip() != "```":
                block.append(lines[i])
                i += 1
            if i < n:
                i += 1
            for block_line in block:
                paragraph = doc.add_paragraph()
                paragraph.add_run(block_line)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            title = heading.group(2).strip().rstrip("#").rstrip()
            hashes = len(heading.group(1))
            heading_tuple = _parse_number_tuple(title)
            if hashes >= 3 and _NUMBERED_CLAUSE_RE.match(title):
                nt = heading_tuple
                if section_anchor:
                    _emit_section_clause(nt, 0, title)
                else:
                    body_num_id, body_last = _pick_body_list(doc, body_num_id, body_last, nt)
                    ilvl = _cap_ilvl(len(nt) - 1, 1) if nt else 1
                    _add_numbered_body(doc, title, body_num_id, ilvl)
                i += 1
                continue
            if heading_tuple and hashes >= 2:
                num_id = _outline()
                ilvl = _cap_ilvl(len(heading_tuple) - 1)
                paragraph = _add_heading_native(
                    doc, _strip_leading_number(title) or title, hashes,
                )
                _apply_list_number(paragraph, num_id, ilvl)
                section_anchor = heading_tuple
                body_num_id = num_id
                body_last = heading_tuple
                nest_under = None
                i += 1
                continue
            _add_heading_native(doc, title, hashes)
            if hashes >= 2:
                section_anchor = None
                nest_under = None
            peeked = _peek_number_tuple(lines, i + 1)
            if peeked is not None and not _continues_list(body_last, peeked, allow_repeat=True):
                if not (body_num_id is not None and hashes == 1):
                    body_num_id = None
                    body_last = None
            i += 1
            continue

        if _is_table_line(raw):
            rows = []
            while i < n and _is_table_line(lines[i]):
                if not _TABLE_SEP_RE.match(lines[i].strip()):
                    rows.append(_split_table_row(lines[i]))
                i += 1
            _add_table_native(doc, rows)
            continue

        classified = _classify_line(raw, in_list=False)
        if classified and classified[0] == "clause":
            indent, text = classified[1], classified[2]
            nt = _parse_number_tuple(text)
            if section_anchor:
                _emit_section_clause(nt, indent, text)
            elif indent and body_num_id is not None and not (nt and len(nt) > 1):
                _add_numbered_body(doc, text, body_num_id, _cap_ilvl(indent))
            else:
                body_num_id, body_last = _pick_body_list(doc, body_num_id, body_last, nt)
                ilvl = _cap_ilvl(len(nt) - 1) if nt else _cap_ilvl(indent)
                _add_numbered_body(doc, text, body_num_id, ilvl)
            i += 1
            while i < n:
                cont = lines[i]
                if not cont.strip():
                    break
                if (
                    _HEADING_RE.match(cont.strip())
                    or _is_table_line(cont)
                    or _classify_line(cont) is not None
                    or cont.strip().startswith("```")
                ):
                    break
                if cont[:1] in " \t":
                    doc.paragraphs[-1].add_run(" " + cont.strip())
                    i += 1
                    continue
                break
            continue

        if _HR_RE.match(stripped):
            i += 1
            continue

        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip():
                break
            if (
                _HEADING_RE.match(nxt.strip())
                or _is_table_line(nxt)
                or _classify_line(nxt, in_list=False) is not None
                or nxt.strip().startswith("```")
                or _HR_RE.match(nxt.strip())
            ):
                break
            para_lines.append(nxt.strip())
            i += 1
        paragraph = doc.add_paragraph()
        _add_formatted_runs(paragraph, " ".join(para_lines))


def _preprocess_markdown_for_docx(markdown_text: str) -> str:
    markdown_text = strip_blockquote_markers(markdown_text)
    lines = markdown_text.split("\n")
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\d+\.\s*$", stripped) or re.match(r"^[\*\-]\s*$", stripped):
            continue
        fixed_lines.append(line)
    markdown_text = "\n".join(fixed_lines)
    markdown_text = re.sub(
        r"\*\*([^*]+?)\*\*", lambda m: "**" + m.group(1).strip() + "**", markdown_text
    )

    defenced = []
    src_lines = markdown_text.split("\n")
    i3 = 0
    while i3 < len(src_lines):
        line3 = src_lines[i3]
        if re.match(r"^```(?:text|txt|markdown|md)?\s*$", line3.strip(), re.IGNORECASE):
            block = []
            j3 = i3 + 1
            while j3 < len(src_lines) and src_lines[j3].strip() != "```":
                block.append(src_lines[j3])
                j3 += 1
            if j3 < len(src_lines) and not _looks_like_code("\n".join(block)):
                defenced.extend(block)
                i3 = j3 + 1
                continue
            if j3 >= len(src_lines):
                i3 += 1
                continue
        defenced.append(line3)
        i3 += 1
    return "\n".join(defenced)


def convert_markdown_to_docx(markdown_text: str, base_template_bytes: Optional[bytes] = None) -> bytes:
    """Собирает .docx из markdown через python-docx (стили, заголовки, списки, таблицы)."""
    markdown_text = _preprocess_markdown_for_docx(markdown_text)

    if base_template_bytes:
        doc = Document(io.BytesIO(base_template_bytes))
    else:
        doc = Document()
    # Здесь, а не только в blank_copy_of_template: шаблон пользователя
    # приходит сюда напрямую ещё из api/documents.py и services/chat_service.py,
    # и там ровно так же не хватало стиля списка.
    try:
        _ensure_required_styles(doc)
        _normalize_heading_styles(doc)
    except Exception as e:
        logger.warning("Не удалось привести стили документа: %s", e)

    try:
        _render_markdown_native(doc, markdown_text)
    except Exception:
        logger.exception("Не удалось собрать DOCX из markdown")
        doc.add_paragraph(CONVERSION_FAILED_MARKER)
        doc.add_paragraph(markdown_text)
    
    # 4. Добавляем границы таблиц
    try:
        add_table_borders(doc)
    except Exception as e:
        print(f"Table borders warning: {e}")

    # 4b. Авто-ширина столбцов: числовые — узкие, текстовые — широкие
    try:
        auto_size_table_columns(doc)
    except Exception as e:
        print(f"Table column sizing warning: {e}")

    # 4c. Защитная очистка моноширинных шрифтов от ложных code-блоков
    preserve_template = bool(base_template_bytes)
    try:
        fix_monospace_fonts(doc)
    except Exception as e:
        print(f"Monospace font fix warning: {e}")

    # 4d. Ячейки таблиц — по левому краю, даже когда остальное оформление
    # берётся из шаблона: выключка по ширине рвёт узкие столбцы по слогам.
    try:
        _left_align_table_cells(doc)
    except Exception as e:
        print(f"Table cell alignment warning: {e}")

    # 5. Удаляем пустые пункты списков (артефакты конвертации)
    try:
        remove_empty_list_items(doc)
    except Exception as e:
        print(f"Empty list cleanup warning: {e}")
    
    # 6. Исправляем нумерацию списков (сброс нумерации для новых списков)
    try:
        _strip_heading_numbering(doc)
        fix_numbered_lists(doc)
    except Exception as e:
        print(f"List fix warning: {e}")

    try:
        _unify_body_fonts(doc)
    except Exception as e:
        print(f"Font unify warning: {e}")

    # 7. Выравнивание: заголовки по центру, списки по левому краю,
    # обычный текст по ширине с красной строкой. Skip when a customer
    # template is the base — GOST forms already define alignment, first-line
    # indent and heading placement, and overriding them is how "оформление
    # по шаблону" used to come out as a generic Word document.
    if not preserve_template:
        try:
            apply_paragraph_formatting(doc)
        except Exception as e:
            print(f"Paragraph alignment warning: {e}")

    # 6. Сохраняем в байты
    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    
    return file_stream.read()


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Стили, которые python-docx ждёт для add_heading / списков / таблиц.
# Если шаблон заказчика их не определяет, add_heading бросает
# "no style with name 'Heading 2'", convert_markdown_to_docx уходит в
# аварийную ветку и кладёт в документ СЫРОЙ markdown.
_REQUIRED_STYLE_NAMES = (
    "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5", "Heading 6",
    "List Bullet", "List Number", "List Paragraph", "Normal", "Table Grid",
)


def _set_rfonts(element, name: str) -> None:
    """Пишет гарнитуру во все слоты w:rFonts (ascii/hAnsi/cs/eastAsia).

    Одного style.font.name мало: htmldocx и шаблоны ГОСТ часто ставят Times
    в ascii и другую гарнитуру в eastAsia — Word тогда рисует заголовок
    одним шрифтом, а абзац другим.
    """
    rPr = element.find(qn('w:rPr'))
    if rPr is None:
        if element.tag == qn('w:rPr'):
            rPr = element
        else:
            rPr = OxmlElement('w:rPr')
            element.insert(0, rPr)
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    for key in ('ascii', 'hAnsi', 'cs', 'eastAsia'):
        rFonts.set(qn(f'w:{key}'), name)


def _strip_numpr(element) -> None:
    for numPr in list(element.findall(f".//{{{_W_NS}}}numPr")):
        parent = numPr.getparent()
        if parent is not None:
            parent.remove(numPr)


def _strip_heading_numbering(doc) -> None:
    """Снимает нумерацию только со стилей Heading/Title.

    Прямой numPr на абзаце заголовка — наш ГОСТ-контур (раздел 2 и пункты
    2.1 в одном списке). Стилевой outline шаблона оставлять нельзя: он
    делил счётчик со списками, и из 1.3 выходило 5.1.
    """
    for style in doc.styles:
        name = (style.name or "").lower()
        if name.startswith(("heading", "title", "заголовок")):
            _strip_numpr(style.element)


def _unify_body_fonts(doc) -> None:
    """Все прогоны тела — гарнитура Normal. Колонтитулы не трогаем."""
    try:
        name = doc.styles["Normal"].font.name
    except KeyError:
        return
    if not name:
        return
    for p in doc.paragraphs:
        for run in p.runs:
            if run.font.name in {"Courier New", "Consolas", "Lucida Console", "Courier", "Monaco", "Menlo"}:
                continue
            run.font.name = name
            _set_rfonts(run._element, name)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for run in p.runs:
                        if run.font.name in {"Courier New", "Consolas", "Lucida Console", "Courier", "Monaco", "Menlo"}:
                            continue
                        run.font.name = name
                        _set_rfonts(run._element, name)


def _ensure_required_styles(doc) -> None:
    """Доносит в шаблон недостающие определения стилей из стандартного шаблона
    python-docx. Собственные стили шаблона не трогаются — дописываются только
    отсутствующие, поэтому оформление остаётся исходным."""
    import copy

    have = {style.name for style in doc.styles}
    missing = [name for name in _REQUIRED_STYLE_NAMES if name not in have]
    if not missing:
        return
    default_styles = Document().styles
    target = doc.styles.element
    for name in missing:
        try:
            source = default_styles[name].element
        except KeyError:
            continue
        injected = copy.deepcopy(source)
        # У стандартных Heading в python-docx цвет синий (accent1). Подставить
        # такой стиль в шаблон заказчика — это самому принести в деловой
        # документ синие заголовки, которых там быть не должно.
        for color in injected.findall(f".//{{{_W_NS}}}color"):
            color.getparent().remove(color)
        target.append(injected)
    logger.info("В шаблон оформления добавлены недостающие стили: %s", ", ".join(missing))


def _ensure_default_paragraph_style(doc) -> None:
    """Помечает Normal стилем по умолчанию, если в шаблоне не помечен никто.

    LibreOffice при конвертации .doc не ставит w:default ни одному стилю. Из-за
    этого обычные абзацы остаются вообще без стиля: Word берёт для них
    docDefaults и игнорирует и шрифт, и размер, и интервалы шаблона. В готовом
    ИТТ так оказались 32 абзаца из 164.
    """
    styles_root = doc.styles.element
    tag = f"{{{_W_NS}}}style"
    default_attr = f"{{{_W_NS}}}default"
    type_attr = f"{{{_W_NS}}}type"
    id_attr = f"{{{_W_NS}}}styleId"
    paragraph_styles = [el for el in styles_root.findall(tag) if el.get(type_attr) == "paragraph"]
    if any(el.get(default_attr) == "1" for el in paragraph_styles):
        return
    for el in paragraph_styles:
        if (el.get(id_attr) or "").lower() in ("normal", "standard"):
            el.set(default_attr, "1")
            logger.info("Стиль %s помечен как стиль абзаца по умолчанию", el.get(id_attr))
            return


def _normalize_heading_styles(doc) -> None:
    """Заголовок не может быть мельче основного текста и другим шрифтом.

    Замерено на реальном шаблоне ИТТ: его Heading 1 задан 12 pt при тексте
    14 pt, а Heading 2 и 3 не определены вовсе и подставляются со стандартными
    13 pt и чужой гарнитурой. В готовом документе заголовки выходили мельче
    текста и не Times — это то, что заказчик увидел первым.

    Семейство берётся у Normal, размер — не меньше Normal с прибавкой по
    уровню. Явно больший размер, заданный шаблоном, не трогается.
    """
    from docx.shared import Pt

    normal = doc.styles["Normal"]
    base_name = normal.font.name
    base_size = normal.font.size or Pt(14)
    bumps = {"Heading 1": 2, "Heading 2": 1, "Heading 3": 0,
             "Heading 4": 0, "Heading 5": 0, "Heading 6": 0}
    for name, bump in bumps.items():
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        wanted = Pt(base_size.pt + bump)
        if style.font.size is None or style.font.size < wanted:
            style.font.size = wanted
        if base_name:
            style.font.name = base_name
            _set_rfonts(style.element, base_name)
        if style.font.bold is None:
            style.font.bold = True


def _left_align_table_cells(doc) -> None:
    """Ячейки таблиц — по левому краю, без выключки по ширине.

    Выключка правильна для абзацев текста и разрушительна в узкой ячейке:
    «Версия/редакция» растягивалось на строки «В ерсия/ редак ция», а «3.2.7»
    разрывалось надвое. Ячейки наследуют выравнивание из Normal, куда оно
    попадает вместе с оформлением шаблона, поэтому его надо снимать здесь.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if paragraph.paragraph_format.alignment in (None, WD_ALIGN_PARAGRAPH.JUSTIFY):
                        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    paragraph.paragraph_format.first_line_indent = Cm(0)
                    pPr = paragraph._element.get_or_add_pPr()
                    if pPr.find(qn("w:suppressAutoHyphens")) is None:
                        no_hyph = OxmlElement("w:suppressAutoHyphens")
                        no_hyph.set(qn("w:val"), "true")
                        pPr.append(no_hyph)


_MATH_OR_SYMBOL_FONTS = frozenset({
    "Cambria Math", "Symbol", "Wingdings", "Wingdings 2", "Wingdings 3",
    "Webdings", "MT Extra", "MS Reference Specialty",
})


def _typeface_name(value: Optional[str]) -> Optional[str]:
    name = (value or "").strip()
    if not name or name in _MATH_OR_SYMBOL_FONTS:
        return None
    return name


def _rfonts_typeface(r_fonts) -> Optional[str]:
    if r_fonts is None:
        return None
    for key in ("ascii", "hAnsi", "cs"):
        found = _typeface_name(r_fonts.get(qn(f"w:{key}")))
        if found:
            return found
    return None


def _run_typeface(run) -> Optional[str]:
    found = _typeface_name(run.font.name)
    if found:
        return found
    rPr = run._element.rPr
    if rPr is None:
        return None
    return _rfonts_typeface(rPr.rFonts)


def _doc_defaults_typeface(doc) -> tuple:
    """Шрифт и размер из w:docDefaults — то, что Word рисует, когда у прогона нет rFonts.

    У конвертированных .doc ИТТ так набран почти весь текст: Times New Roman 14
    в docDefaults, на прогонах пусто, и одна формула в Cambria Math. Если брать
    «любой названный шрифт», тело уезжает в математический шрифт.
    """
    from docx.shared import Pt

    defaults = doc.styles.element.find(f"{{{_W_NS}}}docDefaults")
    if defaults is None:
        return None, None
    rPr = defaults.find(f".//{{{_W_NS}}}rPr")
    if rPr is None:
        return None, None
    name = _rfonts_typeface(rPr.find(f"{{{_W_NS}}}rFonts"))
    size = None
    sz = rPr.find(f"{{{_W_NS}}}sz")
    if sz is not None:
        raw = sz.get(qn("w:val"))
        if raw and str(raw).isdigit():
            size = Pt(int(raw) / 2)
    return name, size


def _promote_direct_formatting(doc) -> None:
    """Переносит прямое форматирование тела шаблона в стиль Normal.

    Инженерные документы обычно оформлены не стилями, а руками: выделили всё,
    поставили Times New Roman 14, интервал и отступ первой строки. Такое
    форматирование живёт на самих абзацах и исчезает вместе с ними при
    очистке — новый документ выходил дефолтным Calibri 11, хотя пример был
    по ГОСТу. Здесь берётся преобладающее значение по телу шаблона и
    записывается в Normal, но только то, чего стиль не задаёт сам:
    настоящий стиль шаблона всегда важнее замера по абзацам.
    """
    from collections import Counter

    names, sizes, indents, spacings, aligns = Counter(), Counter(), Counter(), Counter(), Counter()
    body_chars = 0
    for paragraph in doc.paragraphs:
        if not paragraph.text.strip():
            continue
        style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
        if style_name.startswith(("heading", "title", "заголовок")):
            continue
        body_chars += len(paragraph.text)
        for run in paragraph.runs:
            # Вес — в символах, а не в числе прогонов: одна подпись под
            # таблицей не должна перевешивать страницы основного текста.
            typeface = _run_typeface(run)
            if typeface:
                names[typeface] += len(run.text)
            if run.font.size:
                sizes[run.font.size] += len(run.text)
        fmt = paragraph.paragraph_format
        if fmt.first_line_indent is not None:
            indents[fmt.first_line_indent] += 1
        if fmt.line_spacing is not None:
            spacings[fmt.line_spacing] += 1
        if fmt.alignment is not None:
            aligns[fmt.alignment] += 1

    normal = doc.styles["Normal"]
    default_name, default_size = _doc_defaults_typeface(doc)
    # Замер побеждает стиль, если им набрано большинство текста примера.
    # Проверено на конвертированном из .doc ИТТ: Normal там формально 10 pt,
    # а 96% символов набраны прямым форматированием в 14 pt — и документы
    # выходили целиком мелкими, потому что «стиль важнее» держало 10 pt.
    majority = max(1, body_chars // 2)

    def _dominant(counter):
        if not counter:
            return None
        value, weight = counter.most_common(1)[0]
        return value if weight >= majority else None

    dominant_name, dominant_size = _dominant(names), _dominant(sizes)
    if dominant_name:
        chosen_name = dominant_name
    elif not _typeface_name(normal.font.name):
        chosen_name = default_name
    else:
        chosen_name = None
    if chosen_name:
        normal.font.name = chosen_name
        _set_rfonts(normal.element, chosen_name)
    if dominant_size is not None:
        normal.font.size = dominant_size
    elif normal.font.size is None and default_size is not None:
        normal.font.size = default_size
    fmt = normal.paragraph_format
    if fmt.first_line_indent is None and indents:
        fmt.first_line_indent = indents.most_common(1)[0][0]
    if fmt.line_spacing is None and spacings:
        fmt.line_spacing = spacings.most_common(1)[0][0]
    if fmt.alignment is None and aligns:
        fmt.alignment = aligns.most_common(1)[0][0]


def blank_copy_of_template(template_bytes: bytes) -> Optional[bytes]:
    """Шаблон без его собственного текста: стили, поля, колонтитулы и нумерация
    остаются, содержимое убирается.

    convert_markdown_to_docx открывает базовый шаблон как документ и дописывает
    новый текст в конец — вместе со всем текстом примера. Для оформления «как в
    исходнике» нужна именно пустая заготовка: иначе каждый из десяти новых
    документов начинался бы с чужого ИТТ целиком.

    Последний <w:sectPr> в теле хранит поля страницы и привязку колонтитулов,
    поэтому он единственный переживает очистку. Возвращает None, если файл
    не открылся как .docx — вызывающий тогда просто работает без шаблона.
    """
    try:
        import copy

        doc = Document(io.BytesIO(template_bytes))
        body = doc.element.body

        # Строго до очистки: прямое форматирование живёт на самих абзацах и
        # исчезнет вместе с ними.
        _promote_direct_formatting(doc)

        # Настройки страницы берём у ПЕРВОГО раздела, а не у последнего.
        # У шаблона с альбомным приложением в конце последний sectPr
        # альбомный — и весь новый документ выходил бы альбомным.
        sect_prs = body.findall(f".//{{{_W_NS}}}sectPr")
        body_sect_pr = body.find(f"{{{_W_NS}}}sectPr")
        if sect_prs and body_sect_pr is not None and sect_prs[0] is not body_sect_pr:
            body.replace(body_sect_pr, copy.deepcopy(sect_prs[0]))

        for child in list(body):
            # sectPr — не содержимое, а настройки страницы этого раздела.
            if not child.tag.endswith("}sectPr"):
                body.remove(child)

        _ensure_required_styles(doc)
        _ensure_default_paragraph_style(doc)
        _strip_heading_numbering(doc)
        _normalize_heading_styles(doc)
        buffer = io.BytesIO()
        doc.save(buffer)
        return buffer.getvalue()
    except Exception as e:
        logger.warning("Не удалось подготовить шаблон оформления: %s", e)
        return None


_LEFTOVER_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(?=\S)")


def _all_paragraphs(doc):
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def scrub_markdown_marks(data: bytes) -> bytes:
    """Убирает из готового .docx остатки markdown: «### 2.1.4 …» и «**».

    Пилот иногда собирает Word своим скриптом, который понимает только # и ##,
    и решётки уходят в текст. Такой абзац становится жирным подзаголовком.
    Файл без остатков возвращается как был."""
    try:
        doc = Document(io.BytesIO(data))
    except Exception:
        return data
    changed = False
    for paragraph in _all_paragraphs(doc):
        runs = paragraph.runs
        if not runs:
            continue
        prefix = _LEFTOVER_HEADING_RE.match(paragraph.text)
        if prefix:
            left = prefix.end()
            for run in runs:
                cut = min(left, len(run.text))
                run.text = run.text[cut:]
                left -= cut
                run.bold = True
                if left <= 0:
                    break
            for run in runs:
                run.bold = True
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.keep_with_next = True
            changed = True
        for run in runs:
            if "**" in run.text:
                run.text = run.text.replace("**", "")
                changed = True
    if not changed:
        return data
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
