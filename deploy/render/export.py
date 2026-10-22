"""The hosted store, copied out of the running service: a gzipped tar, base64, on stdout, with a line on stderr naming
each file and the copy's sha256. Run inside the running service (reads only):

    railway ssh --service signals -i ~/.ssh/railway_research_key -- python3 - < deploy/render/export.py > signals-store.b64

Each SQLite database is copied with SQLite's own backup (a consistent copy while the engine keeps writing), one at a
time through /tmp; everything else is copied as it is. The price cache isn't copied: it's a cache, refilled as pages
are read. Journal files (-wal, -shm, -journal) aren't copied either: the backup already holds what's in them.
"""

import base64
import hashlib
import os
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

STORE = Path(os.environ.get("SIGNALS_STORE_DIR", "/data"))
SKIP = {"price-cache", "lost+found", "incoming"}
JOURNAL = ("-wal", "-shm", "-journal")


class B64Out:
    """A file-like sink that writes base64 lines to stdout and hashes the raw bytes."""

    def __init__(self) -> None:
        self.buf, self.sha, self.size = b"", hashlib.sha256(), 0

    def write(self, b: bytes) -> int:
        self.sha.update(b)
        self.size += len(b)
        self.buf += b
        n = len(self.buf) // 57 * 57  # 57 raw bytes = one 76-character line
        if n:
            sys.stdout.buffer.write(base64.encodebytes(self.buf[:n]))
            self.buf = self.buf[n:]
        return len(b)

    def close(self) -> None:
        if self.buf:
            sys.stdout.buffer.write(base64.encodebytes(self.buf))
        sys.stdout.buffer.flush()


def is_sqlite(p: Path) -> bool:
    with p.open("rb") as f:
        return f.read(16) == b"SQLite format 3\x00"


out = B64Out()
with tarfile.open(fileobj=out, mode="w|gz") as tar:  # type: ignore[call-overload]
    for p in sorted(STORE.iterdir()):
        if p.name in SKIP or p.name.endswith(JOURNAL):
            continue
        if p.is_file() and is_sqlite(p):
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / p.name
                src, dst = sqlite3.connect(f"file:{p}?mode=ro", uri=True), sqlite3.connect(copy)
                src.backup(dst)
                ok = dst.execute("PRAGMA quick_check").fetchone()[0]
                src.close(), dst.close()
                if ok != "ok":
                    sys.exit(f"{p.name}: the copy failed its check ({ok}); nothing usable was written")
                tar.add(copy, arcname=p.name)
                print(f"{p.name}: database, {copy.stat().st_size / 1e6:.1f} MB, checked", file=sys.stderr)
        else:
            tar.add(p, arcname=p.name)
            print(f"{p.name}: copied as it is", file=sys.stderr)
out.close()
print(f"store copied: {out.size / 1e6:.1f} MB gzipped, sha256 {out.sha.hexdigest()}", file=sys.stderr)
