"""
Модуль для извлечения текста из документов (DOCX, PDF)
"""

import io
import re
import logging
import base64
import asyncio
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Optional

from docx import Document
import pdfplumber
import fitz  # PyMuPDF
import pandas as pd

logger = logging.getLogger(__name__)


async def extract_text_from_docx(file_data: bytes) -> str:
    """Извлекает текст из DOCX файла в отдельном потоке."""
    def _extract():
        try:
            doc = Document(io.BytesIO(file_data))
            text_parts = []
            
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    prefix = ""
                    # Пытаемся определить, список ли это
                    try:
                        pPr = paragraph._element.pPr
                        if pPr is not None and pPr.numPr is not None:
                            ilvl = 0
                            if pPr.numPr.ilvl is not None:
                                ilvl = int(pPr.numPr.ilvl.val)
                            # Добавляем визуальный маркер уровня для ИИ
                            prefix = f"[L{ilvl+1}] "
                    except Exception:
                        pass
                    
                    text_parts.append(prefix + paragraph.text)
            
            # Извлекаем текст из таблиц
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        if cell.text.strip():
                            row_text.append(cell.text.strip())
                    if row_text:
                        text_parts.append(" | ".join(row_text))
            
            result = "\n".join(text_parts)
            if len(result) > MAX_EXTRACT_CHARS:
                result = result[:MAX_EXTRACT_CHARS] + "\n\n[Текст обрезан: файл слишком длинный для одного сообщения.]"
            return result
        except Exception as e:
            return f"Ошибка при чтении DOCX: {str(e)}"
            
    return await asyncio.to_thread(_extract)

# Лимиты для извлечения изображений из PDF
MAX_IMAGES_PER_PDF = 8
MIN_IMAGE_SIZE = 5000
MIN_IMAGE_DIMENSION = 80
MAX_PDF_PAGES = 40
MAX_PDF_TABLE_PAGES = 6
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_EXTRACT_CHARS = 180_000
_OCR_MAX_SIDE = 1800


def _pdf_text_is_usable(text: str) -> bool:
    """False for empty pages and WinAnsi Cyrillic collapse (IIIII / nnnnn)."""
    stripped = (text or "").strip()
    if len(stripped) < 8:
        return False
    letters = [ch for ch in stripped if ch.isalpha()]
    if len(letters) >= 12:
        top, count = Counter(ch.lower() for ch in letters).most_common(1)[0]
        if count / len(letters) >= 0.45 and top in {"i", "n", "l", "x"}:
            return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", stripped)
    return len(words) >= 1


def _image_is_blank_or_black(img_bytes: bytes) -> bool:
    """Excel-to-PDF often embeds a fully black JPEG; the page pixmap is readable."""
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(img_bytes)).convert("L")
        image.thumbnail((96, 96))
        hist = image.histogram()
        total = sum(hist) or 1
        dark = sum(hist[:16]) / total
        bright = sum(hist[240:]) / total
        return dark > 0.9 or bright > 0.97
    except Exception:
        return False


def _page_png_for_ocr(page, max_side: int = _OCR_MAX_SIDE) -> bytes:
    width = max(float(page.rect.width), 1.0)
    height = max(float(page.rect.height), 1.0)
    scale = min(3.0, max_side / max(width, height))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return pixmap.tobytes("png")


async def _ocr_image_via_openai(image_bytes: bytes, user_id: int = None) -> str:
    """
    Отправляет изображение в OpenAI Vision API для распознавания текста.
    Возвращает извлечённый текст или описание содержимого.
    """
    from openai import AsyncOpenAI
    from config import OPENAI_API_KEY
    from conversations import conversation_manager

    # Используем gpt-5.6-luna для OCR — дешёвая, быстрая, с поддержкой Vision
    OCR_MODEL = "gpt-5.6-luna"
    
    try:
        # Используем глобальный клиент, чтобы не создавать новый на каждую картинку
        if not hasattr(_ocr_image_via_openai, "_client"):
            _ocr_image_via_openai._client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        client = _ocr_image_via_openai._client
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        mime = "image/jpeg" if image_bytes[:3] == b"\xff\xd8\xff" else "image/png"
        
        response = await client.chat.completions.create(
            model=OCR_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Внимательно проанализируй это изображение и извлеки ВСЮ информацию:\n"
                            "1. Если это ЧЕРТЁЖ или ТЕХНИЧЕСКИЙ РИСУНОК – перечисли ВСЕ размеры (в мм), "
                            "обозначения (R, Ø, ∠ и т.д.), допуски, шероховатости, номера позиций. "
                            "Опиши геометрию детали и расположение элементов.\n"
                            "2. Если это ТАБЛИЦА, штатное расписание или Excel-лист – воспроизведи "
                            "все строки, колонки и числа, ничего не сокращай.\n"
                            "3. Если это ГРАФИК или ДИАГРАММА – перечисли все оси, значения, подписи и данные.\n"
                            "4. Если это СХЕМА – опиши все элементы и связи между ними.\n"
                            "5. Извлеки ВЕСЬ текст, подписи и надписи на изображении.\n"
                            "Если кадр почти чёрный или пустой – так и скажи, не выдумывай таблицу.\n"
                            "Будь максимально точен и подробен. Отвечай только контентом, без вступлений."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64_image}",
                            "detail": "high"
                        }
                    }
                ]
            }],
            max_completion_tokens=4000
        )

        usage = getattr(response, "usage", None)
        if usage and user_id:
            conversation_manager.track_tokens(
                user_id, OCR_MODEL,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )

        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"OCR via OpenAI failed: {e}")
        return f"[Не удалось распознать изображение: {str(e)[:80]}]"


async def extract_tables_from_pdf_page(page) -> str:
    """
    Извлекает таблицы с конкретной страницы PDF через pdfplumber 
    и конвертирует их в Markdown для ИИ.
    """
    try:
        tables = page.extract_tables()
        if not tables:
            return ""
            
        md_tables = []
        for i, table in enumerate(tables):
            if not table or not any(row for row in table if any(cell for cell in row)):
                continue
                
            # Чистим данные от None и лишних пробелов
            cleaned_table = []
            for row in table:
                cleaned_row = [(str(cell).strip().replace("\n", " ") if cell is not None else "") for cell in row]
                cleaned_table.append(cleaned_row)
            
            if not cleaned_table:
                continue
                
            # Формируем Markdown
            headers = cleaned_table[0]
            rows = cleaned_table[1:]
            
            md = f"\n[TABLE {i+1} START]\n"
            # Заголовки
            md += "| " + " | ".join(headers) + " |\n"
            # Разделитель
            md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
            # Данные
            for row in rows:
                md += "| " + " | ".join(row) + " |\n"
            md += f"[TABLE {i+1} END]\n"
            md_tables.append(md)
            
        return "\n".join(md_tables)
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")
        return ""


async def extract_text_from_pdf(file_data: bytes, status_callback=None, user_id: int = None) -> str:
    """
    Извлекает текст из PDF файла, включая распознавание текста на изображениях.
    Тяжёлое извлечение вынесено в поток. Большие PDF читаются частично, без pdfplumber на сотнях страниц.
    """
    try:
        def _extract_base_data():
            if len(file_data) > MAX_PDF_BYTES:
                mb = MAX_PDF_BYTES // (1024 * 1024)
                return (
                    [f"PDF больше {mb} МБ. Пришлите выдержку или файл меньшего размера."],
                    [],
                    "",
                )

            parts: list[str] = []
            img_metadata: list[tuple[bytes, int, int, int]] = []
            plumber_pdf = None
            notice = ""
            with fitz.open(stream=file_data, filetype="pdf") as fitz_doc:
                num_pages = len(fitz_doc)
                take = min(num_pages, MAX_PDF_PAGES)
                if num_pages > take:
                    notice = (
                        f"В файле {num_pages} страниц. Прочитал первые {take} – "
                        "целиком такой том в чат не поместится.\n"
                    )
                if take <= MAX_PDF_TABLE_PAGES:
                    try:
                        plumber_pdf = pdfplumber.open(io.BytesIO(file_data))
                    except Exception:
                        plumber_pdf = None
                try:
                    for p_num in range(take):
                        page = fitz_doc[p_num]
                        page_text = page.get_text().strip()
                        page_content = f"--- Страница {p_num + 1} ---\n"
                        if plumber_pdf is not None and p_num < len(plumber_pdf.pages):
                            try:
                                tables = plumber_pdf.pages[p_num].extract_tables()
                            except Exception:
                                tables = None
                            if tables:
                                md_tables = []
                                for i, table in enumerate(tables):
                                    if not table or not any(row for row in table if any(cell for cell in row)):
                                        continue
                                    cleaned_table = [
                                        [(str(cell).strip().replace("\n", " ") if cell is not None else "") for cell in row]
                                        for row in table
                                    ]
                                    if not cleaned_table:
                                        continue
                                    headers = cleaned_table[0]
                                    md = f"\n[TABLE {i+1} START]\n| " + " | ".join(headers) + " |\n"
                                    md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                    for row in cleaned_table[1:]:
                                        md += "| " + " | ".join(row) + " |\n"
                                    md += f"[TABLE {i+1} END]\n"
                                    md_tables.append(md)
                                if md_tables:
                                    page_content += "\n--- ТАБЛИЦЫ ---\n" + "\n".join(md_tables) + "\n"
                        usable = _pdf_text_is_usable(page_text)
                        if usable:
                            page_content += "\n--- ТЕКСТ ---\n" + page_text
                        elif page_text:
                            page_content += "\n[Текст слоя PDF без кириллицы – читаю страницу как изображение]\n"
                        parts.append(page_content)
                        if len(img_metadata) >= MAX_IMAGES_PER_PDF:
                            continue
                        if not usable:
                            try:
                                png = _page_png_for_ocr(page)
                                if png and not _image_is_blank_or_black(png):
                                    img_metadata.append((png, p_num, 0, 0))
                            except Exception:
                                logger.debug("PDF page raster failed page=%s", p_num, exc_info=True)
                            continue
                        for img_info in page.get_images(full=True):
                            if len(img_metadata) >= MAX_IMAGES_PER_PDF:
                                break
                            try:
                                xref = img_info[0]
                                base_image = fitz_doc.extract_image(xref)
                                if not base_image:
                                    continue
                                img_bytes = base_image["image"]
                                w, h = base_image.get("width", 0), base_image.get("height", 0)
                                if (
                                    len(img_bytes) >= MIN_IMAGE_SIZE
                                    and w >= MIN_IMAGE_DIMENSION
                                    and h >= MIN_IMAGE_DIMENSION
                                    and not _image_is_blank_or_black(img_bytes)
                                ):
                                    img_metadata.append((img_bytes, p_num, w, h))
                            except Exception:
                                continue
                finally:
                    if plumber_pdf is not None:
                        plumber_pdf.close()
            return parts, img_metadata, notice

        # Выполняем базовое извлечение
        text_parts, images_to_process, notice = await asyncio.to_thread(_extract_base_data)
        
        # 2. Если есть изображения — запускаем OCR параллельно (Async OpenAI)
        if images_to_process:
            if status_callback: 
                await status_callback(f"🖼 Найдено {len(images_to_process)} изображений. Распознаю текст...")

            # Ограничиваем количество одновременных запросов к OpenAI
            semaphore = asyncio.Semaphore(10)
            
            async def sem_ocr(img_data, idx, p_num, w, h):
                async with semaphore:
                    text = await _ocr_image_via_openai(img_data, user_id=user_id)
                    return text, idx, p_num, w, h

            ocr_tasks = [
                sem_ocr(img[0], i, img[1], img[2], img[3]) 
                for i, img in enumerate(images_to_process)
            ]
            ocr_results = await asyncio.gather(*ocr_tasks)
            
            # Добавляем результаты OCR к соответствующим страницам
            for text, idx, p_num, w, h in ocr_results:
                if not text.strip() or "[Не удалось распознать" in text: continue
                if 0 <= p_num < len(text_parts):
                    ocr_block = f"\n\n[📷 Изображение {idx+1} (стр. {p_num+1}, {w}x{h}px)]\n{text}\n[/Изображение {idx+1}]"
                    text_parts[p_num] += ocr_block

            text_parts.insert(0, f"[ℹ️ Из PDF извлечено и распознано {len(images_to_process)} изображений]\n")

        chunks = [notice] + text_parts if notice else text_parts
        joined = "\n\n".join(item for item in chunks if item)
        if len(joined) > MAX_EXTRACT_CHARS:
            joined = joined[:MAX_EXTRACT_CHARS] + "\n\n[Текст обрезан: файл слишком длинный для одного сообщения.]"
        return joined
    except Exception as e:
        logger.error(f"Error in extract_text_from_pdf: {e}", exc_info=True)
        return f"Ошибка при чтении PDF: {str(e)}"


async def extract_text_from_txt(file_data: bytes) -> str:
    """
    Извлекает текст из TXT файла с автоопределением кодировки.
    
    Args:
        file_data: Байты файла TXT
        
    Returns:
        Извлеченный текст
    """
    # Пробуем разные кодировки
    encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'cp1252', 'latin-1', 'iso-8859-1', 'koi8-r']
    
    for encoding in encodings:
        try:
            return file_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Если ничего не подошло, декодируем с ошибками
    return file_data.decode('utf-8', errors='replace')


async def extract_text_from_excel(file_data: bytes, file_name: str) -> str:
    """
    Извлекает данные из Excel файла (.xlsx, .xls) и конвертирует их в Markdown.
    Читает все листы документа.
    """
    def _extract():
        try:
            # Используем pandas для чтения
            # engine определим по расширению
            engine = 'openpyxl' if file_name.lower().endswith('.xlsx') else 'xlrd'
            
            # Читаем все листы (sheet_name=None возвращает словарь)
            excel_data = pd.read_excel(io.BytesIO(file_data), sheet_name=None, engine=engine)
            
            output_parts = []
            
            for sheet_name, df in excel_data.items():
                if df.empty:
                    continue
                
                output_parts.append(f"### Лист: {sheet_name}")
                
                # Keep every row. TSV is materially more token-efficient than a
                # Markdown table and is later chunked by the shared map-reduce path.
                df_cleaned = df.fillna("")
                output_parts.append(df_cleaned.to_csv(index=False, sep="\t"))
                output_parts.append("\n")
                
            if not output_parts:
                return f"Файл Excel '{file_name}' пуст."
                
            return "\n".join(output_parts)
        except Exception as e:
            logger.error(f"Error in extract_text_from_excel: {e}")
            return f"Ошибка при чтении Excel ({file_name}): {str(e)}"
            
    return await asyncio.to_thread(_extract)


async def extract_text_from_zip_document(file_data: bytes, file_name: str) -> Optional[str]:
    """Extract readable XML/HTML text from PPTX, OpenDocument and EPUB containers."""
    def _extract() -> Optional[str]:
        try:
            parts = []
            with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
                names = archive.namelist()
                suffix = Path(file_name).suffix.lower()
                if suffix == ".pptx":
                    wanted = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.search(r"\d+", n).group()))
                elif suffix == ".epub":
                    wanted = [n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))]
                else:
                    wanted = [n for n in names if n in {"content.xml", "styles.xml"}]
                for index, name in enumerate(wanted):
                    raw = archive.read(name)
                    try:
                        root = ET.fromstring(raw)
                        text = " ".join(piece.strip() for piece in root.itertext() if piece.strip())
                    except ET.ParseError:
                        from bs4 import BeautifulSoup
                        text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
                    if text:
                        label = f"--- Слайд {index + 1} ---" if suffix == ".pptx" else f"--- Раздел {index + 1} ---"
                        parts.append(f"{label}\n{text}")
            if suffix == ".pptx":
                try:
                    from studio.pptx_style import extract_pptx_visual_brief

                    visual = extract_pptx_visual_brief(file_data)
                except Exception:
                    visual = ""
                if visual:
                    parts.insert(0, visual)
            return "\n\n".join(parts) or None
        except (zipfile.BadZipFile, OSError):
            return None
    return await asyncio.to_thread(_extract)


async def extract_text_from_rtf(file_data: bytes) -> str:
    text = await extract_text_from_txt(file_data)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return re.sub(r"[ \t]+", " ", text)


async def extract_text_from_html(file_data: bytes) -> str:
    from bs4 import BeautifulSoup
    text = await extract_text_from_txt(file_data)
    return await asyncio.to_thread(lambda: BeautifulSoup(text, "html.parser").get_text("\n", strip=True))


async def extract_text_from_file(file_data: bytes, file_name: str, status_callback=None, user_id: int = None) -> Optional[str]:
    """
    Определяет тип файла и извлекает текст.
    
    Args:
        file_data: Байты файла
        file_name: Имя файла
        status_callback: Опциональная async-функция для обновления статуса
        
    Returns:
        Извлеченный текст или None, если формат не поддерживается
    """
    file_name_lower = file_name.lower()
    
    suffix = Path(file_name_lower).suffix

    if suffix == '.docx':
        return await extract_text_from_docx(file_data)
    elif suffix == '.pdf':
        return await extract_text_from_pdf(file_data, status_callback=status_callback, user_id=user_id)
    elif suffix in {'.xlsx', '.xls'}:
        return await extract_text_from_excel(file_data, file_name)
    elif suffix in {'.pptx', '.odt', '.ods', '.odp', '.epub'}:
        return await extract_text_from_zip_document(file_data, file_name)
    elif suffix == '.rtf':
        return await extract_text_from_rtf(file_data)
    elif suffix in {'.html', '.htm'}:
        return await extract_text_from_html(file_data)
    elif suffix in {
        '.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.jsonl', '.xml', '.yaml', '.yml',
        '.log', '.ini', '.cfg', '.conf', '.sql', '.py', '.js', '.jsx', '.ts', '.tsx', '.java',
        '.c', '.h', '.cpp', '.hpp', '.cs', '.go', '.rs', '.php', '.rb', '.sh', '.ps1', '.tex',
    }:
        return await extract_text_from_txt(file_data)
    else:
        return None


import unicodedata

def normalize_text(text):
    """Нормализует текст для надежного сравнения (NFKC + очистка пробелов)."""
    if not text:
        return ""
    # NFKC объединяет похожие символы и нормализует спецсимволы
    normalized = unicodedata.normalize('NFKC', text)
    # Заменяем все виды пробелов (включая неразрывные \xa0) на обычный пробел
    return " ".join(normalized.replace('\xa0', ' ').split())

async def edit_docx_with_replacements(file_data: bytes, replacements: dict) -> bytes:
    """Редактирует DOCX документ в отдельном потоке, сохраняя форматирование."""
    def _edit():
        doc = Document(io.BytesIO(file_data))
        
        def strip_list_prefix(text):
            """Удаляет префиксы списков (1., 1), a., •, -) из текста ИИ."""
            if not text: return ""
            # Регулярка для 1., 1.1., a), •, -, * и т.д.
            return re.sub(r'^\s*(\d+([\.\d]+)?[\.\)]+|[a-zA-Z][\.\)]+|[•\-\*])\s+', '', text).strip()

        def apply_style_reset(paragraph, new_text):
            """Больше не сбрасывает стиль в Normal, чтобы сохранить автоматическую нумерацию Word."""
            return

        def replace_in_paragraph(paragraph, old_text, new_text):
            if not paragraph.text or not old_text: return False
            
            # Если абзац — это список, очищаем входящий текст от префиксов (1., 2. и т.д.)
            is_list = False
            if paragraph.style and paragraph.style.name:
                style_name = paragraph.style.name
                if 'Bullet' in style_name or 'List' in style_name:
                    is_list = True
            
            if is_list:
                new_text = strip_list_prefix(new_text)

            full_text = paragraph.text
            norm_full = normalize_text(full_text)
            norm_old = normalize_text(old_text)
            
            if norm_old in norm_full:
                main_run = None
                if paragraph.runs:
                    main_run = max(paragraph.runs, key=lambda r: len(r.text) if r.text else 0)
                
                font_props = {}
                if main_run:
                    font_props = {
                        'name': main_run.font.name,
                        'size': main_run.font.size,
                        'bold': main_run.bold,
                        'italic': main_run.italic,
                        'underline': main_run.underline,
                        'color': main_run.font.color.rgb if main_run.font.color else None
                    }
                
                if old_text in full_text:
                    new_full_text = full_text.replace(old_text, new_text)
                else:
                    new_full_text = norm_full.replace(norm_old, new_text)
                
                for run in paragraph.runs:
                    run.text = ""
                
                new_run = paragraph.add_run(new_full_text)
                if font_props:
                    if font_props['name']: new_run.font.name = font_props['name']
                    if font_props['size']: new_run.font.size = font_props['size']
                    new_run.bold = font_props['bold']
                    new_run.italic = font_props['italic']
                    new_run.underline = font_props['underline']
                    if font_props['color']: new_run.font.color.rgb = font_props['color']

                apply_style_reset(paragraph, new_full_text)
                return True
            return False

        for full_key, new_text in replacements.items():
            if full_key == "_error": continue
            marker_match = re.search(r'^\[П(\d+)\|.*?\]\s*(.*)', full_key)
            if marker_match:
                idx = int(marker_match.group(1)) - 1
                old_text_clean = marker_match.group(2).strip()
                if 0 <= idx < len(doc.paragraphs):
                    p = doc.paragraphs[idx]
                    if old_text_clean: replace_in_paragraph(p, old_text_clean, new_text)
                    else: p.text = new_text; apply_style_reset(p, new_text)
                    continue

            clean_key = re.sub(r'^\[П\d+.*?\]\s*', '', full_key).strip()
            if not clean_key: continue
            
            for paragraph in doc.paragraphs:
                replace_in_paragraph(paragraph, clean_key, new_text)
            
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            replace_in_paragraph(p, clean_key, new_text)
            
            for section in doc.sections:
                if section.header:
                    for paragraph in section.header.paragraphs:
                        replace_in_paragraph(paragraph, clean_key, new_text)
                if section.footer:
                    for paragraph in section.footer.paragraphs:
                        replace_in_paragraph(paragraph, clean_key, new_text)
        
        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return output.read()
    
    return await asyncio.to_thread(_edit)


async def get_docx_structure_for_ai(file_data: bytes) -> str:
    """Извлекает структуру документа в отдельном потоке."""
    def _get():
        doc = Document(io.BytesIO(file_data))
        parts = ["=== СОДЕРЖИМОЕ ДОКУМЕНТА ===\n"]
        for i, paragraph in enumerate(doc.paragraphs):
            if paragraph.text.strip():
                style_name = paragraph.style.name if paragraph.style else "Normal"
                ilvl_str = ""
                try:
                    pPr = paragraph._element.pPr
                    if pPr is not None and pPr.numPr is not None and pPr.numPr.ilvl is not None:
                        ilvl_str = f"|Ур{int(pPr.numPr.ilvl.val)+1}"
                except Exception: pass
                
                parts.append(f"[П{i+1}|{style_name}{ilvl_str}] {paragraph.text}")
        for t_idx, table in enumerate(doc.tables):
            parts.append(f"\n--- ТАБЛИЦА {t_idx + 1} ---")
            for r_idx, row in enumerate(table.rows):
                cells = [cell.text.strip() for cell in row.cells]
                parts.append(f"  Строка {r_idx + 1}: {' | '.join(cells)}")
        return "\n".join(parts)
    return await asyncio.to_thread(_get)
