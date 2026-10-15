"""FloodGuard: a burst of updates must never take the bot down.

aiogram handles every update in its own task, so an unguarded bot turns a
flood into unbounded concurrency (each task holding a database session) - the
outage this guard exists to prevent.
"""

from __future__ import annotations

import asyncio

from app.bot.middlewares.flood import FloodGuardMiddleware
from tests.mock_telegram import make_message, make_update_message




async def test_a_burst_from_one_user_is_muted():
    guard = FloodGuardMiddleware(window=10.0, per_window=3, mute_seconds=10.0)
    handled: list[int] = []

    async def handler(event, data):
        handled.append(event.from_user.id)
        return "ok"

    for _ in range(3):
        assert await guard(handler, make_message(1, "hi"), {}) == "ok"
    assert handled == [1, 1, 1]

    # The fourth update is over budget: dropped and the user muted.
    assert await guard(handler, make_message(1, "hi"), {}) is None
    assert handled == [1, 1, 1]

    # Still muted: further updates are dropped without reaching the handler.
    assert await guard(handler, make_message(1, "hi"), {}) is None
    assert handled == [1, 1, 1]
    assert guard.dropped_user >= 2


async def test_one_users_flood_does_not_touch_another():
    guard = FloodGuardMiddleware(window=10.0, per_window=2, mute_seconds=10.0)
    handled: list[int] = []

    async def handler(event, data):
        handled.append(event.from_user.id)
        return "ok"

    for _ in range(6):
        await guard(handler, make_message(1, "hi"), {})

    # A different user is served normally despite the first user's flood.
    assert await guard(handler, make_message(2, "hi"), {}) == "ok"
    assert await guard(handler, make_message(2, "hi"), {}) == "ok"
    assert handled.count(2) == 2


async def test_global_in_flight_ceiling_sheds_load():
    guard = FloodGuardMiddleware(max_in_flight=1)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def slow(event, data):
        entered.set()
        await release.wait()
        return "ok"

    task = asyncio.create_task(guard(slow, make_message(1, "hi"), {}))
    await entered.wait()

    # While one update is mid-handling, another is shed rather than queued.
    assert await guard(slow, make_message(2, "hi"), {}) is None
    assert guard.dropped_global == 1

    release.set()
    assert await task == "ok"


async def test_the_guard_sees_the_user_through_an_update_wrapper():
    """Update-level middlewares receive the ``Update``, not the message - the
    guard must unwrap it, or in production it would silently do nothing."""
    guard = FloodGuardMiddleware(window=10.0, per_window=2, mute_seconds=10.0)
    handled: list[int] = []

    async def handler(event, data):
        handled.append(1)
        return "ok"

    for _ in range(2):
        assert await guard(handler, make_update_message(7, "hi"), {}) == "ok"
    # Over budget now - dropped, which proves the user id was recognised
    # through the Update wrapper rather than the guard being a no-op.
    assert await guard(handler, make_update_message(7, "hi"), {}) is None
    assert len(handled) == 2


async def test_the_in_flight_cap_stays_under_the_db_pool():
    """The invariant that keeps the pool from exhausting.

    Every update holds a database connection while its database work runs, and
    the background services need connections too. If the guard allowed updates
    to occupy the whole pool, the pool would run dry - which is precisely the
    crash this guard exists to prevent ("QueuePool limit reached").
    """
    from app.bot.middlewares.flood import GLOBAL_MAX_IN_FLIGHT
    from app.database.database import pool_capacity

    capacity = pool_capacity()
    assert GLOBAL_MAX_IN_FLIGHT < capacity
    # At most half the pool for updates - the rest is headroom for background
    # services and bursts, not a hair's breadth.
    assert GLOBAL_MAX_IN_FLIGHT <= capacity // 2


async def test_the_guard_bookkeeping_stays_bounded(monkeypatch):
    from app.bot.middlewares import flood as flood_module

    monkeypatch.setattr(flood_module, "_MAX_TRACKED_USERS", 100)
    guard = FloodGuardMiddleware(window=1.0, per_window=5, mute_seconds=0.0)

    async def handler(event, data):
        return "ok"

    for uid in range(1000):
        await guard(handler, make_message(uid, "hi"), {})

    # A flood of distinct ids cannot grow the guard's own state without bound.
    assert len(guard._hits) <= 100 + 1
