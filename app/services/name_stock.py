"""A ready supply of *verified* free usernames.

The problem this solves
-----------------------
Telegram rate-limits the authoritative availability check hard - roughly 20-30
calls per account per minute - and proving one name free costs several calls,
because most candidates are taken. So a search that hunts on demand has a hard
throughput ceiling: past it the bot can only wait, and waiting is exactly what
"users are waiting" means.

The fix is to decouple *verification* from *delivery*:

* a background **harvester** spends the quota while the bot is idle, proving
  names free and parking them in the ``free_names`` table;
* a **search** serves one of them after a single re-confirmation.

The re-confirmation is what keeps the promise honest. A stored name is only
handed over when Telegram answers "claimable" for it *at that moment*, so a
stale row (somebody claimed the name meanwhile) can never be delivered as free -
it is dropped and the search carries on. Nothing here is allowed to invent a
verdict: the stock only ever stores names the same authoritative check accepted.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

from app.config import settings
from app.database import repository as repo
from app.database.database import session_scope
from app.search.finder import TARGET_FREE, SearchCriteria, UsernameFinder
from app.search.pattern import premium_rating
from app.telegram.username_checker import UsernameChecker
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# The shapes the harvester keeps in stock. The length is the user's filter and
# the most requested values are the short ones, so those are refilled first.
HARVEST_LENGTHS = (5, 6, 7, 8)
# How often the harvester may spend a *harvest* confirmation relative to the
# pool's own pace. Two means the harvester never takes more than half of the
# spare capacity: live searches always come first.
HARVEST_PACE_FACTOR = 2.0


class NameStock:
    """Background harvester plus the dispenser a search reads from.

    The harvester is deliberately timid. It yields to live searches (it skips a
    tick whenever one is running), it refills one name per tick, and it stops as
    soon as the target level is reached. Its whole purpose is to make the *idle*
    quota useful, never to compete with a user who is waiting.
    """

    def __init__(
        self,
        checker: UsernameChecker,
        collectible: Any | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._checker = checker
        self._collectible = collectible
        self._rng = rng or random.Random()
        self._task: asyncio.Task | None = None
        self._queue: Any | None = None
        self.harvested = 0
        self.discarded = 0

    # ------------------------------------------------------------------ control
    def attach_queue(self, queue: Any) -> None:
        """Give the harvester the search runner, so it can yield to live traffic."""
        self._queue = queue

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def enabled(self) -> bool:
        return settings.name_stock_target > 0

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "name stock harvester running (target %d, every %.0fs)",
            settings.name_stock_target, settings.name_stock_interval,
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        # A short first delay: let the bot finish booting and serve whatever
        # request arrives first before the harvester starts spending quota.
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(min(10.0, settings.name_stock_interval))
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a broken harvest must never kill the bot
                logger.warning("name stock harvest failed: %s", exc)
            try:
                await asyncio.sleep(max(1.0, settings.name_stock_interval))
            except asyncio.CancelledError:
                raise

    async def _tick(self) -> None:
        if self._queue is not None and getattr(self._queue, "busy", False):
            logger.debug("name stock: a search is running - yielding")
            return

        size = await self.size()
        if size >= settings.name_stock_target:
            await self._prune()
            return

        harvested = await self.harvest_once()
        if harvested is None:
            # Nothing was provable this round - most likely Telegram throttled
            # every session. Say nothing to the user; try again next tick.
            logger.debug("name stock: nothing harvested this round")
        await self._prune()

    async def _prune(self) -> None:
        try:
            async with session_scope() as session:
                removed = await repo.prune_free_names(session, settings.name_stock_ttl)
            if removed:
                logger.info("name stock: pruned %d stale name(s)", removed)
        except Exception as exc:  # pragma: no cover - database dependent
            logger.debug("name stock prune failed: %s", exc)

    # ------------------------------------------------------------------ harvest
    def _criteria(self) -> SearchCriteria:
        """The next shape to refill: short names first, digits half the time."""
        length = self._rng.choice(HARVEST_LENGTHS)
        return SearchCriteria(
            length=length,
            allow_digits=self._rng.random() < 0.5,
            target=TARGET_FREE,
        )

    async def harvest_once(self) -> str | None:
        """Prove one more name free and store it. ``None`` if none could be.

        The hunt itself is the ordinary search - the same generator gates, the
        same public-page screen, the same authoritative confirmation and the
        same Fragment veto. Only the *deadline* differs: a harvest yields after
        a short wait instead of holding the quota for minutes, because a live
        search must never queue behind background work.
        """
        criteria = self._criteria()
        finder = UsernameFinder(self._checker, self._collectible, rng=self._rng)
        attempt = await finder.find_one(
            criteria, max_seconds=settings.name_stock_harvest_seconds
        )
        if not attempt.hit or not attempt.username:
            return None

        # Only a verdict Telegram actually confirmed is worth storing. An
        # unverified "nobody owns it" is not a name the bot may hand out.
        detail = getattr(attempt.basic, "detail", None)
        if detail != "claimability_verified":
            logger.debug(
                "name stock: @%s resolved but is not verified claimable - not stored",
                attempt.username,
            )
            return None

        name = attempt.username
        stored = False
        try:
            async with session_scope() as session:
                stored = await repo.add_free_name(
                    session,
                    name,
                    length=len(name),
                    has_digits=any(ch.isdigit() for ch in name),
                    score=premium_rating(name).total,
                    source="harvest",
                )
        except Exception as exc:  # pragma: no cover - database dependent
            logger.warning("name stock: could not store @%s: %s", name, exc)
            return None

        if stored:
            self.harvested += 1
            logger.info("name stock: @%s verified free and stored (total %d)", name, self.harvested)
            return name
        return None

    # ------------------------------------------------------------------ dispense
    async def size(self) -> int:
        try:
            async with session_scope() as session:
                return await repo.count_free_names(session)
        except Exception as exc:  # pragma: no cover - database dependent
            logger.debug("name stock size failed: %s", exc)
            return 0

    async def take(self, length: int | None, allow_digits: bool) -> str | None:
        """Reserve a stored name matching the requested shape, if there is one.

        ``None`` simply means "nothing suitable in stock" - the caller then hunts
        normally, so an empty stock degrades to the old behaviour instead of
        blocking anything.
        """
        if not self.enabled:
            return None
        try:
            async with session_scope() as session:
                return await repo.take_free_name(
                    session, length=length, allow_digits=allow_digits
                )
        except Exception as exc:  # pragma: no cover - database dependent
            logger.debug("name stock take failed: %s", exc)
            return None

    async def release(self, username: str) -> None:
        """Put a reserved name back - it could not be verified this time."""
        try:
            async with session_scope() as session:
                await repo.release_free_name(session, username)
        except Exception as exc:  # pragma: no cover - database dependent
            logger.debug("name stock release failed: %s", exc)

    async def discard(self, username: str) -> None:
        """Forget a stored name: Telegram no longer says it is claimable."""
        self.discarded += 1
        try:
            async with session_scope() as session:
                await repo.drop_free_name(session, username)
            logger.info("name stock: @%s is no longer claimable - dropped", username)
        except Exception as exc:  # pragma: no cover - database dependent
            logger.debug("name stock discard failed: %s", exc)

    async def consume(self, username: str) -> None:
        """Retire a name that has just been delivered to a user.

        It is deliberately removed rather than left behind: the name is now out
        in the world and will very likely be claimed, so keeping it would only
        feed a later search a stale entry that has to be thrown away.
        """
        try:
            async with session_scope() as session:
                await repo.drop_free_name(session, username)
            logger.info("name stock: @%s delivered and retired", username)
        except Exception as exc:  # pragma: no cover - database dependent
            logger.debug("name stock consume failed: %s", exc)
