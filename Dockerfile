# Signals, hosted: the engine (SIGNALS_HOSTED=1). Render builds this (render.yaml); Railway did (railway.json).
# The store (the Worth following result, the price cache) lives on a volume mounted at /data.
# One process only: the Worth following check and the caches live in its memory.
FROM python:3.14-slim

WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.21
COPY pyproject.toml uv.lock ./
COPY signals ./signals
COPY deploy/start.sh ./deploy/start.sh
RUN uv sync --frozen --no-dev
# Render's SSH (to copy a store in, deploy/render/README.md) needs the running user's ~/.ssh
RUN mkdir -p /root/.ssh && chmod 0700 /root/.ssh

ENV SIGNALS_HOSTED=1 \
    SIGNALS_STORE_DIR=/data \
    PYTHONUNBUFFERED=1
# One process: deploy/start.sh moves a copied-in store into place, if one is waiting, then starts uvicorn (no access log)
CMD ["sh", "deploy/start.sh"]
