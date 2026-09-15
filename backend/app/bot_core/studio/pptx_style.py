"""Pull a short visual kit from an example PPTX so Studio can repeat the client's look."""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _hex(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    srgb = el.find(f".//{_A}srgbClr")
    if srgb is not None and srgb.get("val"):
        return "#" + srgb.get("val").strip().lstrip("#").upper()[:6]
    sys = el.find(f".//{_A}sysClr")
    if sys is not None and sys.get("lastClr"):
        return "#" + sys.get("lastClr").strip().lstrip("#").upper()[:6]
    return None


def _typeface(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    latin = el.find(f"{_A}latin")
    name = (latin.get("typeface") if latin is not None else None) or ""
    name = name.strip()
    if not name or name.startswith("+"):
        return None
    return name[:48]


def extract_pptx_visual_brief(file_data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(file_data)) as archive:
            names = archive.namelist()
            theme_name = next((n for n in names if re.match(r"ppt/theme/theme\d+\.xml$", n)), None)
            lines: list[str] = ["--- Визуальный стиль образца ---"]
            if theme_name:
                root = ET.fromstring(archive.read(theme_name))
                scheme = root.find(f".//{_A}clrScheme")
                if scheme is not None:
                    bg = _hex(scheme.find(f"{_A}dk1")) or _hex(scheme.find(f"{_A}lt1"))
                    paper = _hex(scheme.find(f"{_A}lt1")) or _hex(scheme.find(f"{_A}dk1"))
                    text = _hex(scheme.find(f"{_A}dk2")) or _hex(scheme.find(f"{_A}dk1"))
                    accent = _hex(scheme.find(f"{_A}accent1"))
                    if bg:
                        lines.append(f"Фон: {bg}")
                    if paper:
                        lines.append(f"Поверхность: {paper}")
                    if text:
                        lines.append(f"Текст: {text}")
                    if accent:
                        lines.append(f"Акцент: {accent}")
                fonts = root.find(f".//{_A}fontScheme")
                if fonts is not None:
                    title_font = _typeface(fonts.find(f"{_A}majorFont"))
                    body_font = _typeface(fonts.find(f"{_A}minorFont"))
                    if title_font:
                        lines.append(f"Шрифт заголовков: {title_font}")
                    if body_font:
                        lines.append(f"Шрифт тела: {body_font}")
            slide_files = sorted(
                (n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                key=lambda n: int(re.search(r"\d+", n).group()),
            )
            if slide_files:
                lines.append(f"Кадров в образце: {len(slide_files)}")
                first = ET.fromstring(archive.read(slide_files[0]))
                has_pic = first.find(f".//{_P}pic") is not None
                texts = [(t.text or "").strip() for t in first.iter(f"{_A}t") if (t.text or "").strip()]
                if has_pic:
                    lines.append("Ритм: есть фото на кадре, текст поверх или рядом, не пустой фон.")
                if texts:
                    lines.append("Первый кадр (как эталон плотности): " + " / ".join(texts[:6])[:280])
            if len(lines) < 3:
                return ""
            lines.append(
                "Повтори этот визуальный язык один в один: палитра, шрифты, densность текста, "
                "сетка. Не уходи в чёрный кинематограф, если образец другой."
            )
            return "\n".join(lines)
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return ""
