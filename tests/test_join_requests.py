"""A pending join request counts as a subscription.

The channels are private and requests are approved by hand, and approval is not
always immediate. Leaving a user on the gate while their request sits in the
admin's queue punishes them for something that is not their fault - so a pending
request has to pass. The tests here are about that, and about the limits of it:
a request must never be read as "exists" when Telegram could not be asked, and it
must stop counting once it is too old to be believable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram.types import Chat, ChatJoinRequest, User as TgUser

from app.database import repository as repo
from app.database.database import session_scope
from app.database.models import JoinRequest, utcnow
from app.services import subscriptions as subs_module
from app.services.access import access_guard
from app.services.subscriptions import RequiredSub
from app.telegram import mtproto as mtproto_module
from app.telegram.mtproto import MtprotoClient
from app.utils.enums import MembershipStatus
from tests.mock_telegram import MockTelegramSession


CHAT_ID = -1004317388446
USER_ID = 7054502451


# ------------------------------------------------------------------ repository
async def test_a_request_is_remembered_and_matched():
    async with session_scope() as session:
        await repo.record_join_request(session, CHAT_ID, USER_ID)

    async with session_scope() as session:
        assert await repo.has_join_request(session, CHAT_ID, USER_ID, ttl_seconds=3600)
        # A different user or a different chat must not match.
        assert not await repo.has_join_request(session, CHAT_ID, USER_ID + 1, 3600)
        assert not await repo.has_join_request(session, CHAT_ID + 1, USER_ID, 3600)


async def test_re_asking_refreshes_the_request():
    """Telegram re-sends a request when the user asks again - trust restarts."""
    async with session_scope() as session:
        await repo.record_join_request(session, CHAT_ID, USER_ID)
        row = (
            await session.execute(
                __import__("sqlalchemy").select(JoinRequest).where(
                    JoinRequest.chat_id == CHAT_ID, JoinRequest.user_id == USER_ID
                )
            )
        ).scalar_one()
        row.requested_at = utcnow() - timedelta(seconds=7200)

    async with session_scope() as session:
        assert not await repo.has_join_request(session, CHAT_ID, USER_ID, 3600)
        await repo.record_join_request(session, CHAT_ID, USER_ID)

    async with session_scope() as session:
        assert await repo.has_join_request(session, CHAT_ID, USER_ID, 3600)


async def test_an_old_request_stops_counting_and_is_pruned():
    """A request that was never approved (or was declined) must not last for ever."""
    async with session_scope() as session:
        await repo.record_join_request(session, CHAT_ID, USER_ID)
        row = (
            await session.execute(
                __import__("sqlalchemy").select(JoinRequest).where(
                    JoinRequest.chat_id == CHAT_ID, JoinRequest.user_id == USER_ID
                )
            )
        ).scalar_one()
        row.requested_at = utcnow() - timedelta(seconds=200_000)

    async with session_scope() as session:
        assert not await repo.has_join_request(session, CHAT_ID, USER_ID, 3600)
        removed = await repo.prune_join_requests(session, older_than_seconds=86400)
    assert removed == 1


# ---------------------------------------------------------------- the queue read
async def test_queue_read_needs_a_user_session_and_never_guesses():
    """``messages.getChatInviteImporters`` is bot-forbidden, so without a user
    session the answer is "unknown" - never a silent "no request"."""
    client = MtprotoClient()
    client._user_clients = []
    assert await client.join_request_pending(CHAT_ID, USER_ID) is None


async def test_queue_read_finds_the_user(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "request_delay", 0.0)

    class FailingClient:
        async def get_input_entity(self, chat_id):
            raise AssertionError("must not be reached")

    class QueueClient:
        def __init__(self, ids):
            self._ids = ids

        async def get_input_entity(self, chat_id):
            return ("peer", chat_id)

        async def __call__(self, request):
            assert getattr(request, "requested", None) is True
            importers = [type("I", (), {"user_id": uid})() for uid in self._ids]
            return type("R", (), {"importers": importers})()

    client = MtprotoClient()
    client._user_clients = [
        {"name": "u", "client": QueueClient([1, 2, USER_ID]), "ready": True, "cooldown_until": 0.0}
    ]
    assert await client.join_request_pending(CHAT_ID, USER_ID) is True

    client._user_clients = [
        {"name": "u", "client": QueueClient([1, 2]), "ready": True, "cooldown_until": 0.0}
    ]
    assert await client.join_request_pending(CHAT_ID, USER_ID) is False

    # An error (not an administrator, wrong id) must not be read as "no request".
    client._user_clients = [
        {"name": "u", "client": FailingClient(), "ready": True, "cooldown_until": 0.0}
    ]
    assert await client.join_request_pending(CHAT_ID, USER_ID) is None


# ------------------------------------------------------------------- the update
async def test_join_request_update_is_remembered_for_a_required_chat(
    session, monkeypatch
):
    from app.bot.handlers import subscription as handler_module

    monkeypatch.setattr(
        handler_module, "required_subs", lambda: [RequiredSub(key="channel", chat_id=CHAT_ID)]
    )

    event = ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="channel", title="Main"),
        from_user=TgUser(id=USER_ID, is_bot=False, first_name="New"),
        user_chat_id=USER_ID,
        date=datetime(2026, 1, 1),
    )
    await handler_module.on_join_request(event, session)
    await session.commit()

    async with session_scope() as check:
        assert await repo.has_join_request(check, CHAT_ID, USER_ID, ttl_seconds=3600)


async def test_join_request_update_ignores_unrelated_chats(session, monkeypatch):
    from app.bot.handlers import subscription as handler_module

    monkeypatch.setattr(
        handler_module, "required_subs", lambda: [RequiredSub(key="channel", chat_id=CHAT_ID)]
    )

    event = ChatJoinRequest(
        chat=Chat(id=-1009999999999, type="channel", title="Other"),
        from_user=TgUser(id=USER_ID, is_bot=False, first_name="New"),
        user_chat_id=USER_ID,
        date=datetime(2026, 1, 1),
    )
    await handler_module.on_join_request(event, session)
    await session.commit()

    async with session_scope() as check:
        assert not await repo.has_join_request(check, -1009999999999, USER_ID, 3600)


# --------------------------------------------------------------------- the gate
async def test_the_gate_lets_in_a_user_whose_request_is_pending(session, bot, monkeypatch):
    """The whole point: not a member yet, but the request is in - let them in."""
    sub = RequiredSub(key="channel", chat_id=CHAT_ID)
    monkeypatch.setattr(subs_module, "required_subs", lambda: [sub])
    monkeypatch.setattr("app.services.access.required_subs", lambda: [sub])

    async def not_a_member(bot_, ref, user_id):
        return MembershipStatus.LEFT

    monkeypatch.setattr("app.services.access.get_membership", not_a_member)

    async def no_queue(session_, bot_, s, user_):
        return True

    monkeypatch.setattr(access_guard, "join_request_pending", no_queue)

    user, _ = await repo.get_or_create_user(session, USER_ID, username="pending")
    await session.commit()

    state = await access_guard.evaluate(session, bot, user, live_membership=True)

    assert state.subs_ok is True
    assert state.pending_subs == []


async def test_the_gate_still_blocks_when_there_is_no_request(session, bot, monkeypatch):
    sub = RequiredSub(key="channel", chat_id=CHAT_ID)
    monkeypatch.setattr("app.services.access.required_subs", lambda: [sub])

    async def not_a_member(bot_, ref, user_id):
        return MembershipStatus.LEFT

    monkeypatch.setattr("app.services.access.get_membership", not_a_member)

    async def no_request(session_, bot_, s, user_):
        return False

    monkeypatch.setattr(access_guard, "join_request_pending", no_request)

    user, _ = await repo.get_or_create_user(session, USER_ID + 5, username="stranger")
    await session.commit()

    state = await access_guard.evaluate(session, bot, user, live_membership=True)

    assert state.subs_ok is False
    assert [s.key for s in state.pending_subs] == ["channel"]


async def test_a_remembered_request_is_trusted_without_asking_the_queue(
    session, bot, monkeypatch
):
    """Once Telegram has told the bot about the request, the next check is free.

    The queue read costs a call on the user session, so a request the bot was
    already told about must not be re-queried every time the gate runs.
    """
    from app.telegram.mtproto import mtproto_client

    sub = RequiredSub(key="channel", chat_id=CHAT_ID)
    monkeypatch.setattr("app.services.access.required_subs", lambda: [sub])

    async def not_a_member(bot_, ref, user_id):
        return MembershipStatus.LEFT

    monkeypatch.setattr("app.services.access.get_membership", not_a_member)

    asked = {"queue": 0}

    async def queue(chat_id, user_id):
        asked["queue"] += 1
        return True

    monkeypatch.setattr(mtproto_client, "join_request_pending", queue)

    user, _ = await repo.get_or_create_user(session, USER_ID + 7, username="pending2")
    await session.commit()

    first = await access_guard.evaluate(session, bot, user, live_membership=True)
    assert first.subs_ok is True
    assert asked["queue"] == 1

    access_guard.invalidate(user.telegram_id)
    second = await access_guard.evaluate(session, bot, user, live_membership=True)
    assert second.subs_ok is True
    assert asked["queue"] == 1, "a remembered request must not be re-queried"
