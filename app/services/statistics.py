"""Statistics and system-status service. All numbers come from real sources."""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheService
from app.collectible.checker import collectible_engine_available
from app.config import settings
from app.database import repository as repo
from app.telegram.mtproto import mtproto_client
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


async def gather(session: AsyncSession) -> dict[str, Any]:
    return await repo.collect_statistics(session)


async def system_status(bot: Bot, cache: CacheService | None) -> dict[str, Any]:
    from app.database.database import ping_db

    db_ok = await ping_db()

    cache_ok = False
    cache_info: dict[str, Any] = {"available": False}
    if cache is not None:
        cache_ok = await cache.ping()
        if cache_ok:
            cache_info = await cache.info()

    telegram_ok = False
    bot_username = None
    try:
        me = await bot.get_me()
        telegram_ok = True
        bot_username = me.username
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("get_me failed: %s", exc)

    if settings.mtproto_configured:
        mtproto_state = "ok" if mtproto_client.ready else "not_authorised"
    else:
        mtproto_state = "not_configured"

    return {
        "bot_online": True,
        "bot_username": bot_username,
        "database": db_ok,
        "redis": cache_ok,
        "redis_info": cache_info,
        "telegram_api": telegram_ok,
        "mtproto": mtproto_state,
        "collectible_engine": "ok" if collectible_engine_available() else "disabled",
        "cache_ttl": settings.cache_ttl,
        "max_concurrent_checks": settings.max_concurrent_checks,
        "max_search_results": settings.max_search_results,
    }
