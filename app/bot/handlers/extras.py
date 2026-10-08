"""Extra features: bulk check, instant rating, leaderboard and favourites.

Every number shown here is computed from real rows or from the name itself.
Nothing is estimated, and the rating is explicitly labelled as our own
aesthetic score rather than a price.
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
    back_home_keyboard,
    favorites_keyboard,
    favorite_toggle_keyboard,
)
from app.bot.states.states import FinderStates
from app.database import repository as repo
from app.database.models import User
from app.search.finder import SearchCriteria, TARGET_VARIANTS
from app.search.pattern import premium_rating
from app.search.scanner import UsernameScanner
from app.services.i18n import t
from app.services.search_queue import SearchQueue
from app.telegram.username_checker import UsernameChecker
from app.utils.logging_setup import get_logger
from app.utils.username import parse_username

logger = get_logger(__name__)
router = Router(name="extras")

BULK_MAX = 25
TOP_SIZE = 10
FAVORITES_MAX = 50


# --------------------------------------------------------------------- instant rating
@router.message(Command("rate"))
async def cmd_rate(
    message: Message, command: CommandObject, lang: str = "en"
) -> None:
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(t(lang, "rate.usage"))
        return

    parsed = parse_username(raw)
    if not parsed.is_valid:
        await message.answer(t(lang, "rate.invalid"))
        return

    premium = premium_rating(parsed.value)
    await message.answer(
        texts.rate_screen(lang, parsed.value, premium),
        reply_markup=favorite_toggle_keyboard(lang, parsed.value, premium.total),
    )


# --------------------------------------------------------------------- variants
@router.message(Command("variants"))
async def cmd_variants(
    message: Message, command: CommandObject, lang: str = "en",
    search_queue: SearchQueue | None = None, bot: Bot | None = None,
    user: User | None = None,
) -> None:
    """Find free alternatives to a name the user cannot have.

    Runs through the same queue as a search: the scarce MTProto confirmations
    are paced, so the result arrives when it is ready and the user is not left
    staring at a frozen screen.
    """
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(t(lang, "variants.usage"))
        return

    parsed = parse_username(raw)
    if not parsed.is_valid:
        await message.answer(t(lang, "variants.invalid"))
        return

    if search_queue is None or bot is None or user is None:
        await message.answer(t(lang, "error.body"))
        return

    criteria = SearchCriteria(target=TARGET_VARIANTS, seed=parsed.value)
    placeholder = await message.answer(t(lang, "variants.started"))

    ahead = await search_queue.submit(
        user_id=message.from_user.id,
        chat_id=placeholder.chat.id,
        message_id=placeholder.message_id,
        criteria=criteria,
        lang=lang,
        used=1,
    )

    if ahead == -1:
        await placeholder.edit_text(
            t(lang, "search.queue_full"), reply_markup=back_home_keyboard(lang)
        )
        return
    if ahead == 0:
        await placeholder.edit_text(t(lang, "search.running"))
        return

    try:
        await placeholder.edit_text(t(lang, "variants.started"))
    except Exception:
        await bot.send_message(placeholder.chat.id, t(lang, "variants.started"))


@router.callback_query(F.data.startswith(f"{cb.FIND_VARIANTS_PREFIX}:"))
async def cb_variants(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    search_queue: SearchQueue, lang: str = "en",
) -> None:
    """The "Variants" button on a result: re-hunt free alternatives.

    Edits the very message it was pressed on, so the result lands in place.
    """
    seed = (callback.data or "").split(":")[-1]
    parsed = parse_username(seed)
    if not parsed.is_valid:
        await callback.answer(t(lang, "variants.invalid"), show_alert=True)
        return

    criteria = SearchCriteria(target=TARGET_VARIANTS, seed=parsed.value)
    message = callback.message
    chat_id = message.chat.id if message is not None else callback.from_user.id
    message_id = message.message_id if message is not None else None

    ahead = await search_queue.submit(
        user_id=callback.from_user.id,
        chat_id=chat_id,
        message_id=message_id,
        criteria=criteria,
        lang=lang,
        used=1,
    )

    if ahead == -1:
        await callback.answer(t(lang, "search.queue_full"), show_alert=True)
        return
    if ahead == 0:
        await callback.answer(t(lang, "search.running"))
        return

    await callback.answer()
    # No buttons while the hunt runs - the result replaces this message.
    if message is not None:
        try:
            await message.edit_text(t(lang, "variants.started"))
            return
        except Exception:
            pass
    await bot.send_message(chat_id, t(lang, "variants.started"))


# --------------------------------------------------------------------- bulk check
@router.callback_query(F.data == cb.MENU_BULK)
async def cb_bulk(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(FinderStates.waiting_bulk)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            t(lang, "bulk.title") + "\n\n" + t(lang, "bulk.body", max=BULK_MAX),
            reply_markup=back_home_keyboard(lang),
        )


@router.message(FinderStates.waiting_bulk, F.text)
async def on_bulk(
    message: Message,
    session: AsyncSession,
    user: User,
    checker: UsernameChecker,
    state: FSMContext,
    lang: str = "en",
) -> None:
    await state.set_state(None)

    raw = (message.text or "").replace(",", "\n").replace(";", "\n")
    seen: set[str] = set()
    names: list[str] = []
    for chunk in raw.split():
        parsed = parse_username(chunk)
        if parsed.is_valid and parsed.value not in seen:
            seen.add(parsed.value)
            names.append(parsed.value)

    if not names:
        await message.answer(t(lang, "bulk.empty"))
        return

    if len(names) > BULK_MAX:
        await message.answer(t(lang, "bulk.too_many", max=BULK_MAX))
        names = names[:BULK_MAX]

    placeholder = await message.answer(t(lang, "bulk.running", n=len(names)))
    try:
        summary = await UsernameScanner(checker).scan(names)
    except Exception as exc:
        logger.exception("bulk check failed: %s", exc)
        await placeholder.edit_text(texts.error_screen(lang), reply_markup=back_home_keyboard(lang))
        return

    hits = sorted(
        ((name, premium_rating(name).total) for name in summary.available_usernames),
        key=lambda pair: pair[1],
        reverse=True,
    )

    await repo.increment_search_count(session, user, summary.checked)
    await repo.add_search(session, user, "bulk", "bulk")
    await session.commit()

    lines = [
        t(lang, "bulk.result"),
        "",
        t(lang, "bulk.summary", n=summary.total),
        t(lang, "bulk.hits", n=len(hits)),
    ]
    if hits:
        lines.append("")
        for name, score in hits[:15]:
            lines.append(f"{texts.premium_icon(score)} <b>@{texts.esc(name)}</b> \u2014 {score}/5")
    else:
        lines += ["", t(lang, "bulk.none")]

    keyboard = (
        favorite_toggle_keyboard(lang, hits[0][0], hits[0][1])
        if hits
        else back_home_keyboard(lang)
    )
    try:
        await placeholder.edit_text("\n".join(lines), reply_markup=keyboard)
    except Exception:
        await message.answer("\n".join(lines), reply_markup=keyboard)


# --------------------------------------------------------------------- leaderboard
@router.callback_query(F.data == cb.MENU_TOP)
async def cb_top(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    names = list(await repo.recent_available_usernames(session, limit=400))
    scored = sorted(
        ((name, premium_rating(name).total) for name in set(names)),
        key=lambda pair: pair[1],
        reverse=True,
    )[:TOP_SIZE]

    await callback.answer()
    if not scored:
        text = t(lang, "top.empty")
    else:
        lines = [t(lang, "top.title"), "", t(lang, "top.body"), ""]
        for index, (name, score) in enumerate(scored, start=1):
            lines.append(t(lang, "top.line", rank=index, name=texts.esc(name), score=score))
        text = "\n".join(lines)

    if callback.message is not None:
        await show_screen(callback, bot, text, keyboard=back_home_keyboard(lang))


# --------------------------------------------------------------------- favourites
@router.callback_query(F.data.startswith(f"{cb.FAV_ADD_PREFIX}:"))
async def cb_fav_add(
    callback: CallbackQuery, session: AsyncSession, user: User, lang: str = "en"
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    username = parts[2]
    try:
        score = int(parts[3])
    except ValueError:
        score = 0

    if await repo.count_favorites(session, user.telegram_id) >= FAVORITES_MAX:
        await callback.answer(t(lang, "fav.full", max=FAVORITES_MAX), show_alert=True)
        return

    _row, created = await repo.add_favorite(session, user, username, score=score)
    await session.commit()
    await callback.answer(
        t(lang, "fav.added", name=username) if created else t(lang, "fav.exists", name=username)
    )


@router.callback_query(F.data == cb.MENU_FAVORITES)
async def cb_favorites(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    rows = list(await repo.list_favorites(session, user))
    await callback.answer()
    if not rows:
        text = t(lang, "fav.empty")
    else:
        lines = [t(lang, "fav.title"), ""]
        for row in rows[:12]:
            note = f" \u2014 {texts.esc(row.note)}" if row.note else ""
            lines.append(
                t(lang, "fav.line", icon=texts.premium_icon(row.score or 0),
                  name=texts.esc(row.username), score=row.score or 0, note=note)
            )
        text = "\n".join(lines)

    if callback.message is not None:
        await show_screen(callback, bot, text, keyboard=favorites_keyboard(lang, rows))


@router.callback_query(F.data.startswith(f"{cb.FAV_DEL_PREFIX}:"))
async def cb_fav_del(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    try:
        favorite_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    await repo.remove_favorite(session, user, favorite_id)
    await session.commit()
    rows = list(await repo.list_favorites(session, user))
    await callback.answer(t(lang, "fav.removed"))

    text = t(lang, "fav.empty") if not rows else (
        t(lang, "fav.title")
        + "\n\n"
        + "\n".join(
            t(lang, "fav.line", icon=texts.premium_icon(row.score or 0),
              name=texts.esc(row.username), score=row.score or 0, note="")
            for row in rows[:12]
        )
    )
    if callback.message is not None:
        await show_screen(callback, bot, text, keyboard=favorites_keyboard(lang, rows))
