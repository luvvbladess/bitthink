FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 libfreecad-python3-0.20 freecad-common \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir mcp==1.26.0

WORKDIR /opt/cad
COPY cad/plate.py cad/server.py cad/preview.html ./
RUN useradd --no-create-home --home-dir /tmp --uid 10001 cad
USER cad
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
EXPOSE 8091
CMD ["python", "-u", "server.py"]
