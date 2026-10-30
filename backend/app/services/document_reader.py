"""Structured DOCX reading content. Never return executable document HTML."""
import io
import re
import zipfile
from urllib.parse import urlsplit

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table

ALLOWED_IMAGES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}


def open_docx(data: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 4096 or sum(e.file_size for e in entries) > 120 * 1024 * 1024:
                raise ValueError('Документ слишком большой для режима чтения. Откройте «Оригинал».')
        return Document(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError('Не удалось прочитать документ. Откройте «Оригинал».') from exc


def image_bytes(data: bytes, relationship: str):
    document = open_docx(data)
    part = document.part.related_parts.get(relationship)
    if part is None or part.content_type not in ALLOWED_IMAGES:
        raise ValueError('Изображение недоступно в режиме чтения.')
    return part.blob, part.content_type


def reading_content(data: bytes, image_url):
    document = open_docx(data)
    nodes = 0
    characters = 0
    counters = {}
    warnings = set()
    notes = set()

    def number_text(value, fmt):
        if fmt in {'upperRoman', 'lowerRoman'} and 0 < value < 4000:
            result = ''
            for size, label in [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]:
                while value >= size:
                    result += label; value -= size
            return result.lower() if fmt == 'lowerRoman' else result
        if fmt in {'upperLetter', 'lowerLetter'} and value > 0:
            result = ''
            while value:
                value, remainder = divmod(value-1, 26); result = chr(65+remainder) + result
            return result.lower() if fmt == 'lowerLetter' else result
        if fmt == 'decimalZero':
            return str(value).zfill(2)
        if fmt not in {'decimal', 'none'}:
            warnings.add('Специальное оформление некоторых списков доступно в «Оригинале».')
        return str(value)

    def text(value, style=None, href=None):
        nonlocal characters
        characters += len(value)
        if characters > 500_000:
            raise ValueError('Документ слишком большой для режима чтения. Откройте «Оригинал».')
        return {'text': value, **(style or {}), **({'href': href} if href else {})}

    def inlines(element, style=None, href=None):
        result = []
        for child in element:
            if child.tag == qn('w:del'):
                continue
            if child.tag == qn('w:r'):
                props = child.find(qn('w:rPr'))
                run_style = dict(style or {})
                if props is not None:
                    for prop, name in [('b', 'bold'), ('i', 'italic'), ('u', 'underline'), ('strike', 'strike')]:
                        item = props.find(qn('w:' + prop))
                        if item is not None:
                            run_style[name] = item.get(qn('w:val'), 'true') not in {'0', 'false', 'none'}
                    alignment = props.find(qn('w:vertAlign'))
                    if alignment is not None:
                        run_style['position'] = alignment.get(qn('w:val'))
                result.extend(inlines(child, run_style, href))
            elif child.tag == qn('w:hyperlink'):
                rel = document.part.rels.get(child.get(qn('r:id')))
                target = rel.target_ref if rel and rel.is_external else ''
                safe = target if urlsplit(target).scheme.lower() in {'https', 'http', 'mailto', 'tel'} else None
                result.extend(inlines(child, style, safe))
            elif child.tag == qn('w:t'):
                result.append(text(child.text or '', style, href))
            elif child.tag in {qn('w:br'), qn('w:cr')}:
                result.append(text('\n', style))
            elif child.tag == qn('w:tab'):
                result.append(text('\t', style))
            elif child.tag == qn('w:footnoteReference'):
                note = child.get(qn('w:id'), '')
                notes.add(note)
                result.append(text('[' + note + ']', {'position': 'superscript'}))
            elif child.tag == qn('w:commentReference'):
                warnings.add('Комментарии доступны в «Оригинале».')
            elif child.tag == qn('w:drawing') or child.tag == qn('w:pict'):
                embeds = child.findall('.//' + qn('a:blip')) + child.findall('.//{urn:schemas-microsoft-com:vml}imagedata')
                if not embeds:
                    warnings.add('Диаграммы и плавающие объекты доступны в «Оригинале».')
                for embed in embeds:
                    rel_id = embed.get(qn('r:embed')) or embed.get(qn('r:id'))
                    part = document.part.related_parts.get(rel_id)
                    if part and part.content_type in ALLOWED_IMAGES:
                        description = next(iter(child.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr')), None)
                        extent = next(iter(child.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent')), None)
                        dimensions = {'width': max(1, min(10000, int(extent.get('cx', '0')) // 9525)), 'height': max(1, min(10000, int(extent.get('cy', '0')) // 9525))} if extent is not None else {}
                        result.append({'image': image_url(rel_id), 'alt': (description.get('descr') or description.get('name')) if description is not None else 'Изображение документа', **dimensions})
                    else:
                        warnings.add('Некоторые иллюстрации доступны в «Оригинале».')
            elif child.tag == qn('m:oMath') or child.tag == qn('m:oMathPara'):
                warnings.add('Формулы с математической разметкой доступны в «Оригинале».')
                value = ''.join(child.itertext())
                if value:
                    result.append(text(value, style))
            elif child.tag not in {qn('w:pPr'), qn('w:rPr')}:
                result.extend(inlines(child, style, href))
        return result

    def list_label(paragraph):
        num = paragraph._p.find('./' + qn('w:pPr') + '/' + qn('w:numPr'))
        if num is None and paragraph.style is not None:
            num = paragraph.style.element.find('./' + qn('w:pPr') + '/' + qn('w:numPr'))
        if num is None:
            return None
        id_element = num.find(qn('w:numId'))
        if id_element is None or id_element.get(qn('w:val')) == '0':
            return None
        num_id = id_element.get(qn('w:val'))
        level_element = num.find(qn('w:ilvl'))
        level = int(level_element.get(qn('w:val'))) if level_element is not None else 0
        root = document.part.numbering_part.element
        number = next((n for n in root.findall(qn('w:num')) if n.get(qn('w:numId')) == num_id), None)
        abstract_id = number.find(qn('w:abstractNumId')) if number is not None else None
        abstract = next((n for n in root.findall(qn('w:abstractNum')) if abstract_id is not None and n.get(qn('w:abstractNumId')) == abstract_id.get(qn('w:val'))), None)
        def level_definition(index):
            override = next((n for n in number.findall(qn('w:lvlOverride')) if n.get(qn('w:ilvl')) == str(index)), None) if number is not None else None
            base = next((n for n in abstract.findall(qn('w:lvl')) if n.get(qn('w:ilvl')) == str(index)), None) if abstract is not None else None
            custom = override.find(qn('w:lvl')) if override is not None else None
            return custom if custom is not None else base, override
        definition, override = level_definition(level)
        fmt = definition.find(qn('w:numFmt')) if definition is not None else None
        if fmt is not None and fmt.get(qn('w:val')) == 'bullet':
            return {'label': '•', 'level': min(level, 4)}
        start = definition.find(qn('w:start')) if definition is not None else None
        if override is not None and override.find(qn('w:startOverride')) is not None:
            start = override.find(qn('w:startOverride'))
        key = (num_id, level)
        counters[key] = counters.get(key, int(start.get(qn('w:val'))) - 1 if start is not None else 0) + 1
        for existing in list(counters):
            if existing[0] == num_id and existing[1] > level:
                del counters[existing]
        template = definition.find(qn('w:lvlText')) if definition is not None else None
        label = template.get(qn('w:val')) if template is not None else '%' + str(level+1) + '.'
        for index in range(level+1):
            item, _ = level_definition(index)
            style = item.find(qn('w:numFmt')) if item is not None else None
            label = label.replace('%'+str(index+1), number_text(counters.get((num_id,index),1), style.get(qn('w:val')) if style is not None else 'decimal'))
        return {'label': label, 'level': min(level, 4)}

    def blocks(parent, owner, depth=0):
        nonlocal nodes
        if depth > 4:
            raise ValueError('Сложные вложенные таблицы доступны в «Оригинале».')
        output = []
        for child in parent:
            nodes += 1
            if nodes > 10_000:
                raise ValueError('Документ слишком большой для режима чтения. Откройте «Оригинал».')
            if child.tag == qn('w:p'):
                paragraph = Paragraph(child, owner)
                content = inlines(child)
                if not content:
                    continue
                name = paragraph.style.name if paragraph.style is not None else ''
                heading = re.search(r'(?:heading|заголовок)\s*(\d)', name, re.I)
                block = {'type': 'paragraph', 'content': content}
                if heading:
                    block['heading'] = min(6, int(heading.group(1)))
                elif name.lower() in {'title', 'название'}:
                    block['heading'] = 1
                label = list_label(paragraph)
                if label:
                    block['list'] = label
                output.append(block)
            elif child.tag == qn('w:tbl'):
                table = Table(child, owner)
                rows = []
                anchors = {}
                for row in table.rows:
                    cells = []
                    groups = []
                    for cell in row.cells:
                        if groups and groups[-1][0]._tc is cell._tc:
                            groups[-1][1] += 1
                        else:
                            groups.append([cell, 1])
                    for cell, span in groups:
                        if cell._tc in anchors:
                            anchors[cell._tc]['rowSpan'] += 1
                        else:
                            item = {'span': span, 'rowSpan': 1, 'blocks': blocks(cell._tc, cell, depth+1)}
                            cells.append(item)
                            anchors[cell._tc] = item
                    rows.append({'header': row._tr.find('./' + qn('w:trPr') + '/' + qn('w:tblHeader')) is not None, 'cells': cells})
                output.append({'type': 'table', 'rows': rows})
            elif child.tag in {qn('w:sdt'), qn('w:sdtContent'), qn('w:ins')}:
                output.extend(blocks(child, owner, depth))
        return output

    content = blocks(document.element.body, document)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if notes and 'word/footnotes.xml' in archive.namelist():
            from lxml import etree
            root = etree.fromstring(archive.read('word/footnotes.xml'), parser=etree.XMLParser(resolve_entities=False, no_network=True))
            content.append({'type': 'paragraph', 'heading': 2, 'content': [text('Сноски')]})
            for note in root:
                if note.get(qn('w:id')) in notes:
                    value = ' '.join(''.join(p.itertext(qn('w:t'))) for p in note.findall(qn('w:p')))
                    content.append({'type': 'paragraph', 'content': [text('[' + note.get(qn('w:id')) + '] ' + value)]})
        if any(re.fullmatch(r'word/(?:header|footer)\d+\.xml', n) for n in archive.namelist()):
            warnings.add('Колонтитулы и расположение на страницах доступны в «Оригинале».')
    return {'blocks': content, 'warnings': sorted(warnings)}
