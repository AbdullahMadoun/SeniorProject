ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SKYLINK_BRIDGE_PORT=8001 \
    SKYLINK_ENABLE_QUICK_TUNNEL=true \
    SKYLINK_CLOUDFLARED_BIN=/usr/local/bin/cloudflared

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates openssh-client bash \
    && curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements-backend.txt .
RUN pip install --upgrade pip && pip install -r requirements-backend.txt

COPY app/src ./src
COPY app/.env.example ./.env.example
COPY model_server ./model_server
COPY deploy/model_server ./deploy/model_server

RUN mkdir -p /var/lib/skylink

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('SKYLINK_BRIDGE_PORT', '8001'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health').read()"

CMD ["python", "src/server.py"]
