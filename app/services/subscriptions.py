"""The list of subscriptions a user must join before using the bot.

The gate used to have exactly two hard-coded slots - one channel and one chat.
A deployment can now require any number, described by a JSON list in
``REQUIRED_SUBSCRIPTIONS``. When that is empty the legacy channel/chat pair is
used, so an existing ``.env`` keeps working with no changes.

A subscription is "joined" when Telegram's ``getChatMember`` says so - never
because a button was pressed. The button only asks Telegram again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.i18n import t
from app.services.runtime_config import runtime


@dataclass(frozen=True)
class RequiredSub:
    """One channel/chat the user has to join."""

    key: str
    chat_id: int = 0
    username: str = ""
    invite_url: str = ""
    # A literal title from config, or an i18n key (used by the legacy fallback).
    label: str | None = None
    label_key: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.chat_id or self.username)


def _parse(raw: str) -> list[RequiredSub]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    subs: list[RequiredSub] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        try:
            chat_id = int(item.get("id") or item.get("chat_id") or 0)
        except (TypeError, ValueError):
            chat_id = 0
        username = str(item.get("username") or "").lstrip("@")
        invite = str(item.get("invite_url") or item.get("invite") or "")
        if not (chat_id or username or invite):
            continue
        label = str(item.get("title") or "").strip() or None
        subs.append(
            RequiredSub(
                key=str(item.get("key") or f"sub{index}"),
                chat_id=chat_id,
                username=username,
                invite_url=invite,
                label=label,
            )
        )
    return subs


def _from_legacy() -> list[RequiredSub]:
    """Build the list from the old REQUIRED_CHANNEL_* / REQUIRED_CHAT_* pair."""
    subs: list[RequiredSub] = []
    if runtime.channel_configured:
        subs.append(
            RequiredSub(
                key="channel",
                chat_id=runtime.required_channel_id,
                username=runtime.required_channel_username.lstrip("@"),
                invite_url=runtime.required_channel_invite_url,
                label_key="gate.channel.name",
            )
        )
    if runtime.chat_configured:
        subs.append(
            RequiredSub(
                key="chat",
                chat_id=runtime.required_chat_id,
                username=runtime.required_chat_username.lstrip("@"),
                invite_url=runtime.required_chat_invite_url,
                label_key="gate.chat.name",
            )
        )
    return subs


def required_subs() -> list[RequiredSub]:
    """Every required subscription, in display order."""
    return _parse(runtime.required_subscriptions) or _from_legacy()


def find_sub(key: str) -> RequiredSub | None:
    for sub in required_subs():
        if sub.key == key:
            return sub
    return None


def sub_label(lang: str, sub: RequiredSub, index: int = 1) -> str:
    """A human title for one subscription, localised where possible."""
    if sub.label:
        return sub.label
    if sub.label_key:
        return t(lang, sub.label_key)
    return t(lang, "gate.subs.generic", n=index)
