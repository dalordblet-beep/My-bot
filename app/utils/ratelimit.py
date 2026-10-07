"""Async rate limiting primitives.

A single shared limiter protects every outbound Telegram call. FloodWait
handling is cooperative: whoever receives it calls :meth:`pause` and the whole
queue waits out the window instead of hammering the API.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Token-free, delay-based limiter with a global pause window."""

    min_interval: float = 0.35
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_call: float = 0.0
    _paused_until: float = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._paused_until > now:
                await asyncio.sleep(self._paused_until - now)
                now = time.monotonic()
            wait = self.min_interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    def pause(self, seconds: float) -> None:
        """Stop all callers for ``seconds``. Safe to call from any task."""
        self._paused_until = max(self._paused_until, time.monotonic() + max(seconds, 0.0))

    @property
    def paused_for(self) -> float:
        return max(0.0, self._paused_until - time.monotonic())

    def clear_pause(self) -> None:
        """Drop the current pause window (used once a real call has succeeded)."""
        self._paused_until = 0.0


def spend_flood_window(limiter: RateLimiter, limit_seconds: float) -> float:
    """Report how long the limiter is paused, and clear it if it is short.

    Callers that must stay responsive (a search the user is waiting on) cannot
    afford to block inside :meth:`RateLimiter.acquire` for hours when Telegram
    hands out a FloodWait. This turns that situation into a decision:

    * the wait is short enough to absorb -> clear it and let the caller proceed;
    * the wait is too long -> leave it in place and return the remaining time so
      the caller can abort and tell the user the truth.

    Returns the number of seconds still paused (``0.0`` when it is fine to go).
    """
    remaining = limiter.paused_for
    if remaining <= 0:
        return 0.0
    if remaining <= limit_seconds:
        # Short wait: absorb it in the normal throttling path instead of failing.
        limiter.clear_pause()
        return 0.0
    return remaining


class FloodWaitBudget:
    """Accumulates FloodWait pauses so the UI can report why things are slow."""

    def __init__(self) -> None:
        self.total_paused: float = 0.0
        self.events: int = 0

    def record(self, seconds: float) -> None:
        self.total_paused += seconds
        self.events += 1
