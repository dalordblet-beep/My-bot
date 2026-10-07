"""Admin service: role resolution, permission checks and privileged actions.

Every privileged action is (a) permission-checked and (b) written to the admin
audit log. Callbacks are never trusted - the caller passes a freshly loaded
``User`` row, and the role is resolved from the database, not from the payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import repository as repo
from app.database.models import User
from app.utils.enums import (
    AdminRole,
    Permission,
    Privilege,
    admin_permissions_for,
    permissions_for,
)
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


def resolve_admin_role(user: User) -> AdminRole | None:
    """SUPERADMIN comes from ADMIN_IDS, ADMIN from the stored privilege."""
    if user.telegram_id in settings.admin_id_set:
        return AdminRole.SUPERADMIN
    if user.privilege == Privilege.ADMIN.value:
        if user.admin_role in AdminRole._value2member_map_:
            return AdminRole(user.admin_role)
        return AdminRole.ADMIN
    return None


def is_admin(user: User) -> bool:
    return resolve_admin_role(user) is not None


def has_permission(user: User, permission: Permission) -> bool:
    role = resolve_admin_role(user)
    if role is not None and permission in admin_permissions_for(role):
        return True
    try:
        privilege = Privilege(user.privilege)
    except ValueError:
        privilege = Privilege.FREE
    return permission in permissions_for(privilege)


def role_label(role: AdminRole | None) -> str:
    return role.value if role else "USER"


# --------------------------------------------------------------------------- actions
async def ban(
    session: AsyncSession, actor: User, target: User, reason: str | None
) -> None:
    await repo.ban_user(session, target, reason=reason, admin_id=actor.telegram_id)
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="ban",
        target_user_id=target.telegram_id,
        reason=reason,
    )
    logger.info("admin=%s banned user=%s", actor.telegram_id, target.telegram_id)


async def unban(session: AsyncSession, actor: User, target: User) -> None:
    await repo.unban_user(session, target)
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="unban",
        target_user_id=target.telegram_id,
    )
    logger.info("admin=%s unbanned user=%s", actor.telegram_id, target.telegram_id)


async def restrict(
    session: AsyncSession,
    actor: User,
    target: User,
    seconds: int,
    reason: str | None,
) -> datetime:
    until = await repo.restrict_user(
        session, target, seconds=seconds, reason=reason, admin_id=actor.telegram_id
    )
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="restrict",
        target_user_id=target.telegram_id,
        reason=reason,
        metadata={"seconds": seconds, "until": until.isoformat()},
    )
    logger.info(
        "admin=%s restricted user=%s for %ss", actor.telegram_id, target.telegram_id, seconds
    )
    return until


async def clear_restrictions(session: AsyncSession, actor: User, target: User) -> None:
    await repo.unban_user(session, target)
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="clear_restrictions",
        target_user_id=target.telegram_id,
    )


async def grant_privilege(
    session: AsyncSession, actor: User, target: User, privilege: Privilege
) -> None:
    await repo.set_privilege(session, target, privilege)
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="grant_privilege",
        target_user_id=target.telegram_id,
        metadata={"privilege": privilege.value},
    )
    logger.info(
        "admin=%s granted %s to user=%s", actor.telegram_id, privilege.value, target.telegram_id
    )


async def set_admin_role(
    session: AsyncSession, actor: User, target: User, role: AdminRole
) -> None:
    target.admin_role = role.value
    if role is not None and target.privilege != Privilege.ADMIN.value:
        target.privilege = Privilege.ADMIN.value
    await session.flush()
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="set_admin_role",
        target_user_id=target.telegram_id,
        metadata={"role": role.value},
    )


async def set_note(session: AsyncSession, actor: User, target: User, note: str) -> None:
    target.admin_note = note
    await session.flush()
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="set_note",
        target_user_id=target.telegram_id,
        metadata={"note": note[:200]},
    )


async def update_bot_setting(
    session: AsyncSession, actor: User, key: str, value: str
) -> None:
    await repo.set_bot_setting(session, key, value)
    await repo.log_admin_action(
        session,
        admin_id=actor.telegram_id,
        action="update_bot_setting",
        metadata={"key": key, "value": value},
    )
    logger.info("admin=%s updated bot setting %s", actor.telegram_id, key)


async def snapshot(session: AsyncSession) -> dict[str, Any]:
    return await repo.all_bot_settings(session)
