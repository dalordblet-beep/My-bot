"""The search wizard and traps.

One search = one attempt: pressing Run performs exactly one Telegram lookup.
Criteria live in the FSM so the wizard survives navigation, and the defaults
come from the user's settings.
"""

from __future__ import annotations

import asyncio
import contextlib

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.gate import show_screen
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.features_kb import (
    back_home_keyboard,
    filter_keyboard,
    length_keyboard,
    search_setup_keyboard,
    watch_keyboard,
)
from app.bot.states.states import FinderStates
from app.collectible.checker import CollectibleChecker
from app.database import repository as repo
from app.database.models import User
from app.search.finder import TARGET_FREE, SearchCriteria, UsernameFinder
from app.search.pattern import mask_is_usable
from app.services import user as user_service
from app.services.i18n import t
from app.services.runtime_config import runtime
from app.services.search_queue import SearchQueue
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus
from app.utils.logging_setup import get_logger
from app.utils.username import parse_username

logger = get_logger(__name__)
router = Router(name="finder")

MAX_ACTIVE_WATCHES_PER_USER = 10


async def _criteria(session: AsyncSession, user: User, state: FSMContext) -> SearchCriteria:
    """FSM criteria, seeded from the user's saved defaults on first open.

    There is no user-facing rating filter and no target choice: every search
    hunts beautiful, unoccupied, premium names and double-checks each result.
    """
    data = await state.get_data()
    if "criteria" in data:
        raw = data["criteria"]
        # Criteria saved by an older build may still carry a min_score/target
        # pair; strip anything the dataclass no longer knows about.
        known = {field for field in SearchCriteria.__dataclass_fields__}
        raw = {key: value for key, value in raw.items() if key in known}
        return SearchCriteria(**raw)

    row = await user_service.get_settings_row(session, user)
    criteria = SearchCriteria(
        length=row.search_length or None,
        allow_digits=bool(row.search_digits),
        mask=row.search_mask or None,
        target=TARGET_FREE,
    )
    await state.update_data(criteria=criteria.describe())
    return criteria


async def _store(state: FSMContext, criteria: SearchCriteria) -> None:
    await state.update_data(criteria=criteria.describe())


async def _name_watches(session: AsyncSession, user: User) -> list:
    return [
        watch for watch in await repo.list_traps(session, user)
        if watch.kind == "name" and watch.active
    ]


async def _render_setup(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    state: FSMContext, lang: str,
) -> None:
    criteria = await _criteria(session, user, state)
    text = texts.search_setup_screen(
        lang, length=criteria.length, digits=criteria.allow_digits, mask=criteria.mask,
    )
    keyboard = search_setup_keyboard(
        lang, length=criteria.length, digits=criteria.allow_digits, mask=criteria.mask,
    )
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


# --------------------------------------------------------------------- entry
@router.callback_query(F.data == cb.MENU_SEARCH_ENGINE)
async def cb_open(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    state: FSMContext, lang: str = "en",
) -> None:
    """Open the setup screen directly.

    The old flow showed a target picker ("free / collectible") first. The
    search has a single target now - beautiful unoccupied names worth
    reselling - so the picker went away and this screen is the entry point.
    """
    await callback.answer()
    criteria = await _criteria(session, user, state)
    await callback.message.answer(
        texts.search_setup_screen(
            lang, length=criteria.length, digits=criteria.allow_digits, mask=criteria.mask,
        ),
        reply_markup=search_setup_keyboard(
            lang, length=criteria.length, digits=criteria.allow_digits, mask=criteria.mask,
        ),
    )


# --------------------------------------------------------------------- length
@router.callback_query(F.data.startswith(f"{cb.FIND_LEN_PREFIX}:"))
async def cb_length(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    state: FSMContext, lang: str = "en",
) -> None:
    raw = (callback.data or "").split(":")[-1]
    criteria = await _criteria(session, user, state)

    if raw == "menu":
        await callback.answer()
        if callback.message is not None:
            await show_screen(
                callback, bot,
                f"{t(lang, 'search.length_title')}\n\n{t(lang, 'search.length_body')}",
                keyboard=length_keyboard(lang, criteria.length),
            )
        return

    try:
        value = int(raw)
    except ValueError:
        await callback.answer()
        return

    criteria.length = value or None
    if value:
        await repo.update_user_settings(session, user.id, search_length=value)
    await _store(state, criteria)
    await callback.answer()
    await _render_setup(callback, session, user, bot, state, lang)


# --------------------------------------------------------------------- digits
@router.callback_query(F.data.startswith(f"{cb.FIND_DIGITS_PREFIX}:"))
async def cb_digits(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    state: FSMContext, lang: str = "en",
) -> None:
    raw = (callback.data or "").split(":")[-1]
    criteria = await _criteria(session, user, state)
    criteria.allow_digits = raw == "1"
    await repo.update_user_settings(session, user.id, search_digits=criteria.allow_digits)
    await _store(state, criteria)
    await callback.answer()
    await _render_setup(callback, session, user, bot, state, lang)


# --------------------------------------------------------------------- filters
@router.callback_query(F.data == cb.FIND_FILTER)
async def cb_filter(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext,
    bot: Bot, lang: str = "en",
) -> None:
    criteria = await _criteria(session, user, state)
    await callback.answer()
    if callback.message is not None:
        await show_screen(
            callback, bot,
            f"{t(lang, 'search.filter_title')}\n\n{t(lang, 'search.filter_body')}",
            keyboard=filter_keyboard(lang, criteria.mask),
        )


@router.callback_query(F.data == cb.FIND_MASK)
async def cb_mask(
    callback: CallbackQuery, state: FSMContext, lang: str = "en"
) -> None:
    await state.set_state(FinderStates.waiting_mask)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "search.filter_mask_prompt"), reply_markup=back_home_keyboard(lang)
        )


@router.message(FinderStates.waiting_mask, F.text)
async def on_mask(
    message: Message, session: AsyncSession, user: User, bot: Bot,
    state: FSMContext, lang: str = "en",
) -> None:
    raw = (message.text or "").strip().lower()
    criteria = await _criteria(session, user, state)
    await state.set_state(None)

    if raw in ("-", "/skip", ""):
        criteria.mask = None
        await _store(state, criteria)
        # Persist the clear too: the mask lives in the user's settings, not only
        # in the FSM, so leaving the wizard does not silently bring it back.
        await repo.update_user_settings(session, user.id, search_mask="")
        await _send_setup(message, lang, criteria)
        return

    if not mask_is_usable(raw):
        await message.answer(t(lang, "search.filter_mask_bad"))
        await state.set_state(FinderStates.waiting_mask)
        return

    criteria.mask = raw
    await _store(state, criteria)
    # The mask is saved to the user's settings - the FSM alone is wiped whenever
    # the user taps Main menu, which used to make the mask look "applied" and
    # then silently disappear before the search ran.
    await repo.update_user_settings(session, user.id, search_mask=raw)
    await _send_setup(message, lang, criteria)


async def _send_setup(message: Message, lang: str, criteria: SearchCriteria) -> None:
    """Show the search screen so the saved mask is visible and Run is one tap."""
    await message.answer(
        texts.search_setup_screen(
            lang, length=criteria.length, digits=criteria.allow_digits, mask=criteria.mask,
        ),
        reply_markup=search_setup_keyboard(
            lang, length=criteria.length, digits=criteria.allow_digits, mask=criteria.mask,
        ),
    )


@router.callback_query(F.data == cb.FIND_CLEAR)
async def cb_clear(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    state: FSMContext, lang: str = "en",
) -> None:
    criteria = await _criteria(session, user, state)
    criteria.mask = None
    await _store(state, criteria)
    await repo.update_user_settings(session, user.id, search_mask="")
    await callback.answer(t(lang, "search.filter_cleared"))
    await _render_setup(callback, session, user, bot, state, lang)


# --------------------------------------------------------------------- run
@router.callback_query(F.data == cb.FIND_RUN)
async def cb_run(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    checker: UsernameChecker, collectible_checker: CollectibleChecker,
    search_queue: SearchQueue, state: FSMContext, lang: str = "en",
) -> None:
    """Queue the search and answer at once.

    The search itself is paced to a safe Telegram rate, so running it inline
    would make the user sit and wait on that pacing - and the wait would grow
    with every other person using the bot. The queue takes the job and the
    worker delivers the result to this same message when it is ready.
    """
    criteria = await _criteria(session, user, state)

    data = await state.get_data()
    used = int(data.get("attempts", 0)) + 1

    message = callback.message
    chat_id = message.chat.id if message is not None else callback.from_user.id
    message_id = message.message_id if message is not None else None

    ahead = await search_queue.submit(
        user_id=callback.from_user.id,
        chat_id=chat_id,
        message_id=message_id,
        criteria=criteria,
        lang=lang,
        used=used,
    )

    if ahead == -1:
        # The bot is at capacity. Say so plainly instead of silently doing
        # nothing - the search is NOT running yet, so the home button is safe.
        text = t(lang, "search.queue_full")
        if message is not None:
            with contextlib.suppress(Exception):
                await message.edit_text(text, reply_markup=back_home_keyboard(lang))
        await callback.answer()
        return

    if ahead == 0:
        # An identical search is already running - do not count the attempt
        # twice, and do not start the work twice.
        await callback.answer(t(lang, "search.running"))
        return

    await state.update_data(attempts=used)
    await callback.answer()

    # No buttons on a running search: leaving this message alone is exactly
    # what keeps the live progress screen (and its result) intact.
    text = t(lang, "search.started")
    if message is not None:
        try:
            await message.edit_text(text)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text)


# -------------------------------------------------------------- username watches
@router.callback_query(F.data == cb.MENU_WATCH)
async def cb_watch_open(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    """The dedicated Watch screen replaces the old search-wizard trap entry."""
    watches = await _name_watches(session, user)
    await callback.answer()
    if callback.message is not None:
        await show_screen(
            callback, bot,
            texts.watch_screen(lang, watches, interval=runtime.trap_interval),
            keyboard=watch_keyboard(lang, watches),
        )


@router.callback_query(F.data.startswith(f"{cb.WATCH_CHECK_PREFIX}:"))
async def cb_watch_check(
    callback: CallbackQuery, session: AsyncSession, user: User, checker: UsernameChecker,
    bot: Bot, lang: str = "en",
) -> None:
    """Run one authoritative release check and refresh that watch's status."""
    try:
        watch_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    watch = await repo.get_trap(session, watch_id)
    if (
        watch is None
        or watch.telegram_id != user.telegram_id
        or watch.kind != "name"
        or not watch.active
    ):
        await callback.answer(t(lang, "watch.removed"), show_alert=True)
        return

    await callback.answer(t(lang, "watch.checking", name=watch.username))
    try:
        from app.search.traps import TrapWatcher, WATCH_CHECK_TIMEOUT

        result = await asyncio.wait_for(
            checker.check_for_release(watch.username), timeout=WATCH_CHECK_TIMEOUT
        )
        recorded = await TrapWatcher._record(
            watch.id,
            result.status.value,
            freed=result.status is CheckStatus.AVAILABLE,
        )
        await session.commit()
    except Exception as exc:
        logger.warning("manual username-watch check failed for %s: %s", watch.username, exc)
        if callback.message is not None:
            await callback.message.answer(texts.error_screen(lang))
        return

    if result.status is CheckStatus.AVAILABLE and recorded:
        message = texts.watch_alert(lang, watch.username)
        if callback.message is not None:
            await callback.message.answer(message)
        else:
            await bot.send_message(callback.from_user.id, message)

    watches = await _name_watches(session, user)
    if callback.message is not None:
        await show_screen(
            callback, bot,
            texts.watch_screen(lang, watches, interval=runtime.trap_interval),
            keyboard=watch_keyboard(lang, watches),
        )


@router.callback_query(F.data == cb.WATCH_ADD)
async def cb_watch_add(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(FinderStates.waiting_watch)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "watch.add_prompt"), reply_markup=back_home_keyboard(lang)
        )


@router.message(FinderStates.waiting_watch, F.text)
async def on_watch_add(
    message: Message, session: AsyncSession, user: User,
    state: FSMContext, lang: str = "en",
) -> None:
    parsed = parse_username(message.text or "")
    await state.set_state(None)
    if not parsed.is_valid:
        await message.answer(t(lang, "search.filter_mask_bad"))
        return

    watches = await _name_watches(session, user)
    if any(w.username == parsed.value and w.active for w in watches):
        await message.answer(t(lang, "watch.exists", name=parsed.value))
        return
    if sum(1 for watch in watches if watch.active) >= MAX_ACTIVE_WATCHES_PER_USER:
        await message.answer(
            t(lang, "watch.limit", max=MAX_ACTIVE_WATCHES_PER_USER),
            reply_markup=back_home_keyboard(lang),
        )
        return

    watch, created = await repo.create_trap(session, user, parsed.value, kind="name")
    await session.commit()
    if not created:
        await message.answer(t(lang, "watch.exists", name=parsed.value))
        return

    watches = await _name_watches(session, user)
    await message.answer(
        f"{t(lang, 'watch.added', name=parsed.value)}\n\n"
        f"{texts.watch_screen(lang, watches, interval=runtime.trap_interval)}",
        reply_markup=watch_keyboard(lang, watches),
    )


@router.callback_query(F.data.startswith(f"{cb.WATCH_DEL_PREFIX}:"))
async def cb_watch_delete(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    try:
        watch_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    await repo.deactivate_trap(session, user, watch_id)
    await session.commit()
    watches = await _name_watches(session, user)
    await callback.answer(t(lang, "watch.removed"))
    if callback.message is not None:
        await show_screen(
            callback, bot,
            texts.watch_screen(lang, watches, interval=runtime.trap_interval),
            keyboard=watch_keyboard(lang, watches),
        )
