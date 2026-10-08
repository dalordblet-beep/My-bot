"""The search runner: dedup, back-pressure and per-search isolation.

There is no queue any more: every search runs as its own independent task, so
a wedged search can only stall itself. These tests pin the properties that
still matter - duplicate work is refused, the bot cannot be pushed past its
capacity, no submitted search is ever silently lost, and stop() owns the
live tasks.
"""

from __future__ import annotations

import asyncio

import pytest

from app.search.finder import SearchCriteria
from app.services.search_queue import SearchQueue


def _criteria() -> SearchCriteria:
    return SearchCriteria(length=6)


@pytest.fixture
def recorder(monkeypatch):
    """Replace the real search with a recorder so no network work happens."""
    processed: list = []

    async def fake_process(self, job):
        processed.append(job)
        await asyncio.sleep(0)

    monkeypatch.setattr(SearchQueue, "_process", fake_process)
    return processed


async def test_an_identical_running_search_is_not_started_twice():
    """Pressing Run twice for the same thing must not duplicate the work."""
    runner = SearchQueue(None, None, None)  # not started: submissions are held
    common = dict(chat_id=1, message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await runner.submit(user_id=1, **common) == 1
    # Same user, same criteria: already running, so this is a no-op.
    assert await runner.submit(user_id=1, **common) == 0
    assert runner.pending == 1

    # A different user asking the same thing is a genuinely different search.
    assert await runner.submit(user_id=2, **common) == 1
    assert runner.pending == 2


async def test_at_capacity_is_refused_rather_than_growing_without_bound():
    runner = SearchQueue(None, None, None, max_pending=2)
    common = dict(message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await runner.submit(user_id=1, chat_id=1, **common) == 1
    assert await runner.submit(user_id=2, chat_id=2, **common) == 1
    assert await runner.submit(user_id=3, chat_id=3, **common) == -1
    assert runner.pending == 2


async def test_jobs_submitted_before_start_are_not_lost(recorder):
    """start() spawns everything that was held while the runner was off."""
    runner = SearchQueue(None, None, None)
    common = dict(chat_id=1, message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await runner.submit(user_id=1, **common) == 1
    assert recorder == []  # held, not spawned

    runner.start()
    for _ in range(20):
        if recorder:
            break
        await asyncio.sleep(0.01)
    assert len(recorder) == 1
    await runner.stop()


async def test_start_makes_submit_run_immediately(recorder):
    """Once started there is no waiting line: submit == running now."""
    runner = SearchQueue(None, None, None)
    runner.start()
    common = dict(chat_id=1, message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await runner.submit(user_id=1, **common) == 1
    for _ in range(20):
        if recorder:
            break
        await asyncio.sleep(0.01)
    assert len(recorder) == 1
    await runner.stop()


async def test_stop_cancels_a_live_search():
    """A cancelled shutdown must not leave searches spinning in the background."""
    runner = SearchQueue(None, None, None)
    runner.start()

    async def slow_process(job):
        await asyncio.sleep(60)

    runner._process = slow_process  # type: ignore[method-assign]
    common = dict(message_id=None, criteria=_criteria(), lang="en", used=1)
    assert await runner.submit(user_id=1, chat_id=1, **common) == 1
    await asyncio.sleep(0)

    await runner.stop()
    assert runner.pending == 0
    assert runner.done == 0


async def test_a_failing_search_counts_as_failed_and_does_not_spread(recorder, monkeypatch):
    async def broken_process(self, job):
        raise RuntimeError("wedged search")

    monkeypatch.setattr(SearchQueue, "_process", broken_process)
    runner = SearchQueue(None, None, None)
    runner.start()
    common = dict(message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await runner.submit(user_id=1, chat_id=1, **common) == 1
    for _ in range(20):
        if runner.failed:
            break
        await asyncio.sleep(0.01)
    assert runner.failed == 1
    assert runner.done == 0
    # The slot is released: the same search can be started again.
    assert runner.pending == 0
    assert await runner.submit(user_id=1, chat_id=1, **common) == 1
    await runner.stop()


def test_drain_clears_everything_alive():
    runner = SearchQueue(None, None, None)
    runner.done = 5
    runner.failed = 2
    runner.drain()

    assert runner.pending == 0
    assert runner.done == 0
    assert runner.failed == 0
