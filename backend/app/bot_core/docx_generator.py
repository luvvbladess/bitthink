"""
Модуль для генерации DOCX документов из Markdown/текста.
Использует связку markdown -> html -> docx для поддержки таблиц и форматирования.
"""

import io
import re
import unicodedata
from typing import Optional
import markdown
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, RGBColor
from docx.oxml.shared import OxmlElement
from docx.oxml.ns import qn
from htmldocx import HtmlToDocx
import logging

logger = logging.getLogger(__name__)

# Текст этого абзаца — признак того, что htmldocx не справился и в документ
# лёг сырой markdown. Вызывающий код ищет его, чтобы не выдать такой файл
# пользователю за готовый.
CONVERSION_FAILED_MARKER = "Ошибка при конвертации форматирования. Исходный текст:"

def create_list_numbering(doc, is_bullet=False):
    """
    Создает полностью новый вложенный (multilevel) шаблон нумерации.
    Гарантирует формат 1.1, 1.1.1 для цифр и разные маркеры для bullet-списков.
    """
    from docx.oxml.shared import OxmlElement
    from docx.oxml.ns import qn
    import random
    
    try:
        numbering_part = doc.part.numbering_part
    except (NotImplementedError, AttributeError):
        return None
        
    numbering_element = numbering_part.numbering_definitions._numbering
    
    current_abs_ids = [int(a.get(qn('w:abstractNumId'))) for a in numbering_element.xpath('w:abstractNum')]
    next_abs_id = max(current_abs_ids, default=-1) + 1
    
    abs_num = OxmlElement('w:abstractNum')
    abs_num.set(qn('w:abstractNumId'), str(next_abs_id))
    
    nsid = OxmlElement('w:nsid')
    nsid.set(qn('w:val'), ''.join(random.choices('0123456789ABCDEF', k=8)))
    abs_num.append(nsid)
    
    multiLevelType = OxmlElement('w:multiLevelType')
    multiLevelType.set(qn('w:val'), 'multilevel')
    abs_num.append(multiLevelType)
    
    bullets = ['\u25cf', '\u25cb', '\u25a0', '\u25b7', '\u2666', '\u261e', '\u27a4', '\u25c6', '\u2756']
    
    for i in range(9):
        lvl = OxmlElement('w:lvl')
        lvl.set(qn('w:ilvl'), str(i))
        
        start = OxmlElement('w:start')
        start.set(qn('w:val'), '1')
        lvl.append(start)
        
        numFmt = OxmlElement('w:numFmt')
        lvlText = OxmlElement('w:lvlText')
        lvlJc = OxmlElement('w:lvlJc')
        lvlJc.set(qn('w:val'), 'left')
        
        if is_bullet:
            numFmt.set(qn('w:val'), 'bullet')
            lvlText.set(qn('w:val'), bullets[i])
            rPr = OxmlElement('w:rPr')
            rFonts = OxmlElement('w:rFonts')
            rFonts.set(qn('w:ascii'), 'Arial')
            rFonts.set(qn('w:hAnsi'), 'Arial')
            rFonts.set(qn('w:cs'), 'Arial')
            rPr.append(rFonts)
            lvl.append(rPr)
        else:
            numFmt.set(qn('w:val'), 'decimal')
            text_val = ".".join([f"%{j+1}" for j in range(i+1)]) + "."
            lvlText.set(qn('w:val'), text_val)
            
        lvl.append(numFmt)
        lvl.append(lvlText)
        lvl.append(lvlJc)
        
        pPr = OxmlElement('w:pPr')
        ind = OxmlElement('w:ind')
        ind.set(qn('w:left'), str(720 + (i * 360)))
        ind.set(qn('w:hanging'), '360')
        pPr.append(ind)
        lvl.append(pPr)
        
        abs_num.append(lvl)
        
    nums = numbering_element.xpath('w:num')
    if nums:
        nums[0].addprevious(abs_num)
    else:
        numbering_element.append(abs_num)
        
    current_ids = [int(n.get(qn('w:numId'))) for n in numbering_element.xpath('w:num')]
    next_num_id = max(current_ids, default=0) + 1
    
    num = OxmlElement('w:num')
    num.set(qn('w:numId'), str(next_num_id))
    
    absId = OxmlElement('w:abstractNumId')
    absId.set(qn('w:val'), str(next_abs_id))
    num.append(absId)
    
    numbering_element.append(num)
    
    return next_num_id

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
    """
    Пост-обработка документа для сброса и настройки многоуровневых списков (Multilevel 1.1.1).
    Каждый блок верхнего уровня (ilvl=0) после другого верхнего уровня считается
    ОДНИМ связным многоуровневым списком. Разрыв между блоками (Normal-абзац) сбрасывает счётчик.
    """
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.table import CT_Tbl
    from docx.text.paragraph import Paragraph
    from docx.oxml.ns import qn

    # Один numId для всего текущего непрерывного многоуровневого блока
    current_num_id_num = None
    current_num_id_bullet = None
    # Предыдущий уровень вложенности (чтобы отслеживать возврат на 0)
    prev_ilvl = -1
    
    list_style_keywords = {'list', 'bullet', 'number', 'список'}

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            p = Paragraph(child, doc)
            style_name = p.style.name.lower() if p.style else ""
            is_empty = not p.text.strip()
            
            has_num_pr = False
            try:
                pPr_elem = p._element.pPr
                if pPr_elem is not None and pPr_elem.numPr is not None:
                    has_num_pr = True
            except Exception: pass
            
            is_list_style = any(kw in style_name for kw in list_style_keywords)
            
            if is_list_style or has_num_pr:
                # 1. Определяем тип (маркер или цифра)
                is_bullet = 'bullet' in style_name
                if has_num_pr and not is_bullet:
                    try:
                        num_id_val = p._element.pPr.numPr.numId.val
                        numbering = doc.part.numbering_part.numbering_definitions._numbering
                        num_def = numbering.get_num(num_id_val)
                        abstract_num = numbering.find_abstract_num(num_def.abstractNumId.val)
                        if getattr(getattr(abstract_num, 'lvl_lst', [None])[0], 'numFmt', None) and abstract_num.lvl_lst[0].numFmt.val == 'bullet':
                            is_bullet = True
                    except Exception: pass

                # 2. Определяем уровень вложенности на основе отступа (htmldocx: 0.5in = level 1, 1.0in = level 2, ...)
                ilvl = 0
                try:
                    if p.paragraph_format and p.paragraph_format.left_indent:
                        inches = p.paragraph_format.left_indent.inches
                        computed = int(round(inches / 0.5)) - 1
                        if computed > 0:
                            ilvl = computed
                except Exception: pass
                
                ilvl = min(max(ilvl, 0), 8)
                
                # 3. Сброс numId при разрыве: если текущий элемент на уровне 0,
                #    а предыдущий тоже был на уровне 0 (т.е. это новый верхний пункт),
                #    НО между ними была пустая строка — сброс уже произошёл через ветку else.
                #    Если же нет разрыва (непрерывный список), продолжаем тот же numId.

                try:
                    if 'List Paragraph' in doc.styles:
                        p.style = 'List Paragraph'
                except Exception: pass

                if is_bullet:
                    if current_num_id_bullet is None:
                        current_num_id_bullet = create_list_numbering(doc, True)
                    target_num_id = current_num_id_bullet
                else:
                    if current_num_id_num is None:
                        current_num_id_num = create_list_numbering(doc, False)
                    target_num_id = current_num_id_num
                
                prev_ilvl = ilvl
                
                if target_num_id is not None:
                    pPr = p._element.get_or_add_pPr()
                    numPr = pPr.get_or_add_numPr()
                    
                    numId_el = numPr.get_or_add_numId()
                    numId_el.set(qn('w:val'), str(target_num_id))
                    
                    ilvl_el = numPr.get_or_add_ilvl()
                    ilvl_el.set(qn('w:val'), str(ilvl))
            else:
                if not is_empty:
                    # Реальный текстовый разрыв (не пустая строка) — сбрасываем счётчики
                    current_num_id_num = None
                    current_num_id_bullet = None
                    prev_ilvl = -1
                elif is_empty and prev_ilvl == 0:
                    # Пустая строка между пунктами верхнего уровня = новый независимый список
                    current_num_id_num = None
                    current_num_id_bullet = None
                    prev_ilvl = -1
        
        elif isinstance(child, CT_Tbl):
            current_num_id_num = None
            current_num_id_bullet = None
            prev_ilvl = -1

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
    MIN_RATIO = 0.07       # минимум 7% ширины страницы на столбец
    MAX_RATIO = 0.65       # максимум 65% ширины страницы на столбец

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
            longest_word = max((len(w) for w in re.split(r"[\s/]+", header) if w), default=0)
            weights.append(max(weight, longest_word, 4))

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

        if is_heading:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = None
        elif is_list or is_short_label:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.first_line_indent = None
        else:
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = FIRST_LINE_INDENT


def strip_blockquote_markers(markdown_text: str) -> str:
    """
    htmldocx рендерит Markdown-цитаты (строки '> ...') буквальным символом '>'
    на каждой строке плюс схлопывает несколько строк цитаты в один абзац с
    выравниванием по ширине - в документе это выглядит как рваные пробелы и
    лишние символы '>'. Технические тексты обычно используют '>' как
    неформальное визуальное выделение, а не как настоящую цитату, поэтому
    убираем маркер целиком перед конвертацией - остальная пост-обработка
    (нормализация списков, абзацев) сама разберётся с получившимся обычным
    текстом. Должно выполняться ДО escape_stray_angle_brackets: иначе '>' уже
    станет '&gt;' и markdown всё равно не распознает в нём цитату.
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


def convert_markdown_to_docx(markdown_text: str, base_template_bytes: Optional[bytes] = None) -> bytes:
    """
    Конвертирует Markdown текст в DOCX документ.

    Args:
        markdown_text: Исходный текст в формате Markdown
        base_template_bytes: Байты базового шаблона DOCX (опционально)

    Returns:
        Байты сгенерированного DOCX файла
    """
    # -2. Убираем маркеры Markdown-цитат ('> ...'), которые htmldocx рендерит
    # с лишними '>' и рваными пробелами (см. strip_blockquote_markers).
    markdown_text = strip_blockquote_markers(markdown_text)

    # -1. Защита от случайных '<'/'>' в тексте (формулы в угловых скобках и т.п.),
    # которые markdown -> HTML конвертер иначе примет за HTML-теги и вырежет.
    markdown_text = escape_stray_angle_brackets(markdown_text)

    # 0. Препроцессинг текста
    lines = markdown_text.split('\n')
    fixed_lines = []
    
    for i, line in enumerate(lines):
        # 1. Удаляем пустые пункты списков (строки вида "1. ", "2. ", "- " без текста)
        stripped = line.strip()
        if re.match(r'^\d+\.\s*$', stripped) or re.match(r'^[\*\-]\s*$', stripped):
            continue
        
        # 2. Исправление таблиц
        if "|" in line and i > 0 and lines[i-1].strip() and not lines[i-1].strip().startswith("|"):
             if i + 1 < len(lines) and set(lines[i+1].strip()) <= set("|-:| "):
                 fixed_lines.append("")
        
        # 3. Нормализация заголовков
        if re.match(r'^\s*#{1,6}\s', line) and i > 0 and lines[i-1].strip():
             fixed_lines.append("")
        
        # 4. Нормализация списков (вставляем пустую строку перед началом списка, если её нет)
        if re.match(r'^\s*(\d+\.|\*|-)\s', line) and i > 0 and lines[i-1].strip():
             if not re.match(r'^\s*(\d+\.|\*|-)\s', lines[i-1]):
                 fixed_lines.append("")
             
        fixed_lines.append(line)
        
    markdown_text = "\n".join(fixed_lines)

    # 5. Исправление сломанного форматирования жирного текста (удаляем пробелы внутри **)
    # LLM часто генерируют "** текст **", что не парсится markdown.
    markdown_text = re.sub(r'\*\*([^*]+?)\*\*', lambda m: '**' + m.group(1).strip() + '**', markdown_text)

    # 6. Второй проход: надёжная вставка пустых строк вокруг блоков таблиц.
    # Стандартный парсер markdown требует пустую строку перед таблицей.
    # Первый проход (шаг 2) проверяет только следующую строку — ненадёжно.
    # Этот проход явно оборачивает каждый блок '|'-строк пустыми строками.
    pass2_lines = markdown_text.split('\n')
    table_fixed = []
    i2 = 0
    while i2 < len(pass2_lines):
        line2 = pass2_lines[i2]
        if "|" in line2 and line2.strip().startswith("|"):
            if table_fixed and table_fixed[-1].strip():
                table_fixed.append("")
            while i2 < len(pass2_lines) and "|" in pass2_lines[i2] and pass2_lines[i2].strip().startswith("|"):
                table_fixed.append(pass2_lines[i2])
                i2 += 1
            if i2 < len(pass2_lines) and pass2_lines[i2].strip():
                table_fixed.append("")
        else:
            table_fixed.append(line2)
            i2 += 1
    markdown_text = "\n".join(table_fixed)

    # 7. Де-фенсинг "случайных" блоков кода без указания языка.
    # LLM иногда оборачивает обычный текст (примеры, цитаты, фрагменты для замены) в ``` ```,
    # хотя это не код. markdown.fenced_code превращает такой блок в <pre><code>, а htmldocx
    # рисует его моноширинным шрифтом — документ выглядит "рваным" по шрифтам.
    # Если блок начинается с ``` без языка или с текстовым языком (```text), и не похож
    # на код — убираем обёртку ``` и оставляем текст как обычные абзацы.
    _CODE_INDICATORS = (
        'def ', 'function ', 'class ', 'import ', 'const ', 'let ', 'var ', 'public ',
        'private ', 'void ', 'return ', '{', '}', ';', '=>', '<?php', '#include',
        'SELECT ', 'INSERT ', 'UPDATE ', 'CREATE TABLE', '<html', '<div', '</', '==', '!=',
    )

    def _looks_like_code(text: str) -> bool:
        return any(ind in text for ind in _CODE_INDICATORS)

    defenced = []
    src_lines = markdown_text.split('\n')
    i3 = 0
    while i3 < len(src_lines):
        line3 = src_lines[i3]
        if re.match(r'^```(?:text|txt|markdown|md)?\s*$', line3.strip(), re.IGNORECASE):
            block = []
            j3 = i3 + 1
            while j3 < len(src_lines) and src_lines[j3].strip() != '```':
                block.append(src_lines[j3])
                j3 += 1
            if j3 < len(src_lines) and not _looks_like_code('\n'.join(block)):
                # Закрывающий ``` найден, и содержимое не похоже на код — снимаем обёртку
                defenced.extend(block)
                i3 = j3 + 1
                continue
            if j3 >= len(src_lines):
                i3 += 1
                continue
        defenced.append(line3)
        i3 += 1
    markdown_text = "\n".join(defenced)

    # 1. Конвертируем Markdown в HTML
    html_text = markdown.markdown(
        markdown_text,
        extensions=['tables', 'extra', 'fenced_code', 'nl2br']
    )
    
    # htmldocx ломается и теряет списки (оставляя Normal абзацы), если Markdown парсер 
    # оборачивает текст внутри <li> в параграфы <p>. Поэтому мы 'уплощаем' их.
    html_text = re.sub(r'<li>\s*<p>', '<li>', html_text)
    html_text = re.sub(r'</p>\s*(<(ol|ul)>)', r'\1', html_text)
    html_text = re.sub(r'</p>\s*</li>', '</li>', html_text)
    
    # 2. Создаем документ и парсер
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
    new_parser = HtmlToDocx()
    
    # 3. Парсим HTML и добавляем в документ
    try:
        new_parser.add_html_to_document(html_text, doc)
    except Exception as e:
        # В случае ошибки добавляем текст как есть
        print(f"HTMLDOCX CRITICAL ERROR: {e}")
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
        fix_numbered_lists(doc)
    except Exception as e:
        print(f"List fix warning: {e}")

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

# Стили, которыми htmldocx размечает результат. Если шаблон заказчика их не
# определяет — а минимальный шаблон обычно определяет только свои — htmldocx
# бросает "no style with name 'Heading 2'", convert_markdown_to_docx уходит в
# аварийную ветку и кладёт в документ СЫРОЙ markdown. Молча: сводка при этом
# всё равно сообщает, что оформление взято из шаблона.
_REQUIRED_STYLE_NAMES = (
    "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5", "Heading 6",
    # htmldocx верстает <ul> стилем List Bullet, а <ol> — List Number. Их
    # отсутствие в шаблоне ронял конвертацию на первом же списке: заказчик
    # получил документ с сырым markdown («- Заказчик – ООО ...») вместо текста.
    "List Bullet", "List Number", "List Paragraph", "Normal", "Table Grid",
)


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
        if base_name and style.font.name is None:
            style.font.name = base_name
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
    for paragraph in doc.paragraphs:
        if not paragraph.text.strip():
            continue
        style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
        if style_name.startswith(("heading", "title", "заголовок")):
            continue
        for run in paragraph.runs:
            if run.font.name:
                names[run.font.name] += 1
            if run.font.size:
                sizes[run.font.size] += 1
        fmt = paragraph.paragraph_format
        if fmt.first_line_indent is not None:
            indents[fmt.first_line_indent] += 1
        if fmt.line_spacing is not None:
            spacings[fmt.line_spacing] += 1
        if fmt.alignment is not None:
            aligns[fmt.alignment] += 1

    normal = doc.styles["Normal"]
    if normal.font.name is None and names:
        normal.font.name = names.most_common(1)[0][0]
    if normal.font.size is None and sizes:
        normal.font.size = sizes.most_common(1)[0][0]
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
        buffer = io.BytesIO()
        doc.save(buffer)
        return buffer.getvalue()
    except Exception as e:
        logger.warning("Не удалось подготовить шаблон оформления: %s", e)
        return None
