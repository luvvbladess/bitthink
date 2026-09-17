FROM python:3.12-slim

WORKDIR /app

# Install system deps for document parsing / matplotlib / PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Старый формат .doc: только LibreOffice превращает его в .docx с сохранением
# шрифтов, полей, колонтитулов и таблиц, а без этого присланный образец
# оформления в .doc остаётся набором слов и шаблоном служить не может.
# Замерено на настоящем ИТТ: +375 МБ к образу, 1.08 с на файл. Код работает и
# без пакета — тогда .doc читается как текст, без оформления.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer-nogui \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Make sure the uploads directory exists (used by document upload / static files).
RUN mkdir -p /app/uploads

ENV PYTHONPATH=/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
