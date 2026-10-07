"""User-facing service layer."""

from __future__ import annotations

from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import repository as repo
from app.database.models import User, UserSetting
from app.utils.enums import Privilege


async def ensure_user(session: AsyncSession, tg_user: TgUser) -> tuple[User, bool]:
    """Create or refresh the local record for a Telegram user."""
    user, created = await repo.get_or_create_user(
        session,
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    await repo.touch_last_seen(session, user)
    return user, created


async def ensure_admin_privilege(session: AsyncSession, user: User, admin_ids: set[int]) -> bool:
    """Promote configured ADMIN_IDS to the ADMIN privilege once."""
    if user.telegram_id in admin_ids and user.privilege != Privilege.ADMIN.value:
        await repo.set_privilege(session, user, Privilege.ADMIN)
        return True
    return False


async def get_settings_row(session: AsyncSession, user: User) -> UserSetting:
    return await repo.get_user_settings(session, user.id)


async def update_settings(session: AsyncSession, user: User, **fields) -> UserSetting:
    return await repo.update_user_settings(session, user.id, **fields)


def describe_privilege(privilege: str) -> str:
    labels = {
        Privilege.FREE.value: "FREE",
        Privilege.VIP.value: "VIP",
        Privilege.PREMIUM.value: "PREMIUM",
        Privilege.ADMIN.value: "ADMIN",
    }
    return labels.get(privilege, privilege)
