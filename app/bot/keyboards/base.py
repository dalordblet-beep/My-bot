"""Shared helpers for keyboards.

Button colour IS supported by the Bot API - ``InlineKeyboardButton.style``
accepts exactly three values, verified against Telegram's servers:

    primary  blue    main navigation, lookups, lists
    success  green   positive / safe / confirm
    danger   red     destructive, or the flagship action
    None     neutral default styling (back, settings, history)

(aiogram also exposes ``ButtonStyle.LINK``, but Telegram rejects it for
InlineKeyboardButton - verified. Do not use it here.)

Personality is carried by a per-action emoji icon. If a real custom-emoji id is
configured for that icon in ``CUSTOM_EMOJI_IDS``, it is passed through
``icon_custom_emoji_id`` instead and the Unicode prefix is dropped, so the
button is never double-iconed.
"""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton

from app.services.emoji import emoji as _e

PRIMARY = ButtonStyle.PRIMARY
SUCCESS = ButtonStyle.SUCCESS
DANGER = ButtonStyle.DANGER
NEUTRAL = None


def btn(text: str, *, icon: str | None = None, style: str | None = None, **kwargs) -> InlineKeyboardButton:
    """Build a colour-coded, icon-carrying inline button."""
    custom_id = _e.custom_id(icon) if icon else None
    if custom_id:
        return InlineKeyboardButton(
            text=text, icon_custom_emoji_id=custom_id, style=style, **kwargs
        )
    glyph = _e.plain(icon) if icon else ""
    label = f"{glyph} {text}".strip() if glyph else text
    return InlineKeyboardButton(text=label, style=style, **kwargs)
