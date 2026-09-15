import zipfile
from io import BytesIO

from app.services.code_archive import (
    extract_code_files,
    maybe_package_reply_archive,
    scrub_missing_archive_excuse,
    wants_code_archive,
)


def test_wants_code_archive_detects_russian_requests():
    assert wants_code_archive("напиши мне бота на питоне и закинь архив")
    assert wants_code_archive("весь код в zip пожалуйста")
    assert wants_code_archive("кинь архив")
    assert not wants_code_archive("какая погода в Москве")
    assert not wants_code_archive("переделай договор и ТЗ с новой датой")
    assert not wants_code_archive("Вот для этого ТЗ нужно переделать документы")
    assert not wants_code_archive("сколько будут стоить батареи при закупке в России")
    assert not wants_code_archive("прикрепил файл ТЗ, переделай спецификацию")
    assert not wants_code_archive("скачай как PDF и поправь даты")
    assert not wants_code_archive("вот исходник ТЗ, сделай смету")
    assert not wants_code_archive("файлы проектно-сметной документации")
    assert not wants_code_archive("напиши ботанику про растения")


def test_extract_and_package_markdown_project():
    reply = """
Готово.

```python
# file: bot.py
print("hello")
TOKEN = "x"
```

```text
# file: requirements.txt
aiogram==3.0.0
```

```markdown
# file: README.md
Run the bot
```
"""
    files = extract_code_files(reply)
    assert {name for name, _ in files} >= {"bot.py", "requirements.txt", "README.md"}
    packaged = maybe_package_reply_archive("сделай бота и кинь архив", reply, [])
    assert packaged and packaged["filename"] == "project.zip"
    assert packaged["bytes"][:2] == b"PK"
    with zipfile.ZipFile(BytesIO(packaged["bytes"])) as archive:
        names = set(archive.namelist())
    assert "bot.py" in names
    assert "requirements.txt" in names


def test_package_skipped_when_zip_already_attached():
    reply = "```python\nprint(1)\n```"
    existing = [{"filename": "ready.zip", "bytes": b"PK\x03\x04fake"}]
    assert maybe_package_reply_archive("кинь архив", reply, existing) is None


def test_package_skipped_when_docx_already_attached():
    reply = "```python\nprint('inspect tz helper')\n```"
    existing = [{"filename": "dogovor.docx", "bytes": b"PK\x03\x04fake-docx"}]
    assert maybe_package_reply_archive("кинь архив", reply, existing) is None


def test_scrub_missing_archive_excuse():
    text = (
        "Бот готов.\n"
        "В текущем чате файл физически не был сформирован и прикреплён, поэтому кнопки скачивания пока не будет.\n"
        "Код проекта подготовлен выше."
    )
    cleaned = scrub_missing_archive_excuse(text, attached=True)
    assert "физически не был" not in cleaned
    assert "прикреплён" in cleaned.lower() or "скача" in cleaned.lower()
