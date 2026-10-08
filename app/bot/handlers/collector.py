"""Collector tools: name appraisal, portfolio, and Fragment listing watch.

Everything here is backed by real data - Telegram for availability, Fragment for
prices - and every button does something. The appraisal is the flagship: one
command answers "can I get this name, what is it worth, and should I touch it".
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.gate import show_screen
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.features_kb import (
    appraise_keyboard,
    back_home_keyboard,
    portfolio_keyboard,
)
from app.bot.states.states import FinderStates
from app.collectible.checker import CollectibleChecker
from app.collectible.valuation import estimate_price
from app.database import repository as repo
from app.database.models import User
from app.services.i18n import t
from app.telegram.mtproto import mtproto_client
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus, CollectibleStatus
from app.utils.logging_setup import get_logger
from app.utils.username import parse_username
from app.utils.value import estimate_value, is_brand

logger = get_logger(__name__)
router = Router(name="collector")

PORTFOLIO_MAX = 50


def _tons(value: float) -> str:
    return f"{value:,.0f}"


async def _portfolio_estimates(items: list, collectible: CollectibleChecker) -> dict:
    """Comparables estimates for holdings that are not currently listed."""
    missing = [item for item in items if not item.last_price]
    if not missing:
        return {}
    try:
        listings = await collectible.fragment.market_listings()
    except Exception as exc:
        logger.debug("portfolio estimate fetch failed: %s", exc)
        return {}
    out: dict[str, int] = {}
    for item in missing:
        price = estimate_price(item.username, listings)
        if price:
            out[item.username] = price
    return out


async def _refresh_item(session: AsyncSession, item, collectible: CollectibleChecker) -> None:
    """Read a holding's live Fragment state and store it. Best-effort.

    Goes straight to the Fragment source: the high-level collectible checker is
    fine, but this is the one place where the *price* matters, and Fragment is
    the only thing that knows it.
    """
    try:
        lookup = await collectible.fragment.lookup(item.username)
    except Exception as exc:
        logger.debug("portfolio lookup failed for %s: %s", item.username, exc)
        return
    await repo.update_portfolio_value(session, item, lookup.price, lookup.status.value)


# --------------------------------------------------------------------- appraisal
async def _run_appraise(
    message: Message, raw: str, checker: UsernameChecker,
    collectible: CollectibleChecker, lang: str,
) -> None:
    parsed = parse_username(raw)
    if not parsed.is_valid:
        await message.answer(t(lang, "appraise.invalid"))
        return

    name = parsed.value
    placeholder = await message.answer(t(lang, "appraise.running"))

    basic = await checker.check_basic_username(name, use_cache=False)
    availability = texts.appraise_availability(lang, basic, mtproto_client.user_ready)

    # Ask Fragment directly. The high-level collectible checker short-circuits
    # to "not listed" whenever Telegram says the name is unowned - but an
    # unassigned collectible (owned on-chain, not linked to any account) is
    # exactly that, so that shortcut would mislabel a real 5,000 TON name.
    fragment_line: str | None = None
    try:
        lookup = await collectible.fragment.lookup(name)
    except Exception as exc:
        logger.debug("appraise fragment lookup failed for %s: %s", name, exc)
        lookup = None
    if lookup is not None:
        if lookup.is_collectible:
            fragment_line = t(
                lang, "appraise.fragment_sale",
                status=texts.esc(texts.collectible_label(lang, lookup.status)),
                price=texts.esc(lookup.price or t(lang, "collectible.s_unknown")),
            )
        elif lookup.status is CollectibleStatus.NOT_DETECTED:
            fragment_line = t(lang, "appraise.fragment_none")
        else:
            fragment_line = t(lang, "appraise.fragment_unknown")

    market_line: str | None = None
    try:
        listings = await collectible.fragment.market_listings()
    except Exception as exc:
        logger.debug("appraise market fetch failed: %s", exc)
        listings = []
    price = estimate_price(name, listings) if listings else None
    if price:
        similar = sum(1 for item in listings if len(item.name) == len(name))
        market_line = t(
            lang, "appraise.market", price=f"{price:,}", n=similar, length=len(name)
        )
    else:
        market_line = t(lang, "appraise.market_none")

    value = estimate_value(name)
    body = texts.appraise_screen(
        lang, name, availability, fragment_line, market_line, value, is_brand(name)
    )
    keyboard = appraise_keyboard(lang, name, basic.status is CheckStatus.AVAILABLE)

    try:
        await placeholder.edit_text(body, reply_markup=keyboard)
    except Exception:
        await message.answer(body, reply_markup=keyboard)


@router.message(Command("appraise"))
async def cmd_appraise(
    message: Message, command: CommandObject,
    checker: UsernameChecker, collectible_checker: CollectibleChecker, lang: str = "en",
) -> None:
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(t(lang, "appraise.usage"))
        return
    await _run_appraise(message, raw, checker, collectible_checker, lang)


@router.callback_query(F.data == cb.MENU_APPRAISE)
async def cb_appraise(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(FinderStates.waiting_appraise)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "appraise.usage"), reply_markup=back_home_keyboard(lang)
        )


@router.message(FinderStates.waiting_appraise, F.text)
async def on_appraise(
    message: Message, checker: UsernameChecker, collectible_checker: CollectibleChecker,
    state: FSMContext, lang: str = "en",
) -> None:
    await state.set_state(None)
    await _run_appraise(message, message.text or "", checker, collectible_checker, lang)


# --------------------------------------------------------------------- portfolio
async def _render_portfolio(
    message: Message, session: AsyncSession, user: User, lang: str,
    collectible: CollectibleChecker, prefix: str | None = None,
) -> None:
    items = list(await repo.list_portfolio(session, user))
    estimates = await _portfolio_estimates(items, collectible)
    body = texts.portfolio_screen(lang, items, estimates)
    if prefix:
        body = f"{prefix}\n\n{body}"
    await message.answer(body, reply_markup=portfolio_keyboard(lang, items))


@router.callback_query(F.data == cb.MENU_PORTFOLIO)
async def cb_portfolio(
    callback: CallbackQuery, session: AsyncSession, user: User,
    collectible_checker: CollectibleChecker, bot: Bot, lang: str = "en",
) -> None:
    items = list(await repo.list_portfolio(session, user))
    estimates = await _portfolio_estimates(items, collectible_checker)
    await callback.answer()
    if callback.message is not None:
        await show_screen(
            callback, bot,
            texts.portfolio_screen(lang, items, estimates),
            keyboard=portfolio_keyboard(lang, items),
        )


@router.callback_query(F.data == cb.PORT_ADD)
async def cb_port_add(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(FinderStates.waiting_portfolio)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "portfolio.add_prompt"), reply_markup=back_home_keyboard(lang)
        )


@router.message(FinderStates.waiting_portfolio, F.text)
async def on_port_add(
    message: Message, session: AsyncSession, user: User,
    collectible_checker: CollectibleChecker, state: FSMContext, lang: str = "en",
) -> None:
    await state.set_state(None)
    parsed = parse_username(message.text or "")
    if not parsed.is_valid:
        await message.answer(t(lang, "appraise.invalid"))
        return
    if await repo.count_portfolio(session, user.telegram_id) >= PORTFOLIO_MAX:
        await message.answer(t(lang, "portfolio.full", max=PORTFOLIO_MAX))
        return
    item, created = await repo.add_portfolio(session, user, parsed.value)
    if created:
        await _refresh_item(session, item, collectible_checker)
    await session.commit()
    notice = t(
        lang, "portfolio.added" if created else "portfolio.exists", name=parsed.value
    )
    await _render_portfolio(message, session, user, lang, collectible_checker, prefix=notice)


@router.callback_query(F.data.startswith(f"{cb.PORT_ADD_NAME_PREFIX}:"))
async def cb_port_add_name(
    callback: CallbackQuery, session: AsyncSession, user: User,
    collectible_checker: CollectibleChecker, lang: str = "en",
) -> None:
    parsed = parse_username((callback.data or "").split(":")[-1])
    if not parsed.is_valid:
        await callback.answer(t(lang, "appraise.invalid"), show_alert=True)
        return
    if await repo.count_portfolio(session, user.telegram_id) >= PORTFOLIO_MAX:
        await callback.answer(t(lang, "portfolio.full", max=PORTFOLIO_MAX), show_alert=True)
        return
    item, created = await repo.add_portfolio(session, user, parsed.value)
    if created:
        await _refresh_item(session, item, collectible_checker)
    await session.commit()
    await callback.answer(
        t(lang, "portfolio.added" if created else "portfolio.exists", name=parsed.value)
    )


@router.callback_query(F.data.startswith(f"{cb.PORT_DEL_PREFIX}:"))
async def cb_port_del(
    callback: CallbackQuery, session: AsyncSession, user: User,
    collectible_checker: CollectibleChecker, bot: Bot, lang: str = "en",
) -> None:
    try:
        item_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    await repo.remove_portfolio(session, user, item_id)
    await session.commit()
    items = list(await repo.list_portfolio(session, user))
    estimates = await _portfolio_estimates(items, collectible_checker)
    await callback.answer(t(lang, "portfolio.removed"))
    if callback.message is not None:
        await show_screen(
            callback, bot,
            texts.portfolio_screen(lang, items, estimates),
            keyboard=portfolio_keyboard(lang, items),
        )


@router.callback_query(F.data == cb.PORT_REFRESH)
async def cb_port_refresh(
    callback: CallbackQuery, session: AsyncSession, user: User,
    collectible_checker: CollectibleChecker, bot: Bot, lang: str = "en",
) -> None:
    items = list(await repo.list_portfolio(session, user))
    await callback.answer(t(lang, "appraise.running"))
    for item in items:
        await _refresh_item(session, item, collectible_checker)
    await session.commit()
    items = list(await repo.list_portfolio(session, user))
    estimates = await _portfolio_estimates(items, collectible_checker)
    if callback.message is not None:
        await show_screen(
            callback, bot,
            t(lang, "portfolio.refresh_done")
            + "\n\n"
            + texts.portfolio_screen(lang, items, estimates),
            keyboard=portfolio_keyboard(lang, items),
        )


# --------------------------------------------------------------------- listing watch
@router.callback_query(F.data == cb.WATCH_LISTING)
async def cb_watch_listing(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(FinderStates.waiting_listing)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "watch.listing_prompt"), reply_markup=back_home_keyboard(lang)
        )


@router.message(FinderStates.waiting_listing, F.text)
async def on_listing(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str = "en"
) -> None:
    await state.set_state(None)
    keyword = (message.text or "").strip().lower().lstrip("@")
    if len(keyword) < 2:
        await message.answer(t(lang, "appraise.invalid"))
        return
    _trap, created = await repo.create_trap(session, user, keyword, kind="listing")
    await session.commit()
    if not created:
        await message.answer(t(lang, "trap.exists", name=keyword))
        return
    await message.answer(
        t(lang, "watch.listing_added", q=texts.esc(keyword))
        + "\n\n"
        + t(lang, "watch.listing_note")
    )


@router.callback_query(F.data.startswith(f"{cb.WATCH_ADD_NAME_PREFIX}:"))
async def cb_watch_add_name(
    callback: CallbackQuery, session: AsyncSession, user: User, lang: str = "en"
) -> None:
    parsed = parse_username((callback.data or "").split(":")[-1])
    if not parsed.is_valid:
        await callback.answer(t(lang, "appraise.invalid"), show_alert=True)
        return
    _trap, created = await repo.create_trap(session, user, parsed.value, kind="name")
    await session.commit()
    await callback.answer(
        t(lang, "watch.added" if created else "watch.exists", name=parsed.value)
    )
