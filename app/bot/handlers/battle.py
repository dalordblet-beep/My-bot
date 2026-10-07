"""Username battle: a manual duel and a shareable challenge.

Manual mode runs entirely in the chat. Challenge mode uses inline mode, so a
challenge can be posted into any chat the user is in without the bot needing to
be a member - the challenger picks the chat, not the bot.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    KeyboardButton,
    KeyboardButtonRequestChat,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.features_kb import back_home_keyboard, battle_accept_keyboard, battle_keyboard
from app.bot.states.states import BattleStates
from app.collectible.checker import CollectibleChecker
from app.database import repository as repo
from app.database.models import User
from app.search.battle import compare
from app.services.i18n import t
from app.telegram.username_checker import UsernameChecker
from app.utils.logging_setup import get_logger
from app.utils.username import parse_username

logger = get_logger(__name__)
router = Router(name="battle")


BATTLE_CHECK_TIMEOUT = 45.0


async def _compare_once(
    left: str, right: str, checker: UsernameChecker,
    collectible: CollectibleChecker,
):
    """Run one bounded lookup pass so the screen cannot stay on COMPARING."""
    try:
        return await asyncio.wait_for(
            compare(left, right, checker, collectible),
            timeout=BATTLE_CHECK_TIMEOUT,
        ), False
    except asyncio.TimeoutError:
        logger.warning("battle comparison timed out for @%s vs @%s", left, right)
        return None, True


def _battle_text(lang: str, result, timed_out: bool) -> str:
    if timed_out:
        return t(lang, "battle.timeout")
    if result is None:
        return t(lang, "battle.invalid")
    return texts.battle_result(lang, result)


# --------------------------------------------------------------------- entry
@router.callback_query(F.data == cb.MENU_BATTLE)
async def cb_battle(callback: CallbackQuery, lang: str = "en") -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(texts.battle_screen(lang), reply_markup=battle_keyboard(lang))


# --------------------------------------------------------------------- manual
@router.callback_query(F.data == cb.BATTLE_MANUAL)
async def cb_manual(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(BattleStates.waiting_left)
    await state.update_data(battle_left=None)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "battle.enter_left"), reply_markup=back_home_keyboard(lang)
        )


@router.message(BattleStates.waiting_left, F.text)
async def on_left(message: Message, state: FSMContext, lang: str = "en") -> None:
    parsed = parse_username(message.text or "")
    if not parsed.is_valid:
        await message.answer(t(lang, "battle.invalid"))
        return
    await state.update_data(battle_left=parsed.value)
    await state.set_state(BattleStates.waiting_right)
    await message.answer(t(lang, "battle.enter_right"), reply_markup=back_home_keyboard(lang))


@router.message(BattleStates.waiting_right, F.text)
async def on_right(
    message: Message,
    session: AsyncSession,
    user: User,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    state: FSMContext,
    lang: str = "en",
) -> None:
    data = await state.get_data()
    left = data.get("battle_left")
    await state.set_state(None)

    parsed = parse_username(message.text or "")
    if not left or not parsed.is_valid:
        await message.answer(t(lang, "battle.invalid"))
        return

    placeholder = await message.answer(t(lang, "battle.comparing"))
    result, timed_out = await _compare_once(
        left, parsed.value, checker, collectible_checker
    )
    rendered = _battle_text(lang, result, timed_out)

    try:
        await placeholder.edit_text(rendered, reply_markup=battle_keyboard(lang))
    except Exception:
        await message.answer(rendered, reply_markup=battle_keyboard(lang))

    if result is not None:
        try:
            battle = await repo.create_battle(
                session, user.telegram_id, left, parsed.value, status="done"
            )
            winner_id = user.telegram_id if result.winner == "left" else None
            await repo.finish_battle(
                session, battle, result.to_dict(), winner_id=winner_id
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("battle result was delivered but not saved")


# --------------------------------------------------------------------- challenge
@router.callback_query(F.data == cb.BATTLE_CHALLENGE)
async def cb_challenge(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    """Open Telegram's native chat picker.

    Only chats where the bot is already a member are offered, because the bot
    has to be able to post the challenge there. This needs no BotFather setup,
    unlike inline mode.
    """
    if not user.username:
        await callback.answer(t(lang, "battle.need_username"), show_alert=True)
        return

    await callback.answer()
    picker = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=t(lang, "battle.pick_chat"),
                    request_chat=KeyboardButtonRequestChat(
                        request_id=callback.from_user.id % 2_000_000_000,
                        chat_is_channel=False,
                        bot_is_member=True,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=t(lang, "battle.pick_chat"),
    )
    if callback.message is not None:
        await callback.message.answer(t(lang, "battle.pick_chat_hint"), reply_markup=picker)


@router.message(F.chat_shared)
async def on_chat_shared(
    message: Message,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
    lang: str = "en",
) -> None:
    """The user picked a chat - post the challenge there."""
    shared = message.chat_shared
    await message.answer(
        t(lang, "battle.challenge_sent"), reply_markup=ReplyKeyboardRemove()
    )

    if shared is None or not shared.chat_id:
        return
    if not user.username:
        await message.answer(t(lang, "battle.need_username"))
        return

    rival_placeholder = t(lang, "battle.open_rival")

    battle = await repo.create_battle(
        session, user.telegram_id, user.username, status="pending"
    )
    await session.commit()

    text = texts.battle_challenge_open(lang, user.username, rival_placeholder)
    try:
        await bot.send_message(
            chat_id=shared.chat_id,
            text=text,
            reply_markup=battle_accept_keyboard(lang, battle.id),
        )
    except Exception as exc:
        logger.warning("could not post the challenge to %s: %s", shared.chat_id, exc)
        await message.answer(t(lang, "battle.cannot_post"))
        return

    await message.answer(t(lang, "battle.challenge_waiting"))


@router.inline_query()
async def on_inline(
    inline: InlineQuery,
    session: AsyncSession,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    lang: str = "en",
) -> None:
    """``@bot battle @rival`` posts a challenge with an accept button."""
    query = (inline.query or "").strip()
    parts = query.split()

    if len(parts) < 2 or parts[0].lower() not in ("battle", "vs", "duel"):
        await inline.answer(
            results=[],
            cache_time=0,
            switch_pm_text="Send: battle @username",
            switch_pm_parameter="battle",
        )
        return

    rival = parse_username(parts[1])
    challenger = parse_username(inline.from_user.username or "")
    if not rival.is_valid or not challenger.is_valid:
        await inline.answer(results=[], cache_time=0)
        return
    if rival.value == challenger.value:
        await inline.answer(
            results=[],
            cache_time=0,
            switch_pm_text=t(lang, "battle.self_challenge").replace("<b>", "").replace("</b>", ""),
            switch_pm_parameter="battle",
        )
        return

    battle = await repo.create_battle(
        session, inline.from_user.id, challenger.value, rival.value, status="pending"
    )
    await session.commit()

    await inline.answer(
        results=[
            InlineQueryResultArticle(
                id=str(battle.id),
                title=t(lang, "battle.accept"),
                description=f"@{challenger.value} vs @{rival.value}",
                input_message_content=InputTextMessageContent(
                    message_text=texts.battle_challenge_text(lang, challenger.value, rival.value),
                    parse_mode="HTML",
                ),
                reply_markup=battle_accept_keyboard(lang, battle.id),
            )
        ],
        cache_time=0,
    )


@router.callback_query(F.data.startswith(f"{cb.BATTLE_ACCEPT_PREFIX}:"))
async def cb_accept(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    lang: str = "en",
) -> None:
    try:
        battle_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    battle = await repo.get_battle(session, battle_id)
    if battle is None:
        await callback.answer(t(lang, "battle.invalid"), show_alert=True)
        return

    accepter = callback.from_user
    if accepter.id == battle.challenger_id:
        await callback.answer(t(lang, "battle.self_challenge"), show_alert=True)
        return
    if battle.status == "done":
        await callback.answer()
        return

    rival_username = accepter.username
    if not rival_username:
        await callback.answer(t(lang, "battle.invalid"), show_alert=True)
        return

    battle.rival_id = accepter.id
    battle.rival_username = rival_username.lower()

    placeholder = callback.message
    if placeholder is not None:
        try:
            await placeholder.edit_text(t(lang, "battle.comparing"))
        except Exception:
            pass
    # Clear Telegram's callback spinner before the bounded external lookups.
    await callback.answer()

    result, timed_out = await _compare_once(
        battle.challenger_username, rival_username, checker, collectible_checker
    )
    rendered = _battle_text(lang, result, timed_out)
    delivered = False
    if placeholder is not None:
        try:
            await placeholder.edit_text(rendered)
            delivered = True
        except Exception:
            pass
    if not delivered:
        await bot.send_message(callback.from_user.id, rendered)

    if result is not None:
        try:
            winner_id = None
            if result.winner == "left":
                winner_id = battle.challenger_id
            elif result.winner == "right":
                winner_id = accepter.id
            await repo.finish_battle(
                session, battle, result.to_dict(), winner_id=winner_id
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("accepted battle result was delivered but not saved")
