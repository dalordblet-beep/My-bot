"""Username checking: Basic, Collectible and All-in-One."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.main_menu import back_to_menu_keyboard, main_menu_keyboard
from app.bot.states.states import UsernameStates
from app.collectible.checker import CollectibleChecker
from app.database import repository as repo
from app.database.models import User
from app.services import user as user_service
from app.services.emoji import emoji
from app.services.i18n import t
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import UsernameType
from app.utils.logging_setup import get_logger
from app.utils.results import CheckResult, CollectibleResult

logger = get_logger(__name__)
router = Router(name="username")

MODE_BASIC = "basic"
MODE_COLLECTIBLE = "collectible"
MODE_ALL_IN_ONE = "all_in_one"

MODE_PROMPT_KEYS = {
    MODE_BASIC: "prompt.basic",
    MODE_COLLECTIBLE: "prompt.collectible",
    MODE_ALL_IN_ONE: "prompt.allinone",
}

PROMPTS = {
    "prompt.basic": {
        "en": "Send a username to check.\n\nAccepted: <code>@name</code>, <code>name</code>, <code>https://t.me/name</code>",
        "ru": "Отправьте username для проверки.\n\nПринимается: <code>@name</code>, <code>name</code>, <code>https://t.me/name</code>",
    },
    "prompt.collectible": {
        "en": "Send a username to look up on Fragment.\n\nAccepted: <code>@name</code>, <code>name</code>, <code>https://t.me/name</code>",
        "ru": "Отправьте username для поиска на Fragment.\n\nПринимается: <code>@name</code>, <code>name</code>, <code>https://t.me/name</code>",
    },
    "prompt.allinone": {
        "en": "Send a username for a full check.\n\nBasic + Collectible + enrichment in one pass.",
        "ru": "Отправьте username для полной проверки.\n\nОсновная + коллекционная + обогащение за один проход.",
    },
}


def prompt_text(lang: str, mode: str) -> str:
    key = MODE_PROMPT_KEYS.get(mode, "prompt.basic")
    table = PROMPTS[key]
    return table.get(lang, table["en"])


async def perform_check(
    session: AsyncSession,
    user: User,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    target: str,
    mode: str,
    lang: str,
) -> str:
    """Run the requested mode and return the rendered message."""
    basic: CheckResult | None = None
    collectible: CollectibleResult | None = None

    if mode in (MODE_BASIC, MODE_ALL_IN_ONE):
        basic = await checker.check_basic_username(target)
        await repo.record_username_check(
            session,
            username=basic.username,
            status=basic.status.value,
            type_=UsernameType.BASIC.value,
            source=basic.source,
            metadata=basic.to_cache(),
        )

    if mode in (MODE_COLLECTIBLE, MODE_ALL_IN_ONE):
        collectible = await collectible_checker.check_collectible_username(target)
        await repo.record_username_check(
            session,
            username=collectible.username,
            status=collectible.status.value,
            type_=UsernameType.COLLECTIBLE.value,
            source=collectible.source,
            metadata=collectible.to_dict(),
        )

    await repo.add_search(session, user, target.lstrip("@").lower(), mode)
    await repo.increment_search_count(session, user)

    if mode == MODE_COLLECTIBLE and collectible is not None:
        return texts.collectible_result(lang, collectible)
    if mode == MODE_ALL_IN_ONE and basic is not None:
        return texts.all_in_one_result(lang, basic, collectible)
    if basic is not None:
        return texts.basic_result(lang, basic)
    return texts.error_screen(lang)


async def _prompt(message: Message, state: FSMContext, mode: str, lang: str) -> None:
    await state.set_state(UsernameStates.waiting_username)
    await state.update_data(mode=mode)
    await message.answer(prompt_text(lang, mode))


# --------------------------------------------------------------------- callbacks
@router.callback_query(F.data == cb.MENU_CHECK)
async def cb_check(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    lang: str = "en",
) -> None:
    settings_row = await user_service.get_settings_row(session, user)
    await callback.answer()
    if callback.message is not None:
        await _prompt(callback.message, state, settings_row.default_mode, lang)


@router.callback_query(F.data == cb.MENU_BASIC)
async def cb_basic(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await callback.answer()
    if callback.message is not None:
        await _prompt(callback.message, state, MODE_BASIC, lang)


@router.callback_query(F.data == cb.MENU_COLLECTIBLE)
async def cb_collectible(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await callback.answer()
    if callback.message is not None:
        await _prompt(callback.message, state, MODE_COLLECTIBLE, lang)


@router.callback_query(F.data == cb.MENU_ALL_IN_ONE)
async def cb_all_in_one(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await callback.answer()
    if callback.message is not None:
        await _prompt(callback.message, state, MODE_ALL_IN_ONE, lang)


# --------------------------------------------------------------------- commands
@router.message(Command("check"))
async def cmd_check(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    state: FSMContext,
    lang: str = "en",
) -> None:
    settings_row = await user_service.get_settings_row(session, user)
    target = (command.args or "").strip()
    if not target:
        await _prompt(message, state, settings_row.default_mode, lang)
        return

    await state.clear()
    await run_and_reply(
        message, session, user, checker, collectible_checker, target,
        settings_row.default_mode, lang,
    )


@router.message(UsernameStates.waiting_username, F.text)
async def on_username_input(
    message: Message,
    session: AsyncSession,
    user: User,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    state: FSMContext,
    lang: str = "en",
) -> None:
    data = await state.get_data()
    mode = data.get("mode", MODE_BASIC)
    await state.clear()

    target = (message.text or "").strip()
    if not target:
        await message.answer(texts.error_screen(lang), reply_markup=back_to_menu_keyboard(lang))
        return

    await run_and_reply(message, session, user, checker, collectible_checker, target, mode, lang)


async def run_and_reply(
    message: Message,
    session: AsyncSession,
    user: User,
    checker: UsernameChecker,
    collectible_checker: CollectibleChecker,
    target: str,
    mode: str,
    lang: str,
) -> None:
    placeholder = await message.answer(
        f"{emoji.plain('search')} <b>{texts.esc(target)}</b>"
    )
    try:
        rendered = await perform_check(
            session, user, checker, collectible_checker, target, mode, lang
        )
    except Exception as exc:
        logger.exception("check failed for %s: %s", target, exc)
        rendered = texts.error_screen(lang)

    keyboard = main_menu_keyboard(lang)
    try:
        await placeholder.edit_text(rendered, reply_markup=keyboard)
    except Exception:
        await message.answer(rendered, reply_markup=keyboard)
