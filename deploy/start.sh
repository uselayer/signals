#!/bin/sh
# Starts the engine (the Dockerfile's command). A store copied in from another host waits in $STORE/incoming, marked
# ready by deploy/render/README.md's import step, and is moved into place here, before anything opens it: each file
# replaces the one of its name, with that database's journal files, so no old journal is applied to a new database.
set -e
STORE="${SIGNALS_STORE_DIR:-/data}"
if [ -f "$STORE/incoming/.ready" ]; then
  rm -f "$STORE/incoming/.ready"
  for f in "$STORE"/incoming/*; do
    [ -e "$f" ] || continue
    n=$(basename "$f")
    rm -rf "${STORE:?}/$n" "$STORE/$n-wal" "$STORE/$n-shm" "$STORE/$n-journal"
    mv "$f" "$STORE/$n"
    echo "Copied store: moved $n into $STORE"
  done
  rmdir "$STORE/incoming"
fi
# No access log: it would keep visitors' IP addresses (and, beside them, the alert links they tap).
exec .venv/bin/uvicorn signals.app:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1 --proxy-headers --forwarded-allow-ips='*' --no-access-log
