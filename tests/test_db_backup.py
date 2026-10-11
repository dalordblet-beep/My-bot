"""Tests for the database snapshot / restore service.

The hosting starts the bot in a NEW folder on every deploy, so the in-project
SQLite file dies with the old one. The service snapshots the database into the
user session's Saved Messages and restores the newest snapshot over a *fresh*
database on boot - never over one that already has users.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from contextlib import closing

from app.services import db_backup as mod
from app.services.db_backup import (
    CAPTION_MARKER,
    _parse_caption,
    restore_if_fresh,
    snapshot_to,
    upload_backup,
)


class _FakeDoc:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeMessage:
    def __init__(self, doc_name: str, caption: str) -> None:
        self.document = _FakeDoc(doc_name)
        self.message = caption


class _FakeSavedMessages:
    """Saved Messages with a list of (message, file-bytes) backups."""

    def __init__(self) -> None:
        self.messages: list[_FakeMessage] = []
        self.files: dict[str, bytes] = {}
        self.uploaded: list[str] = []

    async def iter_messages(self, peer, limit=50):
        for message in reversed(self.messages):
            yield message

    async def send_file(self, peer, path, caption=None, force_document=False):
        data = open(path, "rb").read()
        name = f"backup{len(self.uploaded)}.db"
        self.files[name] = data
        self.uploaded.append(caption)
        self.messages.append(_FakeMessage(name, caption))

    async def download_media(self, document, file=None):
        import os

        out = os.path.join(file, document.name)
        with open(out, "wb") as handle:
            handle.write(self.files[document.name])
        return out


def _caption(users: int, minutes_ago: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return f"{CAPTION_MARKER}|{stamp.isoformat(timespec='seconds')}|{users}"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """A real empty SQLite database, and the db path pointed at it."""
    db_path = tmp_path / "username_scanner.db"
    monkeypatch.setattr(mod.settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    # Make the engine-independent helpers see the same file.
    monkeypatch.setattr(mod, "_db_file", lambda: db_path)
    # A real (empty) file: every helper assumes the database exists.
    db_path.write_bytes(b"")
    return db_path


async def test_parse_caption():
    stamp = _parse_caption(_caption(12, 0))
    assert stamp is not None
    assert _parse_caption("some random text") is None
    assert _parse_caption(None) is None


async def test_snapshot_copies_the_database(tmp_path, fresh_db):
    import sqlite3

    with closing(sqlite3.connect(fresh_db)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()

    snapshot = tmp_path / "snap.db"
    assert snapshot_to(snapshot) is True
    with closing(sqlite3.connect(snapshot)) as conn:
        assert conn.execute("SELECT x FROM t").fetchone()[0] == 42


async def test_snapshot_refuses_a_non_sqlite_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod.settings, "database_url", "postgresql+asyncpg://x/y"
    )
    assert snapshot_to(tmp_path / "snap.db") is False


async def test_upload_uses_the_saved_messages_of_the_user_session(
    fresh_db, monkeypatch
):
    class _StubMtproto:
        def first_user_client(self):
            return saved

    saved = _FakeSavedMessages()
    monkeypatch.setattr(mod.mtproto_client, "first_user_client", lambda: saved)
    async def seven() -> int:
        return 7

    monkeypatch.setattr(mod, "_user_count", seven)

    assert await upload_backup() is True
    assert len(saved.uploaded) == 1
    assert saved.uploaded[0].startswith(CAPTION_MARKER)
    assert saved.uploaded[0].endswith("|7")


async def test_upload_without_a_user_session_is_a_noop(fresh_db, monkeypatch):
    monkeypatch.setattr(mod.mtproto_client, "first_user_client", lambda: None)
    assert await upload_backup() is False


async def test_restore_fills_a_fresh_database(fresh_db, monkeypatch):
    """A brand-new deploy with no users gets the snapshot downloaded into it."""
    import sqlite3

    saved = _FakeSavedMessages()
    # The snapshot the *previous* deployment uploaded: two tables, two rows.
    old_db = fresh_db.parent / "old.db"
    with closing(sqlite3.connect(old_db)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'alice'), (2, 'bob')")
        conn.commit()
    saved.files["prev.db"] = old_db.read_bytes()
    saved.messages.append(_FakeMessage("prev.db", _caption(2, 90)))

    # The new deployment's database: schema only, no users.
    with closing(sqlite3.connect(fresh_db)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()

    monkeypatch.setattr(mod.mtproto_client, "first_user_client", lambda: saved)
    # users==0 -> fresh.
    async def zero():
        return 0

    monkeypatch.setattr(mod, "_user_count", zero)

    # init_db() would need a real engine; stub it - the swap itself is the unit.
    called = {"init": 0}

    async def fake_init():
        called["init"] += 1
        return True

    monkeypatch.setattr(mod, "init_db", fake_init)
    monkeypatch.setattr(mod, "dispose_db", lambda: _noop())

    assert await restore_if_fresh() is True
    assert called["init"] == 1
    with closing(sqlite3.connect(fresh_db)) as conn:
        rows = conn.execute("SELECT name FROM users").fetchall()
    assert {row[0] for row in rows} == {"alice", "bob"}


async def _noop():
    return None


async def test_restore_never_touches_a_database_with_users(fresh_db, monkeypatch):
    import sqlite3

    saved = _FakeSavedMessages()
    saved.files["prev.db"] = b"malicious or stale data"
    saved.messages.append(_FakeMessage("prev.db", _caption(2, 90)))

    monkeypatch.setattr(mod.mtproto_client, "first_user_client", lambda: saved)

    async def two():
        return 2

    monkeypatch.setattr(mod, "_user_count", two)
    swopped = {"dispose": 0}

    async def fake_dispose():
        swopped["dispose"] += 1

    monkeypatch.setattr(mod, "dispose_db", fake_dispose)

    assert await restore_if_fresh() is False
    assert swopped["dispose"] == 0, "a live database must never be replaced"
    # The file is untouched.
    assert fresh_db.exists()


async def test_restore_picks_the_newest_snapshot(fresh_db, monkeypatch):
    import sqlite3

    saved = _FakeSavedMessages()
    old_db = fresh_db.parent / "old.db"
    with closing(sqlite3.connect(old_db)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    for i, minutes in enumerate((300, 5), start=1):
        saved.files[f"b{i}.db"] = old_db.read_bytes()
        saved.messages.append(_FakeMessage(f"b{i}.db", _caption(1, minutes)))

    with closing(sqlite3.connect(fresh_db)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()

    monkeypatch.setattr(mod.mtproto_client, "first_user_client", lambda: saved)

    async def zero():
        return 0

    monkeypatch.setattr(mod, "_user_count", zero)
    monkeypatch.setattr(mod, "init_db", _noop)
    monkeypatch.setattr(mod, "dispose_db", _noop)

    assert await restore_if_fresh() is True
