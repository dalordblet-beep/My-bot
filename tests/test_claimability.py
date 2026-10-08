"""Claimability honesty: 'not occupied' must never silently become 'free'.

``contacts.resolveUsername`` answers "not occupied" for names Telegram will
still refuse to assign (reserved / cooldown / anti-abuse). Only the user-only
``account.checkUsername`` separates the two - and when that check is
unavailable, the result must say so, and the search must not stop for the
unverifiable name as if it were a proven win.
"""

from __future__ import annotations

import pytest

from app.search import finder as finder_module
from app.search.finder import SearchCriteria, UsernameFinder
from app.telegram import mtproto as mtproto_module
from app.telegram.mtproto import MtprotoResult
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus
from app.utils.results import CheckResult
from tests.mock_telegram import FakePageProbe


def _available(name: str, detail: str | None) -> CheckResult:
    return CheckResult(
        username=name, status=CheckStatus.AVAILABLE, source="mtproto", detail=detail,
    )


# ------------------------------------------------------------------- checker
async def test_a_parked_gate_reports_limited_never_free(monkeypatch):
    """A throttled user session answers nothing - and that must not read "free".

    ``account.checkUsername`` is the verdict now, so a throttle is the only way
    the answer can be missing - and it is reported as such instead of being
    dressed up as an available name.
    """
    client = mtproto_module.mtproto_client

    async def parked(name):
        return MtprotoResult("flood", "90")

    monkeypatch.setattr(client, "claim_verdict", parked, raising=False)
    monkeypatch.setattr(
        client, "_user_clients",
        [{"name": "t", "client": None, "ready": True, "cooldown_until": 0.0}],
        raising=False,
    )

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("recap")

    assert result.status is CheckStatus.RATE_LIMITED
    assert result.reason == "flood_wait"


async def test_claimable_means_verified(monkeypatch):
    """One definitive call, and the verdict is provable - not "probably"."""
    client = mtproto_module.mtproto_client

    async def free(name):
        return MtprotoResult("free")

    monkeypatch.setattr(client, "claim_verdict", free, raising=False)
    monkeypatch.setattr(
        client, "_user_clients",
        [{"name": "t", "client": None, "ready": True, "cooldown_until": 0.0}],
        raising=False,
    )

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("iduc9")

    assert result.status is CheckStatus.AVAILABLE
    assert result.detail == "claimability_verified"


async def test_an_occupied_name_is_reported_occupied(monkeypatch):
    """USERNAME_OCCUPIED must map to OCCUPIED - it used to fall through as
    "unknown", because the exception was never caught."""
    client = mtproto_module.mtproto_client

    async def occupied(name):
        return MtprotoResult("occupied", "occupied_error")

    monkeypatch.setattr(client, "claim_verdict", occupied, raising=False)

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("durov")

    assert result.status is CheckStatus.OCCUPIED


async def test_a_fragment_lot_is_not_claimable_but_is_flagged(monkeypatch):
    """USERNAME_PURCHASE_AVAILABLE means "for sale on Fragment": not free, but
    the user should be told it can be bought rather than just "taken"."""
    client = mtproto_module.mtproto_client

    async def for_sale(name):
        return MtprotoResult("fragment", "purchase_available")

    monkeypatch.setattr(client, "claim_verdict", for_sale, raising=False)

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("emanim")

    assert result.status is CheckStatus.OCCUPIED
    assert result.detail == "purchase_available"


async def test_one_call_decides_availability(monkeypatch):
    """The whole point of the new engine: one checkUsername call per candidate.

    contacts.resolveUsername is not an availability check - the documentation
    calls it "resolve a @username to get peer info" - so it must not run on this
    path at all. It used to, which doubled the quota cost of every candidate.
    """
    client = mtproto_module.mtproto_client
    calls = {"claim": 0, "resolve": 0}

    async def claim(name):
        calls["claim"] += 1
        return MtprotoResult("free")

    async def resolve(name):
        calls["resolve"] += 1
        return MtprotoResult("not_occupied")

    monkeypatch.setattr(client, "claim_verdict", claim, raising=False)
    monkeypatch.setattr(client, "resolve_username", resolve, raising=False)

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("iduc9")

    assert result.status is CheckStatus.AVAILABLE
    assert calls == {"claim": 1, "resolve": 0}


# -------------------------------------------------------------------- finder
async def test_unverified_names_are_never_delivered_as_results(monkeypatch):
    """When claimability cannot be verified, the run says so instead of
    inventing a "free" name - the exact failure the user kept hitting."""
    monkeypatch.setattr(settings_, "allow_bot_api_availability", True)

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    confirmed = 0

    async def unverified(name):
        nonlocal confirmed
        confirmed += 1
        return _available(name, "claimability_unverified")

    checker.confirm_availability = unverified
    attempt = await UsernameFinder(checker, None).find_one(SearchCriteria(length=8))

    # The run kept hunting (it did not stop at the first unverifiable name)...
    assert confirmed > 1
    # ...and in the end refused to invent a result: no username, honest reason.
    assert attempt.hit is False
    assert attempt.username == ""
    assert attempt.reason == "claim_unavailable"


async def test_a_dead_gate_aborts_the_hunt_instead_of_burning_the_budget(monkeypatch):
    """A FloodWait-parked gate cannot verify anything: hunting on behind it
    looks like an infinite search. One unverified confirm must be enough to
    stop the run with the honest 'cannot verify' screen."""
    from app.telegram import mtproto as mtproto_module

    monkeypatch.setattr(settings_, "allow_bot_api_availability", True)
    client = mtproto_module.mtproto_client
    # Park the user session exactly as a FloodWait does.
    monkeypatch.setattr(
        client, "_user_clients",
        [{"name": "t", "client": None, "ready": True, "cooldown_until": float("inf")}],
        raising=False,
    )

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    confirmed = 0

    async def unverified(name):
        nonlocal confirmed
        confirmed += 1
        return _available(name, "claimability_unverified")

    checker.confirm_availability = unverified
    attempt = await UsernameFinder(checker, None).find_one(SearchCriteria(length=8))

    assert confirmed == 1
    assert attempt.hit is False
    assert attempt.reason == "claim_unavailable"


async def test_verified_hit_stops_the_search_immediately(monkeypatch):
    monkeypatch.setattr(settings_, "allow_bot_api_availability", True)

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    confirmed = 0

    async def verified(name):
        nonlocal confirmed
        confirmed += 1
        return _available(name, "claimability_verified")

    checker.confirm_availability = verified
    attempt = await UsernameFinder(checker, None).find_one(SearchCriteria(length=8))

    assert attempt.hit is True
    assert confirmed == 1


async def test_search_refuses_to_run_without_the_claimability_gate():
    """No user session -> no search at all: every verdict would be a guess."""
    from app.telegram import mtproto as mtproto_module

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    finder = UsernameFinder(checker, None)

    async def broken_confirm(name):  # must never be reached
        raise AssertionError("the search must refuse before confirming anything")

    checker.confirm_availability = broken_confirm
    saved = mtproto_module.mtproto_client._user_clients
    mtproto_module.mtproto_client._user_clients = []
    try:
        attempt = await finder.find_one(SearchCriteria(length=8))
    finally:
        mtproto_module.mtproto_client._user_clients = saved

    assert attempt.hit is False
    assert attempt.reason == "claim_unavailable"
    assert attempt.generated_tries == 0


async def test_result_screen_carries_the_caveat():
    from app.bot import texts
    from app.search.pattern import premium_rating

    class _Attempt:
        username = "recap"
        premium = premium_rating("recap")
        hit = True
        reason = "free_found"
        basic = _available("recap", "claimability_unverified")
        value = None
        generated_tries = 3
        seed = None
        variants = None
        fragment_clear = True
        fragment_checked = True

    body = texts._find_result_body("en", _Attempt(), 1)
    assert "not verified" in body.lower()


from app.config import settings as settings_  # noqa: E402  (used via alias above)
