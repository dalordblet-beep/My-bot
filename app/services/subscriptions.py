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


def legacy_subs() -> list[RequiredSub]:
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
    return _parse(runtime.required_subscriptions) or legacy_subs()


def parse_subs(raw: str) -> list[RequiredSub]:
    """Public alias of the JSON parser used by the admin subscription manager."""
    return _parse(raw)


def serialize_subs(subs: list[RequiredSub]) -> str:
    """Turn the managed list back into the JSON stored in runtime config."""
    data: list[dict] = []
    for sub in subs:
        item: dict = {"key": sub.key}
        if sub.chat_id:
            item["id"] = sub.chat_id
        if sub.username:
            item["username"] = sub.username
        if sub.invite_url:
            item["invite_url"] = sub.invite_url
        if sub.label:
            item["title"] = sub.label
        data.append(item)
    return json.dumps(data, ensure_ascii=False)


def list_managed_subs() -> list[RequiredSub]:
    """Only the subscriptions stored in the runtime JSON list (no legacy pair)."""
    return _parse(runtime.required_subscriptions)


def _unique_key(subs: list[RequiredSub], sub: RequiredSub) -> str:
    """Pick a key for ``sub`` that does not collide with an existing one."""
    if sub.key and not any(s.key == sub.key for s in subs):
        return sub.key
    base = sub.username or sub.invite_url or "sub"
    candidate = base
    index = 2
    existing = {s.key for s in subs}
    while candidate in existing:
        candidate = f"{base}{index}"
        index += 1
    return candidate


async def save_managed_subs(session: AsyncSession, subs: list[RequiredSub]) -> None:
    """Persist the managed list and forget cached membership verdicts."""
    from app.services.access import access_guard

    await runtime.set(session, "required_subscriptions", serialize_subs(subs))
    access_guard.invalidate_all()


async def add_subscription(session: AsyncSession, sub: RequiredSub) -> list[RequiredSub]:
    """Append a subscription; returns the resulting managed list."""
    subs = list_managed_subs()
    if any(s.key == sub.key for s in subs):
        sub = RequiredSub(
            key=_unique_key(subs, sub),
            chat_id=sub.chat_id,
            username=sub.username,
            invite_url=sub.invite_url,
            label=sub.label,
            label_key=sub.label_key,
        )
    subs.append(sub)
    await save_managed_subs(session, subs)
    return subs


async def remove_subscription(session: AsyncSession, key: str) -> list[RequiredSub]:
    """Drop the subscription with ``key``; returns the resulting managed list."""
    subs = [s for s in list_managed_subs() if s.key != key]
    await save_managed_subs(session, subs)
    return subs


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
