"""The verdict cache: what may be remembered, and for how long.

This is the cheapest throughput win in the bot - remembering a verdict costs no
Telegram quota - but it is also the one place where a mistake would make the bot
lie. These tests pin the asymmetry that keeps it safe.
"""

from __future__ import annotations

import time

from app.utils.enums import CheckStatus
from app.utils.results import CheckResult
from app.utils.verdict_cache import VerdictCache


def _result(name: str, status: CheckStatus) -> CheckResult:
    return CheckResult(username=name, status=status, source="test")


def test_occupied_is_remembered():
    cache = VerdictCache()
    cache.put(_result("crane", CheckStatus.OCCUPIED))

    hit = cache.get("crane")
    assert hit is not None
    assert hit.status is CheckStatus.OCCUPIED
    assert hit.cached is True


def test_unknown_and_rate_limited_are_never_remembered():
    """Freezing "we do not know" would turn an outage into a wrong answer."""
    cache = VerdictCache()
    cache.put(_result("a", CheckStatus.UNKNOWN))
    cache.put(_result("b", CheckStatus.RATE_LIMITED))
    cache.put(_result("c", CheckStatus.ERROR))

    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.get("c") is None
    assert cache.size == 0


def test_reserved_names_are_remembered_too():
    """INVALID from Telegram means "reserved" - as stable as OCCUPIED."""
    cache = VerdictCache()
    cache.put(_result("tgapp", CheckStatus.INVALID))

    hit = cache.get("tgapp")
    assert hit is not None
    assert hit.status is CheckStatus.INVALID


def test_occupied_outlives_free():
    """A stale "taken" only causes a miss; a stale "free" would be a lie."""
    cache = VerdictCache(occupied_ttl=3600, free_ttl=0.01)
    cache.put(_result("crane", CheckStatus.OCCUPIED))
    cache.put(_result("fresh", CheckStatus.AVAILABLE))

    time.sleep(0.02)

    assert cache.get("crane") is not None
    assert cache.get("fresh") is None


def test_cache_is_bounded_by_lru():
    cache = VerdictCache(max_entries=3)
    for index in range(10):
        cache.put(_result(f"name{index}", CheckStatus.OCCUPIED))

    assert cache.size == 3
    # The oldest entries were evicted, the newest survived.
    assert cache.get("name0") is None
    assert cache.get("name9") is not None
