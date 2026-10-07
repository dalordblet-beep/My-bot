"""Thin Bot API helpers used for membership checks and the fallback check.

Everything here uses the official Bot API through aiogram. Failures are
translated into explicit states, never into optimistic guesses.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.utils.enums import MembershipStatus
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

_MEMBER_STATUS_MAP = {
    "creator": MembershipStatus.CREATOR,
    "administrator": MembershipStatus.ADMINISTRATOR,
    "member": MembershipStatus.MEMBER,
    "restricted": MembershipStatus.RESTRICTED,
    "left": MembershipStatus.LEFT,
    "kicked": MembershipStatus.KICKED,
}


class ChatLookupResult:
    __slots__ = ("found", "chat_id", "chat_type", "title", "reason")

    def __init__(
        self,
        found: bool,
        chat_id: int | None = None,
        chat_type: str | None = None,
        title: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.found = found
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.title = title
        self.reason = reason


async def get_membership(bot: Bot, chat_ref: int | str, user_id: int) -> MembershipStatus:
    """Resolve a user's membership status in a channel/chat.

    Returns ``UNKNOWN`` when Telegram refuses to answer (bot not an admin,
    wrong chat id, network issue) - the caller must treat that as "not proven".
    """
    try:
        member = await bot.get_chat_member(chat_id=chat_ref, user_id=user_id)
    except TelegramRetryAfter as exc:
        logger.warning("get_chat_member flood wait %ss for %s", exc.retry_after, chat_ref)
        return MembershipStatus.UNKNOWN
    except TelegramBadRequest as exc:
        # "user not found" / "chat not found" / "member list is inaccessible"
        logger.debug("get_chat_member bad request for %s: %s", chat_ref, exc.message)
        return MembershipStatus.UNKNOWN
    except TelegramForbiddenError:
        logger.warning("bot is not a member/admin of %s", chat_ref)
        return MembershipStatus.UNKNOWN
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("get_chat_member failed for %s: %s", chat_ref, exc)
        return MembershipStatus.UNKNOWN

    status = getattr(member, "status", None)
    if hasattr(status, "value"):
        status = status.value
    return _MEMBER_STATUS_MAP.get(str(status), MembershipStatus.UNKNOWN)


async def lookup_chat(bot: Bot, chat_ref: int | str) -> ChatLookupResult:
    """Try to resolve a public chat/username via the Bot API."""
    try:
        chat = await bot.get_chat(chat_id=chat_ref)
    except TelegramRetryAfter:
        return ChatLookupResult(False, reason="flood_wait")
    except TelegramBadRequest as exc:
        message = (exc.message or "").lower()
        # Only the exact "chat not found" answer is a not-found signal. Matching
        # a bare "not found" would swallow "user not found", "message not found"
        # and similar, turning real errors into a free-username claim.
        if "chat not found" in message:
            return ChatLookupResult(False, reason="not_found")
        return ChatLookupResult(False, reason="bad_request")
    except TelegramForbiddenError:
        return ChatLookupResult(False, reason="forbidden")
    except Exception as exc:  # pragma: no cover
        logger.debug("lookup_chat failed for %s: %s", chat_ref, exc)
        return ChatLookupResult(False, reason="error")

    chat_type = getattr(chat, "type", None)
    if hasattr(chat_type, "value"):
        chat_type = chat_type.value
    return ChatLookupResult(
        True,
        chat_id=getattr(chat, "id", None),
        chat_type=str(chat_type) if chat_type else None,
        title=getattr(chat, "title", None) or getattr(chat, "full_name", None),
    )


async def invite_link(bot: Bot, chat_ref: int | str) -> str | None:
    try:
        chat = await bot.get_chat(chat_id=chat_ref)
    except Exception:
        return None
    if getattr(chat, "invite_link", None):
        return chat.invite_link
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}"
    return None


def build_chat_ref(chat_id: int, username: str) -> int | str:
    """Prefer the numeric id (works for private chats) but fall back to @name."""
    if chat_id:
        return chat_id
    return f"@{username.lstrip('@')}" if username else ""


def resolve_bot_username(chat: Any) -> str | None:
    return getattr(chat, "username", None)
