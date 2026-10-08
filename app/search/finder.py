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
from typing import Iterator

from app.collectible.checker import CollectibleChecker
from app.collectible.valuation import estimate_price
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
# When claimability cannot be verified (no user session, or its checkUsername
# was rate-limited), an unoccupied name is *not* a provable win. The search
# keeps hunting for a provable one and delivers the best unverified candidate
# only after this many more confirmations - never silently, the result screen
# carries the caveat.
UNVERIFIED_GRACE = 5
# If a FloodWait is longer than this, do not sit on it: a search the user is
# waiting on must answer now and say "Telegram is throttling us", not hang.
# A multi-minute wait is not a search, it is a stuck screen.
MAX_SEARCHABLE_FLOOD_WAIT = 90.0


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
    # A name that resolves as unoccupied but whose claimability could not be
    # verified (no user session, or its checkUsername was rate-limited). It is
    # never allowed to stop the search as a "win" right away - the run keeps
    # hunting for a provable name and only falls back to this one at the end.
    unverified_hit: "FindAttempt | None" = None
    unverified_seen: int = 0


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


class UsernameFinder:
    def __init__(
        self,
        checker: UsernameChecker,
        collectible: CollectibleChecker | None,
        rng: random.Random | None = None,
    ) -> None:
        self._checker = checker
        self._collectible = collectible
        self._rng = rng or random.Random()

    async def _price(self, name: str) -> int | None:
        """One-number market estimate from live Fragment comparables."""
        if self._collectible is None:
            return None
        try:
            listings = await self._collectible.fragment.market_listings()
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("price estimate failed for %s: %s", name, exc)
            return None
        return estimate_price(name, listings)

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

    async def find_one(self, criteria: SearchCriteria, progress=None) -> FindAttempt:
        """Run a search. ``progress``, when given, is called as
        ``progress(phase, confirmations, budget, screened)`` after every
        authoritative check so a caller can animate the wait with real numbers
        instead of a fake spinner."""
        if criteria.target == TARGET_VARIANTS:
            return await self._find_variants(criteria)

        return await self._find_free(criteria, progress)

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
        free = 500 if high else FREE_CONFIRM_BUDGET
        short = 500 if high else SHORT_NAME_CONFIRM_BUDGET
        if criteria.length is not None and criteria.length <= SHORT_NAME_LENGTH:
            return max(free, short)
        return free

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
        the user needs to hear about - a confirmed free name, or a throttle.
        ``None`` means "budget spent on this stream, carry on with the next one".

        ``budget`` is a ceiling on ``state.confirmations``, so several sweeps in
        one search share a single MTProto allowance instead of each taking their
        own. ``screen_cap`` is the *per-sweep* screening ceiling - it must be
        local, not the shared ``state.screened``, or the first pass can spend the
        whole allowance and leave the guarantee pass unable to look at anything.
        """
        screened_here = 0
        while screened_here < screen_cap and state.confirmations < budget:
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

            for name in survivors:
                if state.confirmations >= budget:
                    break

                basic = await self._checker.confirm_availability(name)
                state.confirmations += 1
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
                        # "Nobody owns it" is proven, "Telegram will hand it
                        # over" is not. Do not stop the run for this - keep
                        # hunting for a provable name, and only fall back to
                        # the best unverified candidate when the hunt is over.
                        if state.unverified_hit is None:
                            state.unverified_hit = attempt
                        state.unverified_seen += 1
                        if state.unverified_seen >= UNVERIFIED_GRACE:
                            return attempt
                        continue
                    return attempt

                if basic.status is CheckStatus.OCCUPIED:
                    state.occupied_seen += 1
                elif basic.status is CheckStatus.RATE_LIMITED:
                    # Telegram started throttling mid-run. Do not burn the rest
                    # of the budget sleeping - report a throttle, not "taken".
                    logger.warning(
                        "search stopped after %d candidates: flood wait hit",
                        state.screened,
                    )
                    return FindAttempt(
                        username="",
                        premium=state.best_premium or premium_rating(""),
                        hit=False,
                        reason="throttled",
                        generated_tries=state.screened,
                        value=estimate_value(state.best) if state.best else None,
                    )
                elif basic.status is CheckStatus.INVALID:
                    # Cannot be claimed either way - skip it silently.
                    continue
                else:
                    # UNKNOWN. Not a "taken" verdict - the channel simply could
                    # not confirm. Counted separately so the message stays honest.
                    state.unknown_seen += 1

        return None

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
            value={**estimate_value(name), "price": await self._price(name)},
            fragment_clear=fragment_clear,
            fragment_checked=fragment_checked,
        )

    async def _find_free(
        self, criteria: SearchCriteria, progress=None
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
           actually wants - claiming up to ``VALUABLE_CONFIRM_BUDGET``
           confirmations;
        2. the *guarantee* pass - clean coinages, which are effectively never
           registered - spending whatever is left of ``FREE_CONFIRM_BUDGET``.

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
        screen_cap = 5000 if high else SCREEN_CAP
        guarantee_cap = 20000 if high else GUARANTEE_SCREEN_CAP

        # If Telegram has already thrown a long FloodWait at us, a search cannot
        # be carried out right now. Say so immediately instead of hanging on the
        # limiter for hours while the user stares at "SEARCHING...".
        paused = spend_flood_window(self._checker.limiter, MAX_SEARCHABLE_FLOOD_WAIT)
        if paused:
            logger.warning("search aborted: telegram flood wait %.0fs outstanding", paused)
            return FindAttempt(
                username="", premium=premium_rating(""), hit=False,
                reason="throttled", generated_tries=0,
            )

        budget = self._confirm_budget(criteria)

        # Pass 1: the desirable names. Capped so they cannot eat the guarantee.
        valuable_budget = min(500 if high else VALUABLE_CONFIRM_BUDGET, budget)
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

        # Nothing provably free within the budget. If an unverified candidate
        # was found along the way (claimability could not be checked), it is
        # still the best answer - delivered with its loud caveat on the result
        # screen, never dressed up as a guaranteed win.
        if state.unverified_hit is not None:
            return state.unverified_hit

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

        # If Telegram has already thrown a long FloodWait at us, a variants run
        # cannot be carried out right now - say so instead of hanging.
        paused = spend_flood_window(self._checker.limiter, MAX_SEARCHABLE_FLOOD_WAIT)
        if paused:
            logger.warning("variants aborted: telegram flood wait %.0fs outstanding", paused)
            return FindAttempt(
                username="", premium=premium_rating(base), hit=False,
                reason="throttled", seed=base,
            )

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
        throttled = False
        for start in range(0, screen_limit, VARIANT_SCREEN_BATCH):
            if len(free) >= VARIANTS_CAP or confirmations >= VARIANT_CONFIRM_BUDGET:
                break
            batch = candidates[start:min(start + VARIANT_SCREEN_BATCH, screen_limit)]
            survivors = await self._screen(batch)
            screened += len(batch)
            for name in survivors:
                if len(free) >= VARIANTS_CAP or confirmations >= VARIANT_CONFIRM_BUDGET:
                    break
                basic = await self._checker.confirm_availability(name)
                confirmations += 1
                if basic.status is CheckStatus.RATE_LIMITED:
                    # A throttle is an instruction to stop, not a reason to burn
                    # the remaining confirmation budget. Anything already in
                    # ``free`` remains authoritative and safe to return.
                    logger.warning(
                        "variants stopped after %d confirmations: flood wait hit",
                        confirmations,
                    )
                    throttled = True
                    break
                if basic.status is CheckStatus.AVAILABLE:
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
                            value={**estimate_value(name), "price": await self._price(name)},
                            fragment_clear=fragment_clear,
                            fragment_checked=fragment_checked,
                        )
                    )
            if throttled:
                break

        return FindAttempt(
            username="", premium=premium_rating(base), hit=False, reason="variants",
            seed=base, variants=free, generated_tries=screened,
        )
