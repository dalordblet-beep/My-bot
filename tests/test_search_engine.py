"""Search wizard engines: masks, premium rating, one-shot finder and battle."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.config import settings
from app.search import pattern
from app.search.battle import CRITERIA, compare, score_side
from app.search.finder import PREMIUM_FLOOR, SearchCriteria, UsernameFinder
from app.search.pattern import (
    build_mask,
    compile_mask,
    generate_from_mask,
    mask_is_usable,
    premium_rating,
    rate,
)
from app.telegram import username_checker as uc_module
from app.telegram.username_checker import UsernameChecker
from tests.mock_telegram import FakePageProbe


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


async def _failing_judge(self, username):
    """A public path that cannot settle anything (no network in tests)."""
    from app.telegram.public_verdict import PublicVerdict

    return PublicVerdict("unknown", "fragment_inconclusive", confidence="none")


# --------------------------------------------------------------------------- masks
def test_mask_compiles_to_an_anchored_pattern():
    compiled = compile_mask("??ged")
    assert compiled is not None
    assert compiled.match("moged")
    assert compiled.match("boged")
    assert not compiled.match("mogedx")
    assert not compiled.match("mged")


def test_mask_supports_digits_and_stars():
    digits = compile_mask("m#ged")
    assert digits is not None
    assert digits.match("m7ged")
    assert not digits.match("maged")

    star = compile_mask("*dev")
    assert star is not None
    assert star.match("mydev")
    assert star.match("abdev")
    # Telegram itself rejects names shorter than 5 characters.
    assert not star.match("dev")


def test_bad_masks_are_rejected_not_crashed():
    for bad in ("", "bad!mask", "UPPER ok", "?? ged"):
        assert compile_mask(bad) is None
        assert not mask_is_usable(bad)


def test_generated_names_always_match_the_mask():
    for _ in range(60):
        name = generate_from_mask("??ged")
        assert name is not None
        assert compile_mask("??ged").match(name), name
        assert pattern.MIN_LENGTH <= len(name) <= pattern.MAX_LENGTH
        assert not name.startswith("_") and not name.endswith("_")


def test_build_mask_respects_length_and_digits():
    assert build_mask(length=7, allow_digits=False) == "???????"
    assert "#" in build_mask(length=7, allow_digits=True)
    assert build_mask(explicit="??ged") == "??ged"
    assert build_mask(prefix="moged", length=8) == "moged???"


def test_broad_candidates_reach_beyond_the_pronounceable_space():
    """The guarantee needs a stream wider than "pretty" coinages.

    At five characters the pronounceable space is exhausted (measured live), so
    a free short name only exists among the full-alphabet combinations. The
    broad stream must emit valid handles of exactly the requested length.
    """
    from app.search.generator import broad_candidates

    names = list(
        broad_candidates(length=5, allow_digits=False, min_score=45, rng=random.Random(0), limit=50)
    )
    assert names
    for name in names:
        assert len(name) == 5, name
        assert name.isalpha(), name
        assert any(ch in "aeiouy" for ch in name), name  # kept merely sayable


def test_digits_are_placed_inside_the_length_not_appended():
    """The length setting is the TOTAL length; digits sit inside it.

    ``length=5, digits on`` must yield five-character names carrying 1-2 digits -
    not a five-letter stem with digits glued on (which produced 6-7 char names).
    """
    from app.search.generator import beautiful_candidates

    names = [
        n for n in beautiful_candidates(
            length=5, allow_digits=True, min_score=45, rng=random.Random(1), limit=200
        )
    ][:20]
    assert names
    for name in names:
        assert len(name) == 5, name
        digits = sum(ch.isdigit() for ch in name)
        assert 1 <= digits <= 2, name
        assert not name[0].isdigit(), name  # never a leading digit


# --------------------------------------------------------------------------- rating
def test_rating_rewards_short_clean_names():
    # A real word is worth more than a pronounceable coinage of the same shape,
    # which in turn beats an unpronounceable random string.
    assert rate("crane").total > rate("moged").total > rate("tyzoc").total
    # Digits and separators are penalised, in that order.
    assert rate("moged").total > rate("m0ged").total
    assert rate("moged").total > rate("mo_ged").total


def test_rating_is_bounded_and_explainable():
    for name in ("abcde", "m" * 32, "a_b_c_d", "12345", ""):
        rating = rate(name)
        assert 0 <= rating.total <= 100
        assert set(rating.parts) == {"length", "word", "spelling", "digits", "separators"}
        assert rating.total == sum(rating.parts.values())


# --------------------------------------------------------------------------- premium
def test_premium_counts_five_quality_criteria():
    premium = premium_rating("crane")
    assert premium.total == sum(
        (premium.no_digits, premium.no_separators, premium.collectible,
         premium.readable, premium.dictionary)
    )
    # A clean 5-letter dictionary word clears every gate.
    assert premium.total == 5


def test_premium_punishes_digits_and_separators():
    assert premium_rating("m0ged").no_digits is False
    assert premium_rating("mo_ged").no_separators is False
    # A long handle is out of the collectible window but can still be clean.
    long_clean = premium_rating("mobiledevteam")
    assert long_clean.collectible is False
    assert long_clean.no_digits is True
    assert long_clean.no_separators is True


# --------------------------------------------------------------------------- finder
async def test_finder_screens_with_the_page_before_confirming(bot, monkeypatch):
    """The free page carries the wide net; MTProto is spent only on survivors."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    probe = FakePageProbe(state="free")
    checker = UsernameChecker(cache=None, bot=bot, page_probe=probe)

    confirms = 0
    original = checker.confirm_availability

    async def counting(name):
        nonlocal confirms
        confirms += 1
        return await original(name)

    checker.confirm_availability = counting

    class CountingCollectible:
        calls = 0

        async def check_collectible_username(self, username):
            CountingCollectible.calls += 1
            raise AssertionError("collectible must not run in free mode")

    finder = UsernameFinder(checker, CountingCollectible())
    attempt = await finder.find_one(SearchCriteria(length=8))

    assert attempt.username
    assert attempt.hit is True
    assert attempt.basic is not None
    # The page screened a whole batch for free...
    assert len(probe.calls) > 1
    # ...and exactly one scarce MTProto confirmation produced the result.
    assert confirms == 1


async def test_finder_only_returns_premium_candidates(bot, monkeypatch):
    """There is no user score filter any more - the bot applies its own taste.

    Every name the finder hands back must clear the premium floor, so the N/5
    verdict shown to the user is never a name that failed the bot's own gate.
    """
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=6))
    assert attempt.username
    assert attempt.premium.total >= PREMIUM_FLOOR


async def test_finder_never_reports_a_taken_name(bot, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="occupied", title="X"))
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=7))
    # Free mode must never hand back an occupied name - that result is worthless.
    assert attempt.hit is False
    assert attempt.username == ""
    assert attempt.reason in ("all_taken", "no_free_found")


async def test_finder_gives_up_gracefully_when_nothing_is_free(bot):
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="occupied"))
    finder = UsernameFinder(checker, None)

    # The probe says every name is taken, so the search must exhaust its budget
    # and report honestly instead of returning a taken name.
    attempt = await finder.find_one(SearchCriteria(length=8))
    assert attempt.username == ""
    assert attempt.hit is False
    assert attempt.reason == "all_taken"


async def test_finder_exhausts_its_budget_before_giving_up(bot, monkeypatch):
    """The regression that made the bot say "checked 1 user and it's taken"."""
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(finder_module, "FREE_CONFIRM_BUDGET", 3)
    # The page cannot rule anything out, so every candidate costs a confirmation.
    probe = FakePageProbe(state="unknown")
    checker = UsernameChecker(cache=None, bot=bot, page_probe=probe)

    confirms = 0

    async def occupied(name):
        nonlocal confirms
        confirms += 1
        return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")

    checker.confirm_availability = occupied
    finder = UsernameFinder(checker, None)

    # Length 8 uses the base budget (short names earn an enlarged one, because
    # the short space is the most squatted - that is the point of the split).
    attempt = await finder.find_one(SearchCriteria(length=8))

    # A single lookup is not a search, and the scarce MTProto budget is honoured.
    assert attempt.username == ""
    assert attempt.hit is False
    assert attempt.reason == "all_taken"
    assert confirms == 3


async def test_short_names_get_an_enlarged_budget(bot, monkeypatch):
    """5-6 letter handles are the most squatted space on Telegram; a base
    budget would end those searches in "all taken" far too often."""
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    probe = FakePageProbe(state="unknown")
    checker = UsernameChecker(cache=None, bot=bot, page_probe=probe)

    confirms = 0

    async def occupied(name):
        nonlocal confirms
        confirms += 1
        return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")

    checker.confirm_availability = occupied
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=5))

    assert attempt.reason == "all_taken"
    assert confirms == finder_module.SHORT_NAME_CONFIRM_BUDGET


async def test_digits_on_names_always_carry_digits(bot, monkeypatch):
    """Digits enabled is a promise, not a permission: every candidate the
    search may return must actually carry 1-2 digits."""
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=5, allow_digits=True))

    assert attempt.hit is True
    assert attempt.username
    digits = sum(ch.isdigit() for ch in attempt.username)
    assert 1 <= digits <= 2
    # The length setting is the TOTAL length: digits sit inside it, not on top.
    assert len(attempt.username) == 5


async def test_finder_walks_past_occupied_names_to_find_a_free_one(bot, monkeypatch):
    """Many taken names in a row must not abort the run."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)

    class NthFreeProbe(FakePageProbe):
        def __init__(self, free_after: int) -> None:
            super().__init__(state="occupied")
            self.free_after = free_after

        async def check(self, username: str):
            from app.telegram.public_page import FREE, OCCUPIED, PublicPageResult

            self.calls.append(username)
            if len(self.calls) >= self.free_after:
                return PublicPageResult(FREE, reason="fake")
            return PublicPageResult(OCCUPIED, title="Somebody", reason="fake")

    probe = NthFreeProbe(free_after=6)
    finder = UsernameFinder(UsernameChecker(cache=None, bot=bot, page_probe=probe), None)

    attempt = await finder.find_one(SearchCriteria(length=7))

    assert attempt.hit is True
    assert attempt.username
    assert attempt.username == probe.calls[-1]
    # It really did walk past the occupied ones.
    assert len(probe.calls) >= 6


async def test_guarantee_pass_finds_a_free_name_when_real_words_are_taken(bot, monkeypatch):
    """The promise the product rests on: a search given a length and a digit
    preference ends with a genuinely free name, not "everything is taken".

    Real dictionary words are almost all registered, so the valuable pass is
    allowed to fail on them - the guarantee pass then leans on the coinage
    stream, which is effectively never registered, and lands a name that still
    clears every one of the bot's own gates.
    """
    from app.search.pattern import _WORD_SET
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))

    async def words_taken(name: str) -> CheckResult:
        if name in _WORD_SET:
            return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")
        return CheckResult(username=name, status=CheckStatus.AVAILABLE, source="mtproto")

    checker.confirm_availability = words_taken
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is True
    assert attempt.reason == "free_found"
    assert attempt.username
    assert attempt.username not in _WORD_SET
    # The name is not a consolation prize - it cleared the bot's own gates.
    assert attempt.premium.total >= PREMIUM_FLOOR


async def test_guarantee_pass_runs_after_the_valuable_pass_exhausts_its_share(bot, monkeypatch):
    """The valuable stream gets first refusal but cannot consume the budget.

    With the valuable pass capped at two confirmations and the first four names
    occupied, only a second pass over the coinage stream can reach the free one -
    so a hit here proves the two-pass structure, not just a lucky candidate.
    """
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    monkeypatch.setattr(finder_module, "VALUABLE_CONFIRM_BUDGET", 2)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))

    confirmations = 0

    async def taken_four_times(name: str) -> CheckResult:
        nonlocal confirmations
        confirmations += 1
        if confirmations <= 4:
            return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")
        return CheckResult(username=name, status=CheckStatus.AVAILABLE, source="mtproto")

    checker.confirm_availability = taken_four_times
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is True
    assert attempt.reason == "free_found"
    # Two passes really ran: the valuable pass stopped at its cap and the
    # guarantee pass carried on past it.
    assert confirmations > 2


async def test_finder_reports_unconfirmed_when_nothing_can_be_verified(bot):
    """UNKNOWN must never be silently reported as "taken" or as "free"."""
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is False
    assert attempt.username == ""
    assert attempt.reason == "unconfirmed"


async def test_free_result_requires_mtproto_not_just_the_page(bot, monkeypatch):
    """The core promise: the page alone may never declare a name free.

    The public page renders its "free"-looking signup shape for names it simply
    cannot preview, so a search that trusted it would hand out taken names -
    exactly the bug that was reported. Availability must come from MTProto.
    """
    monkeypatch.setattr(settings, "allow_bot_api_availability", False)
    # The page insists the name is free; there is no authoritative channel.
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    finder = UsernameFinder(checker, None)

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is False
    assert attempt.username == ""
    assert attempt.reason == "unconfirmed"


async def test_repeat_search_reuses_verdicts_instead_of_re_probing(bot):
    """The second identical search must not re-spend anything.

    Telegram quota is the bottleneck, and users press Search repeatedly. A
    remembered OCCUPIED verdict makes the repeat run free.
    """
    probe = FakePageProbe(state="occupied")
    checker = UsernameChecker(cache=None, bot=bot, page_probe=probe)
    criteria = SearchCriteria(length=6)

    # The same seed produces the same candidate list both times.
    await UsernameFinder(checker, None, rng=random.Random(7)).find_one(criteria)
    first = len(probe.calls)
    assert first > 0

    await UsernameFinder(checker, None, rng=random.Random(7)).find_one(criteria)
    second = len(probe.calls) - first

    assert second == 0
    assert checker.verdicts.hits > 0


async def test_finder_answers_from_public_pages_on_a_long_flood_wait(bot, monkeypatch):
    """A multi-hour FloodWait must not freeze the screen - and must not be an excuse.

    A parked session used to end the run with "Telegram is limiting us", which is
    an excuse, not an answer. The search now falls back to the session-free
    public path: it screens and classifies from ``t.me`` + ``fragment.com``, so a
    user with a dead session still gets a real name (or a real "everything here
    is taken"), never a bare throttle notice.
    """
    from app.utils.ratelimit import RateLimiter
    from app.telegram.public_verdict import PublicVerdict

    limiter = RateLimiter(min_interval=0.0)
    limiter.pause(20702.0)  # what a real Telegram ban looked like
    checker = UsernameChecker(
        cache=None, bot=bot, rate_limiter=limiter, page_probe=FakePageProbe(state="free")
    )

    # The public path must be exercised without touching the network here, so it
    # is stubbed to answer "free" for the candidate it is asked about.
    async def fake_judge(self, username):
        return PublicVerdict("free", "no_public_trace_anywhere")

    monkeypatch.setattr(
        "app.telegram.public_verdict.PublicVerdictClient.judge", fake_judge
    )

    finder = UsernameFinder(checker, None)

    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=6)), timeout=5
    )

    # It answers at once, with a real name, and says the verdict came from the
    # public path rather than pretending Telegram confirmed it.
    assert attempt.hit is True
    assert attempt.username != ""
    assert attempt.public_confidence == "public"


async def test_finder_keeps_hunting_when_a_throttle_mid_run(bot, monkeypatch):
    """A FloodWait mid-run is routed around, never turned into a dead end.

    This is the regression behind "the bot keeps answering with 'Telegram is
    limiting us'": a throttle used to end the run, so a user got an excuse
    instead of a name. The search now confirms throttled names through the
    public pages and keeps going; the moment a session answers again the
    hunt delivers the free name it was after.
    """
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    # The page cannot rule names out, so each survivor reaches the authoritative
    # check - and the first two of those come back limited.
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))
    monkeypatch.setattr(finder_module, "FLOOD_RETRY_PAUSE", 0.01)

    seen = 0

    async def throttling_then_free(name):
        nonlocal seen
        seen += 1
        if seen <= 2:
            return CheckResult(
                username=name, status=CheckStatus.RATE_LIMITED,
                source="mtproto", reason="flood_wait",
            )
        return CheckResult(username=name, status=CheckStatus.AVAILABLE, source="mtproto")

    checker.confirm_availability = throttling_then_free
    finder = UsernameFinder(checker, None)

    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=7)), timeout=5
    )

    # It did not stop on the throttle: it waited, retried, and produced a name.
    assert attempt.hit is True
    assert attempt.reason == "free_found"
    assert attempt.username
    assert seen >= 3


async def test_finder_never_reports_throttled_when_both_paths_are_dead(bot, monkeypatch):
    """The throttle notice is gone - it was an excuse, not an answer.

    A permanently flooded session used to end the run with "Telegram is
    limiting us", no matter what the public pages could prove. The search
    now confirms every throttled name through the public path, so the
    throttle message is unreachable by design: the worst case is an honest
    ``unconfirmed`` / ``all_taken``, which tells the user the real reason
    instead of blaming Telegram.
    """
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))
    # No wait to skip, but keep the time budgets tiny so the test does not spin.
    monkeypatch.setattr(finder_module, "MAX_SEARCH_SECONDS", 0.05)
    monkeypatch.setattr(finder_module, "ABSOLUTE_SEARCH_SECONDS", 0.05)
    # Both channels are dead: the session is permanently throttled and the
    # public path cannot settle the name either.
    monkeypatch.setattr(
        "app.telegram.public_verdict.PublicVerdictClient.judge", _failing_judge
    )

    async def always_limited(name):
        return CheckResult(
            username=name, status=CheckStatus.RATE_LIMITED,
            source="mtproto", reason="flood_wait",
        )

    checker.confirm_availability = always_limited
    finder = UsernameFinder(checker, None)

    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=7)), timeout=5
    )

    # The throttle message must never appear. The honest answer here is
    # "unconfirmed" - the public pages could not settle any name, so we
    # say so instead of pretending Telegram confirmed or denied anything.
    assert attempt.reason != "throttled", "the throttle notice is unreachable by design"
    assert attempt.reason == "unconfirmed"
    assert attempt.username == ""
    assert attempt.hit is False
    assert attempt.generated_tries > 1, "the search gave up without trying"


async def test_a_dead_session_falls_back_to_public_pages_instead_of_giving_up(
    bot, monkeypatch
):
    """The regression behind "stopped after 10 checks": a thrice-failed search
    must hand over to the public path, not answer with the throttle notice.

    A search could spend its whole wait budget on a parked pool and then report
    "Telegram is limiting this account" - the exact message the user kept seeing.
    The public pages need no session, so the run now continues there and returns
    a real, honestly-labelled verdict.
    """
    from app.search import finder as finder_module
    from app.telegram.public_verdict import PublicVerdict
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))
    monkeypatch.setattr(finder_module, "FLOOD_RETRY_PAUSE", 0.01)
    monkeypatch.setattr(finder_module, "MAX_SEARCH_SECONDS", 0.05)
    monkeypatch.setattr(finder_module, "ABSOLUTE_SEARCH_SECONDS", 0.05)

    async def always_limited(name):
        return CheckResult(
            username=name, status=CheckStatus.RATE_LIMITED,
            source="mtproto", reason="flood_wait",
        )

    async def public_free(self, username):
        return PublicVerdict("free", "no_public_trace_anywhere")

    checker.confirm_availability = always_limited
    monkeypatch.setattr(
        "app.telegram.public_verdict.PublicVerdictClient.judge", public_free
    )
    finder = UsernameFinder(checker, None)

    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=7)), timeout=5
    )

    # Not a throttle notice: a real name, labelled as a public verdict.
    assert attempt.reason == "free_found"
    assert attempt.hit is True
    assert attempt.username
    assert attempt.public_confidence == "public"
    assert attempt.basic.source == "public_verdict"


async def test_a_throttled_session_does_not_freeze_the_search(bot, monkeypatch):
    """A FloodWait mid-run never freezes the screen and never kills the hunt.

    This is the regression behind "the search sat at 1% for 218 seconds":
    the old code waited out a throttle on the same name, so a flooded pool
    could pin a run to the placeholder for minutes. The search now routes
    every throttled confirmation through the public path instead, so the
    hunt keeps moving and the free name it was after still arrives.
    """
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))
    monkeypatch.setattr(finder_module, "FLOOD_RETRY_PAUSE", 0.01)

    seen = 0

    async def throttling_then_free(name):
        nonlocal seen
        seen += 1
        if seen <= 3:
            return CheckResult(
                username=name, status=CheckStatus.RATE_LIMITED,
                source="mtproto", reason="flood_wait",
            )
        return CheckResult(username=name, status=CheckStatus.AVAILABLE, source="mtproto")

    checker.confirm_availability = throttling_then_free
    finder = UsernameFinder(checker, None)

    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=7)), timeout=5
    )

    # The working budget alone would have ended the run on the very first
    # throttle; extending it by the wait is what let it reach the free name.
    assert attempt.hit is True
    assert attempt.reason == "free_found"
    assert seen >= 4


async def test_a_hopeless_search_ends_on_time_not_on_the_budget(bot, monkeypatch):
    """A search also has a wall clock, not just a work budget.

    When the bot pool is parked every confirmation is paid on the user session,
    so a request that cannot be satisfied - a five-letter name with digits off is
    the classic - would otherwise sit on the screen for many minutes before the
    confirmation budget ran out. Ending on time gives the user an answer and the
    hint that actually helps.
    """
    import time

    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    # A budget so large the only thing that can stop the run is the clock.
    monkeypatch.setattr(finder_module, "FREE_CONFIRM_BUDGET", 1_000_000)
    monkeypatch.setattr(finder_module, "MAX_SEARCH_SECONDS", 0.3)

    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))

    async def occupied(name):
        return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")

    checker.confirm_availability = occupied
    finder = UsernameFinder(checker, None)

    started = time.monotonic()
    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=8)), timeout=15
    )
    elapsed = time.monotonic() - started

    assert attempt.hit is False
    assert elapsed < 5.0, f"the search ran for {elapsed:.1f}s past its clock"
    assert attempt.reason in ("all_taken", "unconfirmed")
    assert attempt.generated_tries > 0


async def test_unlimited_mode_still_funds_the_guarantee_pass(bot, monkeypatch):
    """In unlimited mode the valuable pass used to claim ``min(500, budget)`` -
    which *is* the whole budget - so the guarantee pass never ran and the search
    ended in "everything is taken" while free coinages were still out there.
    The valuable stream must stay a share, not the whole allowance.
    """
    from app.search import finder as finder_module
    from app.search.pattern import _WORD_SET
    from app.services.runtime_config import runtime
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(runtime, "_overrides", {"unlimited_search": True})
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="unknown"))

    async def words_taken(name: str) -> CheckResult:
        if name in _WORD_SET:
            return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")
        return CheckResult(username=name, status=CheckStatus.AVAILABLE, source="mtproto")

    checker.confirm_availability = words_taken
    finder = UsernameFinder(checker, None)

    # The reservation really is a share, not the whole ceiling.
    budget = finder._confirm_budget(SearchCriteria(length=6))
    assert finder_module.UNLIMITED_SHORT_CONFIRM_BUDGET == budget
    assert max(finder_module.VALUABLE_CONFIRM_BUDGET, budget // 4) < budget

    attempt = await asyncio.wait_for(
        finder.find_one(SearchCriteria(length=6)), timeout=10
    )

    assert attempt.hit is True
    assert attempt.username
    assert attempt.username not in _WORD_SET


# --------------------------------------------------------------------------- battle
def test_battle_scores_every_criterion():
    side = score_side("moged", "taken")
    assert set(side.scores) == set(CRITERIA)
    assert side.total == round(sum(side.scores.values()) / len(CRITERIA), 1)


def test_battle_short_name_beats_a_long_one():
    short = score_side("moged", "taken")
    long = score_side("mogeddevteam", "taken")
    assert short.total > long.total


def test_collectible_status_scores_highest():
    assert score_side("moged", "collectible").total > score_side("moged", "taken").total
    assert score_side("moged", "taken").total > score_side("moged", "free").total


async def test_compare_picks_a_winner(bot, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="occupied"))

    result = await compare("moged", "mogeddevteam", checker, None)
    assert result is not None
    assert result.winner == "left"
    assert result.left.total > result.right.total


async def test_compare_rejects_invalid_and_identical(bot):
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    assert await compare("ab", "moged", checker, None) is None
    assert await compare("moged", "@moged", checker, None) is None


# --------------------------------------------------------------------------- fragment double-check
class _FakeFragment:
    """Stands in for the Fragment marketplace: lists names matching ``listed_if``."""

    def __init__(self, listed_if):
        self._listed_if = listed_if
        self.calls = 0

    async def lookup(self, name):
        from app.utils.enums import CollectibleStatus
        from app.utils.results import CollectibleResult

        self.calls += 1
        if self._listed_if(name):
            return CollectibleResult(
                username=name, status=CollectibleStatus.AVAILABLE_FOR_PURCHASE,
                is_collectible=True, marketplace="Fragment", price="100 TON",
                source="fragment_web",
            )
        return CollectibleResult(
            username=name, status=CollectibleStatus.NOT_DETECTED,
            is_collectible=False, reason="not_listed", source="fragment_web",
        )


class _FakeCollectibleChecker:
    """The double-check's Fragment side, as the finder reaches it."""

    def __init__(self, listed_if):
        self.fragment = _FakeFragment(listed_if)


async def test_finder_rejects_names_listed_on_fragment(bot, monkeypatch):
    """The second half of the double check: a Fragment listing vetoes a free name."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    collectible = _FakeCollectibleChecker(lambda name: True)  # everything is listed
    finder = UsernameFinder(checker, collectible)

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is False
    assert attempt.username == ""
    assert attempt.reason == "all_taken"
    assert collectible.fragment.calls > 0


async def test_finder_confirms_fragment_clear_on_a_hit(bot, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    collectible = _FakeCollectibleChecker(lambda name: False)  # nothing listed
    finder = UsernameFinder(checker, collectible)

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is True
    assert attempt.fragment_clear is True
    assert attempt.fragment_checked is True


async def test_finder_says_fragment_was_not_checked_when_marketplace_is_down(bot, monkeypatch):
    """A dead marketplace must not block a search - but it must not claim a check either."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    finder = UsernameFinder(checker, None)  # no marketplace configured

    attempt = await finder.find_one(SearchCriteria(length=6))

    assert attempt.hit is True
    assert attempt.fragment_checked is False


# ----------------------------------------------------- saturated-name regression
async def test_finder_returns_a_free_name_when_every_word_is_taken(bot, monkeypatch):
    """The reported bug: the search walked saturated names and said "all taken".

    Everything word-like is occupied here and only coinages are free - the worst
    realistic case. The finder must still come back with a free name, and it must
    do so quickly instead of burning the budget on occupied words.
    """
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)

    from app.search.pattern import BRAND_SUFFIXES, is_real_word
    from app.telegram.public_page import OCCUPIED, UNKNOWN, PublicPageResult
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    suffixes = tuple(BRAND_SUFFIXES)

    def taken(name: str) -> bool:
        return is_real_word(name) or name.endswith(suffixes)

    class SaturatedProbe(FakePageProbe):
        def __init__(self) -> None:
            super().__init__(state="unknown")

        async def check(self, username: str):
            self.calls.append(username)
            verdict = OCCUPIED if taken(username) else UNKNOWN
            return PublicPageResult(verdict, reason="fake")

    checker = UsernameChecker(cache=None, bot=bot, page_probe=SaturatedProbe())

    async def confirm(name: str):
        status = CheckStatus.OCCUPIED if taken(name) else CheckStatus.AVAILABLE
        return CheckResult(username=name, status=status, source="mtproto")

    checker.confirm_availability = confirm
    finder = UsernameFinder(checker, None, rng=random.Random(3))

    for length in (5, 6, 8, None):
        attempt = await finder.find_one(SearchCriteria(length=length))
        assert attempt.hit is True, f"length={length}: gave up with {attempt.reason}"
        assert attempt.username
        assert not taken(attempt.username), f"length={length}: returned an occupied name"
        # A free name has to show up in the first screen batch, not after 150
        # occupied ones.
        assert attempt.generated_tries <= 12, f"length={length}: {attempt.generated_tries} tries"
