"""Shared helpers for keyboards.

Visual rule of the bot: **one colour per screen**. Every action button
renders in the same primary style; icons carry the meaning, not colour. A
muted row (nav, back) uses the neutral default. The three Bot API styles stay
available because the admin theme can remap roles at runtime - but the
out-of-the-box theme maps them all to one.

    primary  blue    everything: navigation, lookups, lists, confirms
    danger   red     unused by default (mapped to primary); admin theme may restore it
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

# role -> Telegram style; mutable so the admin's theme can recolour everything.
_STYLE_BY_NAME = {
    "primary": ButtonStyle.PRIMARY,
    "success": ButtonStyle.SUCCESS,
    "danger": ButtonStyle.DANGER,
    "neutral": None,
}
# The shipped look: success and danger roles also render as primary, so a
# screen never shows blue, green AND red buttons at once - the "rainbow". An
# admin can still split them again via the runtime button theme.
_THEME = {
    "primary": ButtonStyle.PRIMARY,
    "success": ButtonStyle.PRIMARY,
    "danger": ButtonStyle.PRIMARY,
    "neutral": None,
}
_ROLE_OF = {
    ButtonStyle.PRIMARY: "primary",
    ButtonStyle.SUCCESS: "success",
    ButtonStyle.DANGER: "danger",
    None: "neutral",
}


def apply_button_theme(theme: dict | None) -> None:
    """Recolour every button by remapping the three semantic roles.

    ``theme`` is a mapping like ``{"primary": "success"}``; unknown roles or
    values fall back to the default style for that role.
    """
    theme = theme or {}
    for role in ("primary", "success", "danger", "neutral"):
        target = str(theme.get(role, role)).lower()
        _THEME[role] = _STYLE_BY_NAME.get(target, _STYLE_BY_NAME[role])


def btn(text: str, *, icon: str | None = None, style: str | None = None, **kwargs) -> InlineKeyboardButton:
    """Build a colour-coded, icon-carrying inline button."""
    style = _THEME.get(_ROLE_OF.get(style, "neutral"), style)
    custom_id = _e.custom_id(icon) if icon else None
    if custom_id:
        return InlineKeyboardButton(
            text=text, icon_custom_emoji_id=custom_id, style=style, **kwargs
        )
    glyph = _e.plain(icon) if icon else ""
    label = f"{glyph} {text}".strip() if glyph else text
    return InlineKeyboardButton(text=label, style=style, **kwargs)
