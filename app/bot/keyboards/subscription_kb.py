"""Channel / chat subscription keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.base import NEUTRAL, PRIMARY, SUCCESS, btn
from app.services.i18n import t
from app.services.subscriptions import RequiredSub, sub_label


def _join_button(label: str, icon: str, url: str | None, style) -> InlineKeyboardButton | None:
    if not url:
        return None
    return btn(label, icon=icon, style=style, url=url)


def subscriptions_keyboard(
    lang: str, items: list[tuple[RequiredSub, bool, str | None]]
) -> InlineKeyboardMarkup:
    """One row per required subscription: join it, then confirm.

    ``items`` is a list of ``(subscription, verified, join_url)``. Each row has
    a URL button to open the channel and a "I subscribed" button that makes the
    bot ask Telegram whether the user is really in - the click itself is never
    trusted.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for index, (sub, verified, url) in enumerate(items, start=1):
        row: list[InlineKeyboardButton] = []
        join = _join_button(
            f"{t(lang, 'btn.subscribe')}: {sub_label(lang, sub, index)}",
            "satellite", url, PRIMARY,
        )
        if join is not None:
            row.append(join)
        row.append(
            btn(
                t(lang, "btn.subscribed"),
                icon="check",
                style=SUCCESS if verified else NEUTRAL,
                callback_data=f"{cb.SUB_CHECK_PREFIX}:{sub.key}",
            )
        )
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def channel_keyboard(lang: str, join_url: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    join = _join_button(t(lang, "btn.subscribe"), "satellite", join_url, PRIMARY)
    if join is not None:
        rows.append([join])
    rows.append(
        [btn(t(lang, "btn.verify"), icon="check", style=SUCCESS, callback_data=cb.SUB_CHECK_CHANNEL)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_keyboard(lang: str, join_url: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    join = _join_button(t(lang, "btn.join_chat"), "chat", join_url, SUCCESS)
    if join is not None:
        rows.append([join])
    rows.append(
        [btn(t(lang, "btn.verify"), icon="check", style=SUCCESS, callback_data=cb.SUB_CHECK_CHAT)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
