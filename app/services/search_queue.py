"""A queue for user-initiated searches.

Why this exists
---------------
Telegram rate-limits the authoritative username check at roughly 20-30 calls per
account per minute, and the bot paces every call at ``REQUEST_DELAY`` to stay
under it. Running a search inline therefore makes the *user* wait on that
pacing - up to ~30 seconds - and the wait grows with the number of people using
the bot at once.

A queue separates the two: the user asks for a search and is answered
immediately ("queued, N ahead"), while a worker performs the work at the safe
rate and delivers the result when it is ready.

The physical limit does not disappear - it never can. What disappears is the
*user-facing* limit: anyone may queue as many searches as they like, and higher
privileges are simply served first. That is what a paid tier actually buys, and
it is how large public bots can offer "unlimited" search without dying.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from aiogram import Bot

from app.bot import texts
from app.bot.keyboards.features_kb import (
    claim_kit_keyboard,
    search_setup_keyboard,
    variants_keyboard,
)
from app.collectible.checker import CollectibleChecker
from app.database import repository as repo
from app.database.database import session_scope
from app.search.finder import SearchCriteria, TARGET_VARIANTS, UsernameFinder
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import Privilege
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# Lower number = served sooner. Everyone shares one queue, so the priority is
# the whole point of a paid tier.
PRIORITY_BY_PRIVILEGE = {
    Privilege.ADMIN.value: 0,
    Privilege.PREMIUM.value: 10,
    Privilege.VIP.value: 20,
    Privilege.FREE.value: 30,
}
DEFAULT_PRIORITY = 30

# Refuse to grow without bound if something goes wrong upstream.
MAX_PENDING = 500


def priority_for(privilege: str | None) -> int:
    """Queue priority for a privilege level - lower is served first."""
    return PRIORITY_BY_PRIVILEGE.get(privilege or "", DEFAULT_PRIORITY)


@dataclass(order=True)
class SearchJob:
    """One queued search. Ordered by ``(priority, seq)`` so ties stay FIFO."""

    priority: int
    seq: int
    user_id: int = field(compare=False)
    chat_id: int = field(compare=False)
    message_id: int | None = field(compare=False)
    criteria: SearchCriteria = field(compare=False)
    lang: str = field(compare=False)
    used: int = field(compare=False)
    # "search" for a normal press of Run, "digest" for a Daily Drop so the
    # delivered message can carry the Daily Drop banner.
    kind: str = field(compare=False, default="search")

    @property
    def dedup_key(self) -> str:
        return f"{self.user_id}:{self.criteria.describe()}"


class SearchQueue:
    """Serialises searches through worker task(s) so the user never waits."""

    def __init__(
        self,
        bot: Bot,
        checker: UsernameChecker,
        collectible_checker: CollectibleChecker | None = None,
        workers: int = 1,
        max_pending: int = MAX_PENDING,
    ) -> None:
        self._bot = bot
        self._checker = checker
        self._collectible = collectible_checker
        self._workers = max(1, int(workers))
        self._max_pending = max(1, int(max_pending))
        self._queue: asyncio.PriorityQueue[SearchJob] = asyncio.PriorityQueue()
        self._tasks: list[asyncio.Task] = []
        self._seq = 0
        self._pending: dict[str, SearchJob] = {}
        self.done = 0
        self.failed = 0

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        if self.running:
            return
        self._tasks = [
            asyncio.create_task(self._worker(), name=f"search-worker-{index}")
            for index in range(self._workers)
        ]
        logger.info("search queue started with %d worker(s)", self._workers)

    @property
    def running(self) -> bool:
        return any(not task.done() for task in self._tasks)

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("search queue stopped")

    def drain(self) -> None:
        """Drop anything still waiting and reset the counters.

        Used on shutdown and between tests, so a job queued in one context can
        never be delivered in another.
        """
        self._pending.clear()
        while not self._queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self.done = 0
        self.failed = 0
        self._seq = 0

    # ------------------------------------------------------------------ submit
    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def submit(
        self,
        *,
        user_id: int,
        chat_id: int,
        message_id: int | None,
        criteria: SearchCriteria,
        lang: str,
        used: int,
        priority: int = DEFAULT_PRIORITY,
        kind: str = "search",
    ) -> int:
        """Queue a search. Returns how many jobs are ahead of it.

        ``-1`` means the queue is full, ``0`` means an identical request from the
        same user is already waiting (so pressing Run twice does not queue the
        work twice).
        """
        key = f"{user_id}:{criteria.describe()}"
        if key in self._pending:
            return 0
        if self._queue.qsize() >= self._max_pending:
            logger.warning("search queue is full (%d), rejecting a job", self._max_pending)
            return -1

        self._seq += 1
        job = SearchJob(
            priority, self._seq, user_id, chat_id, message_id, criteria, lang, used, kind
        )
        self._pending[key] = job
        await self._queue.put(job)
        return self._queue.qsize()

    # ------------------------------------------------------------------ worker
    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._process(job)
                self.done += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one bad job must not kill the worker
                self.failed += 1
                logger.exception("search job failed: %s", exc)
                await self._deliver_error(job)
            finally:
                self._pending.pop(job.dedup_key, None)
                self._queue.task_done()

    async def _process(self, job: SearchJob) -> None:
        finder = UsernameFinder(self._checker, self._collectible)
        attempt = await finder.find_one(job.criteria)

        async with session_scope() as session:
            user = await repo.get_user_by_telegram_id(session, job.user_id)
            if user is not None:
                await repo.add_search(
                    session, user, attempt.username or "search", f"find_{job.criteria.target}"
                )
                await repo.increment_search_count(session, user)
            await session.commit()

        keyboard = self._result_keyboard(job, attempt)
        body = texts.find_result(job.lang, attempt, job.used)
        if job.kind == "digest":
            body = f"{texts.digest_header(job.lang)}\n\n{body}"
        await self._deliver(job, body, keyboard)

    @staticmethod
    def _result_keyboard(job: SearchJob, attempt):
        """Pick the action row that matches what the result actually is.

        A variants shortlist gets re-roll / leave controls; a confirmed-free
        name gets the claim kit (open, save, variants, new search); everything
        else falls back to the search wizard so the user can adjust and retry.
        """
        if attempt.reason == "variants":
            return variants_keyboard(job.lang, attempt.seed or "")
        if attempt.hit:
            return claim_kit_keyboard(
                job.lang, attempt.username, attempt.premium.total
            )
        return search_setup_keyboard(
            job.lang,
            length=job.criteria.length,
            digits=job.criteria.allow_digits,
            mask=job.criteria.mask,
        )

    # ------------------------------------------------------------------ delivery
    async def _deliver(self, job: SearchJob, text: str, keyboard) -> None:
        if job.message_id is not None:
            try:
                await self._bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.message_id,
                    text=text,
                    reply_markup=keyboard,
                )
                return
            except Exception as exc:
                logger.debug("could not edit the queued message: %s", exc)
        await self._bot.send_message(job.chat_id, text, reply_markup=keyboard)

    async def _deliver_error(self, job: SearchJob) -> None:
        text = texts.error_screen(job.lang)
        if job.message_id is not None:
            try:
                await self._bot.edit_message_text(
                    chat_id=job.chat_id, message_id=job.message_id, text=text
                )
                return
            except Exception:
                pass
        with contextlib.suppress(Exception):
            await self._bot.send_message(job.chat_id, text)
