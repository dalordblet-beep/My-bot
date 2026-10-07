"""End-to-end flow tests through the real dispatcher.

These exercise the actual routers, middlewares, keyboards and the access gate
using a fake Telegram session - no network, no token.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatMemberStatus

from app.config import settings
from app.database import repository as repo
from app.services.captcha import CaptchaService
from app.telegram import username_checker as uc_module
from tests.mock_telegram import (
    MockTelegramSession,
    make_update_callback,
    make_update_message,
)

NEW_USER = 1001
OTHER_USER = 2002
ADMIN_USER = 3003
CHANNEL = "@test_channel"
CHAT = "@test_chat"


async def feed(dp: Dispatcher, bot: Bot, update):
    return await dp.feed_update(bot, update)


def subscribe(mock: MockTelegramSession, user_id: int) -> None:
    mock.memberships[(CHANNEL, user_id)] = ChatMemberStatus.MEMBER
    mock.memberships[(CHAT, user_id)] = ChatMemberStatus.MEMBER


async def set_language(session, user_id: int, code: str = "en") -> None:
    user, _ = await repo.get_or_create_user(session, user_id, username=f"user{user_id}")
    await repo.update_user_settings(session, user.id, language=code)
    await session.commit()


async def start_gated(
    dispatcher, bot, mock: MockTelegramSession, session, user_id: int, message_id: int = 1
):
    """Pick a language, then run /start so the captcha is the first screen."""
    await set_language(session, user_id, "en")
    mock.reset()
    await feed(dispatcher, bot, make_update_message(user_id, "/start", message_id=message_id))


async def grant_full_access(session, mock: MockTelegramSession, user_id: int, privilege=None):
    subscribe(mock, user_id)
    user, _ = await repo.get_or_create_user(session, user_id, username=f"user{user_id}")
    await repo.update_user_settings(session, user.id, language="en")
    await repo.set_captcha_verified(session, user)
    await repo.set_channel_verified(session, user)
    await repo.set_chat_verified(session, user)
    if privilege is not None:
        await repo.set_privilege(session, user, privilege)
    await session.commit()
    return user


# --------------------------------------------------------------------------- language
async def test_language_is_asked_first(dispatcher, bot, mock_session, session):
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/start", message_id=1))
    text = mock_session.last_sent_text()
    assert "CHOOSE YOUR LANGUAGE" in text
    assert "SECURITY CHECK" not in text


async def test_language_picker_blocks_other_actions(dispatcher, bot, mock_session, session):
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:basic"))
    visible = mock_session.last_edited_text() or mock_session.last_sent_text()
    assert "CHOOSE YOUR LANGUAGE" in visible
    assert "SECURITY CHECK" not in visible


async def test_russian_localisation(dispatcher, bot, mock_session, session):
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/start", message_id=1))
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "lang:ru"))

    # After picking Russian the captcha must be Russian.
    text = mock_session.last_edited_text()
    assert "\u041f\u0420\u041e\u0412\u0415\u0420\u041a\u0410 \u0411\u0415\u0417\u041e\u041f\u0410\u0421\u041d\u041e\u0421\u0422\u0418" in text

    user = await repo.get_user_by_telegram_id(session, NEW_USER)
    row = await repo.get_user_settings(session, user.id)
    assert row.language == "ru"


async def test_settings_language_switch_changes_everything(
    dispatcher, bot, mock_session, session
):
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:settings"))
    assert "SETTINGS" in mock_session.last_edited_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "set:lang:ru"))
    assert "\u041d\u0410\u0421\u0422\u0420\u041e\u0419\u041a\u0418" in mock_session.last_edited_text()

    user = await repo.get_user_by_telegram_id(session, NEW_USER)
    row = await repo.get_user_settings(session, user.id)
    assert row.language == "ru"

    # The main menu must now be Russian too.
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:home"))
    assert "\u0427\u0442\u043e \u0431\u0443\u0434\u0435\u043c \u0434\u0435\u043b\u0430\u0442\u044c" in mock_session.last_edited_text()


# --------------------------------------------------------------------------- onboarding
async def test_start_flow_language_captcha_channel_chat_welcome(
    dispatcher, bot, mock_session, captcha_service: CaptchaService, session
):
    # 0. /start -> language picker
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/start", message_id=1))
    assert "CHOOSE YOUR LANGUAGE" in mock_session.last_sent_text()

    # 1. pick English -> captcha
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "lang:en"))
    assert "SECURITY CHECK" in mock_session.last_edited_text()

    challenge = captcha_service.get(NEW_USER)
    assert challenge is not None

    # 2. wrong answer
    wrong = (challenge.correct_index + 1) % 4
    mock_session.reset()
    await feed(
        dispatcher, bot,
        make_update_callback(NEW_USER, f"captcha:ans:{challenge.session_id}:{wrong}"),
    )
    assert "Wrong answer" in mock_session.last_edited_text()

    # 3. correct answer -> the combined subscriptions screen
    mock_session.reset()
    await feed(
        dispatcher, bot,
        make_update_callback(NEW_USER, f"captcha:ans:{challenge.session_id}:{challenge.correct_index}"),
    )
    text = mock_session.last_edited_text()
    assert "REQUIRED SUBSCRIPTIONS" in text
    # Every required resource is shown at once, with its own join link.
    urls = [
        button.get("url")
        for row in mock_session.edits[-1]["reply_markup"]["inline_keyboard"]
        for button in row
        if button.get("url")
    ]
    assert "https://t.me/test_channel" in urls
    assert "https://t.me/test_chat" in urls

    # 4. verify channel while not subscribed
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "sub:check:channel"))
    assert "Not confirmed yet" in mock_session.last_edited_text()

    # 5. subscribe, verify channel -> channel done, chat still pending
    mock_session.memberships[(CHANNEL, NEW_USER)] = ChatMemberStatus.MEMBER
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "sub:check:channel"))
    text = mock_session.last_edited_text()
    assert "REQUIRED SUBSCRIPTIONS" in text
    assert "\u2705" in text

    # 6. verify chat while not a member
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "sub:check:chat"))
    assert "Not confirmed yet" in mock_session.last_edited_text()

    # 7. join, verify chat -> welcome
    mock_session.memberships[(CHAT, NEW_USER)] = ChatMemberStatus.MEMBER
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "sub:check:chat"))
    assert "WELCOME" in mock_session.last_edited_text()
    assert mock_session.last_keyboard_rows() == 5

    user = await repo.get_user_by_telegram_id(session, NEW_USER)
    assert user.captcha_verified_at is not None
    assert user.channel_verified_at is not None
    assert user.chat_verified_at is not None


async def test_admin_also_passes_language_captcha_and_subscriptions(
    dispatcher, bot, mock_session, session, monkeypatch
):
    """Administrators get the full onboarding - no bypass."""
    from app.utils.enums import Privilege

    monkeypatch.setattr(settings, "admin_ids", str(ADMIN_USER))
    user, _ = await repo.get_or_create_user(session, ADMIN_USER, username="boss")
    await repo.set_privilege(session, user, Privilege.ADMIN)
    await repo.update_user_settings(session, user.id, language="en")
    await session.commit()

    # No memberships -> the gate must apply even though this user is an admin.
    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "/start", message_id=1))
    assert "SECURITY CHECK" in mock_session.last_sent_text()

    # /admin is gated too while onboarding is incomplete.
    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "/admin", message_id=2))
    assert "ADMIN PANEL" not in mock_session.last_sent_text()

    captcha = dispatcher.workflow_data["captcha_service"]
    pending = captcha.get(ADMIN_USER)
    mock_session.reset()
    await feed(
        dispatcher, bot,
        make_update_callback(ADMIN_USER, f"captcha:ans:{pending.session_id}:{pending.correct_index}"),
    )
    assert "REQUIRED SUBSCRIPTIONS" in mock_session.last_edited_text()

    subscribe(mock_session, ADMIN_USER)
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, "sub:check:channel"))
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, "sub:check:chat"))
    assert "WELCOME" in mock_session.last_edited_text()

    # Now /admin works, and the menu carries the admin row.
    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "/admin", message_id=3))
    assert "ADMIN PANEL" in mock_session.last_sent_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "/start", message_id=4))
    assert mock_session.last_keyboard_rows() == 6


async def test_captcha_exhaustion_requires_new_check(
    dispatcher, bot, mock_session, captcha_service: CaptchaService, session
):
    await start_gated(dispatcher, bot, mock_session, session, NEW_USER)
    challenge = captcha_service.get(NEW_USER)
    wrong = (challenge.correct_index + 1) % 4

    for _ in range(settings.max_captcha_attempts):
        mock_session.reset()
        await feed(
            dispatcher, bot,
            make_update_callback(NEW_USER, f"captcha:ans:{challenge.session_id}:{wrong}"),
        )

    assert "Too many attempts" in mock_session.last_edited_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "captcha:retry"))
    assert "SECURITY CHECK" in mock_session.last_edited_text()
    new_challenge = captcha_service.get(NEW_USER)
    assert new_challenge.session_id != challenge.session_id


async def test_captcha_is_not_asked_again(dispatcher, bot, mock_session, session):
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/start", message_id=2))

    assert "WELCOME" in mock_session.last_sent_text()
    assert "SECURITY CHECK" not in mock_session.all_text()


# --------------------------------------------------------------------------- access guard
async def test_guard_blocks_direct_callback_for_ungated_user(
    dispatcher, bot, mock_session, session
):
    await set_language(session, OTHER_USER)
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(OTHER_USER, "menu:basic"))
    assert "SECURITY CHECK" in mock_session.last_edited_text()


async def test_guard_blocks_command_for_ungated_user(dispatcher, bot, mock_session, session):
    await set_language(session, OTHER_USER)
    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(OTHER_USER, "/check moged", message_id=3))
    assert "SECURITY CHECK" in mock_session.last_sent_text()


async def test_guard_blocks_stale_feature_button(dispatcher, bot, mock_session, session):
    await set_language(session, OTHER_USER)
    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(OTHER_USER, "menu:history"))
    assert "SECURITY CHECK" in mock_session.last_edited_text()


async def test_banned_user_is_blocked(dispatcher, bot, mock_session, session):
    user = await grant_full_access(session, mock_session, NEW_USER)
    await repo.ban_user(session, user, reason="spam", admin_id=ADMIN_USER)
    await session.commit()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/start", message_id=4))

    assert "ACCESS BLOCKED" in mock_session.last_sent_text()
    assert "spam" in mock_session.last_sent_text()


async def test_temporarily_restricted_user_is_blocked(dispatcher, bot, mock_session, session):
    user = await grant_full_access(session, mock_session, NEW_USER)
    await repo.restrict_user(session, user, seconds=3600, reason="cooldown", admin_id=ADMIN_USER)
    await session.commit()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/start", message_id=5))

    text = mock_session.last_sent_text()
    assert "ACCESS RESTRICTED" in text
    assert "cooldown" in text


# --------------------------------------------------------------------------- checking
@pytest.fixture(autouse=True)
def fast_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


async def test_basic_check_reports_available_when_opted_in(
    dispatcher, bot, mock_session, session, monkeypatch
):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:basic"))
    assert "Send a username to check" in mock_session.last_sent_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(NEW_USER, "@freename", message_id=6))
    assert "Available" in mock_session.last_edited_text()


async def test_basic_check_is_unknown_without_mtproto(dispatcher, bot, mock_session, session):
    await grant_full_access(session, mock_session, NEW_USER)

    await feed(dispatcher, bot, make_update_message(NEW_USER, "/check @somebody", message_id=7))

    text = mock_session.last_edited_text()
    assert "Unknown" in text
    assert "Available" not in text


async def test_occupied_username_via_bot_api(dispatcher, bot, mock_session, session):
    from aiogram.enums import ChatType
    from aiogram.types import Chat

    await grant_full_access(session, mock_session, NEW_USER)
    mock_session.chats["@takenname"] = Chat(
        id=-100777, type=ChatType.CHANNEL, title="Taken Channel"
    )

    await feed(dispatcher, bot, make_update_message(NEW_USER, "/check @takenname", message_id=8))

    text = mock_session.last_edited_text()
    assert "Occupied" in text
    assert "channel" in text


async def test_invalid_username_is_rejected_without_api_call(
    dispatcher, bot, mock_session, session
):
    await grant_full_access(session, mock_session, NEW_USER)
    mock_session.reset()

    await feed(dispatcher, bot, make_update_message(NEW_USER, "/check @ab", message_id=9))

    text = mock_session.last_edited_text()
    assert "Invalid" in text
    assert not [call for call in mock_session.calls if call.name == "GetChat"]


async def test_all_in_one_shows_both_sections(dispatcher, bot, mock_session, session, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:allinone"))
    await feed(dispatcher, bot, make_update_message(NEW_USER, "@combined", message_id=10))

    text = mock_session.last_edited_text()
    assert "BASIC" in text
    assert "COLLECTIBLE" in text


async def test_collectible_engine_reports_disabled(dispatcher, bot, mock_session, session):
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:collectible"))
    await feed(dispatcher, bot, make_update_message(NEW_USER, "@rarename", message_id=11))

    text = mock_session.last_edited_text()
    assert "COLLECTIBLE" in text
    # The user must get a plain, actionable message - never internal plumbing.
    assert "MTProto" not in text
    assert "login" not in text.lower()
    assert "try again" in text.lower()


# --------------------------------------------------------------------------- search
async def test_username_search_scan(dispatcher, bot, mock_session, session, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:search"))
    assert "USERNAME SEARCH" in mock_session.last_sent_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(NEW_USER, "moged", message_id=12))
    assert "HOW MANY" in mock_session.last_sent_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "scan:count:10"))

    assert "SCAN COMPLETE" in mock_session.last_edited_text()
    assert "Available: 10" in mock_session.last_edited_text()


async def test_scan_count_is_capped_by_privilege(
    dispatcher, bot, mock_session, session, monkeypatch
):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await grant_full_access(session, mock_session, NEW_USER)  # FREE -> cap 50

    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:search"))
    await feed(dispatcher, bot, make_update_message(NEW_USER, "moged", message_id=13))

    keyboard = mock_session.messages[-1]["reply_markup"]
    labels = [button["text"] for button in keyboard["inline_keyboard"][0]]
    assert [text.split(" ", 1)[-1] for text in labels] == ["10", "50"]


# --------------------------------------------------------------------------- history / settings
async def test_history_lists_previous_search(
    dispatcher, bot, mock_session, session, monkeypatch
):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await grant_full_access(session, mock_session, NEW_USER)

    await feed(dispatcher, bot, make_update_message(NEW_USER, "/check @rememberme", message_id=14))

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:history"))

    assert "YOUR HISTORY" in mock_session.last_edited_text()
    assert "rememberme" in mock_session.last_edited_text()


async def test_settings_update(dispatcher, bot, mock_session, session):
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "menu:settings"))
    assert "SETTINGS" in mock_session.last_edited_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "set:len:10"))
    assert "SETTINGS" in mock_session.last_edited_text()

    user = await repo.get_user_by_telegram_id(session, NEW_USER)
    row = await repo.get_user_settings(session, user.id)
    assert row.search_length == 10

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(NEW_USER, "set:dig:1"))
    # Capture the pk before expiring - touching an expired attribute would
    # trigger lazy IO outside the greenlet.
    user_id = user.id
    session.expire_all()
    row = await repo.get_user_settings(session, user_id)
    assert row.search_digits is True


# --------------------------------------------------------------------------- admin
async def test_admin_command_denied_for_regular_user(dispatcher, bot, mock_session, session):
    await grant_full_access(session, mock_session, NEW_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(NEW_USER, "/admin", message_id=15))

    assert "restricted" in mock_session.last_sent_text().lower()


async def test_admin_callback_denied_for_regular_user(dispatcher, bot, mock_session, session):
    await grant_full_access(session, mock_session, OTHER_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(OTHER_USER, "adm:root"))

    assert "ADMIN PANEL" not in mock_session.all_text()
    assert any(
        "authorized" in str(answer.get("text", "")).lower() for answer in mock_session.answers
    )


async def test_admin_panel_opens_for_admin(dispatcher, bot, mock_session, session):
    from app.utils.enums import Privilege

    await grant_full_access(session, mock_session, ADMIN_USER, privilege=Privilege.ADMIN)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "/admin", message_id=16))

    assert "ADMIN PANEL" in mock_session.last_sent_text()


async def test_admin_ban_flow_blocks_target(dispatcher, bot, mock_session, session):
    from app.utils.enums import Privilege

    await grant_full_access(session, mock_session, ADMIN_USER, privilege=Privilege.ADMIN)
    await grant_full_access(session, mock_session, OTHER_USER)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, f"adm:user:{OTHER_USER}"))
    assert "USER PROFILE" in mock_session.last_edited_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, f"adm:ban:{OTHER_USER}"))
    assert "BLOCK USER" in mock_session.last_edited_text()

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "abuse", message_id=17))
    assert "Blocked" in mock_session.last_sent_text()

    session.expire_all()
    refreshed = await repo.get_user_by_telegram_id(session, OTHER_USER)
    assert refreshed.is_banned is True
    assert refreshed.ban_reason == "abuse"

    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(OTHER_USER, "/start", message_id=18))
    assert "ACCESS BLOCKED" in mock_session.last_sent_text()

    actions = await repo.list_admin_actions_for_user(session, OTHER_USER)
    assert any(action.action == "ban" for action in actions)


async def test_admin_statistics_show_real_numbers(dispatcher, bot, mock_session, session):
    from app.utils.enums import Privilege

    await grant_full_access(session, mock_session, ADMIN_USER, privilege=Privilege.ADMIN)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, "adm:stats"))

    text = mock_session.last_edited_text()
    assert "STATISTICS" in text
    assert "Users:" in text


async def test_admin_system_screen(dispatcher, bot, mock_session, session):
    from app.utils.enums import Privilege

    await grant_full_access(session, mock_session, ADMIN_USER, privilege=Privilege.ADMIN)

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, "adm:system"))

    text = mock_session.last_edited_text()
    assert "SYSTEM" in text
    assert "Redis" in text


async def test_admin_can_change_bot_setting(dispatcher, bot, mock_session, session):
    from app.services.runtime_config import runtime
    from app.utils.enums import Privilege

    await grant_full_access(session, mock_session, ADMIN_USER, privilege=Privilege.ADMIN)

    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, "adm:set:cache_ttl"))
    mock_session.reset()
    await feed(dispatcher, bot, make_update_message(ADMIN_USER, "999", message_id=19))

    assert runtime.cache_ttl == 999
    stored = await repo.get_bot_setting(session, "cache_ttl")
    assert stored == "999"


async def test_privilege_grant_changes_permissions(
    dispatcher, bot, mock_session, session, monkeypatch
):
    from app.utils.enums import Privilege

    monkeypatch.setattr(settings, "max_search_results", 500)
    await grant_full_access(session, mock_session, ADMIN_USER, privilege=Privilege.ADMIN)
    await grant_full_access(session, mock_session, OTHER_USER)

    await feed(dispatcher, bot, make_update_callback(ADMIN_USER, f"adm:priv:{OTHER_USER}:VIP"))

    session.expire_all()
    refreshed = await repo.get_user_by_telegram_id(session, OTHER_USER)
    assert refreshed.privilege == Privilege.VIP.value

    mock_session.reset()
    await feed(dispatcher, bot, make_update_callback(OTHER_USER, "menu:search"))
    await feed(dispatcher, bot, make_update_message(OTHER_USER, "moged", message_id=20))
    keyboard = mock_session.messages[-1]["reply_markup"]
    labels = [button["text"] for button in keyboard["inline_keyboard"][0]]
    assert "500" in [text.split(" ", 1)[-1] for text in labels]
