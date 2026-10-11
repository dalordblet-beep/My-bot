"""Database snapshots into Telegram, restored automatically after a redeploy.

Why this exists: the hosting clones the repository into a **new** folder on
every deploy, and the SQLite database lives inside the project folder - so
users, admin-panel settings and favourites died with each redeploy. Sessions
and the .env already survive (they come from environment variables); the
database was the last thing that did not.

The one storage this bot already owns and trusts is the user session's own
Telegram account, so the snapshot is uploaded to its Saved Messages ("me"):

* on start, if the database is *fresh* (no users at all - a brand-new deploy),
  the newest snapshot is found in Saved Messages, downloaded and put in place
  before the bot does anything else;
* on a timer, a consistent snapshot (SQLite backup API, safe against concurrent
  writes) is uploaded with a parseable caption.

No snapshot is ever restored over a database that has users - restore only
fills an empty one, so a running bot can never wipe its own data.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.database.database import (
    dispose_db,
    get_engine,
    init_db,
    session_scope,
)
from app.database.models import User
from app.telegram.mtproto import mtproto_client
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# Every backup message carries this caption: marker|ISO timestamp|user count.
# The marker doubles as the search term when looking for the newest snapshot.
CAPTION_MARKER = "username_scanner.db backup"
_CAPTION_RE = re.compile(
    rf"^{re.escape(CAPTION_MARKER)}\|(?P<stamp>[^|]+)\|(?P<users>\d+)"
)

# How many recent Saved-Messages messages to scan for the newest snapshot.
_SCAN_LIMIT = 50


def _db_file() -> Path:
    """The SQLite file the engine is bound to (relative to the working dir)."""
    raw = settings.database_url
    path = raw.split("///", 1)[-1]
    return Path(path).resolve()


def snapshot_to(path: Path) -> bool:
    """Write a consistent copy of the live SQLite database to ``path``.

    Uses the sqlite3 backup API, which takes a consistent snapshot even while
    the bot keeps writing (WAL included). Returns False for non-SQLite URLs -
    a hosted PostgreSQL does not need this service in the first place.
    """
    if not settings.database_url.startswith("sqlite"):
        logger.warning("db backup: only SQLite is supported, skipping")
        return False
    source = _db_file()
    if not source.exists():
        return False
    try:
        # closing() matters: `with sqlite3.connect(...)` commits but does NOT
        # close, and on Windows an open handle keeps the snapshot file locked
        # (the TemporaryDirectory cleanup then fails with a sharing violation).
        with contextlib.closing(sqlite3.connect(source)) as src, contextlib.closing(
            sqlite3.connect(path)
        ) as dst:
            src.backup(dst)
        return True
    except Exception as exc:
        logger.warning("db backup: snapshot failed: %s", exc)
        return False


async def _user_count() -> int:
    async with session_scope() as session:
        result = await session.execute(select(func.count(User.id)))
        return int(result.scalar_one() or 0)


async def upload_backup() -> bool:
    """Snapshot the database and upload it to the user session's Saved Messages.

    Returns True when a snapshot was actually uploaded. Silently does nothing
    when there is no ready user session - the bot degrades, never breaks.
    """
    client = mtproto_client.first_user_client()
    if client is None:
        logger.debug("db backup: no user session ready - skipped")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "username_scanner.db"
        await asyncio.to_thread(snapshot_to, snapshot)
        if not snapshot.exists():
            return False

        users = await _user_count()
        caption = (
            f"{CAPTION_MARKER}|"
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}|{users}"
        )
        try:
            await client.send_file(
                "me", str(snapshot), caption=caption, force_document=True
            )
        except Exception as exc:
            logger.warning("db backup: upload failed: %s", exc)
            return False

    logger.info("db backup: snapshot uploaded (%d users)", users)
    return True


def _parse_caption(caption: str | None) -> datetime | None:
    if not caption:
        return None
    match = _CAPTION_RE.match(caption.strip())
    if not match:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(match.group("stamp"))
    return None


async def _find_newest_snapshot(client):
    """The most recent backup document in Saved Messages, or None."""
    newest = None
    newest_stamp: datetime | None = None
    async for message in client.iter_messages("me", limit=_SCAN_LIMIT):
        document = getattr(message, "document", None)
        if document is None:
            continue
        stamp = _parse_caption(message.message or message.caption or "")
        if stamp is None:
            continue
        if newest_stamp is None or stamp > newest_stamp:
            newest, newest_stamp = document, stamp
    return newest


async def restore_if_fresh() -> bool:
    """Restore the newest snapshot when the current database has no users.

    Returns True when a snapshot was downloaded and put in place. The engine is
    rebound afterwards, so everything after this call reads the restored data.
    """
    if not settings.database_url.startswith("sqlite"):
        return False

    if await _user_count() > 0:
        logger.debug("db restore: database already has users - nothing to do")
        return False

    client = mtproto_client.first_user_client()
    if client is None:
        logger.debug("db restore: no user session ready - skipped")
        return False

    document = None
    try:
        document = await _find_newest_snapshot(client)
    except Exception as exc:
        logger.warning("db restore: could not scan Saved Messages: %s", exc)
        return False
    if document is None:
        logger.info("db restore: fresh database and no snapshot found - starting clean")
        return False

    tmp_dir = tempfile.mkdtemp()
    try:
        path = await client.download_media(document, file=tmp_dir)
        if not path:
            logger.warning("db restore: download failed")
            return False

        # Swap the file while no engine is bound to it. Windows antivirus can
        # hold a just-written file for a moment, so the replace retries briefly
        # instead of failing on the first sharing violation.
        await dispose_db()
        target = _db_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        incoming = Path(path)
        for attempt in range(5):
            try:
                for suffix in ("", "-wal", "-shm"):
                    with contextlib.suppress(FileNotFoundError):
                        Path(f"{target}{suffix}").unlink()
                shutil.move(str(incoming), str(target))
                break
            except OSError:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.3 * (attempt + 1))

        await init_db()

        users = await _user_count()
        logger.info(
            "db restore: snapshot from Saved Messages restored (%d users) - "
            "the redeploy did not lose the database",
            users,
        )
        return True
    except Exception as exc:
        logger.warning("db restore: failed: %s", exc)
        # Whatever happened, the bot must come back up with a working database.
        await init_db()
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


class DbBackup:
    """Timer loop that uploads a snapshot every ``db_backup_interval`` seconds."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if settings.db_backup_interval <= 0:
            logger.info("db backup disabled by configuration")
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="db-backup")
        logger.info(
            "db backup running (every %ss, into the user session's Saved Messages)",
            settings.db_backup_interval,
        )

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        # First snapshot shortly after boot: a deploy that dies an hour later
        # still gets its data up.
        await asyncio.sleep(60)
        while not self._stopping.is_set():
            with contextlib.suppress(Exception):
                await upload_backup()
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=settings.db_backup_interval
                )
            except asyncio.TimeoutError:
                pass


db_backup = DbBackup()
