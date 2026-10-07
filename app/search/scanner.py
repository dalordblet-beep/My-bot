"""Mass username scanner.

Bounded concurrency, shared rate limiter, throttled progress reporting and a
single aggregate result. Never fires hundreds of requests at once.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from app.config import settings
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus, UsernameType
from app.utils.logging_setup import get_logger
from app.utils.results import ScanItem, ScanSummary
from app.utils.username import parse_username

logger = get_logger(__name__)

ProgressCallback = Callable[[ScanSummary], Awaitable[None]]


class UsernameScanner:
    def __init__(
        self,
        checker: UsernameChecker,
        max_concurrent: int | None = None,
        progress_interval: float = 1.5,
    ) -> None:
        self._checker = checker
        self._max_concurrent = max_concurrent or settings.max_concurrent_checks
        self._progress_interval = progress_interval

    async def scan(
        self,
        usernames: list[str],
        progress_cb: ProgressCallback | None = None,
        on_item: Callable[[ScanItem], Awaitable[None]] | None = None,
    ) -> ScanSummary:
        started = time.perf_counter()

        # 1. normalise + dedupe + validate up front, so we never waste requests.
        unique: list[str] = []
        seen: set[str] = set()
        summary = ScanSummary()
        for raw in usernames:
            parsed = parse_username(raw)
            if not parsed.is_valid:
                summary.invalid += 1
                summary.checked += 1
                summary.total += 1
                continue
            if parsed.value in seen:
                continue
            seen.add(parsed.value)
            unique.append(parsed.value)

        summary.total = summary.checked + len(unique)
        summary.checked = summary.total - len(unique)

        semaphore = asyncio.Semaphore(self._max_concurrent)
        lock = asyncio.Lock()
        last_report = 0.0

        async def report(force: bool = False) -> None:
            nonlocal last_report
            if progress_cb is None:
                return
            now = time.monotonic()
            if not force and now - last_report < self._progress_interval:
                return
            last_report = now
            snapshot = ScanSummary(
                total=summary.total,
                checked=summary.checked,
                available=summary.available,
                occupied=summary.occupied,
                collectible=summary.collectible,
                invalid=summary.invalid,
                unknown=summary.unknown,
                errors=summary.errors,
                rate_limited=summary.rate_limited,
                available_usernames=list(summary.available_usernames),
                collectible_usernames=list(summary.collectible_usernames),
                flood_wait_seconds=summary.flood_wait_seconds,
            )
            await progress_cb(snapshot)

        async def worker(name: str) -> None:
            async with semaphore:
                result = await self._checker.check_basic_username(name)
                # One retry after a flood-wait pause.
                if result.status is CheckStatus.RATE_LIMITED:
                    await asyncio.sleep(settings.floodwait_safety_margin)
                    result = await self._checker.check_basic_username(name, use_cache=False)

            async with lock:
                summary.checked += 1
                if result.status is CheckStatus.AVAILABLE:
                    summary.available += 1
                    summary.available_usernames.append(name)
                elif result.status is CheckStatus.OCCUPIED:
                    summary.occupied += 1
                elif result.status is CheckStatus.INVALID:
                    summary.invalid += 1
                elif result.status is CheckStatus.RATE_LIMITED:
                    summary.rate_limited += 1
                elif result.status is CheckStatus.ERROR:
                    summary.errors += 1
                else:
                    summary.unknown += 1

                if on_item is not None:
                    await on_item(ScanItem(username=name, status=result.status))

            await report()

        if unique:
            await asyncio.gather(*(worker(name) for name in unique))

        summary.duration_seconds = round(time.perf_counter() - started, 2)
        await report(force=True)

        logger.info(
            "scan complete total=%s available=%s occupied=%s unknown=%s duration=%ss",
            summary.total, summary.available, summary.occupied,
            summary.unknown, summary.duration_seconds,
        )
        return summary


def resolve_scan_limit(requested: int, hard_max: int | None = None) -> int:
    limit = hard_max or settings.max_search_results
    if requested <= 0:
        return min(10, limit)
    return min(requested, limit)
