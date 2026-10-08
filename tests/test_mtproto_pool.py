"""The MTProto session pool: rotation, parking and honest degradation.

One Telegram account cannot carry every check for a thousand users without
being temporarily limited. The pool multiplies the quota with extra bot
tokens (BotFather, no phone number involved): each session carries its own
limit, a rate-limited session is parked and the next one answers. Only when
every session is parked does the caller hear about it - and the checker then
falls back to the account-free signals instead of dying.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.telegram import mtproto as mtproto_module
from app.telegram.mtproto import MtprotoResult
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus
from app.utils.ratelimit import RateLimiter
from tests.mock_telegram import FakePageProbe


class FloodWaitFake(Exception):
    """Named so the pool's ``FloodWait in type name`` guard catches it."""

    def __init__(self, seconds: int = 60) -> None:
        super().__init__(f"FloodWait {seconds}")
        self.seconds = seconds


class FakeClient:
    """Stands in for a Telethon client - an async callable over TL requests."""

    def __init__(self, behaviour) -> None:
        self._behaviour = behaviour
        self.calls = 0

    async def __call__(self, request):
        self.calls += 1
        outcome = self._behaviour(request)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _occupied_response():
    """A resolve response shaped like a resolved entity -> OCCUPIED."""
    entity = type("Entity", (), {"id": 1})()
    return type("Response", (), {"chats": [entity], "users": [], "peer": None})()


def _session(name: str, client, ready: bool = True) -> dict:
    return {"name": name, "client": client, "ready": ready, "cooldown_until": 0.0}


class _NoChatBot:
    """A Bot API stand-in that can never resolve anything."""

    async def get_chat(self, chat_id):
        raise RuntimeError("chat not found")


# --------------------------------------------------------------------- config
def test_bot_session_tokens_parse_from_csv(monkeypatch):
    monkeypatch.setattr(settings, "mtproto_bot_sessions", "123:AAA, 456:BBB ,,")
    assert settings.bot_session_tokens == ["123:AAA", "456:BBB"]
    monkeypatch.setattr(settings, "mtproto_bot_sessions", "")
    assert settings.bot_session_tokens == []


# ------------------------------------------------------------------- rotation
async def test_flood_parks_one_session_and_the_next_answers(monkeypatch):
    """The whole point of the pool: one limited account must not stall checks."""
    client = mtproto_module.mtproto_client
    flooding = FakeClient(lambda request: FloodWaitFake(90))
    healthy = FakeClient(lambda request: _occupied_response())

    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", flooding, raising=False)
    monkeypatch.setattr(
        client, "_bot_clients", [_session("main-p2", healthy)], raising=False
    )

    verdict = await client.resolve_username("somebody")
    assert verdict.kind == "occupied"  # the extra session answered
    assert flooding.calls == 1 and healthy.calls == 1

    # The main session is parked: the next call goes straight to the extra one.
    verdict = await client.resolve_username("somebody")
    assert verdict.kind == "occupied"
    assert flooding.calls == 1 and healthy.calls == 2


async def test_all_sessions_parked_reports_flood_with_recovery_time(monkeypatch):
    client = mtproto_module.mtproto_client
    first = FakeClient(lambda request: FloodWaitFake(120))
    second = FakeClient(lambda request: FloodWaitFake(30))

    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", first, raising=False)
    monkeypatch.setattr(
        client, "_bot_clients", [_session("main-p2", second)], raising=False
    )

    verdict = await client.resolve_username("somebody")
    assert verdict.kind == "flood"
    # The soonest recovery is reported: 30s, not the 120s of the first hit.
    assert float(verdict.detail) <= 31


async def test_every_session_shares_the_traffic(monkeypatch):
    """The main session must not answer every call.

    Pinning it to the front of the list meant a five-session pool still carried
    exactly one account's quota: Telegram flooded that account after roughly
    twenty lookups and the search died - the reported "stopped after 20 checks".
    Round-robin over the whole pool is what turns extra tokens into throughput.
    """
    client = mtproto_module.mtproto_client
    main = FakeClient(lambda request: _occupied_response())
    extra = FakeClient(lambda request: _occupied_response())

    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", main, raising=False)
    monkeypatch.setattr(client, "_bot_clients", [_session("p2", extra)], raising=False)
    monkeypatch.setattr(client, "_bot_turn", 0, raising=False)
    monkeypatch.setattr(client, "_main_cooldown", 0.0, raising=False)

    for _ in range(4):
        await client.resolve_username("somebody")

    assert main.calls == 2 and extra.calls == 2


async def test_the_verdict_never_touches_the_bot_pool(monkeypatch):
    """A parked bot pool is now completely irrelevant to availability.

    ``account.checkUsername`` is the verdict, and only a user account may call it
    ("Only users can use this method" - the docs say so outright). So the bot
    sessions - the ones that get flooded - are not on this path at all.
    """
    client = mtproto_module.mtproto_client
    touched = {"resolve": 0}

    async def resolve(name):
        touched["resolve"] += 1
        return MtprotoResult("flood", "90")

    async def claimable(name):
        return MtprotoResult("free")

    monkeypatch.setattr(client, "resolve_username", resolve, raising=False)
    monkeypatch.setattr(client, "claim_verdict", claimable, raising=False)
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", None, raising=False)
    monkeypatch.setattr(settings, "request_delay", 0.0)

    checker = UsernameChecker(
        cache=None, bot=None, rate_limiter=RateLimiter(min_interval=0.0),
        page_probe=FakePageProbe(state="unknown"),
    )
    result = await checker.check_free_candidate("somefree")

    assert result.status is CheckStatus.AVAILABLE
    assert result.source == "mtproto_user"
    assert result.detail == "claimability_verified"
    assert touched["resolve"] == 0, "the bot pool must not be consulted at all"


def test_a_ban_does_not_slow_the_healthy_sessions(monkeypatch):
    """A long FloodWait is an existing ban, not evidence the pace is too fast.

    The banned session is already out of the pace divisor, so backing the healthy
    ones off for it punishes them for nothing - and that double penalty is what
    made every call wait seconds on a pool that could answer perfectly well.
    """
    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", FakeClient(lambda r: _occupied_response()), raising=False)
    monkeypatch.setattr(client, "_bot_clients", [], raising=False)
    monkeypatch.setattr(settings, "request_delay", 3.0)
    client._pace_multiplier = 1.0
    client._last_flood_at = 0.0

    base = client.call_interval

    client._park("main", 70_000)  # a ~19 hour ban
    assert client._pace_multiplier == 1.0, "a ban must not slow the pool down"
    assert client.call_interval == pytest.approx(base)

    client._park("main", 45)  # a short flood - a real pace signal
    assert client._pace_multiplier > 1.0


async def test_a_fully_parked_pool_does_not_freeze_the_check(monkeypatch):
    """Every session parked must not cost the caller the pool's backed-off pace.

    A resolve cannot go anywhere when the whole pool is sitting out a FloodWait,
    yet the check still waited for the shared interval first - and with the
    divisor at 1 and the 16x backoff that interval was 96 seconds. Two lookups
    took five minutes while the user session sat idle and perfectly able to
    answer. Now the pace is only paid when a session can actually take the call.
    """
    import time

    client = mtproto_module.mtproto_client

    async def claimable(name):
        return MtprotoResult("free")

    monkeypatch.setattr(client, "claim_verdict", claimable, raising=False)
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", None, raising=False)
    monkeypatch.setattr(client, "_bot_clients", [], raising=False)
    client._pace_multiplier = 16.0

    assert client.resolve_sessions_live == 0

    checker = UsernameChecker(
        cache=None, bot=None, rate_limiter=RateLimiter(min_interval=0.0),
        page_probe=FakePageProbe(state="unknown"),
    )
    started = time.monotonic()
    result = await checker.check_free_candidate("somefree")
    elapsed = time.monotonic() - started

    # The user session answered, and it did so without queueing behind the pool.
    assert result.status is CheckStatus.AVAILABLE
    assert result.detail == "claimability_verified"
    assert elapsed < 2.0, f"the check waited on a parked pool for {elapsed:.1f}s"


def test_the_backoff_never_looks_like_a_hang(monkeypatch):
    """A big backoff is meant to be cautious, not to make a search look frozen."""
    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", None, raising=False)
    monkeypatch.setattr(client, "_bot_clients", [], raising=False)
    monkeypatch.setattr(settings, "request_delay", 3.0)
    client._pace_multiplier = 16.0
    client._last_flood_at = asyncio.get_event_loop().time()

    assert client.resolve_sessions_live == 0
    # Without the ceiling this was 3.0 * 2.0 * 16 / 1 == 96 seconds.
    assert client.call_interval <= mtproto_module._INTERVAL_CAP


async def test_pool_counts_only_ready_sessions(monkeypatch):
    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", FakeClient(lambda r: _occupied_response()), raising=False)
    monkeypatch.setattr(
        client, "_bot_clients",
        [
            _session("a", FakeClient(lambda r: _occupied_response())),
            _session("b", FakeClient(lambda r: _occupied_response()), ready=False),
        ],
        raising=False,
    )
    assert client.bot_session_count == 2
    assert client.resolve_ready is True

    monkeypatch.setattr(client, "_ready", False, raising=False)
    assert client.resolve_ready is True  # the extra session still answers


async def test_parked_sessions_do_not_inflate_the_shared_pace(monkeypatch):
    """A FloodWait-parked session cannot serve a call, so it must not count
    toward the pace divisor - counting it would over-pace the healthy ones
    and push every account into its next FloodWait."""
    import asyncio

    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", FakeClient(lambda r: _occupied_response()), raising=False)
    monkeypatch.setattr(
        client, "_bot_clients",
        [
            _session("a", FakeClient(lambda r: _occupied_response())),
            _session("b", FakeClient(lambda r: _occupied_response())),
        ],
        raising=False,
    )
    assert client.bot_session_count == 3

    # Park the main session exactly the way resolve_username does.
    monkeypatch.setattr(
        client, "_main_cooldown",
        asyncio.get_event_loop().time() + 999, raising=False,
    )
    assert client.bot_session_count == 2


async def test_check_username_is_paced_per_user_session(monkeypatch):
    """account.checkUsername runs on a real account - unpaced, one session
    would be flood limited within minutes of a busy short-name search."""
    client = mtproto_module.mtproto_client
    monkeypatch.setattr(
        client, "_user_clients", [_session("u", FakeClient(lambda r: True))], raising=False
    )
    monkeypatch.setattr(settings, "user_session_delay", 3.0)

    verdict = await client.check_username("whatever")

    assert verdict is True
    assert client._user_limiter.min_interval == pytest.approx(3.0)


# -------------------------------------------------- degradation without dying
async def test_flood_falls_back_to_account_free_signals(monkeypatch):
    """A full park must degrade to page+Bot API, not freeze every search."""
    client = mtproto_module.mtproto_client

    async def all_parked(name):
        return MtprotoResult("flood", "90")

    monkeypatch.setattr(client, "claim_verdict", all_parked, raising=False)
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", None, raising=False)
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)

    checker = UsernameChecker(
        cache=None, bot=_NoChatBot(), rate_limiter=RateLimiter(min_interval=0.0),
        page_probe=FakePageProbe(state="free"),
    )
    result = await checker.check_free_candidate("somefree")

    assert result.status is CheckStatus.AVAILABLE
    assert result.source == "public_page"


async def test_flood_with_no_signal_still_reports_rate_limited(monkeypatch):
    """When nothing can answer, the caller must hear an honest 'limited'."""
    client = mtproto_module.mtproto_client

    async def all_parked(name):
        return MtprotoResult("flood", "90")

    monkeypatch.setattr(client, "claim_verdict", all_parked, raising=False)
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", None, raising=False)
    monkeypatch.setattr(settings, "allow_bot_api_availability", False)

    checker = UsernameChecker(
        cache=None, bot=_NoChatBot(), rate_limiter=RateLimiter(min_interval=0.0),
        page_probe=FakePageProbe(state="unknown"),
    )
    result = await checker.check_free_candidate("ambiguous")

    assert result.status is CheckStatus.RATE_LIMITED
    assert result.reason == "flood_wait"


async def test_the_user_pool_scales_the_verdict_pace(monkeypatch):
    """N user accounts carry N times the verdicts at the same per-account rate.

    This is the number that matters now. ``account.checkUsername`` *is* the
    availability verdict, only user accounts may call it, and the bot pool cannot
    help - so the user-session pool is what sets the bot's real throughput, and
    adding an account is the only thing that raises it.
    """
    client = mtproto_module.mtproto_client
    monkeypatch.setattr(
        client, "_user_clients",
        [_session(f"u{i}", FakeClient(lambda r: True)) for i in range(4)],
        raising=False,
    )
    monkeypatch.setattr(settings, "user_session_delay", 3.0)

    verdict = await client.claim_verdict("whatever")

    assert verdict.kind == "free"
    # 3.0s per account, divided by 4 live sessions.
    assert client._user_limiter.min_interval == pytest.approx(3.0 / 4)


async def test_occupied_and_for_sale_are_told_apart(monkeypatch):
    """The three outcomes checkUsername documents, mapped without guessing.

    Live behaviour is what matters here: Telegram raises USERNAME_OCCUPIED for a
    taken name and USERNAME_PURCHASE_AVAILABLE for one that is for sale on
    Fragment - and the second one is *not* the same as "taken", it is buyable.
    """
    from telethon.errors import (
        UsernameInvalidError,
        UsernameOccupiedError,
        UsernamePurchaseAvailableError,
    )

    client = mtproto_module.mtproto_client

    cases = [
        (UsernameOccupiedError(request=None), "occupied"),
        (UsernamePurchaseAvailableError(request=None), "fragment"),
        (UsernameInvalidError(request=None), "invalid"),
    ]
    for error, expected in cases:
        def raiser(request, _error=error):
            raise _error

        monkeypatch.setattr(
            client, "_user_clients", [_session("u", FakeClient(raiser))], raising=False
        )
        verdict = await client.claim_verdict("whatever")
        assert verdict.kind == expected, f"{type(error).__name__} -> {verdict.kind}"


def test_flood_backs_the_pool_pace_off_and_it_recovers(monkeypatch):
    """Fresh bot accounts carry smaller quotas than seasoned ones: the pool
    must learn from FloodWaits (doubling its interval) and recover after a
    quiet period instead of staying slow forever."""
    import asyncio

    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", FakeClient(lambda r: _occupied_response()), raising=False)
    monkeypatch.setattr(client, "_bot_clients", [], raising=False)
    monkeypatch.setattr(settings, "request_delay", 3.0)
    client._pace_multiplier = 1.0

    base = client.call_interval
    assert base == pytest.approx(3.0 * 2.0)

    # A flood doubles the interval; another one doubles it again - up to the
    # ceiling, which exists so a cautious pace never reads as a frozen screen.
    client._park("main", 60)
    assert client.call_interval == pytest.approx(base * 2)
    client._park("main", 60)
    assert client.call_interval == pytest.approx(
        min(base * 4, mtproto_module._INTERVAL_CAP)
    )

    # Ten flood-free minutes recover the full speed.
    client._last_flood_at = asyncio.get_event_loop().time() - 601
    assert client.call_interval == pytest.approx(base)
    assert client._pace_multiplier == 1.0


# ------------------------------------------------- fragment (fragment.* calls)
def _collectible_response():
    """A fragment.getCollectibleInfo response shaped like a real one."""
    return type(
        "Info",
        (),
        {
            "url": "https://fragment.com/username/x",
            "purchase_date": None,
            "amount": 1250,  # 12.50 USD
            "currency": "USD",
            "crypto_amount": 12_500_000_000,
            "crypto_currency": "TON",
        },
    )()


async def test_fragment_lookups_skip_parked_sessions_and_are_paced(monkeypatch):
    """fragment.* used to run unpaced on the MAIN session - hammering an
    already-flood-limited account. Now: pool rotation + shared pace."""
    import asyncio

    from app.utils.ratelimit import RateLimiter

    client = mtproto_module.mtproto_client
    flooding = FakeClient(lambda r: FloodWaitFake(500))
    healthy = FakeClient(lambda r: _collectible_response())
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", flooding, raising=False)
    monkeypatch.setattr(
        client, "_main_cooldown",
        asyncio.get_event_loop().time() + 999, raising=False,
    )
    monkeypatch.setattr(client, "_bot_clients", [_session("p2", healthy)], raising=False)
    monkeypatch.setattr(client, "_fragment_limiter", RateLimiter(min_interval=0.0))

    info = await client.collectible_info("somename")

    assert info is not None
    assert info.fiat_amount == 12.5
    assert flooding.calls == 0 and healthy.calls == 1
    assert client._fragment_limiter.min_interval == client.call_interval


async def test_fragment_returns_none_when_every_session_is_parked(monkeypatch):
    from app.utils.ratelimit import RateLimiter

    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", FakeClient(lambda r: FloodWaitFake(500)), raising=False)
    monkeypatch.setattr(
        client, "_main_cooldown",
        asyncio.get_event_loop().time() + 999, raising=False,
    )
    monkeypatch.setattr(
        client, "_bot_clients",
        [_session("p2", FakeClient(lambda r: FloodWaitFake(500)))], raising=False,
    )
    monkeypatch.setattr(client, "_fragment_limiter", RateLimiter(min_interval=0.0))

    assert await client.collectible_info("somename") is None
