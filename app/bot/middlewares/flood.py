"""FloodGuard: keep a burst of updates from taking the bot down.

aiogram handles every update in its own task. That is fine for real traffic and
fatal for a flood: a few thousand messages a minute spawn a few thousand
concurrent tasks, each opening a database session and (through the access gate)
asking Telegram about a membership - and the process dies of exhaustion. The
captcha gate does not help here: it is per-user and a flood comes from many
accounts, or from one account that simply keeps hammering.

So the guard sits *before* any real work and does two things:

* a **per-user budget** - a handful of updates per few seconds. A person
  tapping through menus never notices it; a script does.
* a **global in-flight ceiling** - the total number of updates being handled at
  once is capped, so no amount of traffic can turn into unbounded concurrency.
  Beyond the cap the update is shed: dropping a message is always better than
  dropping the process.

Everything is bounded, including the guard's own bookkeeping - a flood of
distinct user ids must not leak memory either.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.database.database import pool_capacity
from app.services.i18n import DEFAULT_LANGUAGE, t
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# A person never sends more than a few updates per second; a script sends
# hundreds. Six per three seconds leaves real use untouched.
USER_WINDOW_SECONDS = 3.0
USER_MAX_PER_WINDOW = 6
# Once over the budget, the user is ignored for this long. Long enough to blunt
# a burst, short enough that an over-eager real user recovers on their own.
MUTE_SECONDS = 20.0
# The total number of updates allowed to be mid-handling at once. This is the
# number that keeps the bot alive: every update holds a database connection
# while its database work runs, and the background services (trap watcher, name
# stock, daily drop, db backup) need connections too. Exceed the pool and it
# exhausts - exactly the crash we saw: "QueuePool limit of size 10 overflow 20
# reached", after which every update waited 30 seconds for a connection that
# never came. SQLite makes it worse, because writes serialise, so more
# concurrency only makes each write hold its connection longer.
#
# So the cap is derived from the pool, not guessed: updates may use two fifths
# of it, and a flood that tries to exceed that is shed here - before it can
# touch the pool - rather than being allowed to take the process down.
GLOBAL_MAX_IN_FLIGHT = max(4, pool_capacity() * 2 // 5)
# Bookkeeping caps - the guard must not leak under a flood of distinct users.
_MAX_TRACKED_USERS = 20_000


class FloodGuardMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        window: float = USER_WINDOW_SECONDS,
        per_window: int = USER_MAX_PER_WINDOW,
        mute_seconds: float = MUTE_SECONDS,
        max_in_flight: int = GLOBAL_MAX_IN_FLIGHT,
    ) -> None:
        self._window = window
        self._per_window = per_window
        self._mute_seconds = mute_seconds
        self._max_in_flight = max_in_flight
        # user_id -> [monotonic timestamps inside the current window]
        self._hits: dict[int, list[float]] = {}
        # user_id -> monotonic deadline until which the user is ignored
        self._muted: dict[int, float] = {}
        self._in_flight = 0
        self.dropped_user = 0
        self.dropped_global = 0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._user_id(event)
        if user_id is None:
            # Not a user-originated update (channel post, inline, etc.).
            return await handler(event, data)

        now = time.monotonic()

        if self._muted.get(user_id, 0.0) > now:
            self.dropped_user += 1
            return None

        if self._over_budget(user_id, now):
            self._muted[user_id] = now + self._mute_seconds
            self._hits.pop(user_id, None)
            self.dropped_user += 1
            if len(self._muted) > _MAX_TRACKED_USERS:
                self._prune(now)
            logger.warning("flood guard: user %s muted for %.0fs", user_id, self._mute_seconds)
            await self._warn(event, data)
            return None

        if self._in_flight >= self._max_in_flight:
            self.dropped_global += 1
            logger.warning(
                "flood guard: %d updates in flight, shedding one", self._in_flight
            )
            return None

        self._in_flight += 1
        try:
            return await handler(event, data)
        finally:
            self._in_flight -= 1

    # ------------------------------------------------------------------ helpers
    def _over_budget(self, user_id: int, now: float) -> bool:
        stamps = self._hits.get(user_id)
        if stamps is None:
            stamps = []
            self._hits[user_id] = stamps
            if len(self._hits) > _MAX_TRACKED_USERS:
                self._prune(now)
        cutoff = now - self._window
        fresh = [ts for ts in stamps if ts > cutoff]
        fresh.append(now)
        self._hits[user_id] = fresh
        return len(fresh) > self._per_window

    def _prune(self, now: float) -> None:
        """Forget expired windows, then enforce the hard cap.

        Expiry alone is not enough: a burst of distinct ids inside one window
        leaves every entry still live, so the oldest are dropped to keep the
        guard's own memory bounded.
        """
        for uid in [u for u, deadline in self._muted.items() if deadline <= now]:
            self._muted.pop(uid, None)
        for uid, stamps in list(self._hits.items()):
            if not stamps or stamps[-1] <= now - self._window:
                self._hits.pop(uid, None)
        overflow = len(self._hits) - _MAX_TRACKED_USERS
        if overflow > 0:
            oldest = sorted(self._hits.items(), key=lambda item: item[1][-1])[:overflow]
            for uid, _ in oldest:
                self._hits.pop(uid, None)

        muted_overflow = len(self._muted) - _MAX_TRACKED_USERS
        if muted_overflow > 0:
            soonest = sorted(self._muted.items(), key=lambda item: item[1])[:muted_overflow]
            for uid, _ in soonest:
                self._muted.pop(uid, None)

    @staticmethod
    def _inner(event: TelegramObject) -> TelegramObject:
        """The message/callback inside an update.

        This guard is an *update*-level middleware (so it runs before the
        database session), and update-level middlewares receive the ``Update``
        wrapper, not the message or callback itself. Unwrap it; fall back to the
        event when there is nothing to unwrap.
        """
        if isinstance(event, (Message, CallbackQuery)):
            return event
        try:
            return event.event  # type: ignore[attr-defined]
        except Exception:
            return event

    @classmethod
    def _user_id(cls, event: TelegramObject) -> int | None:
        inner = cls._inner(event)
        if isinstance(inner, (Message, CallbackQuery)):
            user = inner.from_user
            if user is not None:
                return user.id
        return None

    @classmethod
    async def _warn(cls, event: TelegramObject, data: dict[str, Any]) -> None:
        """Tell the user once, and never let the notice itself raise."""
        lang = data.get("lang") or DEFAULT_LANGUAGE
        inner = cls._inner(event)
        try:
            if isinstance(inner, CallbackQuery):
                await inner.answer(t(lang, "guard.too_fast"), show_alert=True)
            elif isinstance(inner, Message):
                await inner.answer(t(lang, "guard.too_fast"))
        except Exception:
            pass
