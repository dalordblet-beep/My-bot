"""Admin panel.

Every section is functional: users, blacklist, restrictions, privileges,
statistics, search logs, access settings, bot settings, system status and the
admin audit log. Nothing here is decorative.

Note: administrators are not exempt from the onboarding gate - they pass the
language picker, captcha, channel and chat like everyone else.
"""

from __future__ import annotations

import math

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.admin_kb import (
    admin_back_keyboard,
    admin_root_keyboard,
    blacklist_keyboard,
    logs_keyboard,
    privilege_picker_keyboard,
    subscriptions_admin_keyboard,
    user_list_keyboard,
    user_profile_keyboard,
    user_search_keyboard,
)
from app.bot.keyboards.admin_kb import settings_keyboard as admin_settings_keyboard
from app.bot.middlewares.admin import AdminGuardMiddleware
from app.bot.states.states import AdminStates
from app.database import repository as repo
from app.database.models import User
from app.services import admin as admin_service
from app.services import statistics as stats_service
from app.services.access import access_guard
from app.services.i18n import t
from app.services.runtime_config import OVERRIDABLE, runtime
from app.services.subscriptions import (
    RequiredSub,
    add_subscription,
    legacy_subs,
    list_managed_subs,
    remove_subscription,
    serialize_subs,
)
from app.telegram.bot_api import lookup_chat
from app.utils.enums import Permission, Privilege
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="admin")
router.callback_query.middleware(AdminGuardMiddleware())
router.message.middleware(AdminGuardMiddleware())

PAGE = 8


def _page_count(total: int) -> int:
    return max(1, math.ceil(total / PAGE))


async def _edit(
    callback: CallbackQuery, bot: Bot, text: str, keyboard: InlineKeyboardMarkup | None
) -> None:
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


# --------------------------------------------------------------------- entry
@router.message(Command("admin"))
async def cmd_admin(message: Message, user: User, lang: str = "en") -> None:
    role = admin_service.resolve_admin_role(user)
    if role is None:
        await message.answer(t(lang, "admin.denied"))
        return
    await message.answer(
        texts.admin_root(lang, user, role.value), reply_markup=admin_root_keyboard(lang)
    )


@router.callback_query(F.data == cb.ADMIN_ROOT)
async def cb_admin_root(callback: CallbackQuery, user: User, bot: Bot, lang: str = "en") -> None:
    role = admin_service.resolve_admin_role(user)
    await callback.answer()
    await _edit(
        callback, bot,
        texts.admin_root(lang, user, role.value if role else "USER"),
        admin_root_keyboard(lang),
    )


# --------------------------------------------------------------------- users
@router.callback_query(F.data == cb.ADMIN_USERS)
async def cb_users(callback: CallbackQuery, bot: Bot, state: FSMContext, lang: str = "en") -> None:
    await state.set_state(AdminStates.waiting_user_query)
    await callback.answer()
    await _edit(
        callback, bot,
        f"{t(lang, 'admin.users_title')}\n\n{t(lang, 'admin.users_hint')}",
        user_search_keyboard(lang),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_USERLIST_PAGE_PREFIX}:"))
async def cb_user_list(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext, lang: str = "en"
) -> None:
    await state.clear()
    page = _parse_page(callback.data)
    total = await repo.count_users(session)
    pages = _page_count(total)
    page = max(0, min(page, pages - 1))
    users = await repo.list_users(session, offset=page * PAGE, limit=PAGE)
    await callback.answer()
    await _edit(
        callback, bot,
        f"{t(lang, 'admin.users_count', n=total)}\n"
        f"{t(lang, 'admin.users_page', page=page + 1, total=pages)}",
        user_list_keyboard(lang, list(users), page, pages, cb.ADMIN_USERLIST_PAGE_PREFIX),
    )


@router.message(AdminStates.waiting_user_query, F.text)
async def on_user_query(
    message: Message, session: AsyncSession, state: FSMContext, lang: str = "en"
) -> None:
    query = (message.text or "").strip()
    await state.clear()
    users = await repo.search_users(session, query, limit=10)
    if not users:
        await message.answer(t(lang, "admin.not_found"), reply_markup=admin_back_keyboard(lang))
        return
    await message.answer(
        t(lang, "admin.found", n=len(users)),
        reply_markup=user_list_keyboard(lang, list(users), 0, 1, cb.ADMIN_USERLIST_PAGE_PREFIX),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_USER_PREFIX}:"))
async def cb_user_profile(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    target = await _load_target(session, callback.data)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return
    await callback.answer()
    await _edit(
        callback, bot,
        texts.admin_user_profile(lang, target, target.search_count or 0),
        user_profile_keyboard(lang, target),
    )


# --------------------------------------------------------------------- blacklist
@router.callback_query(F.data == cb.ADMIN_BLACKLIST)
async def cb_blacklist(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    await _render_blacklist(callback, session, bot, 0, lang)


@router.callback_query(F.data.startswith(f"{cb.ADMIN_BLACKLIST_PAGE_PREFIX}:"))
async def cb_blacklist_page(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    await _render_blacklist(callback, session, bot, _parse_page(callback.data), lang)


async def _render_blacklist(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, page: int, lang: str
) -> None:
    total = await repo.count_users(session, only_banned=True)
    pages = _page_count(total)
    page = max(0, min(page, pages - 1))
    users = await repo.list_users(session, offset=page * PAGE, limit=PAGE, only_banned=True)
    await callback.answer()
    if not users:
        await _edit(callback, bot, t(lang, "admin.blacklist_empty"), admin_back_keyboard(lang))
        return
    await _edit(
        callback, bot,
        t(lang, "admin.blacklist_title", n=total)
        + "\n"
        + t(lang, "admin.users_page", page=page + 1, total=pages),
        blacklist_keyboard(lang, list(users), page, pages),
    )


# --------------------------------------------------------------------- restrictions
@router.callback_query(F.data == cb.ADMIN_RESTRICTIONS)
async def cb_restrictions(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    total = await repo.count_restricted_users(session)
    users = await repo.list_restricted_users(session, offset=0, limit=PAGE)
    await callback.answer()
    if not users:
        await _edit(
            callback, bot, t(lang, "admin.restrictions_empty"), admin_back_keyboard(lang)
        )
        return
    await _edit(
        callback, bot,
        t(lang, "admin.restrictions_title", n=total),
        user_list_keyboard(lang, list(users), 0, 1, cb.ADMIN_USERLIST_PAGE_PREFIX),
    )


# --------------------------------------------------------------------- privileges
@router.callback_query(F.data == cb.ADMIN_PRIVILEGES)
async def cb_privileges(
    callback: CallbackQuery, bot: Bot, state: FSMContext, lang: str = "en"
) -> None:
    await state.set_state(AdminStates.waiting_privilege_target)
    await callback.answer()
    await _edit(
        callback, bot,
        f"{t(lang, 'admin.privileges_title')}\n\n{t(lang, 'admin.privileges_hint')}",
        admin_back_keyboard(lang),
    )


@router.message(AdminStates.waiting_privilege_target, F.text)
async def on_privilege_target(
    message: Message, session: AsyncSession, state: FSMContext, lang: str = "en"
) -> None:
    query = (message.text or "").strip()
    await state.clear()
    users = await repo.search_users(session, query, limit=5)
    if not users:
        await message.answer(t(lang, "admin.not_found"), reply_markup=admin_back_keyboard(lang))
        return
    target = users[0]
    name = f"@{texts.esc(target.username)}" if target.username else target.telegram_id
    await message.answer(
        f"{t(lang, 'admin.user')}: <b>{name}</b>\n"
        f"{t(lang, 'admin.privileges_current', value=target.privilege)}",
        reply_markup=privilege_picker_keyboard(lang, target.telegram_id),
    )


# --------------------------------------------------------------------- user actions
@router.callback_query(F.data.startswith(f"{cb.ADMIN_BAN_PREFIX}:"))
async def cb_ban(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext, lang: str = "en"
) -> None:
    target = await _load_target(session, callback.data)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.waiting_ban_reason)
    await state.update_data(target_id=target.telegram_id)
    await _edit(callback, bot, texts.admin_ban_prompt(lang, target), admin_back_keyboard(lang))


@router.message(AdminStates.waiting_ban_reason, F.text)
async def on_ban_reason(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str = "en"
) -> None:
    data = await state.get_data()
    target = await _get_by_id(session, data.get("target_id"))
    await state.clear()
    if target is None:
        await message.answer(t(lang, "admin.not_found"), reply_markup=admin_back_keyboard(lang))
        return

    if not admin_service.has_permission(user, Permission.ADMIN_BLACKLIST):
        await message.answer(t(lang, "admin.denied"), reply_markup=admin_back_keyboard(lang))
        return

    raw = (message.text or "").strip()
    reason = None if raw in ("/skip", "-") else raw
    await admin_service.ban(session, user, target, reason)
    await message.answer(
        t(lang, "admin.blocked", id=target.telegram_id),
        reply_markup=admin_back_keyboard(lang),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_UNBAN_PREFIX}:"))
async def cb_unban(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, user: User, lang: str = "en"
) -> None:
    target = await _load_target(session, callback.data)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return
    if not admin_service.has_permission(user, Permission.ADMIN_RESTRICTIONS):
        await callback.answer(t(lang, "admin.not_authorized"), show_alert=True)
        return
    await admin_service.unban(session, user, target)
    await callback.answer("\u2705")
    await _edit(
        callback, bot,
        texts.admin_user_profile(lang, target, target.search_count or 0),
        user_profile_keyboard(lang, target),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_RESTRICT_PREFIX}:"))
async def cb_restrict(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, user: User, lang: str = "en"
) -> None:
    target_id, raw_seconds = _parse_id_and_value(callback.data)
    if target_id is None or raw_seconds is None:
        await callback.answer()
        return
    try:
        seconds = int(raw_seconds)
    except ValueError:
        await callback.answer()
        return

    target = await _get_by_id(session, target_id)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return
    if not admin_service.has_permission(user, Permission.ADMIN_RESTRICTIONS):
        await callback.answer(t(lang, "admin.not_authorized"), show_alert=True)
        return

    await admin_service.restrict(session, user, target, seconds, reason=None)
    await callback.answer(f"\u23F3 {seconds // 60} min")
    await _edit(
        callback, bot,
        texts.admin_user_profile(lang, target, target.search_count or 0),
        user_profile_keyboard(lang, target),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_CLEAR_PREFIX}:"))
async def cb_clear(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, user: User, lang: str = "en"
) -> None:
    target = await _load_target(session, callback.data)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return
    if not admin_service.has_permission(user, Permission.ADMIN_RESTRICTIONS):
        await callback.answer(t(lang, "admin.not_authorized"), show_alert=True)
        return
    await admin_service.clear_restrictions(session, user, target)
    await callback.answer("\u2705")
    await _edit(
        callback, bot,
        texts.admin_user_profile(lang, target, target.search_count or 0),
        user_profile_keyboard(lang, target),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_PRIV_PREFIX}:"))
async def cb_privilege(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, user: User, lang: str = "en"
) -> None:
    target_id, raw_privilege = _parse_id_and_value(callback.data)
    if target_id is None or raw_privilege is None:
        await callback.answer()
        return

    if not admin_service.has_permission(user, Permission.ADMIN_PRIVILEGES):
        await callback.answer(t(lang, "admin.not_authorized"), show_alert=True)
        return
    if raw_privilege not in Privilege._value2member_map_:
        await callback.answer(t(lang, "settings.unknown"), show_alert=True)
        return

    target = await _get_by_id(session, target_id)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return

    await admin_service.grant_privilege(session, user, target, Privilege(raw_privilege))
    await callback.answer(f"\u2705 {raw_privilege}")
    await _edit(
        callback, bot,
        texts.admin_user_profile(lang, target, target.search_count or 0),
        user_profile_keyboard(lang, target),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_NOTE_PREFIX}:"))
async def cb_note(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext, lang: str = "en"
) -> None:
    target = await _load_target(session, callback.data)
    if target is None:
        await callback.answer(t(lang, "admin.user_not_found"), show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.waiting_note)
    await state.update_data(target_id=target.telegram_id)
    await _edit(callback, bot, texts.admin_note_prompt(lang, target), admin_back_keyboard(lang))


@router.message(AdminStates.waiting_note, F.text)
async def on_note(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str = "en"
) -> None:
    data = await state.get_data()
    target = await _get_by_id(session, data.get("target_id"))
    await state.clear()
    if target is None:
        await message.answer(t(lang, "admin.not_found"), reply_markup=admin_back_keyboard(lang))
        return
    await admin_service.set_note(session, user, target, (message.text or "").strip()[:500])
    await message.answer(t(lang, "admin.note_saved"), reply_markup=admin_back_keyboard(lang))


@router.callback_query(F.data.startswith(f"{cb.ADMIN_ACTIONS_PREFIX}:"))
async def cb_actions(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    target_id = _parse_target_id(callback.data)
    if target_id is None:
        await callback.answer()
        return
    actions = await repo.list_admin_actions_for_user(session, target_id, limit=15)
    await callback.answer()
    if not actions:
        await _edit(callback, bot, t(lang, "admin.no_actions"), admin_back_keyboard(lang))
        return
    body = t(lang, "admin.actions_title") + "\n\n" + "\n\n".join(
        texts.admin_action_line(lang, action) for action in actions
    )
    await _edit(callback, bot, body, admin_back_keyboard(lang))


# --------------------------------------------------------------------- statistics / logs / system
@router.callback_query(F.data == cb.ADMIN_STATS)
async def cb_stats(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    stats = await stats_service.gather(session)
    await callback.answer()
    await _edit(callback, bot, texts.statistics_screen(lang, stats), admin_back_keyboard(lang))


@router.callback_query(F.data == cb.ADMIN_LOGS)
async def cb_logs(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    await _render_search_logs(callback, session, bot, 0, lang)


@router.callback_query(F.data.startswith(f"{cb.ADMIN_LOGS_PAGE_PREFIX}:"))
async def cb_logs_page(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    await _render_search_logs(callback, session, bot, _parse_page(callback.data), lang)


async def _render_search_logs(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, page: int, lang: str
) -> None:
    total = await repo.count_all_searches(session)
    pages = _page_count(total)
    page = max(0, min(page, pages - 1))
    rows = await repo.list_recent_searches(session, offset=page * PAGE, limit=PAGE)
    await callback.answer()
    if not rows:
        await _edit(callback, bot, t(lang, "admin.logs_empty"), admin_back_keyboard(lang))
        return
    lines = [t(lang, "admin.logs_title"), ""]
    for row in rows:
        stamp = row.created_at.strftime("%d.%m %H:%M") if row.created_at else "-"
        lines.append(f"<code>{stamp}</code>  {texts.esc(row.query)}  \u2022  {texts.esc(row.mode)}")
    lines += ["", t(lang, "admin.users_page", page=page + 1, total=pages)]
    await _edit(
        callback, bot, "\n".join(lines), logs_keyboard(lang, page, pages, cb.ADMIN_LOGS_PAGE_PREFIX)
    )


@router.callback_query(F.data == cb.ADMIN_ACTION_LOGS)
async def cb_action_logs(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    await _render_action_logs(callback, session, bot, 0, lang)


@router.callback_query(F.data.startswith(f"{cb.ADMIN_ACTIONLOG_PAGE_PREFIX}:"))
async def cb_action_logs_page(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, lang: str = "en"
) -> None:
    await _render_action_logs(callback, session, bot, _parse_page(callback.data), lang)


async def _render_action_logs(
    callback: CallbackQuery, session: AsyncSession, bot: Bot, page: int, lang: str
) -> None:
    total = await repo.count_admin_actions(session)
    pages = _page_count(total)
    page = max(0, min(page, pages - 1))
    rows = await repo.list_admin_actions(session, offset=page * PAGE, limit=PAGE)
    await callback.answer()
    if not rows:
        await _edit(callback, bot, t(lang, "admin.alogs_empty"), admin_back_keyboard(lang))
        return
    body = t(lang, "admin.alogs_title") + "\n\n" + "\n\n".join(
        texts.admin_action_line(lang, row) for row in rows
    )
    body += "\n\n" + t(lang, "admin.users_page", page=page + 1, total=pages)
    await _edit(
        callback, bot, body,
        logs_keyboard(lang, page, pages, cb.ADMIN_ACTIONLOG_PAGE_PREFIX),
    )


@router.callback_query(F.data == cb.ADMIN_ACCESS)
async def cb_access(callback: CallbackQuery, bot: Bot, lang: str = "en") -> None:
    await callback.answer()
    managed = list_managed_subs()
    # The legacy .env pair applies only when no runtime-managed list exists;
    # required_subs() ignores it once the JSON list is non-empty.
    legacy = legacy_subs() if not managed else []
    await _edit(
        callback, bot,
        texts.subscriptions_admin_screen(lang, managed, legacy),
        subscriptions_admin_keyboard(lang, managed),
    )


@router.callback_query(F.data == cb.ADMIN_SUB_ADD)
async def cb_sub_add(
    callback: CallbackQuery, bot: Bot, state: FSMContext, user: User, lang: str = "en"
) -> None:
    if not admin_service.has_permission(user, Permission.ADMIN_SETTINGS):
        await callback.answer(t(lang, "admin.not_authorized"), show_alert=True)
        return
    await state.set_state(AdminStates.waiting_subscription_target)
    await callback.answer()
    await _edit(
        callback, bot,
        f"{t(lang, 'admin.subs_add_prompt')}\n\n<code>{t(lang, 'admin.subs_add_help')}</code>",
        admin_back_keyboard(lang, cb.ADMIN_ACCESS),
    )


@router.message(AdminStates.waiting_subscription_target, F.text)
async def on_subscription_target(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext, lang: str = "en"
) -> None:
    await state.clear()
    if not admin_service.has_permission(user, Permission.ADMIN_SETTINGS):
        await message.answer(t(lang, "admin.denied"), reply_markup=admin_back_keyboard(lang, cb.ADMIN_ACCESS))
        return

    raw = (message.text or "").strip()
    chat_ref, invite_url = _parse_channel_input(raw)
    if chat_ref is None:
        await message.answer(
            t(lang, "admin.subs_invalid"),
            reply_markup=admin_back_keyboard(lang, cb.ADMIN_ACCESS),
        )
        return

    resolved = await lookup_chat(bot, chat_ref)
    if resolved.found:
        title = resolved.title or (f"@{raw.lstrip('@')}" if raw.startswith("@") else raw)
        key = (raw.lstrip("@").split("/")[-1] if raw.startswith("@") else str(resolved.chat_id))
        sub = RequiredSub(
            key=key,
            chat_id=resolved.chat_id or 0,
            username=(raw.lstrip("@") if raw.startswith("@") else ""),
            invite_url=invite_url or "",
            label=title,
        )
        existing = list_managed_subs()
        if any(s.key == sub.key or (sub.username and s.username == sub.username) for s in existing):
            await message.answer(
                t(lang, "admin.subs_duplicate", title=title),
                reply_markup=admin_back_keyboard(lang, cb.ADMIN_ACCESS),
            )
            return
        new_list = await add_subscription(session, sub)
        await admin_service.update_bot_setting(session, user, "required_subscriptions", serialize_subs(new_list))
        await message.answer(
            t(lang, "admin.subs_added", title=title),
            reply_markup=admin_back_keyboard(lang, cb.ADMIN_ACCESS),
        )
        return

    # Private invite we could not resolve: still usable as a join button.
    if invite_url:
        sub = RequiredSub(key=invite_url.split("/")[-1] or "invite", invite_url=invite_url, label=invite_url)
        await add_subscription(session, sub)
        await message.answer(
            t(lang, "admin.subs_added", title=invite_url),
            reply_markup=admin_back_keyboard(lang, cb.ADMIN_ACCESS),
        )
        return

    await message.answer(
        t(lang, "admin.subs_failed"),
        reply_markup=admin_back_keyboard(lang, cb.ADMIN_ACCESS),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_SUB_REMOVE_PREFIX}:"))
async def cb_sub_remove(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    if not admin_service.has_permission(user, Permission.ADMIN_SETTINGS):
        await callback.answer(t(lang, "admin.not_authorized"), show_alert=True)
        return
    key = (callback.data or "").split(":", 2)[-1]
    existing = list_managed_subs()
    target = next((s for s in existing if s.key == key), None)
    if target is None:
        await callback.answer(t(lang, "admin.subs_invalid"), show_alert=True)
        return
    await remove_subscription(session, key)
    await admin_service.update_bot_setting(session, user, "required_subscriptions", serialize_subs([s for s in existing if s.key != key]))
    await callback.answer(t(lang, "admin.subs_removed", title=target.label or target.username or target.key))
    await callback.answer(t(lang, "admin.subs_removed", title=target.label or target.username or target.key))
    managed = list_managed_subs()
    legacy = legacy_subs() if not managed else []
    await _edit(
        callback, bot,
        texts.subscriptions_admin_screen(lang, managed, legacy),
        subscriptions_admin_keyboard(lang, managed),
    )


@router.callback_query(F.data == cb.ADMIN_SETTINGS)
async def cb_settings(callback: CallbackQuery, bot: Bot, lang: str = "en") -> None:
    await callback.answer()
    pairs = [(key, label) for key, (_, label, _) in OVERRIDABLE.items()]
    await _edit(
        callback, bot,
        f"{t(lang, 'admin.settings_title')}\n\n{t(lang, 'admin.settings_hint')}",
        admin_settings_keyboard(lang, pairs),
    )


@router.callback_query(F.data.startswith(f"{cb.ADMIN_SETTING_PREFIX}:"))
async def cb_setting(
    callback: CallbackQuery, bot: Bot, state: FSMContext, lang: str = "en"
) -> None:
    key = (callback.data or "").split(":", 2)[-1]
    if key not in OVERRIDABLE:
        await callback.answer(t(lang, "admin.setting_unknown"), show_alert=True)
        return
    current = runtime.get(key)
    await callback.answer()
    await state.set_state(AdminStates.waiting_setting_value)
    await state.update_data(setting_key=key)
    await _edit(
        callback, bot,
        texts.admin_setting_prompt(lang, key, str(current)),
        admin_back_keyboard(lang, cb.ADMIN_SETTINGS),
    )


@router.message(AdminStates.waiting_setting_value, F.text)
async def on_setting_value(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lang: str = "en"
) -> None:
    data = await state.get_data()
    key = data.get("setting_key")
    await state.clear()
    if key not in OVERRIDABLE:
        await message.answer(t(lang, "admin.setting_unknown"), reply_markup=admin_back_keyboard(lang))
        return
    if not admin_service.has_permission(user, Permission.ADMIN_SETTINGS):
        await message.answer(t(lang, "admin.denied"), reply_markup=admin_back_keyboard(lang))
        return

    raw = (message.text or "").strip()
    try:
        if raw == "/reset":
            await runtime.reset(session, key)
            await admin_service.update_bot_setting(session, user, key, "")
            await message.answer(
                t(lang, "admin.setting_reset", key=texts.esc(key)),
                reply_markup=admin_back_keyboard(lang, cb.ADMIN_SETTINGS),
            )
            return
        value = await runtime.set(session, key, raw)
        await admin_service.update_bot_setting(session, user, key, str(value))
        await message.answer(
            t(lang, "admin.setting_saved", key=texts.esc(key), value=texts.esc(value)),
            reply_markup=admin_back_keyboard(lang, cb.ADMIN_SETTINGS),
        )
    except (ValueError, TypeError):
        await message.answer(
            t(lang, "admin.setting_invalid"),
            reply_markup=admin_back_keyboard(lang, cb.ADMIN_SETTINGS),
        )


@router.callback_query(F.data == cb.ADMIN_SYSTEM)
async def cb_system(
    callback: CallbackQuery, bot: Bot, cache_service=None, lang: str = "en"
) -> None:
    status = await stats_service.system_status(bot, cache_service)
    await callback.answer()
    await _edit(callback, bot, texts.system_screen(lang, status), admin_back_keyboard(lang))


# --------------------------------------------------------------------- helpers
def _parse_page(data: str | None) -> int:
    try:
        return int((data or "").split(":")[-1])
    except ValueError:
        return 0


def _parse_target_id(data: str | None) -> int | None:
    """Target id is always the last segment: ``adm:ban:<id>``."""
    parts = (data or "").split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


def _parse_id_and_value(data: str | None) -> tuple[int | None, str | None]:
    """For ``adm:restrict:<id>:<seconds>`` style payloads."""
    parts = (data or "").split(":")
    if len(parts) < 3:
        return None, None
    try:
        return int(parts[-2]), parts[-1]
    except ValueError:
        return None, None


def _parse_channel_input(raw: str) -> tuple[int | str | None, str | None]:
    """Turn admin free-text into a chat reference Telegram can resolve.

    Accepts ``@username``, a ``t.me`` link (public or private ``+`` invite),
    or a numeric id. Returns ``(chat_ref, invite_url)`` where ``chat_ref`` is
    what ``bot.get_chat`` accepts and ``invite_url`` is the join link to keep
    for private channels. ``(None, None)`` means the input was unrecognised.
    """
    text = (raw or "").strip()
    lowered = text.lower()

    if "t.me/" in lowered:
        tail = text.split("t.me/", 1)[-1].strip().strip("/")
        if tail.startswith("+"):
            invite = f"https://t.me/{tail}"
            return invite, invite
        if tail:
            return f"@{tail}", f"https://t.me/{tail}"
        return None, None

    if text.startswith("@"):
        username = text.lstrip("@")
        if username:
            return text, f"https://t.me/{username}"
        return None, None

    if text.lstrip("-").isdigit():
        try:
            return int(text), None
        except ValueError:
            return None, None

    # Bare word: treat as a username without the leading @.
    if text and not text.startswith("/") and " " not in text:
        return f"@{text}", f"https://t.me/{text}"

    return None, None


async def _get_by_id(session: AsyncSession, telegram_id: int | None) -> User | None:
    if telegram_id is None:
        return None
    return await repo.get_user_by_telegram_id(session, telegram_id)


async def _load_target(session: AsyncSession, data: str | None) -> User | None:
    return await _get_by_id(session, _parse_target_id(data))
