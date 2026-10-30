FROM node:22-bookworm-slim AS node_runtime
FROM python:3.12-slim-bookworm

# Same supported Node major as the application build. No host runtime mount.
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
        chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 sandbox \
    && mkdir -p /workspaces /opt/sandbox \
    && chown -R sandbox:sandbox /workspaces /opt/sandbox

# Native offline draw.io exporter; pinned official release and checksum.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates xvfb xauth fonts-dejavu-core fonts-liberation \
        libasound2 libgbm1 libgtk-3-0 libnotify4 libnss3 libxss1 libxtst6 libsecret-1-0 libuuid1 libatspi2.0-0 xdg-utils \
    && curl -fL --retry 3 https://github.com/jgraph/drawio-desktop/releases/download/v32.5.5/drawio-amd64-32.5.5.deb -o /tmp/drawio.deb \
    && echo "0ca81780c79d3e5b9f459390173823697f80048d0f7f1e26c3be5077f5c3f611  /tmp/drawio.deb" | sha256sum -c - \
    && dpkg-deb -x /tmp/drawio.deb / \
    && ln -sf /opt/drawio/drawio /usr/local/bin/drawio \
    && rm /tmp/drawio.deb \
    && rm -rf /var/lib/apt/lists/*

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
COPY backend/app/services/page_shot.py /opt/sandbox/page_shot.py
COPY sandbox/healthcheck.py /opt/sandbox/healthcheck.py
COPY sandbox/sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py
# Та же сборка markdown → .docx, что у режима «Документы»: Пилот собирает
# комплект файлов `from bt_docx import convert_markdown_to_docx`, а не пишет
# python-docx вручную на каждый документ. Без python-docx в образе Пилот
# делал один файл и сообщал, что создавать DOCX ему нечем.
COPY backend/app/bot_core/docx_generator.py /usr/local/lib/python3.12/site-packages/bt_docx.py
COPY backend/app/services/diagrams.py /usr/local/lib/python3.12/site-packages/bt_diagrams.py
COPY backend/app/services/workspace_fs.py /opt/sandbox/workspace_fs.py
COPY backend/app/services/product_factory.py /opt/sandbox/product_factory.py
COPY backend/app/services/product_strategy.py /opt/sandbox/product_strategy.py
COPY sandbox/product_smoke.cjs /usr/local/lib/bitthink/product_smoke.cjs

ENV WORKSPACES_DIR=/workspaces \
    WORKSPACE_PYTHON=/usr/local/bin/python \
    SANDBOX_MODE=1 \
    WORKSPACE_ALLOW_LOCAL_RUN=1 \
    PYTHONDONTWRITEBYTECODE=1

USER sandbox
EXPOSE 8090
CMD ["python", "-u", "/opt/sandbox/server.py"]
