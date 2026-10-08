"""Parallel search runner - one independent task per search.

Why there is no queue anymore
-----------------------------
Searches used to be serialised through worker tasks pulling from a priority
queue. That meant a single wedged search - a dead session, an unexpected
Telegram reply, any bug - stalled every user behind it, because everyone
shared one worker. The queue is gone: every search now runs as its own
independent asyncio task, so a broken search can only break itself.

The physical constraint never disappeared - Telegram still throttles the
authoritative username check. It is handled where it belongs: the shared
request-rate limiter inside ``UsernameChecker`` paces every call no matter
how many searches run at once. Concurrency only means the safe rate is
shared, never that it is exceeded.

Back-pressure still exists (``max_pending`` concurrent searches), and pressing
Run twice for the same thing never duplicates the work.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

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
from app.search.finder import (
    SCREEN_CAP,
    UNLIMITED_SCREEN_CAP,
    SearchCriteria,
    UsernameFinder,
)
from app.services.i18n import t
from app.services.runtime_config import runtime
from app.telegram.username_checker import UsernameChecker
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# Refuse to grow without bound if something goes wrong upstream.
MAX_PENDING = 500

# --- the live progress screen -------------------------------------------------
# Telegram has no in-message widgets, so "animation" is a series of edits of
# the placeholder message. The interval is deliberately above one edit per
# couple of seconds: Telegram throttles edits, and the search's own MTProto
# pacing means nothing meaningful changes faster anyway.
ANIMATE_INTERVAL = 2.0
BAR_CELLS = 16
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# The bar has three glyphs: filled progress, empty track, and a scan-head that
# keeps travelling through the empty part. The head is the trick that makes the
# screen feel alive while the *real* numbers barely move (MTProto pacing is
# slow): even when progress stalls, the user sees motion and knows it is working.
_BAR_FILLED = "▰"
_BAR_EMPTY = "▱"
_BAR_HEAD = "◆"

# Maps the finder's ``last_result`` tag to the i18n key that renders it.
_RESULT_KEYS: dict[str, str] = {
    "free": "search.progress_result_free",
    "occupied": "search.progress_result_taken",
    "reserved": "search.progress_result_reserved",
    "unknown": "search.progress_result_unknown",
    "checked": "search.progress_result_checked",
}


@dataclass
class SearchJob:
    """One running search. There is no ordering to express any more."""

    user_id: int
    chat_id: int
    message_id: int | None
    criteria: SearchCriteria
    lang: str
    used: int
    # "search" for a normal press of Run, "digest" for a Daily Drop so the
    # delivered message can carry the Daily Drop banner.
    kind: str = "search"

    @property
    def dedup_key(self) -> str:
        return f"{self.user_id}:{self.criteria.describe()}"


class SearchQueue:
    """Runs every submitted search as its own independent task.

    The name is historical. There is no queue: ``submit`` either starts the
    search immediately (returning ``1``), reports an identical running search
    (``0``), or refuses when the bot is at capacity (``-1``).

    Until :meth:`start` is called - in production, at boot before any request -
    submitted jobs are held and spawned together with everything that follows,
    so no search can be silently lost.
    """

    def __init__(
        self,
        bot: Bot,
        checker: UsernameChecker,
        collectible_checker: CollectibleChecker | None = None,
        max_pending: int = MAX_PENDING,
        stock=None,
    ) -> None:
        self._bot = bot
        self._checker = checker
        self._collectible = collectible_checker
        self._max_pending = max(1, int(max_pending))
        # The ready supply of verified-free names. Optional: without it every
        # search hunts, which is what the tests and one-off runs want.
        self._stock = stock
        self._pending: dict[str, SearchJob] = {}
        self._tasks: set[asyncio.Task] = set()
        self._started = False
        self.done = 0
        self.failed = 0

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        """Arm the runner and spawn anything submitted before it."""
        self._started = True
        for key, job in list(self._pending.items()):
            self._spawn(job, key)

    @property
    def running(self) -> bool:
        return self._started

    async def stop(self) -> None:
        """Cancel every live search. Used on shutdown and between tests."""
        self._started = False
        tasks, self._tasks = list(self._tasks), set()
        self._pending.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("search runner stopped")

    def drain(self) -> None:
        """Drop everything still alive and reset the counters.

        Used between tests, so a search spawned in one context can never be
        delivered in another.
        """
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._pending.clear()
        self.done = 0
        self.failed = 0

    # ------------------------------------------------------------------ submit
    @property
    def pending(self) -> int:
        return len(self._pending)

    @property
    def busy(self) -> bool:
        """True while any search is in flight.

        Background work (the name harvester) reads this and stands down: a user
        who is waiting for a name must always get the quota first.
        """
        return bool(self._tasks)

    async def submit(
        self,
        *,
        user_id: int,
        chat_id: int,
        message_id: int | None,
        criteria: SearchCriteria,
        lang: str,
        used: int,
        kind: str = "search",
    ) -> int:
        """Start a search. ``1`` = started, ``0`` = identical one already
        running for this user, ``-1`` = the bot is at capacity."""
        key = f"{user_id}:{criteria.describe()}"
        if key in self._pending:
            return 0
        if len(self._pending) >= self._max_pending:
            logger.warning("search runner at capacity (%d), refusing a job", self._max_pending)
            return -1

        job = SearchJob(user_id, chat_id, message_id, criteria, lang, used, kind)
        self._pending[key] = job
        if self._started:
            self._spawn(job, key)
        return 1

    def _spawn(self, job: SearchJob, key: str) -> None:
        task = asyncio.create_task(self._run(job, key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job: SearchJob, key: str) -> None:
        try:
            await self._process(job)
            self.done += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # one broken search must never touch another
            self.failed += 1
            logger.exception("search failed: %s", exc)
            await self._deliver_error(job)
        finally:
            self._pending.pop(key, None)

    async def _process(self, job: SearchJob) -> None:
        finder = UsernameFinder(self._checker, self._collectible, stock=self._stock)
        # Live counters for the progress screen; the finder's callback keeps
        # them truthful (real confirmations, real screening counts).
        # The animator reads this dict. ``activity`` / ``last_name`` / ``last_result``
        # are the live signal that keeps the screen moving between confirmations;
        # they default to harmless placeholders so callers that only pass the four
        # legacy arguments still get a working (if less rich) frame.
        snapshot = {
            "phase": "valuable",
            "confirmations": 0,
            "budget": 0,
            "screened": 0,
            "activity": "screening",
            "last_name": None,
            "last_result": None,
        }

        def progress(
            phase: str, confirmations: int, budget: int, screened: int, **extras
        ) -> None:
            snapshot.update(
                phase=phase,
                confirmations=confirmations,
                budget=budget,
                screened=screened,
                **extras,
            )

        stop = asyncio.Event()
        animator = asyncio.create_task(self._animate(job, snapshot, stop))
        try:
            attempt = await finder.find_one(job.criteria, progress)
        finally:
            stop.set()
            with contextlib.suppress(asyncio.CancelledError):
                await animator

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

    # ------------------------------------------------------------------ progress
    async def _animate(self, job: SearchJob, snapshot: dict, stop: asyncio.Event) -> None:
        """Keep the placeholder visibly alive while the search runs.

        The wait cannot be removed - MTProto pacing is physical - but a screen
        that breathes is the difference between waiting and abandoning. The bar
        is driven by the finder's real counters, never invented: what moves is
        what actually happened.
        """
        if job.message_id is None:
            return
        started = time.monotonic()
        step = 0
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=ANIMATE_INTERVAL)
                return
            except asyncio.TimeoutError:
                pass
            step += 1
            frame = self._progress_frame(job.lang, snapshot, started, step)
            try:
                await self._bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.message_id,
                    text=frame,
                )
            except Exception:
                # The placeholder is gone (deleted, or the chat went cold) -
                # stop feeding it. The result delivery has its own fallback.
                return

    @staticmethod
    def _progress_frame(lang: str, snapshot: dict, started: float, step: int) -> str:
        confirmations = snapshot["confirmations"]
        budget = snapshot["budget"] or 1
        screened = snapshot["screened"]
        # The scan limit matches what the finder actually uses, so the bar
        # stays honest in unlimited mode too.
        cap = UNLIMITED_SCREEN_CAP if runtime.unlimited_search else SCREEN_CAP
        # Two truthful sources of motion: confirmations (the scarce resource)
        # and free screening (what carries the search now that the public path
        # answers most checks). Either one moves the bar; together they keep it
        # honest.
        share = max(confirmations / budget, screened / cap)
        share = min(share, 0.99)
        pct = max(1, round(share * 100))
        filled = max(1, min(BAR_CELLS - 1, round(BAR_CELLS * share)))

        # Fill the real progress, then run a scan-head through the empty track so
        # the screen keeps breathing even between checks.
        remaining = BAR_CELLS - filled
        cells = [_BAR_FILLED] * filled + [_BAR_EMPTY] * remaining
        if remaining > 0:
            cells[filled + (step % remaining)] = _BAR_HEAD
        bar = "".join(cells)
        spinner = SPINNER_FRAMES[step % len(SPINNER_FRAMES)]

        # ``activity`` is the live label the finder sets ("screening",
        # "public_confirm", "finished", ...). ``phase`` is the legacy coarse
        # bucket; it still picks the right message when ``activity`` is absent
        # so older callers keep a working screen.
        activity = snapshot.get("activity")
        activity_key = {
            "screening": "search.progress_activity_screening",
            "confirming": "search.progress_activity_confirming",
            "public_confirm": "search.progress_activity_public_confirm",
            "finished": "search.progress_activity_finished",
            "public": "search.progress_activity_public_confirm",
        }.get(activity)
        if activity_key is None:
            activity_key = {
                "guarantee": "search.progress_phase_guarantee",
                "waiting": "search.progress_phase_waiting",
                "stock": "search.progress_phase_stock",
            }.get(snapshot.get("phase"), "search.progress_phase_valuable")

        elapsed = max(int(time.monotonic() - started), 1)
        rate = screened / elapsed if elapsed > 0 else 0.0
        rate_text = f"{rate:.1f}"

        lines = [
            t(lang, "search.progress_title"),
            "",
            f"{spinner} {t(lang, activity_key)}",
            f"<code>{bar}</code>  <b>{pct}%</b>",
            t(lang, "search.progress_stats", n=screened, rate=rate_text, s=elapsed),
        ]

        # ETA only when it is meaningful (we are still screening and have a rate).
        if activity != "finished" and screened > 0 and rate > 0:
            eta_secs = int(max(0.0, (cap - screened) / rate))
            if 0 < eta_secs < 9999:
                lines.append(t(lang, "search.progress_eta", s=eta_secs))

        # The "last candidate" line is what makes the screen feel alive between
        # confirmations: every batch ends with the name and verdict of the most
        # recent check, so something is always moving even during a slow step.
        last_name = snapshot.get("last_name")
        last_result = snapshot.get("last_result")
        if last_name and last_result:
            result_key = _RESULT_KEYS.get(last_result)
            if result_key:
                lines.append(
                    t(
                        lang,
                        "search.progress_last",
                        name=last_name,
                        result=t(lang, result_key),
                    )
                )

        return "\n".join(lines)

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
                logger.debug("could not edit the search message: %s", exc)
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
