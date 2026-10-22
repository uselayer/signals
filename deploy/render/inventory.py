"""What the hosted engine's store and settings are, before a move: run inside the running service, it prints one JSON
line. Read-only: it opens nothing for writing, and prints a setting's value only when it's one of Signals' own switches
(a key, a token or anything else is printed by name only).

    railway ssh --service signals -i ~/.ssh/railway_research_key -- python3 - < deploy/render/inventory.py
"""

import json
import os
from pathlib import Path

STORE = Path(os.environ.get("SIGNALS_STORE_DIR", "/data"))
SECRET = ("KEY", "TOKEN", "SECRET", "PASSWORD", "RPC", "URL")  # printed by name only


def size(p: Path) -> tuple[int, int]:
    """(bytes, files) under p."""
    if p.is_file():
        return p.stat().st_size, 1
    total = files = 0
    for root, _, names in os.walk(p):
        for n in names:
            try:
                total += os.lstat(os.path.join(root, n)).st_size
                files += 1
            except OSError:
                pass
    return total, files


store = {}
for p in sorted(STORE.iterdir()) if STORE.exists() else []:
    b, f = size(p)
    store[p.name] = {"mb": round(b / 1e6, 1), "files": f}
fs = os.statvfs(STORE) if STORE.exists() else None
own = {k: v for k, v in os.environ.items() if (k.startswith("SIGNALS_") or k.startswith("MALLOC_") or k.startswith("USELAYER_")) and not any(s in k for s in SECRET)}
named = sorted(k for k in os.environ if k not in own and not k.startswith("RAILWAY_") and k not in ("PATH", "HOME", "HOSTNAME", "PWD", "SHLVL", "TERM", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "_"))
print(json.dumps({
    "store": store,
    "store_mb": round(sum(v["mb"] for v in store.values()), 1),
    "disk_gb": round(fs.f_blocks * fs.f_frsize / 1e9, 1) if fs else None,
    "disk_used_gb": round((fs.f_blocks - fs.f_bfree) * fs.f_frsize / 1e9, 1) if fs else None,
    "settings": own,
    "settings_by_name_only": named,
}))
