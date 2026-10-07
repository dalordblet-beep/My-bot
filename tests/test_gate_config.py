"""Access-gate configuration: private channels/chats addressed by id only.

This mirrors a real deployment where the required channel and chat are private,
have no @username, and are referenced by their -100... id plus an explicit
invite link.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.enums import ChatMemberStatus

from app.bot.gate import channel_join_url, chat_join_url
from app.config import settings
from app.telegram.bot_api import build_chat_ref
from tests.mock_telegram import MockTelegramSession, make_update_callback, make_update_message

CHANNEL_ID = -1004317388446
CHAT_ID = -1003617691291
CHANNEL_INVITE = "https://t.me/+d5xXRPj0tRE0ZWIy"
CHAT_INVITE = "https://t.me/+HoM2axfR_2g1OTYy"
USER = 7001


def private_config(monkeypatch) -> None:
    monkeypatch.setattr(settings, "required_channel_id", CHANNEL_ID)
    monkeypatch.setattr(settings, "required_channel_username", "")
    monkeypatch.setattr(settings, "required_channel_invite_url", CHANNEL_INVITE)
    monkeypatch.setattr(settings, "required_chat_id", CHAT_ID)
    monkeypatch.setattr(settings, "required_chat_username", "")
    monkeypatch.setattr(settings, "required_chat_invite_url", CHAT_INVITE)


def test_build_chat_ref_prefers_numeric_id():
    assert build_chat_ref(CHANNEL_ID, "") == CHANNEL_ID
    assert build_chat_ref(0, "somechan") == "@somechan"
    assert build_chat_ref(CHANNEL_ID, "somechan") == CHANNEL_ID


async def test_explicit_invite_link_wins(bot, monkeypatch):
    private_config(monkeypatch)
    assert await channel_join_url(bot) == CHANNEL_INVITE
    assert await chat_join_url(bot) == CHAT_INVITE


async def test_username_used_when_no_invite(bot, monkeypatch):
    monkeypatch.setattr(settings, "required_channel_invite_url", "")
    monkeypatch.setattr(settings, "required_channel_username", "my_chan")
    assert await channel_join_url(bot) == "https://t.me/my_chan"


async def test_no_link_configured_returns_none(bot, monkeypatch):
    monkeypatch.setattr(settings, "required_channel_invite_url", "")
    monkeypatch.setattr(settings, "required_channel_username", "")
    monkeypatch.setattr(settings, "required_channel_id", 0)
    assert await channel_join_url(bot) is None


async def test_private_gate_flow_uses_ids_and_invites(
    dispatcher: Dispatcher, bot: Bot, mock_session: MockTelegramSession, monkeypatch, session
):
    private_config(monkeypatch)

    # Language first, then /start -> captcha
    from app.database import repository as repo

    user, _ = await repo.get_or_create_user(session, USER, username="privateuser")
    await repo.update_user_settings(session, user.id, language="en")
    await session.commit()

    await dispatcher.feed_update(bot, make_update_message(USER, "/start", message_id=1))
    assert "SECURITY CHECK" in mock_session.last_sent_text()

    from app.services.captcha import CaptchaService

    captcha_service: CaptchaService = dispatcher.workflow_data["captcha_service"]
    challenge = captcha_service.get(USER)
    assert challenge is not None

    mock_session.reset()
    await dispatcher.feed_update(
        bot,
        make_update_callback(USER, f"captcha:ans:{challenge.session_id}:{challenge.correct_index}"),
    )

    # The combined subscriptions screen must carry both invite links at once.
    subs_keyboard = mock_session.edits[-1]["reply_markup"]
    subs_urls = [
        button.get("url")
        for row in subs_keyboard["inline_keyboard"]
        for button in row
        if button.get("url")
    ]
    assert CHANNEL_INVITE in subs_urls
    assert CHAT_INVITE in subs_urls

    # Verifying while not subscribed must query the numeric id, not a username.
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "sub:check:channel"))
    assert "Not confirmed yet" in mock_session.last_edited_text()
    assert any(call.payload.get("chat_id") == CHANNEL_ID for call in mock_session.calls if call.name == "GetChatMember")

    # Subscribe -> the channel is marked done; the chat is still pending.
    mock_session.memberships[(str(CHANNEL_ID), USER)] = ChatMemberStatus.MEMBER
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "sub:check:channel"))
    text = mock_session.last_edited_text()
    assert "REQUIRED SUBSCRIPTIONS" in text
    assert "\u2705" in text
    remaining_urls = [
        button.get("url")
        for row in mock_session.edits[-1]["reply_markup"]["inline_keyboard"]
        for button in row
        if button.get("url")
    ]
    assert CHAT_INVITE in remaining_urls

    # Join the chat -> full access.
    mock_session.memberships[(str(CHAT_ID), USER)] = ChatMemberStatus.MEMBER
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "sub:check:chat"))
    assert "WELCOME" in mock_session.last_edited_text()

    from app.database import repository as repo

    user = await repo.get_user_by_telegram_id(session, USER)
    assert user.channel_verified_at is not None
    assert user.chat_verified_at is not None
