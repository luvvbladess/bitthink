FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 sandbox \
    && mkdir -p /workspaces /opt/sandbox \
    && chown -R sandbox:sandbox /workspaces /opt/sandbox

RUN pip install --no-cache-dir \
        requests \
        beautifulsoup4 \
        lxml \
        pandas \
        openpyxl \
        pillow \
        python-pptx \
        python-docx \
        matplotlib

WORKDIR /opt/sandbox
COPY sandbox/server.py /opt/sandbox/server.py
COPY sandbox/healthcheck.py /opt/sandbox/healthcheck.py
COPY sandbox/sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py
# Та же сборка markdown → .docx, что у режима «Документы»: Пилот собирает
# комплект файлов `from bt_docx import convert_markdown_to_docx`, а не пишет
# python-docx вручную на каждый документ. Без python-docx в образе Пилот
# делал один файл и сообщал, что создавать DOCX ему нечем.
COPY backend/app/bot_core/docx_generator.py /usr/local/lib/python3.12/site-packages/bt_docx.py
COPY backend/app/services/workspace_fs.py /opt/sandbox/workspace_fs.py

ENV WORKSPACES_DIR=/workspaces \
    WORKSPACE_PYTHON=/usr/local/bin/python \
    SANDBOX_MODE=1 \
    WORKSPACE_ALLOW_LOCAL_RUN=1 \
    PYTHONDONTWRITEBYTECODE=1

USER sandbox
EXPOSE 8090
CMD ["python", "-u", "/opt/sandbox/server.py"]
