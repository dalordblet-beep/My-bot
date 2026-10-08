"""Data access layer. Every function takes an explicit AsyncSession."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AdminAction,
    Battle,
    BotSetting,
    Favorite,
    FreeName,
    PortfolioItem,
    Search,
    Trap,
    User,
    UsernameCacheRow,
    UsernameCheck,
    UserSetting,
    utcnow,
)
from app.utils.enums import CheckStatus, Privilege, UsernameType


# --------------------------------------------------------------------------- users
async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> tuple[User, bool]:
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is not None:
        changed = False
        if username is not None and user.username != username:
            user.username = username
            changed = True
        if first_name is not None and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if changed:
            await session.flush()
        return user, False

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        privilege=Privilege.FREE.value,
        created_at=utcnow(),
        last_seen=utcnow(),
    )
    session.add(user)
    await session.flush()
    session.add(UserSetting(user_id=user.id))
    await session.flush()
    return user, True


async def touch_last_seen(session: AsyncSession, user: User) -> None:
    user.last_seen = utcnow()
    await session.flush()


async def set_captcha_verified(session: AsyncSession, user: User, when: datetime | None = None) -> None:
    user.captcha_verified_at = when or utcnow()
    await session.flush()


async def set_sub_verified(
    session: AsyncSession, user: User, key: str, when: datetime | None = None
) -> None:
    """Record that a required subscription is joined.

    channel/chat are mirrored into their dedicated columns so older code and the
    admin panel keep seeing them.
    """
    moment = when or utcnow()
    current = dict(user.subscriptions_verified or {})
    current[key] = moment.isoformat()
    user.subscriptions_verified = current
    if key == "channel":
        user.channel_verified_at = moment
    elif key == "chat":
        user.chat_verified_at = moment
    await session.flush()


async def clear_sub_verified(session: AsyncSession, user: User, key: str) -> None:
    current = dict(user.subscriptions_verified or {})
    if key in current:
        current.pop(key, None)
        user.subscriptions_verified = current
    if key == "channel":
        user.channel_verified_at = None
    elif key == "chat":
        user.chat_verified_at = None
    await session.flush()


def sub_verified_at(user: User, key: str) -> datetime | None:
    """When this subscription was last confirmed, or None."""
    raw = (user.subscriptions_verified or {}).get(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


async def set_channel_verified(session: AsyncSession, user: User) -> None:
    await set_sub_verified(session, user, "channel")


async def set_chat_verified(session: AsyncSession, user: User) -> None:
    await set_sub_verified(session, user, "chat")


async def increment_search_count(session: AsyncSession, user: User, amount: int = 1) -> None:
    user.search_count = (user.search_count or 0) + amount
    await session.flush()


async def set_privilege(session: AsyncSession, user: User, privilege: Privilege) -> None:
    user.privilege = privilege.value
    await session.flush()


async def search_users(
    session: AsyncSession, query: str, limit: int = 10
) -> Sequence[User]:
    """Find users by numeric telegram id or by (partial) username."""
    query = query.strip().lstrip("@")
    stmt = select(User)
    if query.lstrip("-").isdigit():
        stmt = stmt.where(User.telegram_id == int(query))
    else:
        stmt = stmt.where(func.lower(User.username).like(f"%{query.lower()}%"))
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_users(
    session: AsyncSession, offset: int = 0, limit: int = 10, only_banned: bool = False
) -> Sequence[User]:
    stmt = select(User).order_by(User.created_at.desc())
    if only_banned:
        stmt = stmt.where(User.is_banned.is_(True))
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_users(session: AsyncSession, only_banned: bool = False) -> int:
    stmt = select(func.count(User.id))
    if only_banned:
        stmt = stmt.where(User.is_banned.is_(True))
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def list_restricted_users(
    session: AsyncSession, offset: int = 0, limit: int = 10
) -> Sequence[User]:
    stmt = (
        select(User)
        .where(User.ban_until.is_not(None), User.ban_until > utcnow())
        .order_by(User.ban_until.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_restricted_users(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(User.id)).where(
            User.ban_until.is_not(None), User.ban_until > utcnow()
        )
    )
    return int(result.scalar_one())


async def ban_user(
    session: AsyncSession,
    user: User,
    *,
    reason: str | None,
    admin_id: int,
    until: datetime | None = None,
) -> None:
    user.is_banned = until is None
    user.ban_until = until
    user.ban_reason = reason
    user.banned_by = admin_id
    await session.flush()


async def restrict_user(
    session: AsyncSession,
    user: User,
    *,
    seconds: int,
    reason: str | None,
    admin_id: int,
) -> datetime:
    until = utcnow() + timedelta(seconds=seconds)
    user.ban_until = until
    user.is_banned = False
    user.ban_reason = reason
    user.banned_by = admin_id
    await session.flush()
    return until


async def unban_user(session: AsyncSession, user: User) -> None:
    user.is_banned = False
    user.ban_until = None
    user.ban_reason = None
    user.banned_by = None
    await session.flush()


def restriction_active(user: User) -> bool:
    if user.ban_until is None:
        return False
    until = user.ban_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > utcnow()


# --------------------------------------------------------------------------- searches
async def add_search(session: AsyncSession, user: User, query: str, mode: str) -> Search:
    row = Search(user_id=user.id, query=query, mode=mode)
    session.add(row)
    await session.flush()
    return row


async def list_searches(
    session: AsyncSession, user_id: int, offset: int = 0, limit: int = 10
) -> Sequence[Search]:
    stmt = (
        select(Search)
        .where(Search.user_id == user_id)
        .order_by(Search.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_searches(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count(Search.id)).where(Search.user_id == user_id)
    )
    return int(result.scalar_one())


async def count_all_searches(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(Search.id)))
    return int(result.scalar_one())


async def list_recent_searches(
    session: AsyncSession, offset: int = 0, limit: int = 10
) -> Sequence[Search]:
    stmt = select(Search).order_by(Search.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


# --------------------------------------------------------------------------- username checks
async def record_username_check(
    session: AsyncSession,
    *,
    username: str,
    status: str,
    type_: str,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> UsernameCheck:
    row = UsernameCheck(
        username=username.lower(),
        status=status,
        type=type_,
        source=source,
        meta=metadata,
    )
    session.add(row)
    await session.flush()
    return row


async def count_username_checks(session: AsyncSession, type_: str | None = None) -> int:
    stmt = select(func.count(UsernameCheck.id))
    if type_:
        stmt = stmt.where(UsernameCheck.type == type_)
    result = await session.execute(stmt)
    return int(result.scalar_one())


# --------------------------------------------------------------------------- settings
async def get_user_settings(session: AsyncSession, user_id: int) -> UserSetting:
    result = await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSetting(user_id=user_id)
        session.add(row)
        await session.flush()
    return row


async def update_user_settings(
    session: AsyncSession, user_id: int, **fields: Any
) -> UserSetting:
    row = await get_user_settings(session, user_id)
    for key, value in fields.items():
        # ``None`` means "leave alone" - callers pass real values, including
        # False and 0, which must be written.
        if hasattr(row, key) and value is not None:
            setattr(row, key, value)
    await session.flush()
    return row


async def list_daily_drop_subscribers(
    session: AsyncSession,
) -> list[tuple[int, str]]:
    """Telegram id + language for every active subscriber.

    Used by the Daily Drop scheduler, which enqueues one search per subscriber.
    Banned users are excluded - a suspended account should not be messaged.
    """
    from app.services.i18n import DEFAULT_LANGUAGE, normalise

    stmt = (
        select(User.telegram_id, UserSetting.language)
        .join(UserSetting, UserSetting.user_id == User.id)
        .where(UserSetting.daily_drop.is_(True))
        .where(User.is_banned.is_(False))
    )
    result = await session.execute(stmt)
    return [
        (tg_id, normalise(lang or DEFAULT_LANGUAGE))
        for tg_id, lang in result.all()
    ]


# --------------------------------------------------------------------------- bot settings
async def get_bot_setting(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(BotSetting).where(BotSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_bot_setting(session: AsyncSession, key: str, value: str) -> None:
    result = await session.execute(select(BotSetting).where(BotSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        session.add(BotSetting(key=key, value=value))
    else:
        row.value = value
    await session.flush()


async def all_bot_settings(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(BotSetting))
    return {row.key: row.value for row in result.scalars().all()}


# --------------------------------------------------------------------------- admin actions
async def log_admin_action(
    session: AsyncSession,
    *,
    admin_id: int,
    action: str,
    target_user_id: int | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AdminAction:
    row = AdminAction(
        admin_id=admin_id,
        target_user_id=target_user_id,
        action=action,
        reason=reason,
        meta=metadata,
    )
    session.add(row)
    await session.flush()
    return row


async def list_admin_actions(
    session: AsyncSession, offset: int = 0, limit: int = 10
) -> Sequence[AdminAction]:
    stmt = (
        select(AdminAction)
        .order_by(AdminAction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_admin_actions(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(AdminAction.id)))
    return int(result.scalar_one())


async def list_admin_actions_for_user(
    session: AsyncSession, telegram_id: int, limit: int = 10
) -> Sequence[AdminAction]:
    stmt = (
        select(AdminAction)
        .where(AdminAction.target_user_id == telegram_id)
        .order_by(AdminAction.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# --------------------------------------------------------------------------- cache mirror
async def cache_get(session: AsyncSession, cache_key: str) -> dict[str, Any] | None:
    result = await session.execute(
        select(UsernameCacheRow).where(UsernameCacheRow.cache_key == cache_key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= utcnow():
        await session.delete(row)
        await session.flush()
        return None
    return row.payload


async def cache_set(
    session: AsyncSession, cache_key: str, payload: dict[str, Any], ttl: int
) -> None:
    expires_at = utcnow() + timedelta(seconds=ttl)
    result = await session.execute(
        select(UsernameCacheRow).where(UsernameCacheRow.cache_key == cache_key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        session.add(
            UsernameCacheRow(cache_key=cache_key, payload=payload, expires_at=expires_at)
        )
    else:
        row.payload = payload
        row.expires_at = expires_at
    await session.flush()


async def purge_expired_cache(session: AsyncSession) -> int:
    result = await session.execute(
        delete(UsernameCacheRow).where(UsernameCacheRow.expires_at <= utcnow())
    )
    await session.flush()
    return int(result.rowcount or 0)


# --------------------------------------------------------------------------- statistics
async def collect_statistics(session: AsyncSession) -> dict[str, Any]:
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    users_total = await count_users(session)
    banned_total = await count_users(session, only_banned=True)

    active_today = await session.execute(
        select(func.count(User.id)).where(User.last_seen >= today_start)
    )
    restricted = await session.execute(
        select(func.count(User.id)).where(
            User.ban_until.is_not(None), User.ban_until > utcnow()
        )
    )
    checks_total = await count_username_checks(session)
    checks_collectible = await count_username_checks(session, UsernameType.COLLECTIBLE.value)
    checks_available = await session.execute(
        select(func.count(UsernameCheck.id)).where(
            UsernameCheck.status == CheckStatus.AVAILABLE.value
        )
    )
    searches_total = await count_all_searches(session)

    return {
        "users_total": users_total,
        "active_today": int(active_today.scalar_one()),
        "banned": banned_total,
        "restricted": int(restricted.scalar_one()),
        "checks_total": checks_total,
        "checks_collectible": checks_collectible,
        "checks_available": int(checks_available.scalar_one()),
        "searches_total": searches_total,
    }


# --------------------------------------------------------------------------- traps
async def create_trap(
    session: AsyncSession, user: User, username: str, kind: str = "name"
) -> tuple[Trap, bool]:
    """Create or revive a trap. Returns ``(trap, created)``.

    ``kind="name"`` watches one exact username; ``kind="mask"`` is a sniper that
    keeps generating candidates from the mask until one comes up free.
    """
    name = username.strip().lstrip("@").lower()
    result = await session.execute(
        select(Trap).where(Trap.telegram_id == user.telegram_id, Trap.username == name)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if not existing.active:
            existing.active = True
            existing.kind = kind
            existing.notified_at = None
            existing.freed_at = None
            existing.last_checked_at = None
            existing.last_status = None
            await session.flush()
            return existing, True
        return existing, False

    trap = Trap(
        user_id=user.id, telegram_id=user.telegram_id,
        username=name, kind=kind, active=True,
    )
    session.add(trap)
    await session.flush()
    return trap, True


async def list_traps(session: AsyncSession, user: User) -> Sequence[Trap]:
    result = await session.execute(
        select(Trap)
        .where(Trap.telegram_id == user.telegram_id)
        .order_by(Trap.created_at.desc())
    )
    return result.scalars().all()


async def get_trap(session: AsyncSession, trap_id: int) -> Trap | None:
    result = await session.execute(select(Trap).where(Trap.id == trap_id))
    return result.scalar_one_or_none()


async def list_active_traps(session: AsyncSession, limit: int = 200) -> Sequence[Trap]:
    """Oldest/unseen watches first so a global paced worker stays fair."""
    result = await session.execute(
        select(Trap)
        .where(Trap.active.is_(True))
        .order_by(Trap.last_checked_at.asc().nulls_first(), Trap.id.asc())
        .limit(limit)
    )
    return result.scalars().all()


async def deactivate_trap(session: AsyncSession, user: User, trap_id: int) -> bool:
    result = await session.execute(
        select(Trap).where(Trap.id == trap_id, Trap.telegram_id == user.telegram_id)
    )
    trap = result.scalar_one_or_none()
    if trap is None:
        return False
    trap.active = False
    await session.flush()
    return True


async def touch_trap(
    session: AsyncSession, trap: Trap, status: str, freed: bool = False
) -> None:
    trap.last_checked_at = datetime.now(timezone.utc)
    trap.last_status = status
    if freed:
        trap.freed_at = trap.freed_at or datetime.now(timezone.utc)
        trap.notified_at = trap.notified_at or datetime.now(timezone.utc)
        trap.active = False
    await session.flush()


# --------------------------------------------------------------------------- battles
async def create_battle(
    session: AsyncSession,
    challenger_id: int,
    challenger_username: str,
    rival_username: str | None = None,
    rival_id: int | None = None,
    status: str = "pending",
) -> Battle:
    battle = Battle(
        challenger_id=challenger_id,
        challenger_username=challenger_username.lstrip("@").lower(),
        rival_id=rival_id,
        rival_username=rival_username.lstrip("@").lower() if rival_username else None,
        status=status,
    )
    session.add(battle)
    await session.flush()
    return battle


async def get_battle(session: AsyncSession, battle_id: int) -> Battle | None:
    result = await session.execute(select(Battle).where(Battle.id == battle_id))
    return result.scalar_one_or_none()


async def finish_battle(
    session: AsyncSession,
    battle: Battle,
    result: dict[str, Any],
    winner_id: int | None = None,
) -> Battle:
    battle.result = result
    battle.status = "done"
    battle.winner_id = winner_id
    battle.finished_at = datetime.now(timezone.utc)
    await session.flush()
    return battle


async def count_user_battles(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(Battle.id)).where(
            or_(Battle.challenger_id == telegram_id, Battle.rival_id == telegram_id)
        )
    )
    return int(result.scalar_one())


async def latest_available_username(session: AsyncSession) -> str | None:
    """Most recent username recorded as AVAILABLE - the user's best find."""
    result = await session.execute(
        select(UsernameCheck.username)
        .where(UsernameCheck.status == CheckStatus.AVAILABLE.value)
        .order_by(UsernameCheck.checked_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_active_traps(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(Trap.id)).where(
            Trap.telegram_id == telegram_id, Trap.active.is_(True)
        )
    )
    return int(result.scalar_one())


# --------------------------------------------------------------------------- favorites
async def add_favorite(
    session: AsyncSession, user: User, username: str, note: str | None = None, score: int = 0
) -> tuple[Favorite, bool]:
    name = username.strip().lstrip("@").lower()
    result = await session.execute(
        select(Favorite).where(
            Favorite.telegram_id == user.telegram_id, Favorite.username == name
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if note is not None:
            existing.note = note[:200]
        existing.score = max(existing.score or 0, score)
        await session.flush()
        return existing, False

    favorite = Favorite(
        user_id=user.id, telegram_id=user.telegram_id,
        username=name, note=(note or None), score=score,
    )
    session.add(favorite)
    await session.flush()
    return favorite, True


async def list_favorites(session: AsyncSession, user: User, limit: int = 50) -> Sequence[Favorite]:
    result = await session.execute(
        select(Favorite)
        .where(Favorite.telegram_id == user.telegram_id)
        .order_by(Favorite.score.desc(), Favorite.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def remove_favorite(session: AsyncSession, user: User, favorite_id: int) -> bool:
    result = await session.execute(
        select(Favorite).where(
            Favorite.id == favorite_id, Favorite.telegram_id == user.telegram_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def count_favorites(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(Favorite.id)).where(Favorite.telegram_id == telegram_id)
    )
    return int(result.scalar_one())


# --------------------------------------------------------------------------- portfolio
async def add_portfolio(
    session: AsyncSession, user: User, username: str, note: str | None = None
) -> tuple[PortfolioItem, bool]:
    name = username.strip().lstrip("@").lower()
    result = await session.execute(
        select(PortfolioItem).where(
            PortfolioItem.telegram_id == user.telegram_id,
            PortfolioItem.username == name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False
    item = PortfolioItem(
        user_id=user.id, telegram_id=user.telegram_id,
        username=name, note=(note or None),
    )
    session.add(item)
    await session.flush()
    return item, True


async def list_portfolio(
    session: AsyncSession, user: User, limit: int = 100
) -> Sequence[PortfolioItem]:
    result = await session.execute(
        select(PortfolioItem)
        .where(PortfolioItem.telegram_id == user.telegram_id)
        .order_by(PortfolioItem.created_at.asc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_portfolio_item(
    session: AsyncSession, item_id: int
) -> PortfolioItem | None:
    result = await session.execute(
        select(PortfolioItem).where(PortfolioItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def remove_portfolio(session: AsyncSession, user: User, item_id: int) -> bool:
    result = await session.execute(
        select(PortfolioItem).where(
            PortfolioItem.id == item_id, PortfolioItem.telegram_id == user.telegram_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def update_portfolio_value(
    session: AsyncSession, item: PortfolioItem, price: str | None, status: str
) -> None:
    item.last_price = price
    item.last_status = status
    item.last_checked_at = utcnow()
    await session.flush()


async def count_portfolio(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(PortfolioItem.id)).where(
            PortfolioItem.telegram_id == telegram_id
        )
    )
    return int(result.scalar_one())


# --------------------------------------------------------------------------- achievements
async def count_checks_by_status(session: AsyncSession, status: str) -> int:
    result = await session.execute(
        select(func.count(UsernameCheck.id)).where(UsernameCheck.status == status)
    )
    return int(result.scalar_one())


async def count_collectible_checks(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(UsernameCheck.id)).where(
            UsernameCheck.type == UsernameType.COLLECTIBLE.value,
            UsernameCheck.status != CheckStatus.UNKNOWN.value,
        )
    )
    return int(result.scalar_one())


async def count_traps_created(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(Trap.id)).where(Trap.telegram_id == telegram_id)
    )
    return int(result.scalar_one())


async def count_traps_fired(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(Trap.id)).where(
            Trap.telegram_id == telegram_id, Trap.notified_at.is_not(None)
        )
    )
    return int(result.scalar_one())


async def count_battles_won(session: AsyncSession, telegram_id: int) -> int:
    result = await session.execute(
        select(func.count(Battle.id)).where(
            Battle.status == "done", Battle.winner_id == telegram_id
        )
    )
    return int(result.scalar_one())


async def recent_available_usernames(session: AsyncSession, limit: int = 400) -> Sequence[str]:
    result = await session.execute(
        select(UsernameCheck.username)
        .where(UsernameCheck.status == CheckStatus.AVAILABLE.value)
        .order_by(UsernameCheck.checked_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ------------------------------------------------------------------ free stock
# The ready supply of *verified* free names (see the FreeName model). The
# repository only moves rows; the policy - when to harvest, when a stored name
# is stale - lives in app/services/name_stock.py.
async def add_free_name(
    session: AsyncSession,
    username: str,
    length: int,
    has_digits: bool,
    score: int,
    source: str = "harvest",
) -> bool:
    """Store a name Telegram just confirmed claimable. ``False`` if already held."""
    existing = await session.execute(select(FreeName.id).where(FreeName.username == username))
    if existing.scalar_one_or_none() is not None:
        return False
    session.add(
        FreeName(
            username=username, length=length, has_digits=has_digits,
            score=score, source=source,
        )
    )
    await session.flush()
    return True


async def count_free_names(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(FreeName.id)))
    return int(result.scalar_one())


async def take_free_name(
    session: AsyncSession,
    length: int | None = None,
    allow_digits: bool = True,
    reserve_seconds: int = 180,
) -> str | None:
    """Reserve the best stored name matching the requested shape, and return it.

    The row is *reserved*, not deleted: ``served_at`` is stamped and the row is
    skipped by other callers for ``reserve_seconds``. That way two searches
    running at the same time can never be handed the same username, and a
    delivery that does not complete (the re-confirmation came back throttled)
    returns the row to the pool by itself instead of silently burning it.
    """
    cutoff = utcnow() - timedelta(seconds=max(0, reserve_seconds))
    query = (
        select(FreeName)
        .where(or_(FreeName.served_at.is_(None), FreeName.served_at < cutoff))
        .order_by(FreeName.score.desc(), FreeName.verified_at.desc())
        .limit(40)
    )
    if length is not None:
        query = query.where(FreeName.length == length)
    if not allow_digits:
        query = query.where(FreeName.has_digits.is_(False))

    rows = (await session.execute(query)).scalars().all()
    if not rows:
        return None
    row = rows[0]
    row.served_at = utcnow()
    await session.flush()
    return row.username


async def release_free_name(session: AsyncSession, username: str) -> None:
    """Return a reserved name to the pool (delivery could not be completed)."""
    await session.execute(
        update(FreeName).where(FreeName.username == username).values(served_at=None)
    )


async def drop_free_name(session: AsyncSession, username: str) -> None:
    """Forget a stored name - it is no longer claimable, so it is worthless."""
    await session.execute(delete(FreeName).where(FreeName.username == username))


async def prune_free_names(session: AsyncSession, older_than_seconds: int) -> int:
    """Drop stale rows. A free name can be claimed by anyone at any moment."""
    cutoff = utcnow() - timedelta(seconds=max(0, older_than_seconds))
    result = await session.execute(delete(FreeName).where(FreeName.verified_at < cutoff))
    return int(result.rowcount or 0)
