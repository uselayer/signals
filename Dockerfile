# Signals, hosted: the engine (SIGNALS_HOSTED=1). Railway builds this.
# The store (the Worth following result, the price cache) lives on a volume mounted at /data.
# One process only: the Worth following check and the caches live in its memory.
# The same image runs the order service for one-tap copy (signals/copy_service.py) when SIGNALS_ROLE=copy: its
# own Railway service, in a region Polymarket takes orders from, with no volume.

# The /copy page (copy-web: React, Privy, Polymarket's client), built into static/copy.
FROM node:24-slim AS copyweb
WORKDIR /web
COPY copy-web/package.json copy-web/package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund
COPY copy-web ./
RUN npx vite build --outDir /out/copy --emptyOutDir

FROM python:3.14-slim

WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.21
COPY pyproject.toml uv.lock ./
COPY signals ./signals
COPY --from=copyweb /out/copy ./signals/static/copy
RUN uv sync --frozen --no-dev

ENV SIGNALS_HOSTED=1 \
    SIGNALS_STORE_DIR=/data \
    PYTHONUNBUFFERED=1
# No access log: it would keep visitors' IP addresses (and, beside them, the alert links they tap).
CMD ["sh", "-c", "if [ \"$SIGNALS_ROLE\" = copy ]; then exec .venv/bin/uvicorn signals.copy_service:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-access-log; else exec .venv/bin/uvicorn signals.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips='*' --no-access-log; fi"]
