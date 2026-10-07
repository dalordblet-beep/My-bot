"""In-memory verdict cache - the cheapest throughput win in the bot.

Telegram quota is the scarce resource here, and the same handful of usernames
gets re-checked constantly: a user presses Search again, several users hunt the
same short valuable length, or a trap sweeps a name that was already resolved.
Remembering a verdict costs no quota at all, so this multiplies effective
throughput without touching a single Telegram limit.

The asymmetry between the two verdicts is the whole point:

* **OCCUPIED is stable.** A name taken today is almost certainly taken
  tomorrow. Caching it can only ever cause a *miss* - we skip a candidate - and
  can never produce a false "free". That makes a long TTL safe, and it is what
  saves the most.
* **AVAILABLE is volatile.** Somebody can claim the name within minutes, so it
  is remembered only briefly. A stale "free" would be a lie, which is exactly
  what this bot must never tell.

UNKNOWN and RATE_LIMITED are never cached: they mean "we do not know", and
freezing that would turn a temporary outage into a permanent wrong answer.
"""

from __future__ import annotations

import time
from collections import OrderedDict

from app.utils.enums import CheckStatus
from app.utils.results import CheckResult


class VerdictCache:
    """A bounded, TTL-based, per-process cache of username verdicts.

    Keyed by username. Entries are evicted by expiry or by LRU once the cache
    is full, so a long-running bot cannot grow without bound.
    """

    def __init__(
        self,
        occupied_ttl: float = 86_400.0,
        free_ttl: float = 60.0,
        max_entries: int = 20_000,
    ) -> None:
        self._occupied_ttl = occupied_ttl
        self._free_ttl = free_ttl
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------ reading
    def get(self, username: str) -> CheckResult | None:
        entry = self._store.get(username)
        if entry is None:
            self.misses += 1
            return None

        expires_at, payload = entry
        if expires_at <= time.monotonic():
            self._store.pop(username, None)
            self.misses += 1
            return None

        self._store.move_to_end(username)
        self.hits += 1
        return CheckResult.from_cache(payload)

    # ------------------------------------------------------------------ writing
    def put(self, result: CheckResult) -> None:
        if result.status in (CheckStatus.OCCUPIED, CheckStatus.INVALID):
            # Both are stable: a taken name stays taken, and a name Telegram
            # rejects as reserved stays reserved (that is why reference tools
            # keep a permanent reserved.txt). A stale verdict here can only cost
            # us a missed candidate - never a false "free".
            ttl = self._occupied_ttl
        elif result.status is CheckStatus.AVAILABLE:
            ttl = self._free_ttl
        else:
            # "We do not know" (UNKNOWN / RATE_LIMITED / ERROR) must never become
            # a frozen answer - that would turn a temporary outage into a
            # permanent lie.
            return

        if ttl <= 0:
            return

        self._store[result.username] = (time.monotonic() + ttl, result.to_cache())
        self._store.move_to_end(result.username)

        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    # ------------------------------------------------------------------ upkeep
    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    @property
    def size(self) -> int:
        return len(self._store)

    def stats(self) -> dict[str, int]:
        return {"size": self.size, "hits": self.hits, "misses": self.misses}
