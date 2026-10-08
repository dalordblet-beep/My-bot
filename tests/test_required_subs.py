"""Tests for the runtime-editable mandatory subscription manager.

Covers the JSON round-trip, add/remove persistence, duplicate-key handling
and the membership-cache guard that makes a newly-added channel start
blocking existing users on their next interaction.
"""

from __future__ import annotations

import time

import pytest

from app.database import repository as repo
from app.services import subscriptions as subs_mod
from app.services.access import AccessGuard
from app.services.runtime_config import runtime
from app.services.subscriptions import (
    RequiredSub,
    add_subscription,
    list_managed_subs,
    parse_subs,
    remove_subscription,
    serialize_subs,
)
from app.telegram.bot_api import MembershipStatus


def _sub(key: str, chat_id: int = -1001, username: str = "chan") -> RequiredSub:
    return RequiredSub(key=key, chat_id=chat_id, username=username, invite_url="", label="Chan")


@pytest.fixture
def fake_store(monkeypatch):
    """In-memory bot_settings so runtime.set persists without a database."""
    store: dict[str, str] = {}

    async def set_bot_setting(session, key: str, value: str) -> None:
        store[key] = value

    async def all_bot_settings(session) -> dict[str, str]:
        return dict(store)

    monkeypatch.setattr(repo, "set_bot_setting", set_bot_setting)
    monkeypatch.setattr(repo, "all_bot_settings", all_bot_settings)
    runtime._overrides.clear()
    yield store
    runtime._overrides.clear()


def test_parse_serialize_roundtrip() -> None:
    subs = [
        _sub("a"),
        RequiredSub(key="b", chat_id=0, username="x", invite_url="https://t.me/+abc", label="X"),
    ]
    back = parse_subs(serialize_subs(subs))
    assert [s.key for s in back] == ["a", "b"]
    assert back[0].chat_id == -1001 and back[0].username == "chan"
    assert back[1].username == "x" and back[1].invite_url == "https://t.me/+abc"


async def test_add_and_remove(fake_store) -> None:
    await add_subscription(None, _sub("a"))
    assert [s.key for s in list_managed_subs()] == ["a"]

    # A populated cache must be wiped when the required set changes.
    from app.services.access import access_guard

    access_guard._membership_cache["some_user"] = (0, {})
    await add_subscription(None, RequiredSub(key="b", chat_id=-1002, username="chan2"))
    assert "some_user" not in access_guard._membership_cache
    assert [s.key for s in list_managed_subs()] == ["a", "b"]

    await remove_subscription(None, "a")
    assert [s.key for s in list_managed_subs()] == ["b"]


async def test_add_duplicate_gets_unique_key(fake_store) -> None:
    await add_subscription(None, _sub("chan"))
    await add_subscription(None, RequiredSub(key="chan", chat_id=-1009, username="chan"))
    keys = [s.key for s in list_managed_subs()]
    assert len(keys) == 2
    assert keys[0] == "chan"
    assert keys[1] != "chan"


class _FakeMember:
    status = "member"


class _FakeBot:
    async def get_chat_member(self, chat_id, user_id):
        return _FakeMember()


class _FakeSession:
    async def flush(self):
        return None


class _UserStub:
    def __init__(self, tid: int) -> None:
        self.telegram_id = tid
        self.subscriptions_verified: dict = {}


async def test_check_subs_refetches_when_required_keys_change() -> None:
    """A newly added required channel must force a live re-check, not be
    silently trusted (or ignored) from a stale cache entry."""
    guard = AccessGuard()
    sub_a = RequiredSub(key="a", chat_id=-1001, username="a")
    sub_b = RequiredSub(key="b", chat_id=-1002, username="b")

    # Warm the cache with only sub_a joined.
    guard._membership_cache[42] = (time.monotonic(), {"a": True})

    user = _UserStub(42)
    results = await guard._check_subs(_FakeSession(), _FakeBot(), user, [sub_a, sub_b])

    # The new key must be present (re-queried), proving the cache was rejected.
    assert results == {"a": True, "b": True}


async def test_check_subs_uses_cache_when_keys_unchanged() -> None:
    """When the required set is identical, the cached verdict is reused and no
    Telegram call is made."""
    guard = AccessGuard()
    sub_a = RequiredSub(key="a", chat_id=-1001, username="a")

    class _NoCallBot:
        async def get_chat_member(self, chat_id, user_id):
            raise AssertionError("should not be called - cache hit expected")

    guard._membership_cache[7] = (time.monotonic(), {"a": True})
    user = _UserStub(7)
    results = await guard._check_subs(_FakeSession(), _NoCallBot(), user, [sub_a])
    assert results == {"a": True}
