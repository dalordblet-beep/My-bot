"""Mass scanner: dedupe, concurrency ceiling, progress, aggregation."""

from __future__ import annotations

import asyncio

from app.search.scanner import UsernameScanner, resolve_scan_limit
from app.utils.enums import CheckStatus
from app.utils.results import CheckResult, ScanSummary


class StubChecker:
    def __init__(self, mapping: dict[str, CheckStatus], delay: float = 0.0) -> None:
        self.mapping = mapping
        self.delay = delay
        self.calls: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0

    async def check_basic_username(self, username: str, use_cache: bool = True) -> CheckResult:
        self.calls.append(username)
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            status = self.mapping.get(username, CheckStatus.UNKNOWN)
            return CheckResult(username=username, status=status, source="stub")
        finally:
            self.concurrent -= 1


async def test_deduplicates_and_counts_invalid():
    checker = StubChecker({"alpha": CheckStatus.AVAILABLE})
    scanner = UsernameScanner(checker, max_concurrent=2)

    summary = await scanner.scan(["alpha", "@alpha", "ALPHA", "ab", "bad-dash"])

    assert summary.total == 3
    assert summary.invalid == 2
    assert summary.checked == 3
    assert checker.calls == ["alpha"]


async def test_aggregates_statuses():
    checker = StubChecker(
        {
            "alpha": CheckStatus.AVAILABLE,
            "bravo": CheckStatus.OCCUPIED,
            "charlie": CheckStatus.AVAILABLE,
            "delta": CheckStatus.UNKNOWN,
        }
    )
    scanner = UsernameScanner(checker, max_concurrent=4)

    summary = await scanner.scan(["alpha", "bravo", "charlie", "delta"])

    assert summary.available == 2
    assert summary.occupied == 1
    assert summary.unknown == 1
    assert set(summary.available_usernames) == {"alpha", "charlie"}
    assert summary.checked == 4
    assert summary.duration_seconds >= 0


async def test_concurrency_ceiling_is_respected():
    names = [f"name{index:02d}" for index in range(20)]
    checker = StubChecker({name: CheckStatus.AVAILABLE for name in names}, delay=0.01)
    scanner = UsernameScanner(checker, max_concurrent=3)

    await scanner.scan(names)

    assert checker.max_concurrent <= 3


async def test_progress_callback_receives_final_snapshot():
    names = [f"user{index}" for index in range(6)]
    checker = StubChecker({}, delay=0.0)
    scanner = UsernameScanner(checker, max_concurrent=2, progress_interval=0.0)

    snapshots: list[ScanSummary] = []

    async def on_progress(summary: ScanSummary) -> None:
        snapshots.append(summary)

    await scanner.scan(names, progress_cb=on_progress)

    assert snapshots
    assert snapshots[-1].checked == snapshots[-1].total == 6


async def test_rate_limited_result_is_retried_once():
    class FlakyChecker:
        def __init__(self) -> None:
            self.attempts = 0

        async def check_basic_username(self, username: str, use_cache: bool = True) -> CheckResult:
            self.attempts += 1
            if self.attempts == 1:
                return CheckResult(username=username, status=CheckStatus.RATE_LIMITED, source="stub")
            return CheckResult(username=username, status=CheckStatus.AVAILABLE, source="stub")

    checker = FlakyChecker()
    scanner = UsernameScanner(checker, max_concurrent=1)

    summary = await scanner.scan(["alpha"])

    assert checker.attempts == 2
    assert summary.available == 1


def test_resolve_scan_limit_caps_to_hard_max():
    assert resolve_scan_limit(10, hard_max=50) == 10
    assert resolve_scan_limit(500, hard_max=50) == 50
    assert resolve_scan_limit(0, hard_max=50) == 10
