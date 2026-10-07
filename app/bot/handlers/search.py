"""Username Search: generate variants and mass-scan them with live progress."""

from __future__ import annotations

import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.history_kb import search_count_keyboard
from app.bot.keyboards.main_menu import main_menu_keyboard
from app.bot.states.states import UsernameStates
from app.database import repository as repo
from app.database.models import User
from app.search.generator import UsernameGenerator
from app.search.scanner import UsernameScanner
from app.services.i18n import t
from app.services.runtime_config import runtime
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import Permission, Privilege, permissions_for
from app.utils.logging_setup import get_logger
from app.utils.results import ScanSummary
from app.utils.username import parse_username

logger = get_logger(__name__)
router = Router(name="search")

COUNT_OPTIONS = [10, 50, 100, 500]
PROGRESS_MIN_INTERVAL = 2.2  # Telegram is not a streaming service.

generator = UsernameGenerator()


def _permissions(user: User) -> frozenset[Permission]:
    try:
        privilege = Privilege(user.privilege)
    except ValueError:
        privilege = Privilege.FREE
    return permissions_for(privilege)


def _privilege_cap(user: User) -> int:
    perms = _permissions(user)
    if Permission.MAX_SCAN_RESULTS_5000 in perms:
        return 5000
    if Permission.MAX_SCAN_RESULTS_500 in perms:
        return 500
    return 50


def max_results(user: User) -> int:
    """Effective ceiling: env limit, never above the privilege cap."""
    return min(runtime.max_search_results, _privilege_cap(user))


def allowed_counts(user: User) -> list[int]:
    cap = max_results(user)
    counts = [value for value in COUNT_OPTIONS if value <= cap]
    return counts or [10]


# --------------------------------------------------------------------- entry points
@router.callback_query(F.data == cb.MENU_SEARCH)
async def cb_search(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await callback.answer()
    await state.set_state(UsernameStates.waiting_search_seed)
    if callback.message is not None:
        await callback.message.answer(texts.search_seed_screen(lang))


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    command: CommandObject,
    user: User,
    state: FSMContext,
    lang: str = "en",
) -> None:
    seed = (command.args or "").strip()
    if not seed:
        await state.set_state(UsernameStates.waiting_search_seed)
        await message.answer(texts.search_seed_screen(lang))
        return
    await _offer_counts(message, state, seed, user, lang)


@router.message(UsernameStates.waiting_search_seed, F.text)
async def on_seed(message: Message, user: User, state: FSMContext, lang: str = "en") -> None:
    await _offer_counts(message, state, (message.text or "").strip(), user, lang)


async def _offer_counts(
    message: Message, state: FSMContext, seed: str, user: User, lang: str
) -> None:
    parsed = parse_username(seed)
    if not parsed.is_valid:
        await message.answer(t(lang, "search.bad_seed"))
        return

    await state.set_state(UsernameStates.waiting_search_count)
    await state.update_data(seed=parsed.value)
    await message.answer(
        texts.search_count_screen(lang, parsed.value, max_results(user)),
        reply_markup=search_count_keyboard(lang, allowed_counts(user)),
    )


# --------------------------------------------------------------------- scanning
@router.callback_query(F.data.startswith(f"{cb.SEARCH_COUNT_PREFIX}:"))
async def cb_run_scan(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    checker: UsernameChecker,
    state: FSMContext,
    lang: str = "en",
) -> None:
    data = await state.get_data()
    seed = data.get("seed")
    if not seed:
        await callback.answer(t(lang, "search.need_seed"), show_alert=True)
        return

    try:
        requested = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    ceiling = max(allowed_counts(user))
    count = min(requested, ceiling)
    if requested > ceiling:
        await callback.answer(t(lang, "search.capped", n=ceiling), show_alert=True)
    else:
        await callback.answer()

    await state.clear()

    variants = generator.generate(seed, count=count)
    if not variants:
        if callback.message is not None:
            await callback.message.answer(
                texts.error_screen(lang), reply_markup=main_menu_keyboard(lang)
            )
        return

    await repo.add_search(session, user, seed, "search")
    await session.commit()

    await _run_scan(callback, session, user, bot, checker, variants, lang)


async def _run_scan(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    checker: UsernameChecker,
    variants: list[str],
    lang: str,
) -> None:
    chat_id = callback.from_user.id
    message = callback.message
    initial = texts.scan_progress(lang, ScanSummary(total=len(variants)))
    if message is not None:
        placeholder = await message.answer(initial)
    else:
        placeholder = await bot.send_message(chat_id, initial)

    last_edit = time.monotonic()

    async def on_progress(summary: ScanSummary) -> None:
        nonlocal last_edit
        now = time.monotonic()
        is_final = summary.checked >= summary.total
        if not is_final and now - last_edit < PROGRESS_MIN_INTERVAL:
            return
        last_edit = now
        try:
            await placeholder.edit_text(texts.scan_progress(lang, summary))
        except Exception:
            pass

    scanner = UsernameScanner(checker)
    try:
        summary = await scanner.scan(variants, progress_cb=on_progress)
    except Exception as exc:
        logger.exception("scan failed: %s", exc)
        try:
            await placeholder.edit_text(
                texts.error_screen(lang), reply_markup=main_menu_keyboard(lang)
            )
        except Exception:
            pass
        return

    await repo.increment_search_count(session, user, summary.checked)

    final = texts.scan_complete(lang, summary)
    keyboard = main_menu_keyboard(lang)
    try:
        await placeholder.edit_text(final, reply_markup=keyboard)
    except Exception:
        await bot.send_message(chat_id, final, reply_markup=keyboard)
