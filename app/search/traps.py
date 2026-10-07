"""Trap watcher.

A "trap" is a username the user wants to be told about the moment it becomes
free. Telegram has no "username released" event, so this polls - there is no
honest alternative.

**"Instant" means "within one check interval".** The old design ran a single
global sweep every ten minutes, so a trap created a minute after a sweep waited
nine minutes for its first check. That is indistinguishable from broken.

The scheduler here is per-trap: every trap carries its own next-check time, the
loop wakes on a short tick, and a newly created trap is due immediately. Worst
case latency is therefore one ``interval``, not two.

Design constraints:

* **Gentle.** Checks are sequential with a minimum spacing between them, so a
  hundred traps cannot become a burst.
* **Exactly once.** A trap is deactivated and stamped the moment it is reported,
  so a restart cannot produce a duplicate notification.
* **Never speculative.** Only a confirmed AVAILABLE verdict fires a
  notification. UNKNOWN is not good news and is not reported as such.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from aiogram import Bot

from app.bot import texts
from app.collectible.checker import CollectibleChecker
from app.database.database import session_scope
from app.database import repository as repo
from app.search.pattern import generate_from_mask, mask_is_usable
from app.services.i18n import DEFAULT_LANGUAGE, normalise
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus, CollectibleStatus
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_INTERVAL = 15.0        # fastest supported repeat interval per username
DEFAULT_TICK = 1.0             # detect newly added watches promptly
DEFAULT_PER_CHECK_DELAY = 1.0  # main passes the shared Telegram request interval
# How many candidates a mask sniper tries per check. Bounded on purpose: a
# sniper must stay gentle, it is not a bulk scanner.
MASK_CANDIDATES_PER_SWEEP = 6
WATCH_CHECK_TIMEOUT = 15.0


class TrapWatcher:
    def __init__(
        self,
        bot: Bot,
        checker: UsernameChecker,
        collectible_checker: CollectibleChecker | None = None,
        interval: float = DEFAULT_INTERVAL,
        per_check_delay: float = DEFAULT_PER_CHECK_DELAY,
        tick: float = DEFAULT_TICK,
    ) -> None:
        self._bot = bot
        self._checker = checker
        self._collectible = collectible_checker
        self._interval = max(15.0, float(interval))
        self._per_check_delay = max(0.0, float(per_check_delay))
        self._tick = max(1.0, min(float(tick), self._interval))
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # trap id -> monotonic time it is next due
        self._due: dict[int, float] = {}

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="trap-watcher")
            logger.info(
                "trap watcher started (each trap checked every %ss, tick %ss)",
                int(self._interval), int(self._tick),
            )

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("trap watcher stopped")

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("trap sweep failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._tick)
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------ work
    async def sweep(self, force: bool = False) -> int:
        """Check every trap that is due. Returns how many notifications fired.

        ``force=True`` ignores the schedule - used by tests and by an explicit
        "check now" action.
        """
        async with session_scope() as session:
            traps = list(await repo.list_active_traps(session))
        if not traps:
            self._due.clear()
            return 0

        now = time.monotonic()
        # A trap created since the last tick has no entry yet, so it is due now.
        for trap in traps:
            self._due.setdefault(trap.id, 0.0)

        # Drop entries for traps that are gone or deactivated.
        live = {trap.id for trap in traps}
        for stale in set(self._due) - live:
            self._due.pop(stale, None)

        due = [
            trap for trap in traps
            if force or self._due.get(trap.id, 0.0) <= now
        ]
        fired = 0
        for index, trap in enumerate(due):
            if self._stopping.is_set():
                break

            try:
                # Each kind has its own alert semantics. Lookups stay strictly
                # sequential and evenly paced across all users.
                if getattr(trap, "kind", "name") == "mask":
                    hit = await self._sweep_mask(trap)
                elif getattr(trap, "kind", "name") == "collectible":
                    hit = await self._sweep_collectible(trap)
                else:
                    hit = await self._sweep_name(trap)
                if hit:
                    fired += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watch check failed for row %s", trap.id)
                with contextlib.suppress(Exception):
                    await self._record(trap.id, CheckStatus.ERROR.value)
            finally:
                # Start the interval after this check completes. Setting it
                # before a slow network call can make an overdue watch spin.
                self._due[trap.id] = time.monotonic() + self._interval

            if index < len(due) - 1:
                await self._pace()

        if fired:
            logger.info("trap sweep fired %s notification(s)", fired)
        else:
            logger.debug("trap sweep checked %s trap(s), nothing released", len(traps))
        return fired

    async def _pace(self) -> None:
        """Space every due watch through the shared external-request budget."""
        if self._per_check_delay > 0:
            await asyncio.sleep(self._per_check_delay)

    async def _sweep_name(self, trap) -> str | None:
        """Watch one exact username for release; unknown is never treated as free."""
        if self._stopping.is_set():
            return None
        try:
            result = await asyncio.wait_for(
                self._checker.check_for_release(trap.username),
                timeout=WATCH_CHECK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("username watch timed out for %s", trap.username)
            with contextlib.suppress(Exception):
                await self._record(trap.id, CheckStatus.RATE_LIMITED.value)
            return None
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("trap check failed for %s: %s", trap.username, exc)
            with contextlib.suppress(Exception):
                await self._record(trap.id, CheckStatus.ERROR.value)
            return None

        freed = result.status is CheckStatus.AVAILABLE
        recorded = await self._record(trap.id, result.status.value, freed=freed)
        if not freed or not recorded:
            return None
        await self._notify(trap.telegram_id, trap.username)
        return trap.username

    async def _sweep_collectible(self, trap) -> str | None:
        """Watch a name on Fragment: notify when it goes for sale or drops price.

        Collectibles are never "free" - they are tradeable assets. The useful
        events are: a watched name appears for sale, or its price changes. The
        trap's ``last_status`` stores a compact state ("sale:<price>" / "none")
        so we only fire on a real change, never every sweep.
        """
        if self._collectible is None:
            return None
        try:
            coll = await self._collectible.check_collectible_username(trap.username)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("collectible trap check failed for %s: %s", trap.username, exc)
            return None

        if coll.status is CollectibleStatus.UNKNOWN:
            await self._record(trap.id, "unknown")
            return None

        # OWNED alone is not news: every collectible has an owner, so alerting on
        # it would fire once for every watch the moment it was set. The events
        # worth a notification are "now for sale" and "the asking price moved".
        is_for_sale = coll.status in (
            CollectibleStatus.AVAILABLE_FOR_PURCHASE,
            CollectibleStatus.LISTED,
        )
        new_state = (
            f"sale:{coll.price or ''}:{coll.status.value}" if is_for_sale else "none"
        )
        prev = trap.last_status or ""

        # Fire on first appearance for sale, or on any price/state change.
        notify = is_for_sale and (not prev.startswith("sale") or prev != new_state)
        recorded = await self._record(trap.id, new_state)
        if notify and recorded:
            await self._notify_collectible(trap.telegram_id, trap.username, coll)
            return trap.username
        return None

    async def _sweep_mask(self, trap) -> str | None:
        """Sniper: try a few fresh candidates from the mask, report the first free one."""
        if not mask_is_usable(trap.username):
            logger.warning("mask trap %s has an unusable mask, deactivating", trap.id)
            await self._record(trap.id, "invalid_mask")
            return None

        for _ in range(MASK_CANDIDATES_PER_SWEEP):
            if self._stopping.is_set():
                return None
            candidate = generate_from_mask(trap.username)
            if candidate is None:
                continue
            try:
                result = await self._checker.check_basic_username(candidate, use_cache=False)
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("mask trap check failed for %s: %s", candidate, exc)
                continue

            if result.status is CheckStatus.AVAILABLE:
                recorded = await self._record(trap.id, result.status.value, freed=True)
                if recorded:
                    await self._notify(trap.telegram_id, candidate)
                    return candidate
                return None

            await asyncio.sleep(self._per_check_delay)

        await self._record(trap.id, "searching")
        return None

    @staticmethod
    async def _record(trap_id: int, status: str, freed: bool = False) -> bool:
        """Persist the outcome once; only the process that wins may notify."""
        async with session_scope() as session:
            fresh = await repo.get_trap(session, trap_id)
            if fresh is None or not fresh.active:
                return False
            if freed and fresh.notified_at is not None:
                return False
            await repo.touch_trap(session, fresh, status, freed=freed)
        return True

    async def _notify(self, telegram_id: int, username: str) -> None:
        lang = await self._language_for(telegram_id)
        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=texts.watch_alert(lang, username),
                reply_markup=None,
            )
            logger.info("trap fired: %s notified about %s", telegram_id, username)
        except Exception as exc:
            logger.warning("could not notify %s about %s: %s", telegram_id, username, exc)

    async def _notify_collectible(self, telegram_id: int, username: str, coll) -> None:
        lang = await self._language_for(telegram_id)
        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=texts.trap_collectible(lang, username, coll.price, coll.status.value),
                reply_markup=None,
            )
            logger.info("collectible trap fired: %s notified about %s", telegram_id, username)
        except Exception as exc:
            logger.warning("could not notify %s about %s: %s", telegram_id, username, exc)

    @staticmethod
    async def _language_for(telegram_id: int) -> str:
        try:
            async with session_scope() as session:
                user = await repo.get_user_by_telegram_id(session, telegram_id)
                if user is None:
                    return DEFAULT_LANGUAGE
                row = await repo.get_user_settings(session, user.id)
                return normalise(row.language)
        except Exception:
            return DEFAULT_LANGUAGE
