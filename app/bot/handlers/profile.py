"""Profile screen."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.features_kb import back_home_keyboard, profile_keyboard
from app.database import repository as repo
from app.database.models import User
from app.services import user as user_service
from app.services.achievements import AchievementStats, evaluate, summary as ach_summary
from app.services.i18n import normalise
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="profile")


@router.callback_query(F.data == cb.MENU_PROFILE)
async def cb_profile(
    callback: CallbackQuery, session: AsyncSession, user: User, lang: str = "en"
) -> None:
    row = await user_service.get_settings_row(session, user)
    stats = {
        "checks": user.search_count or 0,
        "searches": await repo.count_searches(session, user.id),
        "traps": await repo.count_active_traps(session, user.telegram_id),
        "battles": await repo.count_user_battles(session, user.telegram_id),
        "best_find": await repo.latest_available_username(session),
        "favorites": await repo.count_favorites(session, user.telegram_id),
        "language": normalise(row.language or lang),
    }
    ach_stats = AchievementStats(
        checks=user.search_count or 0,
        searches=stats["searches"],
        free_found=await repo.count_checks_by_status(session, "AVAILABLE"),
        collectible_found=await repo.count_collectible_checks(session),
        traps_created=await repo.count_traps_created(session, user.telegram_id),
        traps_fired=await repo.count_traps_fired(session, user.telegram_id),
        battles=stats["battles"],
        battles_won=await repo.count_battles_won(session, user.telegram_id),
        best_score=0,
        favorites=stats["favorites"],
    )
    done, total = ach_summary(ach_stats)
    stats["achievements"] = evaluate(ach_stats)
    stats["achievements_done"] = done
    stats["achievements_total"] = total

    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            texts.profile_screen(lang, user, stats), reply_markup=profile_keyboard(lang)
        )


@router.callback_query(F.data == cb.PROFILE_ACH)
async def cb_achievements(
    callback: CallbackQuery, session: AsyncSession, user: User, lang: str = "en"
) -> None:
    """Recomputed on demand - it is a handful of cheap count queries."""
    stats = await _achievement_stats(session, user)
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            texts.profile_achievements(lang, stats), reply_markup=profile_keyboard(lang)
        )


async def _achievement_stats(session: AsyncSession, user: User) -> dict:
    stats_row = await user_service.get_settings_row(session, user)
    ach_stats = AchievementStats(
        checks=user.search_count or 0,
        searches=await repo.count_searches(session, user.id),
        free_found=await repo.count_checks_by_status(session, "AVAILABLE"),
        collectible_found=await repo.count_collectible_checks(session),
        traps_created=await repo.count_traps_created(session, user.telegram_id),
        traps_fired=await repo.count_traps_fired(session, user.telegram_id),
        battles=await repo.count_user_battles(session, user.telegram_id),
        battles_won=await repo.count_battles_won(session, user.telegram_id),
        best_score=0,
        favorites=await repo.count_favorites(session, user.telegram_id),
    )
    done, total = ach_summary(ach_stats)
    return {
        "achievements": evaluate(ach_stats),
        "achievements_done": done,
        "achievements_total": total,
        "language": normalise(stats_row.language or lang),
    }
