"""The finder.

One target only: a **beautiful, unoccupied, premium username worth reselling**.

Every name shown to the user passes a **double check**, in this order:

1. **Telegram** - the public page screens candidates for free, then MTProto -
   the only channel allowed to declare a name AVAILABLE - confirms the
   survivors. A result is never an occupied handle: showing a taken name with
   its owner is information the user can get anywhere and asked not to see.
2. **Fragment** - a confirmed-free name is then checked against the Fragment
   marketplace. A name listed for auction or sale there is *not* claimable, no
   matter what Telegram says about it, so it is rejected and the search
   continues. The result screen states the Fragment verdict explicitly.

There is no user-facing quality filter. The bot applies its own taste: a
candidate must clear the five premium criteria (see :func:`premium_rating`) and
a gentle rubric floor, and the stream is ordered by value (real words first,
then brands, then clean coinages - see :mod:`app.search.generator`). "Beautiful
and potentially valuable, not random" is a requirement, not a preference.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from app.collectible.checker import CollectibleChecker
from app.collectible.valuation import estimate_price, price_basis
from app.config import settings
from app.search.generator import (
    UsernameGenerator,
    beautiful_candidates,
    broad_candidates,
    coinage_candidates,
    letter_part,
)
from app.search.pattern import (
    Premium,
    compile_mask,
    generate_from_mask,
    mask_is_usable,
    premium_rating,
    rate,
)
from app.telegram.username_checker import UsernameChecker
from app.telegram.mtproto import mtproto_client
from app.telegram.public_verdict import PublicVerdict, public_verdict_client
from app.services.runtime_config import runtime
from app.utils.enums import CheckStatus, CollectibleStatus
from app.utils.logging_setup import get_logger
from app.utils.ratelimit import spend_flood_window
from app.utils.results import CheckResult
from app.utils.value import estimate_value

logger = get_logger(__name__)

TARGET_FREE = "free"
TARGET_VARIANTS = "variants"

# The bot's own taste, not a user filter. Two gates decide whether a candidate
# is even worth a lookup:
#
# * ``QUALITY_FLOOR`` - a gentle 0-100 rubric floor that removes digit runs,
#   underscore soup and unpronounceable noise;
# * ``PREMIUM_FLOOR`` - at least this many of the five premium criteria must
#   hold. This is the criterion the user actually sees (N/5), so it is the one
#   the candidate stream is built around: a name that clears fewer than three of
#   the five is not "premium" and is never offered, however available it is.
QUALITY_FLOOR = 45
PREMIUM_FLOOR = 3

MAX_GENERATION_TRIES = 400
# Variants never screen more than this many candidates - the seed already points
# at a small, high-intent family, so a wider net would just dilute it.
VARIANT_SCREEN_CAP = 120
VARIANT_SCREEN_BATCH = 6
# How many MTProto confirmations one variants run may spend. It shares the same
# scarce budget as a free search, so it is capped the same way.
VARIANT_CONFIRM_BUDGET = 6
# How many free alternatives a single run will surface before stopping.
VARIANTS_CAP = 8
# How many candidates one search may examine. Screening runs on the public page,
# which costs nothing - no account, no quota, nothing to ban - so the net can be
# broad. t.me answers a plain GET in ~340ms.
SCREEN_CAP = 160
# The guarantee pass gets its own, larger screening allowance. Screening is free
# and it is exactly what finds a *free* name without spending the scarce MTProto
# budget, so starving it (which the old shared counter did - the valuable pass
# could consume the whole SCREEN_CAP and leave the guarantee pass with nothing to
# do) is the bug that ended short searches in "everything is taken".
GUARANTEE_SCREEN_CAP = 400
# How many public pages to fetch at once. t.me is a plain public endpoint with
# no account behind it; 10 concurrent fetches stay polite while keeping the
# page screen from becoming the slowest stage of a short-name hunt.
SCREEN_BATCH = 10
# How many *authoritative* MTProto confirmations one search may spend in total.
# This is the scarce resource - Telegram escalates at roughly 20-30 resolves per
# account per minute (production evidence via telethon-floodgate), and every
# call is paced by REQUEST_DELAY, so the budget costs time, not ban risk. The
# search stops early on a hit; the budget is only fully spent when candidates
# keep coming back occupied.
FREE_CONFIRM_BUDGET = 16
# How much of that total the desirable real-word stream may claim before the
# guarantee pass takes over. Real words are what a user actually wants, so they
# get first refusal - but they are also almost all taken, so they must not be
# allowed to burn the whole budget and end the search with "everything taken".
# The remainder is reserved for the coinage guarantee.
VALUABLE_CONFIRM_BUDGET = 5
# Short names are a different world: 5-6 letter handles are the most squatted
# space on Telegram, so per-confirmation success collapses and a base budget
# would end in "all taken" far too often. Short searches get more attempts -
# pacing keeps the request rate identical, only the worst-case wait grows, and
# the progress screen exists precisely to make that wait bearable.
SHORT_NAME_LENGTH = 6
SHORT_NAME_CONFIRM_BUDGET = 30
# Unlimited mode ("free bot"): keep hunting until a name is found. The ceiling
# still exists, because "unlimited" must not mean "ten minutes of frozen screen":
# 120 confirmations is already far past the point where the guarantee stream
# hands back a free name, and without a cap one search could sit on the scarce
# Telegram quota and starve every other user.
UNLIMITED_CONFIRM_BUDGET = 120
UNLIMITED_SHORT_CONFIRM_BUDGET = 150
# Screening is free (a plain t.me GET), but it is still work: the unlimited
# allowances are wide enough to feed the confirmation budget, not open-ended.
UNLIMITED_SCREEN_CAP = 800
UNLIMITED_GUARANTEE_SCREEN_CAP = 1500
# If a FloodWait is longer than this, do not sit on it: a search the user is
# waiting on must answer now and say "Telegram is throttling us", not hang.
# A multi-minute wait is not a search, it is a stuck screen.
MAX_SEARCHABLE_FLOOD_WAIT = 90.0
# How long one search may spend *waiting out* Telegram throttling before it
# gives up. A throttle is waited out rather than reported - the user asked for a
# name, not for an explanation - but a search cannot sit there indefinitely.
# Tunable from the environment (MAX_SEARCH_SECONDS).
MAX_SEARCH_SECONDS = settings.max_search_seconds
# The true ceiling on a search, waiting included. ``MAX_SEARCH_SECONDS`` bounds
# only the *working* time (screening + confirmations) and is extended by each
# flood wait, because waiting out a throttle is not work the search did. This
# second limit is what eventually answers a user whose pool is flooded for
# hours: generous enough to let a real flood recovery land inside one search,
# hard enough that the screen never becomes a permanent "SEARCHING...".
ABSOLUTE_SEARCH_SECONDS = settings.absolute_search_seconds
# Pause used when Telegram reports a flood but no session recovery time is
# known (nothing is parked, so the limit came from somewhere else).
FLOOD_RETRY_PAUSE = 5.0


@dataclass
class SearchCriteria:
    length: int | None = None
    allow_digits: bool = False
    mask: str | None = None
    target: str = TARGET_FREE
    seed: str | None = None

    def describe(self) -> dict[str, object]:
        """Serialisable form for the FSM.

        Built with ``asdict`` so the keys can never drift from the dataclass
        fields - a hand-written dict here silently broke every interaction with
        the search screen after the first one.
        """
        return asdict(self)


@dataclass
class _SweepState:
    """Mutable counters shared by every pass of one search.

    ``confirmations`` in particular is shared, so the valuable pass and the
    guarantee pass draw on a single MTProto allowance rather than each spending
    their own.
    """

    screened: int = 0
    confirmations: int = 0
    occupied_seen: int = 0
    unknown_seen: int = 0
    best: str | None = None
    best_premium: Premium | None = None
    # The confirmation ceiling this run shares, and the wall-clock deadline it
    # may not pass while waiting out Telegram throttling. Both live here so the
    # sweeps and the flood wait agree on one budget instead of three.
    budget: int = 0
    deadline: float = 0.0
    # An absolute wall clock that waiting *cannot* push back. ``deadline`` is
    # the working budget and is extended by every flood wait (waiting is not
    # work), so without a second, hard ceiling a pool that floods forever would
    # keep a search on screen indefinitely. This one is the true "the user must
    # be answered now" limit.
    absolute_deadline: float = 0.0
    # A name that resolves as unoccupied but whose claimability could not be
    # verified (no user session, or its checkUsername was rate-limited). It is
    # never delivered as a result - if the hunt ends with only these, the run
    # reports an honest "cannot verify" instead of a false "free".
    unverified_hit: "FindAttempt | None" = None


@dataclass
class FindAttempt:
    username: str
    premium: Premium
    hit: bool
    reason: str
    basic: CheckResult | None = None
    value: dict | None = None
    generated_tries: int = 0
    seed: str | None = None
    variants: list | None = None
    # The Fragment half of the double check, recorded for the result screen:
    # ``checked`` is False when Fragment could not be reached, in which case
    # the screen says so instead of claiming a verification that never ran.
    fragment_clear: bool = False
    fragment_checked: bool = False
    # Set only when the name was classified by the no-session public path
    # (``app/telegram/public_verdict.py``) after Telegram's own channels were
    # unreachable. ``confidence="public"`` tells the result screen to say how
    # the verdict was reached - it is a real answer about a real name, but it is
    # not Telegram's own word, and the screen never pretends otherwise.
    public_confidence: str | None = None
    public_reason: str | None = None


class UsernameFinder:
    def __init__(
        self,
        checker: UsernameChecker,
        collectible: CollectibleChecker | None,
        rng: random.Random | None = None,
        stock: Any | None = None,
    ) -> None:
        self._checker = checker
        self._collectible = collectible
        self._rng = rng or random.Random()
        # The ready supply of names already proven free (see app/services/
        # name_stock.py). Optional: without it the search simply hunts, which is
        # exactly what the tests and one-off runs want.
        self._stock = stock

    async def _price(self, name: str) -> dict:
        """The market estimate **and the listings it rests on**.

        A bare number invites the reader to treat it as a valuation of *this*
        name. Returning the spread and the comparable count alongside it lets the
        result screen show its work - and ``None`` is a real answer, meaning the
        market holds nothing comparable, so no honest price exists. There is no
        substituted fallback figure: an invented price is worse than no price.
        """
        empty = {"price": None, "price_low": None, "price_high": None, "price_comps": 0}
        if self._collectible is None:
            return empty
        try:
            listings = await self._collectible.fragment.market_listings()
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("price estimate failed for %s: %s", name, exc)
            return empty

        basis = price_basis(name, listings)
        if basis is None:
            return empty
        return {
            "price": estimate_price(name, listings),
            "price_low": round(basis.low),
            "price_high": round(basis.high),
            "price_comps": basis.count,
        }

    def _candidates(self, criteria: SearchCriteria):
        """An ordered iterator of candidate names that satisfy local filters.

        A mask, when given, is honoured literally - the user asked for that
        shape. Without one, candidates come from the beautiful-name generator
        (real words, then brands, then clean coinages), never from raw noise.
        The quality gate is the bot's own fixed floor; there is no user
        rating filter any more.
        """
        mask = criteria.mask if criteria.mask and mask_is_usable(criteria.mask) else None

        if mask is not None and any(ch in mask for ch in ("?", "*", "#")):
            compiled = compile_mask(mask)
            for _ in range(MAX_GENERATION_TRIES):
                name = generate_from_mask(mask, self._rng)
                if name is None:
                    continue
                if compiled is not None and not compiled.match(name):
                    continue
                if not criteria.allow_digits and any(ch.isdigit() for ch in name):
                    continue
                if rate(name).total < QUALITY_FLOOR:
                    continue
                if premium_rating(name).total < PREMIUM_FLOOR:
                    continue
                yield name
            return

        # No mask: an exact name (the user typed a word) or a pure quality hunt.
        seed = mask if mask else None
        for name in beautiful_candidates(
            seed=seed,
            length=criteria.length,
            allow_digits=criteria.allow_digits,
            min_score=QUALITY_FLOOR,
            rng=self._rng,
            limit=MAX_GENERATION_TRIES,
        ):
            # Taste judges the letters; digits are the user's own filter.
            if premium_rating(letter_part(name)).total >= PREMIUM_FLOOR:
                yield name

    async def find_one(
        self, criteria: SearchCriteria, progress=None, max_seconds: float | None = None
    ) -> FindAttempt:
        """Run a search. ``progress``, when given, is called as
        ``progress(phase, confirmations, budget, screened)`` after every
        authoritative check so a caller can animate the wait with real numbers
        instead of a fake spinner.

        ``max_seconds`` overrides how long the run may spend waiting out
        Telegram throttling. Background work (the name harvester) passes a short
        value so it can never hold the scarce quota while a user is waiting.
        """
        if criteria.target == TARGET_VARIANTS:
            return await self._find_variants(criteria)

        return await self._find_free(criteria, progress, max_seconds)

    async def _screen(self, names: list[str]) -> list[str]:
        """Drop the names the free public page proves occupied.

        Returns the survivors - the ones the page could *not* rule out. This
        costs no Telegram quota, which is the whole point: most candidates in a
        search are taken, so removing them here keeps the scarce MTProto budget
        for names that actually have a chance.
        """
        sem = asyncio.Semaphore(SCREEN_BATCH)

        async def probe(name: str) -> tuple[str, bool]:
            async with sem:
                try:
                    page = await self._checker.probe_public_page(name)
                except Exception as exc:  # a failed screen must not kill the search
                    logger.debug("page screen failed for %s: %s", name, exc)
                    return name, False
            return name, page.is_occupied

        results = await asyncio.gather(*(probe(n) for n in names))
        return [name for name, occupied in results if not occupied]

    async def _fragment_verdict(self, name: str) -> tuple[bool, bool]:
        """The Fragment half of the double check.

        Returns ``(clear, checked)``:

        * ``(False, True)``  - the name **is** listed on Fragment (auction or
          sale). It cannot be claimed free, whatever Telegram said.
        * ``(True, True)``   - Fragment provably does not list it.
        * ``(True, False)``  - Fragment could not be asked (disabled, rate
          limited, network). The name is not blocked - a dead marketplace must
          not turn the bot off - but the result screen says the check did not
          run instead of claiming it did.
        """
        if self._collectible is None:
            return True, False

        try:
            lookup = await self._collectible.fragment.lookup(name)
        except Exception as exc:  # a dead Fragment must not kill the search
            logger.debug("fragment double-check failed for %s: %s", name, exc)
            return True, False

        if lookup.is_collectible:
            return False, True
        if lookup.status is CollectibleStatus.NOT_DETECTED:
            return True, True
        return True, False

    def _confirm_budget(self, criteria: SearchCriteria) -> int:
        """Total confirmations this search may spend, by name length."""
        high = runtime.unlimited_search
        free = UNLIMITED_CONFIRM_BUDGET if high else FREE_CONFIRM_BUDGET
        short = UNLIMITED_SHORT_CONFIRM_BUDGET if high else SHORT_NAME_CONFIRM_BUDGET
        if criteria.length is not None and criteria.length <= SHORT_NAME_LENGTH:
            return max(free, short)
        return free

    async def _public_fallback(
        self, state: "_SweepState", progress=None
    ) -> FindAttempt | None:
        """Answer from public pages when Telegram's own channels are down.

        This is the no-session path: ``t.me`` plus ``fragment.com``, both plain
        public URLs with no account behind them, so they cannot be FloodWaited
        the way a session can. Nothing here invents a name - it re-checks the
        *best* candidate the search already screened and reports what the public
        pages say about it.

        Returns ``None`` when the public pages cannot settle the question either,
        in which case the caller keeps its original, honest verdict.
        """
        if state.best is None:
            return None

        name = state.best
        try:
            verdict: PublicVerdict = await public_verdict_client.judge(name)
        except Exception as exc:  # a dead public source must not kill the search
            logger.debug("public fallback failed for %s: %s", name, exc)
            return None

        if verdict.status not in ("free", "occupied"):
            # "reserved" or "unknown" - the public pages did not settle it, and
            # this path only ever answers with something it can stand behind.
            return None

        if progress is not None:
            with contextlib.suppress(Exception):
                progress("public", state.confirmations, state.budget or 1, state.screened)

        logger.info(
            "public fallback: @%s -> %s (%s)", name, verdict.status, verdict.reason
        )
        if verdict.status == "free":
            # A real name, verified as trace-free on both public pages. Not
            # claimable-proven (only a user session can do that), so it carries
            # the same caveat as any unverified hit - but it IS a real answer
            # about a real name instead of a bare "Telegram is limiting us".
            basic = CheckResult(
                username=name,
                status=CheckStatus.AVAILABLE,
                source="public_verdict",
                detail="claimability_unverified",
            )
            attempt = await self._hit_attempt(
                name, basic, state, fragment_clear=True, fragment_checked=True
            )
            attempt.public_confidence = verdict.confidence
            attempt.public_reason = verdict.reason
            return attempt
        return FindAttempt(
            username=name,
            premium=state.best_premium or premium_rating(""),
            hit=False,
            reason="all_taken",
            generated_tries=state.screened,
            public_confidence=verdict.confidence,
            public_reason=verdict.reason,
        )

    def _guarantee_candidates(self, criteria: SearchCriteria) -> Iterator[str]:
        """The guarantee stream: names that are actually still free.

        Real words are what a user wants and almost all of them are taken. The
        guarantee leans on two invented sources instead, interleaved so neither
        can starve the other:

        * **coinages** - readable, brandable; preferred, but at five characters
          the pronounceable space is exhausted (measured: thirty coinages ->
          twenty occupied, ten unassignable, *zero* free);
        * **broad** - arbitrary full-alphabet handles, which is where a free
          short name actually lives (a random five-letter draw was claimable
          about one time in six).

        Both go through the identical length / digit / score / premium gates, so
        the guarantee never hands back a name the bot's own taste would reject.
        """
        def gated(stream: Iterator[str]) -> Iterator[str]:
            for name in stream:
                if premium_rating(letter_part(name)).total >= PREMIUM_FLOOR:
                    yield name

        streams = [
            gated(coinage_candidates(
                length=criteria.length,
                allow_digits=criteria.allow_digits,
                min_score=QUALITY_FLOOR,
                rng=self._rng,
                limit=MAX_GENERATION_TRIES * 4,
            )),
            gated(broad_candidates(
                length=criteria.length,
                allow_digits=criteria.allow_digits,
                min_score=QUALITY_FLOOR,
                rng=self._rng,
                limit=MAX_GENERATION_TRIES * 8,
            )),
        ]
        iters = [iter(stream) for stream in streams]
        done = [False] * len(iters)
        while not all(done):
            for index, iterator in enumerate(iters):
                if done[index]:
                    continue
                candidate = next(iterator, None)
                if candidate is None:
                    done[index] = True
                else:
                    yield candidate

    async def _sweep(
        self, candidates: Iterator[str], budget: int, state: _SweepState,
        progress=None, phase: str = "valuable", screen_cap: int = SCREEN_CAP,
    ) -> FindAttempt | None:
        """Screen and confirm candidates until one is free or the budget is spent.

        Returns a :class:`FindAttempt` only when the run must stop for a reason
        the user needs to hear about - a confirmed free name, or, as the very
        last resort, a throttle that outlasted the search's whole wait budget.
        ``None`` means "budget spent on this stream, carry on with the next one".

        ``budget`` is a ceiling on ``state.confirmations``, so several sweeps in
        one search share a single MTProto allowance instead of each taking their
        own. ``screen_cap`` is the *per-sweep* screening ceiling - it must be
        local, not the shared ``state.screened``, or the first pass can spend the
        whole allowance and leave the guarantee pass unable to look at anything.
        """
        screened_here = 0
        while screened_here < screen_cap and state.confirmations < budget:
            # The budget is a ceiling on *work*, but a search also has a wall
            # clock. With the pool parked every confirmation is paid on the user
            # session, so a hopeless request (a five-letter name with digits off,
            # say) could otherwise sit on the screen for many minutes. Stopping
            # on time ends it with an honest answer and the hint that helps.
            if state.deadline and asyncio.get_event_loop().time() > state.deadline:
                logger.info(
                    "search stopped: time budget spent after %d confirmation(s), "
                    "%d screened", state.confirmations, state.screened,
                )
                break

            batch: list[str] = []
            for name in candidates:
                batch.append(name)
                if len(batch) >= SCREEN_BATCH:
                    break
            if not batch:
                return None  # this stream is exhausted

            # Remember the best-looking candidate so a total miss can still be
            # explained ("everything this good is taken") rather than blank.
            for name in batch:
                premium = premium_rating(letter_part(name))
                if state.best_premium is None or premium.total > state.best_premium.total:
                    state.best, state.best_premium = name, premium

            survivors = await self._screen(batch)
            state.screened += len(batch)
            screened_here += len(batch)
            state.occupied_seen += len(batch) - len(survivors)

            # Live activity for the progress screen: every batch reports the last
            # name it touched, so the bar keeps moving even between the (now
            # rare) confirmations. This is what makes the search screen feel
            # alive instead of frozen.
            if progress is not None and batch:
                with contextlib.suppress(Exception):
                    progress(
                        phase, state.confirmations, budget, state.screened,
                        activity="screening",
                        last_name=batch[-1],
                        last_result="checked",
                    )

            index = 0
            while index < len(survivors):
                if state.confirmations >= budget:
                    break

                name = survivors[index]
                basic = await self._checker.confirm_availability(name)

                if basic.status is CheckStatus.RATE_LIMITED:
                    # Telegram is throttling every session in the pool. Waiting
                    # it out would freeze the screen for the full recovery time
                    # - the public pages need no account and answer in ~50ms,
                    # so confirm THIS name through them instead of parking the
                    # whole search on a flood recovery. The search never stops
                    # here; it just routes around the rate limit. The throttle
                    # message (``search.throttled``) is unreachable: the worst
                    # case is an honest ``unconfirmed`` / ``all_taken``.
                    try:
                        verdict: PublicVerdict = await public_verdict_client.judge(name)
                    except Exception as exc:
                        # A dead public source must not kill the search.
                        logger.debug("public confirm failed for %s: %s", name, exc)
                        verdict = PublicVerdict(
                            "unknown", "public_check_failed", confidence="none"
                        )
                    state.confirmations += 1
                    index += 1
                    if progress is not None:
                        with contextlib.suppress(Exception):
                            progress(
                                phase, state.confirmations, budget, state.screened,
                                activity="public_confirm",
                                last_name=name,
                                last_result=verdict.status,
                            )
                    if verdict.status == "free":
                        # Genuinely trace-free on both public pages. Fragment
                        # was already consulted inside ``judge``, so there is
                        # no need to call the collectible checker again.
                        basic = CheckResult(
                            username=name,
                            status=CheckStatus.AVAILABLE,
                            source="public_verdict",
                            detail="claimability_unverified",
                        )
                        attempt = await self._hit_attempt(
                            name, basic, state,
                            fragment_clear=True, fragment_checked=True,
                        )
                        attempt.public_confidence = verdict.confidence
                        attempt.public_reason = verdict.reason
                        return attempt
                    if verdict.status in ("occupied", "reserved"):
                        state.occupied_seen += 1
                    else:
                        state.unknown_seen += 1
                    continue

                state.confirmations += 1
                index += 1
                if progress is not None:
                    with contextlib.suppress(Exception):
                        progress(phase, state.confirmations, budget, state.screened)

                if basic.status is CheckStatus.AVAILABLE:
                    # Telegram is done - now Fragment gets its say.
                    fragment_clear, fragment_checked = await self._fragment_verdict(name)
                    if not fragment_clear:
                        # Listed for auction/sale on Fragment: not claimable.
                        state.occupied_seen += 1
                        continue
                    attempt = await self._hit_attempt(
                        name, basic, state, fragment_clear, fragment_checked
                    )
                    if getattr(basic, "detail", None) == "claimability_unverified":
                        # Not a provable win: "nobody owns it" is proven, but
                        # "Telegram will hand it over" is not. Keep hunting for
                        # a verifiable name while the gate is alive - but the
                        # moment the gate is down (no session, or every one
                        # FloodWait-parked), stop immediately: burning the
                        # whole budget behind a dead gate looks like an
                        # infinite search and changes nothing.
                        if state.unverified_hit is None:
                            state.unverified_hit = attempt
                        if not mtproto_client.user_gate_ready:
                            logger.warning(
                                "search aborted: claimability gate is down "
                                "(user session missing or flood-parked)"
                            )
                            return FindAttempt(
                                username="", premium=premium_rating(""), hit=False,
                                reason="claim_unavailable",
                                generated_tries=state.screened,
                            )
                        continue
                    return attempt

                if basic.status is CheckStatus.OCCUPIED:
                    state.occupied_seen += 1
                elif basic.status is CheckStatus.INVALID:
                    # Cannot be claimed either way - skip it silently.
                    continue
                else:
                    # UNKNOWN. Not a "taken" verdict - the channel simply could
                    # not confirm. Counted separately so the message stays honest.
                    state.unknown_seen += 1

        return None

    async def _serve_from_stock(
        self, criteria: SearchCriteria, state: "_SweepState", progress=None
    ) -> FindAttempt | None:
        """Hand over a stored free name, re-confirmed right now.

        The stored name was proven claimable when it was harvested, but a free
        name can be claimed by anybody at any moment, so it is **never** delivered
        on the strength of the old verdict: it goes through the same authoritative
        check as a freshly found candidate. Only if Telegram still answers
        "claimable" is it handed over - and then it is certain, because that is
        the exact call the Telegram app itself makes.

        Returns ``None`` when there is nothing suitable in stock or the stored
        name turned out to be taken, in which case the caller simply hunts.
        """
        if self._stock is None:
            return None

        name = await self._stock.take(criteria.length, criteria.allow_digits)
        if not name:
            return None

        if progress is not None:
            with contextlib.suppress(Exception):
                progress("stock", 1, state.budget or 1, state.screened)

        # The stored name only has to be shown to be *still* free, and the user
        # session answers that in one call. The full pipeline would spend a
        # resolve on the bot pool as well - and wait out its pace - for a
        # question that does not need it.
        claimable = await self._checker.reconfirm_claimable(name)

        if claimable is True:
            basic = CheckResult(
                username=name, status=CheckStatus.AVAILABLE, source="mtproto_user",
                detail="claimability_verified",
            )
        elif claimable is False:
            # Somebody claimed it since the harvest.
            await self._stock.discard(name)
            return None
        else:
            # The user session could not answer, so ask the full pipeline - which
            # knows how to wait, and which will not invent a verdict either.
            basic = await self._checker.confirm_availability(name)
            state.confirmations += 1
            if basic.status is CheckStatus.RATE_LIMITED:
                logger.info("stock: @%s could not be re-confirmed (throttled) - released", name)
                await self._stock.release(name)
                return None
            if (
                basic.status is not CheckStatus.AVAILABLE
                or getattr(basic, "detail", None) != "claimability_verified"
            ):
                await self._stock.discard(name)
                return None

        fragment_clear, fragment_checked = await self._fragment_verdict(name)
        if not fragment_clear:
            # Listed for sale on Fragment: not claimable, so not a result.
            await self._stock.discard(name)
            return None

        logger.info("stock: @%s re-confirmed free and delivered", name)
        attempt = await self._hit_attempt(
            name, basic, state, fragment_clear, fragment_checked
        )
        # Delivered, so it leaves the store: it is out in the world now and will
        # most likely be claimed, and a stale row would only be served and thrown
        # away later.
        await self._stock.consume(name)
        return attempt

    async def _hit_attempt(
        self, name: str, basic: CheckResult, state: "_SweepState",
        fragment_clear: bool, fragment_checked: bool,
    ) -> FindAttempt:
        """Build the full result for a confirmed-free name."""
        return FindAttempt(
            username=name,
            premium=premium_rating(letter_part(name)),
            hit=True,
            reason="free_found",
            basic=basic,
            generated_tries=state.screened,
            value={**estimate_value(name), **await self._price(name)},
            fragment_clear=fragment_clear,
            fragment_checked=fragment_checked,
        )

    async def _public_only_search(
        self, criteria: SearchCriteria, progress, state: "_SweepState"
    ) -> FindAttempt:
        """Answer without any Telegram session at all.

        This is the path that runs when every session is FloodWait-parked or no
        user session exists. It does exactly what the session path does for
        screening - the same candidate stream, the same public-page screen, the
        same taste gates - but the final verdict comes from
        :mod:`app.telegram.public_verdict` instead of MTProto.

        It is deliberately *narrow*: it only ever announces a name the public
        pages can prove is trace-free on **both** t.me and Fragment, and it says
        plainly that the verdict came from public sources rather than Telegram.
        A name it cannot settle is reported as "everything taken" with the best
        candidate named - never dressed up as free.

        The final verdict is the ``guarantee`` stream (clean coinages), not the
        real-word stream: real words need the authoritative channel to be judged
        at all - they are almost all taken, and t.me cannot tell that apart from
        a name it will not hand over - so on the public path they would burn the
        screen for nothing. The coinage stream is exactly the space where a free
        name lives, which is what makes this path both fast and useful.
        """
        screen_cap = UNLIMITED_SCREEN_CAP if runtime.unlimited_search else SCREEN_CAP
        best: str | None = None
        best_premium: Premium | None = None
        screened = 0
        # Mirror the count onto the shared state: a public-only run still examined
        # real names, and the result screen reports that number.
        state.screened = 0

        stream = self._guarantee_candidates(criteria)
        while screened < screen_cap:
            batch: list[str] = []
            for name in stream:
                batch.append(name)
                if len(batch) >= SCREEN_BATCH:
                    break
            if not batch:
                break

            # Judge the whole batch at once. Each name costs two public GETs and
            # no quota, so the only thing that limits the public path is latency -
            # and fetching serially turned a wide search into a multi-minute
            # wait. Running the batch concurrently makes the run behave like the
            # session path it replaces.
            verdicts = await asyncio.gather(
                *(public_verdict_client.judge(n) for n in batch),
                return_exceptions=True,
            )

            free_hits: list[tuple[str, PublicVerdict]] = []
            for name, verdict in zip(batch, verdicts):
                premium = premium_rating(letter_part(name))
                if best_premium is None or premium.total > best_premium.total:
                    best, best_premium = name, premium
                if isinstance(verdict, Exception):
                    # A failed public fetch is not a verdict - it simply did not
                    # settle this name. It is still one name examined.
                    continue
                if verdict.status == "free":
                    free_hits.append((name, verdict))
            screened += len(batch)
            state.screened = screened

            if free_hits:
                # Prefer the best-looking of the free names found in this batch,
                # so the answer is the nicest one available rather than whichever
                # happened to be first in the batch.
                name, verdict = max(
                    free_hits, key=lambda item: premium_rating(letter_part(item[0])).total
                )
                logger.info("public-only search found @%s (no public trace)", name)
                basic = CheckResult(
                    username=name, status=CheckStatus.AVAILABLE,
                    source="public_verdict", detail="claimability_unverified",
                )
                attempt = await self._hit_attempt(
                    name, basic, state, fragment_clear=True, fragment_checked=True
                )
                attempt.public_confidence = verdict.confidence
                attempt.public_reason = verdict.reason
                return attempt

            if progress is not None and batch:
                last_status = "checked"
                for _n, _v in zip(batch, verdicts):
                    if isinstance(_v, PublicVerdict):
                        last_status = _v.status
                with contextlib.suppress(Exception):
                    progress(
                        "public", screened, screen_cap, screened,
                        activity="public_confirm",
                        last_name=batch[-1],
                        last_result=last_status,
                    )

        if best is not None:
            # Everything the public pages could see was taken. Say exactly that,
            # and say it came from public sources - the same honest verdict the
            # session path gives, just reached without a session. ``username``
            # stays empty on a miss: this project never hands back a name it
            # cannot stand behind, not even as a "best effort".
            return FindAttempt(
                username="",
                premium=best_premium or premium_rating(""),
                hit=False,
                reason="all_taken",
                generated_tries=screened,
                public_confidence="public",
                public_reason="no_public_trace_anywhere",
            )
        return FindAttempt(
            username="", premium=premium_rating(""), hit=False,
            reason="no_candidate", generated_tries=screened,
        )

    async def _find_free(
        self, criteria: SearchCriteria, progress=None, max_seconds: float | None = None
    ) -> FindAttempt:
        """Walk candidates until one survives **both** checks.

        Three channels, deliberately split:

        * the **public page** screens candidates for free - a rendered profile
          card proves ownership without an account, a quota or any ban risk, and
          most candidates are in fact taken, so this removes them cheaply;
        * **MTProto** confirms the survivors, because it is the only channel that
          can truthfully declare a name AVAILABLE. Telegram rate-limits it hard,
          so it is budgeted and never spent on a name the page has killed;
        * **Fragment** gets the final word on the survivors: a name listed for
          auction or sale there is rejected and the hunt continues.

        The run is **two passes over one shared confirmation budget**:

        1. the *valuable* pass - real words, brands and hybrids, the names a user
           actually wants - claiming a **share** of the allowance (never all of
           it);
        2. the *guarantee* pass - clean coinages, which are effectively never
           registered - spending whatever is left.

        That ordering is what makes a search answer with a free name rather than
        "everything is taken": real words get first refusal because they are
        better, but they cannot consume the whole budget, and the coinage stream
        is an inexhaustible supply of names that clear every one of the bot's own
        gates. A success is therefore a real, MTProto-confirmed free name that
        Fragment does not list - and an inconclusive run says so instead of
        dressing up an occupied name.
        """
        state = _SweepState()

        # Free, unlimited bot: when enabled the search keeps scanning until it
        # finds a free name instead of stopping at the original conservative caps.
        high = runtime.unlimited_search
        screen_cap = UNLIMITED_SCREEN_CAP if high else SCREEN_CAP
        guarantee_cap = UNLIMITED_GUARANTEE_SCREEN_CAP if high else GUARANTEE_SCREEN_CAP

        # If Telegram has already thrown a long FloodWait at us, a search cannot
        # be carried out *through a session* right now. The search still happens,
        # though - screening and the final verdict both live on public pages that
        # need no session - so instead of reporting the throttle, hand the run to
        # the public path and answer with a real name.
        paused = spend_flood_window(self._checker.limiter, MAX_SEARCHABLE_FLOOD_WAIT)
        if paused:
            logger.warning("telegram flood wait %.0fs outstanding - public path", paused)
            return await self._public_only_search(criteria, progress, state)

        # The pool may not be *parked yet* but already know the next recovery is
        # further away than this search may ever last. Waiting that out is not a
        # search, it is a frozen screen - so go to the public path immediately
        # instead of burning the waiting budget on a recovery that cannot land.
        recovery = mtproto_client.flood_recovery_seconds
        if recovery and recovery > ABSOLUTE_SEARCH_SECONDS:
            logger.warning(
                "pool recovery is %.0fs away - public path now", recovery
            )
            return await self._public_only_search(criteria, progress, state)

        # The claimability gate is the line between "nobody owns it" and
        # "Telegram will actually hand it over". Only a user session can close
        # it, so without one a session-based "free" would be a guess. Rather than
        # refuse (the old behaviour) or lie, run the public-only path: it screens
        # and classifies from t.me + fragment.com, and every verdict it returns
        # is labelled as coming from public sources.
        if not mtproto_client.user_ready:
            logger.warning(
                "no user session - answering from public pages instead"
            )
            return await self._public_only_search(criteria, progress, state)

        budget = self._confirm_budget(criteria)
        state.budget = budget
        now = asyncio.get_event_loop().time()
        state.deadline = now + (
            MAX_SEARCH_SECONDS if max_seconds is None else max(0.0, max_seconds)
        )
        # The hard ceiling is never shortened by ``max_seconds``: background
        # callers pass a short working budget precisely so they cannot hold the
        # scarce quota while a user waits, and extending that into a long
        # absolute limit would defeat the point.
        state.absolute_deadline = now + (
            ABSOLUTE_SEARCH_SECONDS if max_seconds is None
            else max(0.0, max_seconds) + ABSOLUTE_SEARCH_SECONDS
        )

        # A name already proven free is the cheapest and most certain answer
        # there is: one re-confirmation instead of a whole hunt. Serving from the
        # stock is what lets the bot answer immediately when it is busy, instead
        # of queueing every user behind the same scarce Telegram quota.
        stocked = await self._serve_from_stock(criteria, state, progress)
        if stocked is not None:
            return stocked

        # Pass 1: the desirable names. Capped so they cannot eat the guarantee.
        # In unlimited mode a flat ``min(500, budget)`` *was* the whole budget,
        # which left the guarantee pass with nothing to spend and ended searches
        # in "everything is taken" while free coinages were still out there - the
        # reservation below is what keeps the second pass funded.
        if high:
            valuable_budget = min(max(VALUABLE_CONFIRM_BUDGET, budget // 4), budget)
        else:
            valuable_budget = min(VALUABLE_CONFIRM_BUDGET, budget)
        stopped = await self._sweep(
            self._candidates(criteria), valuable_budget, state, progress, "valuable", screen_cap
        )
        if stopped is not None:
            return stopped

        # Pass 2: the guarantee. Whatever budget is left goes to the stream that
        # is effectively always free, so the search ends on a name, not an excuse.
        # It screens with its own, larger allowance - screening is free and is
        # what lets the guarantee find a free coinage without touching MTProto.
        if state.confirmations < budget:
            stopped = await self._sweep(
                self._guarantee_candidates(criteria), budget, state, progress,
                "guarantee", guarantee_cap,
            )
            if stopped is not None:
                return stopped

        # The hunt found names that look free but whose claimability could not
        # be proven (gate unavailable). They are never presented as results -
        # the honest answer is that verification is down, not a fake "free".
        if state.unverified_hit is not None:
            logger.warning(
                "search ended without a verifiable name after %d screened - "
                "claimability gate unavailable",
                state.screened,
            )
            return FindAttempt(
                username="", premium=premium_rating(""), hit=False,
                reason="claim_unavailable", generated_tries=state.screened,
            )

        # Nothing free within the budget. Before reporting "everything is taken"
        # or "verification did not work", give the run one last look through the
        # public pages: if the MTProto channel refused or never answered, the
        # public path can still settle the best candidate honestly.
        if state.unknown_seen or state.occupied_seen:
            public = await self._public_fallback(state, progress)
            if public is not None:
                return public

        # Nothing free within the budget. Report honestly why the search stopped
        # - and never present an occupied name as a successful result.
        #
        # "Unconfirmed" is checked first on purpose: if any candidate reached the
        # authoritative channel and could not be confirmed, that is the truth the
        # user needs to hear ("verification did not work"), not "everything is
        # taken" - the latter would hide a broken MTProto session behind a false
        # verdict about the names.
        if state.unknown_seen:
            return FindAttempt(
                username="",
                premium=state.best_premium or premium_rating(""),
                hit=False,
                reason="unconfirmed",
                generated_tries=state.screened,
                value=estimate_value(state.best) if state.best else None,
            )

        if state.occupied_seen:
            return FindAttempt(
                username="",
                premium=state.best_premium or premium_rating(""),
                hit=False,
                reason="all_taken",
                generated_tries=state.screened,
                value=estimate_value(state.best) if state.best else None,
            )

        return FindAttempt(
            username="",
            premium=premium_rating(""),
            hit=False,
            reason="no_candidate" if state.best is None else "no_free_found",
            generated_tries=state.screened,
        )

    # ------------------------------------------------------------------ variants
    async def _public_variants(self, criteria: SearchCriteria, base: str) -> FindAttempt:
        """The "find similar" shortlist, built without any session.

        Same seed family as the session run, but every candidate is judged on the
        public pages (``t.me`` + ``fragment.com``), so a parked pool no longer
        turns this screen into a throttle notice. Only names both pages show no
        trace of are offered, and they carry the public label.
        """
        candidates = [
            name for name in beautiful_candidates(
                seed=base, length=None, allow_digits=True, min_score=0,
                rng=self._rng, limit=MAX_GENERATION_TRIES, include_coinages=False,
            ) if name != base
        ]
        screen_limit = min(len(candidates), VARIANT_SCREEN_CAP)
        free: list[FindAttempt] = []

        for start in range(0, screen_limit, VARIANT_SCREEN_BATCH):
            if len(free) >= VARIANTS_CAP:
                break
            batch = candidates[start:min(start + VARIANT_SCREEN_BATCH, screen_limit)]
            verdicts = await asyncio.gather(
                *(public_verdict_client.judge(n) for n in batch),
                return_exceptions=True,
            )
            for name, verdict in zip(batch, verdicts):
                if isinstance(verdict, Exception) or verdict.status != "free":
                    continue
                basic = CheckResult(
                    username=name, status=CheckStatus.AVAILABLE,
                    source="public_verdict", detail="claimability_unverified",
                )
                free.append(
                    FindAttempt(
                        username=name,
                        premium=premium_rating(letter_part(name)),
                        hit=True,
                        reason="free_found",
                        basic=basic,
                        value=await self._price(name),
                        fragment_clear=True,
                        fragment_checked=True,
                        public_confidence=verdict.confidence,
                        public_reason=verdict.reason,
                    )
                )

        return FindAttempt(
            username="", premium=premium_rating(base), hit=False, reason="variants",
            seed=base, variants=free, generated_tries=screen_limit,
        )

    async def _find_variants(self, criteria: SearchCriteria) -> FindAttempt:
        """Free alternatives to a name the user cannot have.

        This is the answer to the most common dead end in the product: the
        perfect name is taken and the user is left with nothing. Given a seed we
        build the small family of brand-style variants around its root (root +
        suffix, prefix + root, root + number) and, exactly like a free search,
        screen them on the public page first, confirm the survivors with the
        authoritative MTProto call second, and let Fragment veto any name it
        lists. The free ones are returned as a shortlist - never the seed
        itself, which is why they were asked.
        """
        seed = (criteria.seed or "").strip().lower().lstrip("@")
        base = UsernameGenerator._base(seed) if seed else ""
        if not base or len(base) < 3:
            return FindAttempt(
                username="", premium=premium_rating(""), hit=False,
                reason="variants_invalid", seed=base or seed,
            )

        # If Telegram has already thrown a long FloodWait at us, a *session*
        # variants run cannot be carried out right now - but the public pages
        # need no session, so the shortlist is still built from them instead of
        # the run ending with a throttle notice.
        paused = spend_flood_window(self._checker.limiter, MAX_SEARCHABLE_FLOOD_WAIT)
        if paused or not mtproto_client.user_ready:
            logger.warning(
                "variants: no usable session (flood wait %.0fs) - public path",
                paused or 0.0,
            )
            return await self._public_variants(criteria, base)

        # The seed family, excluding the seed itself (it is the thing they want
        # but cannot have, so it is useless in the shortlist). Coinages are left
        # out on purpose: a random coinage is not a "close alternative".
        candidates = [
            name for name in beautiful_candidates(
                seed=base, length=None, allow_digits=True, min_score=0,
                rng=self._rng, limit=MAX_GENERATION_TRIES, include_coinages=False,
            ) if name != base
        ]

        free: list[FindAttempt] = []
        screened = 0
        confirmations = 0
        screen_limit = min(len(candidates), VARIANT_SCREEN_CAP)
        for start in range(0, screen_limit, VARIANT_SCREEN_BATCH):
            if len(free) >= VARIANTS_CAP or confirmations >= VARIANT_CONFIRM_BUDGET:
                break
            batch = candidates[start:min(start + VARIANT_SCREEN_BATCH, screen_limit)]
            survivors = await self._screen(batch)
            screened += len(batch)
            index = 0
            while index < len(survivors):
                if len(free) >= VARIANTS_CAP or confirmations >= VARIANT_CONFIRM_BUDGET:
                    break
                name = survivors[index]
                basic = await self._checker.confirm_availability(name)
                if basic.status is CheckStatus.RATE_LIMITED:
                    # Telegram is throttling the pool. A sessionless confirm
                    # through the public pages keeps the shortlist filling
                    # instead of freezing on a flood recovery: anything the
                    # public verdict says is free becomes a variant (labelled
                    # as such), anything else is skipped.
                    try:
                        verdict: PublicVerdict = await public_verdict_client.judge(name)
                    except Exception as exc:
                        logger.debug("variants: public confirm failed for %s: %s", name, exc)
                        verdict = PublicVerdict(
                            "unknown", "public_check_failed", confidence="none"
                        )
                    confirmations += 1
                    index += 1
                    if verdict.status == "free":
                        basic = CheckResult(
                            username=name, status=CheckStatus.AVAILABLE,
                            source="public_verdict", detail="claimability_unverified",
                        )
                        fragment_clear, fragment_checked = await self._fragment_verdict(name)
                        if fragment_clear:
                            free.append(
                                FindAttempt(
                                    username=name,
                                    premium=premium_rating(letter_part(name)),
                                    hit=True,
                                    reason="free_found",
                                    basic=basic,
                                    value={**estimate_value(name), **await self._price(name)},
                                    fragment_clear=fragment_clear,
                                    fragment_checked=fragment_checked,
                                    public_confidence=verdict.confidence,
                                    public_reason=verdict.reason,
                                )
                            )
                        continue
                    continue
                confirmations += 1
                index += 1
                if basic.status is CheckStatus.AVAILABLE:
                    if getattr(basic, "detail", None) == "claimability_unverified":
                        # Unverifiable claimability is never listed as a free
                        # alternative - same rule as the main search.
                        continue
                    # Same double check as a free search: Fragment listings veto.
                    fragment_clear, fragment_checked = await self._fragment_verdict(name)
                    if not fragment_clear:
                        continue
                    free.append(
                        FindAttempt(
                            username=name,
                            premium=premium_rating(letter_part(name)),
                            hit=True,
                            reason="free_found",
                            basic=basic,
                            value={**estimate_value(name), **await self._price(name)},
                            fragment_clear=fragment_clear,
                            fragment_checked=fragment_checked,
                        )
                    )

        return FindAttempt(
            username="", premium=premium_rating(base), hit=False, reason="variants",
            seed=base, variants=free, generated_tries=screened,
        )
