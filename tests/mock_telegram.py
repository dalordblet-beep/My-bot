"""A fake Telegram session for end-to-end testing.

It implements aiogram's ``BaseSession`` interface and answers every Bot API
method locally, so the real dispatcher, middlewares, routers and keyboards can
be exercised without a network or a bot token.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberMember,
    Message,
    Update,
    User as TgUser,
)

BOT_ID = 424242
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def tg_user(user_id: int, username: str = "tester", first_name: str = "Tester") -> TgUser:
    return TgUser(id=user_id, is_bot=False, first_name=first_name, username=username)


def make_message(
    user_id: int,
    text: str | None = None,
    *,
    message_id: int = 1,
    chat_id: int | None = None,
    username: str = "tester",
    first_name: str = "Tester",
) -> Message:
    return Message(
        message_id=message_id,
        date=NOW,
        chat=Chat(id=chat_id if chat_id is not None else user_id, type=ChatType.PRIVATE),
        from_user=tg_user(user_id, username, first_name),
        text=text,
    )


def make_update_message(user_id: int, text: str, *, message_id: int = 1) -> Update:
    return Update(
        update_id=message_id,
        message=make_message(user_id, text, message_id=message_id),
    )


def make_update_callback(
    user_id: int,
    data: str,
    *,
    message_id: int = 10,
    username: str = "tester",
) -> Update:
    message = make_message(user_id, "prev", message_id=message_id, username=username)
    callback = CallbackQuery(
        id=f"cb{message_id}",
        from_user=tg_user(user_id, username),
        chat_instance="chat-instance",
        data=data,
        message=message,
    )
    return Update(update_id=message_id, callback_query=callback)


class RecordedCall:
    __slots__ = ("name", "payload")

    def __init__(self, name: str, payload: dict[str, Any]) -> None:
        self.name = name
        self.payload = payload

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{self.name} {self.payload}>"


class MockTelegramSession(BaseSession):
    """Answers Bot API calls from in-memory state and records everything."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[RecordedCall] = []
        self.messages: list[dict[str, Any]] = []       # send_message payloads
        self.edits: list[dict[str, Any]] = []          # edit_message_text payloads
        self.answers: list[dict[str, Any]] = []        # answer_callback_query payloads
        # (chat_ref, user_id) -> ChatMemberStatus
        self.memberships: Dict[tuple[str, int], ChatMemberStatus] = {}
        # chat_ref -> Chat | None (None means "chat not found")
        self.chats: Dict[str, Chat | None] = {}
        self._message_seq = 1000

    # ------------------------------------------------------------------ session
    async def close(self) -> None:  # pragma: no cover
        return None

    async def stream_content(  # pragma: no cover
        self, url: str, headers=None, timeout: int = 30, chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(
        self, bot: Bot, method: TelegramMethod, timeout: Optional[int] = None
    ) -> Any:
        name = type(method).__name__
        payload = method.model_dump(exclude_none=True)
        self.calls.append(RecordedCall(name, payload))

        if name == "SendMessage":
            self.messages.append(payload)
            return self._message(bot, payload.get("chat_id"), payload.get("text") or "")
        if name == "SendPhoto":
            # Single message carrying the brand photo + the menu caption +
            # the inline keyboard. Mirror SendMessage so tests can read back
            # the caption as ``text`` and the keyboard as ``reply_markup``.
            payload["text"] = payload.get("caption") or ""
            self.messages.append(payload)
            return self._message(bot, payload.get("chat_id"), payload["text"])
        if name == "EditMessageText":
            self.edits.append(payload)
            return self._message(bot, payload.get("chat_id"), payload.get("text") or "")
        if name == "EditMessageMedia":
            # Converting a previous text bubble into the photo+caption menu
            # in place. The caption is what users (and tests) read as text.
            payload["text"] = (payload.get("media") or {}).get("caption") or ""
            self.edits.append(payload)
            return self._message(bot, payload.get("chat_id"), payload["text"])
        if name == "AnswerCallbackQuery":
            self.answers.append(payload)
            return True
        if name == "GetMe":
            return TgUser(id=BOT_ID, is_bot=True, first_name="Scanner", username="test_scanner_bot")
        if name == "GetChatMember":
            return self._chat_member(payload.get("chat_id"), payload.get("user_id"))
        if name == "GetChat":
            return self._get_chat(payload.get("chat_id"), method)
        if name in ("DeleteWebhook", "SetMyCommands", "GetChatMemberCount"):
            return True
        return True

    # ------------------------------------------------------------------ helpers
    def _message(self, bot: Bot, chat_id: Any, text: str) -> Message:
        self._message_seq += 1
        try:
            numeric = int(chat_id)
        except (TypeError, ValueError):
            numeric = BOT_ID
        message = Message(
            message_id=self._message_seq,
            date=NOW,
            chat=Chat(id=numeric, type=ChatType.PRIVATE),
            text=text,
        )
        # Bind the bot so shortcuts such as ``message.edit_text`` work, exactly
        # like a real update does.
        return message.as_(bot)

    def _chat_member(self, chat_id: Any, user_id: int):
        status = self.memberships.get((str(chat_id), user_id), ChatMemberStatus.LEFT)
        user = tg_user(user_id)
        if status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
            return ChatMemberMember(status=ChatMemberStatus.MEMBER, user=user)
        if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            return ChatMemberAdministrator(
                status=ChatMemberStatus.ADMINISTRATOR,
                user=user,
                can_be_edited=False,
                is_anonymous=False,
                can_manage_chat=True,
                can_delete_messages=True,
                can_manage_video_chats=True,
                can_restrict_members=True,
                can_promote_members=True,
                can_change_info=True,
                can_invite_users=True,
            )
        return ChatMemberLeft(status=ChatMemberStatus.LEFT, user=user)

    def _get_chat(self, chat_id: Any, method: TelegramMethod) -> Chat:
        key = str(chat_id)
        if key not in self.chats:
            # Default: unknown public username -> "chat not found".
            raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        chat = self.chats[key]
        if chat is None:
            raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        return chat

    # ------------------------------------------------------------------ asserts
    def last_sent_text(self) -> str:
        return self.messages[-1]["text"] if self.messages else ""

    def last_edited_text(self) -> str:
        return self.edits[-1]["text"] if self.edits else ""

    def last_visible_text(self) -> str:
        """Most recent user-visible text, whether sent or edited."""
        sent = self.messages[-1] if self.messages else None
        edited = self.edits[-1] if self.edits else None
        if sent is None and edited is None:
            return ""
        if edited is None:
            return sent["text"]
        if sent is None:
            return edited["text"]
        return sent["text"]

    def all_text(self) -> str:
        return "\n".join(
            [entry["text"] for entry in self.messages] + [entry["text"] for entry in self.edits]
        )

    def last_keyboard_rows(self) -> int:
        source = self.edits[-1] if self.edits else (self.messages[-1] if self.messages else None)
        if source is None:
            return 0
        markup = source.get("reply_markup")
        if not markup:
            return 0
        if isinstance(markup, dict):
            return len(markup.get("inline_keyboard", []))
        return len(getattr(markup, "inline_keyboard", []) or [])

    def reset(self) -> None:
        self.calls.clear()
        self.messages.clear()
        self.edits.clear()
        self.answers.clear()


class FakePageProbe:
    """Deterministic stand-in for the public t.me preview probe.

    Tests must never touch the real network: the probe's whole job is to answer
    a question the Bot API cannot, so it is stubbed explicitly per test.
    """

    def __init__(self, state: str = "free", title: str | None = None) -> None:
        from app.telegram.public_page import FREE

        self.state = state or FREE
        self.title = title
        self.calls: list[str] = []
        self.closed = False

    async def check(self, username: str):
        from app.telegram.public_page import PublicPageResult

        self.calls.append(username)
        return PublicPageResult(self.state, title=self.title, reason="fake")

    async def close(self) -> None:
        self.closed = True


def make_update_chat_shared(
    user_id: int, chat_id: int, *, message_id: int = 30, username: str = "tester"
) -> Update:
    """A service message carrying the chat the user picked.

    ``username`` matters: the bot treats Telegram as the source of truth for a
    user's username, so this is what the handler will see.
    """
    from aiogram.types import ChatShared

    message = Message(
        message_id=message_id,
        date=NOW,
        chat=Chat(id=user_id, type=ChatType.PRIVATE),
        from_user=tg_user(user_id, username),
        chat_shared=ChatShared(request_id=1, chat_id=chat_id),
    )
    return Update(update_id=message_id, message=message)
