"""Regression tests for SQLite contention and user-context transaction scope."""

from __future__ import annotations

import pytest

from app.bot.middlewares.database import UserContextMiddleware
from app.database.database import get_engine
from app.services import user as user_service
from tests.mock_telegram import make_update_message


async def test_sqlite_uses_wal_and_a_busy_timeout(database):
    """The production SQLite connection tolerates normal concurrent activity."""
    async with get_engine().connect() as connection:
        mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
        timeout = (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()

    assert str(mode).lower() == "wal"
    assert int(timeout) >= 30_000


async def test_user_context_commits_short_writes_before_handler(session):
    """No last_seen/profile write lock should survive into long handler work."""
    middleware = UserContextMiddleware()
    event = make_update_message(9301, "hello").message
    observed = {}

    async def handler(_event, data):
        observed["transaction_open"] = data["session"].in_transaction()
        observed["user_id"] = data["user"].telegram_id
        return "handled"

    result = await middleware(handler, event, {"session": session})

    assert result == "handled"
    assert observed == {"transaction_open": False, "user_id": 9301}


async def test_user_context_does_not_dispatch_with_a_missing_user(session, monkeypatch):
    """Database errors propagate to the outer error handler; user=None is never dispatched."""
    async def database_failure(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(user_service, "ensure_user", database_failure)
    middleware = UserContextMiddleware()
    event = make_update_message(9302, "hello").message
    called = False

    async def handler(_event, _data):
        nonlocal called
        called = True

    with pytest.raises(RuntimeError, match="database is locked"):
        await middleware(handler, event, {"session": session})

    assert called is False


async def test_battle_comparison_has_a_hard_timeout(monkeypatch):
    import asyncio
    from app.bot.handlers import battle as battle_handlers

    async def hangs(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(battle_handlers, "compare", hangs)
    monkeypatch.setattr(battle_handlers, "BATTLE_CHECK_TIMEOUT", 0.001)

    result, timed_out = await battle_handlers._compare_once("crane", "moged", None, None)

    assert result is None
    assert timed_out is True
