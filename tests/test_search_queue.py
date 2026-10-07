"""The search queue: ordering, dedup and back-pressure.

The queue is what lets the bot say "unlimited" to a user while still holding a
safe Telegram request rate. These tests pin the two properties that matter:
higher privileges are served first, and the queue cannot be abused into
unbounded growth or duplicate work.
"""

from __future__ import annotations

from app.search.finder import SearchCriteria
from app.services.search_queue import SearchJob, SearchQueue, priority_for
from app.utils.enums import Privilege


def _criteria() -> SearchCriteria:
    return SearchCriteria(length=6)


def test_privilege_decides_queue_order():
    """A paid tier buys position in the queue - that is the whole product."""
    assert priority_for(Privilege.ADMIN.value) < priority_for(Privilege.PREMIUM.value)
    assert priority_for(Privilege.PREMIUM.value) < priority_for(Privilege.VIP.value)
    assert priority_for(Privilege.VIP.value) < priority_for(Privilege.FREE.value)
    assert priority_for(None) == priority_for(Privilege.FREE.value)
    assert priority_for("nonsense") == priority_for(Privilege.FREE.value)


def test_jobs_are_ordered_by_priority_then_arrival():
    criteria = _criteria()
    premium = SearchJob(10, 2, 2, 2, None, criteria, "en", 1)
    free = SearchJob(30, 1, 1, 1, None, criteria, "en", 1)
    assert premium < free  # premium jumps ahead of an earlier free request

    first = SearchJob(30, 1, 1, 1, None, criteria, "en", 1)
    second = SearchJob(30, 2, 2, 2, None, criteria, "en", 1)
    assert first < second  # equal priority stays FIFO


async def test_an_identical_pending_search_is_not_queued_twice():
    queue = SearchQueue(None, None, None)
    common = dict(chat_id=1, message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await queue.submit(user_id=1, **common) == 1
    # Same user, same criteria: already waiting, so this is a no-op.
    assert await queue.submit(user_id=1, **common) == 0
    assert queue.pending == 1

    # A different user asking the same thing is a genuinely different job.
    assert await queue.submit(user_id=2, **common) == 2
    assert queue.pending == 2


async def test_a_full_queue_is_refused_rather_than_growing_without_bound():
    queue = SearchQueue(None, None, None, max_pending=2)
    common = dict(message_id=None, criteria=_criteria(), lang="en", used=1)

    assert await queue.submit(user_id=1, chat_id=1, **common) == 1
    assert await queue.submit(user_id=2, chat_id=2, **common) == 2
    assert await queue.submit(user_id=3, chat_id=3, **common) == -1


def test_drain_clears_everything_still_waiting():
    queue = SearchQueue(None, None, None)
    queue.done = 5
    queue.failed = 2
    queue.drain()

    assert queue.pending == 0
    assert queue.done == 0
    assert queue.failed == 0
