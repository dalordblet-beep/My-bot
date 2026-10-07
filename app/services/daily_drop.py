"""Daily Drop: one search a day, delivered as a message.

A subscriber opts in from Settings. Each day, near a configured local hour, the
bot enqueues one free search using their saved defaults and the result lands in
their chat - the claim kit when a name is found, the honest "all taken" message
when it is not. The work goes through the same :class:`SearchQueue` as every
other search, so it is paced to the safe Telegram rate and served by privilege.

Why a scheduler at all and not "search on /start"? Because the point is that the
bot keeps hunting while the user is away - a message that arrives at 09:00 with a
fresh name is worth more than anything they would remember to ask for.

Design notes, mirroring the TrapWatcher:

* **Once a day.** Each subscriber is stamped the moment a drop is enqueued, so a
  restart or a missed hour cannot produce two drops for the same day.
* **Gentle.** The scheduler only *enqueues*; the queue paces the actual
  lookups, so a thousand subscribers cannot become a thousand-name burst.
* **No speculative messaging.** Nothing is sent unless a search actually runs,
  and the result is the standard, honest search output - never a fake "you won".
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timezone

from aiogram import Bot

from app.database import repository as repo
from app.database.database import session_scope
from app.search.finder import SearchCriteria, TARGET_FREE
from app.services.search_queue import SearchQueue, priority_for
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# How often the loop wakes to check whether it is drop time.
DEFAULT_TICK = 900.0          # 15 minutes
# The local hour at which drops are released.
DEFAULT_HOUR = 9


class DailyDropService:
    def __init__(
        self,
        bot: Bot,
        search_queue: SearchQueue,
        *,
        hour: int = DEFAULT_HOUR,
        tick: float = DEFAULT_TICK,
    ) -> None:
        self._bot = bot
        self._queue = search_queue
        self._hour = int(hour)
        self._tick = max(60.0, float(tick))
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="daily-drop")
            logger.info("daily drop started (hour=%s, tick=%ss)", self._hour, int(self._tick))

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
            logger.info("daily drop stopped")

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("daily drop sweep failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._tick)
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------ work
    async def sweep(self, force: bool = False) -> int:
        """Enqueue a drop for every due subscriber. Returns how many were queued.

        ``force=True`` ignores the hour gate - used by tests and by an explicit
        "send now" action.
        """
        now = datetime.now()
        if not force and now.hour != self._hour:
            return 0

        async with session_scope() as session:
            subscribers = await repo.list_daily_drop_subscribers(session)
        if not subscribers:
            return 0

        delivered = 0
        for telegram_id, lang in subscribers:
            if self._stopping.is_set():
                break
            if await self._deliver_one(telegram_id, lang):
                delivered += 1

        if delivered:
            logger.info("daily drop queued %s drop(s)", delivered)
        else:
            logger.debug("daily drop: no new drops this cycle")
        return delivered

    async def _deliver_one(self, telegram_id: int, lang: str) -> bool:
        """Queue one search for a subscriber, stamping them so it is not repeated."""
        async with session_scope() as session:
            user = await repo.get_user_by_telegram_id(session, telegram_id)
            if user is None or user.is_banned:
                return False
            row = await repo.get_user_settings(session, user.id)
            if row is None or not row.daily_drop:
                return False

            today = datetime.now(timezone.utc).date()
            if row.daily_drop_last is not None and row.daily_drop_last.date() >= today:
                # Already dropped today - the stamp is the once-a-day guarantee.
                return False

            criteria = SearchCriteria(
                length=row.search_length or None,
                allow_digits=bool(row.search_digits),
                target=TARGET_FREE,
            )
            # Stamp before enqueuing, so a crash between here and delivery cannot
            # enqueue a second drop for the same day on the next cycle.
            await repo.update_user_settings(
                session, user.id, daily_drop_last=datetime.now(timezone.utc)
            )

        ahead = await self._queue.submit(
            user_id=telegram_id,
            chat_id=telegram_id,
            message_id=None,
            criteria=criteria,
            lang=lang,
            used=1,
            priority=priority_for(user.privilege),
            kind="digest",
        )
        if ahead == -1:
            logger.warning("daily drop queue full - skipping %s", telegram_id)
            return False
        return True
