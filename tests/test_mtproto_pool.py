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
    monkeypatch.setattr(settings, "request_delay", 3.0)

    verdict = await client.check_username("whatever")

    assert verdict is True
    assert client._user_limiter.min_interval == pytest.approx(3.0)


# -------------------------------------------------- degradation without dying
async def test_flood_falls_back_to_account_free_signals(monkeypatch):
    """A full park must degrade to page+Bot API, not freeze every search."""
    client = mtproto_module.mtproto_client

    async def all_parked(name):
        return MtprotoResult("flood", "90")

    monkeypatch.setattr(client, "resolve_username", all_parked, raising=False)
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

    monkeypatch.setattr(client, "resolve_username", all_parked, raising=False)
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


async def test_pool_scales_the_shared_pace(monkeypatch):
    """N sessions may carry N times the resolves at the same per-account rate,
    with a safety margin away from the escalation threshold."""
    client = mtproto_module.mtproto_client

    async def fine(name):
        return MtprotoResult("not_occupied")

    monkeypatch.setattr(client, "resolve_username", fine, raising=False)
    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "_client", FakeClient(lambda r: _occupied_response()), raising=False)
    monkeypatch.setattr(
        client, "_bot_clients",
        [
            _session("a", FakeClient(lambda r: _occupied_response())),
            _session("b", FakeClient(lambda r: _occupied_response())),
            _session("c", FakeClient(lambda r: _occupied_response())),
        ],
        raising=False,
    )
    assert client.bot_session_count == 4
    monkeypatch.setattr(settings, "request_delay", 3.0)

    limiter = RateLimiter(min_interval=3.0)
    checker = UsernameChecker(
        cache=None, bot=None, rate_limiter=limiter,
        page_probe=FakePageProbe(state="unknown"),
    )
    await checker.check_free_candidate("whatever")

    # 3.0s per account, divided by 4 sessions, times the 1.5x safety margin.
    assert limiter.min_interval == pytest.approx(3.0 * 1.5 / 4)


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
