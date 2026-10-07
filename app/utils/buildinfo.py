"""Build stamp.

Tells you *which* code is actually running. Handy when a stale process is
serving an older interface and you need to know in one glance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def build_stamp() -> str:
    """Newest source-file mtime under ``app/``, as ``YYYY-MM-DD HH:MM``."""
    newest = 0.0
    for path in APP_DIR.rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    if not newest:
        return "unknown"
    return datetime.fromtimestamp(newest, tz=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )
