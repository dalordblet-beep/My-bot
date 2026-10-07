"""Redis cache with graceful degradation.

Redis is an optimisation, never a dependency. If it is down the bot keeps
working: every method becomes a no-op and ``available`` reports False so the
System screen can be honest about it.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


class CacheService:
    def __init__(self, url: str | None = None, enabled: bool | None = None) -> None:
        self._url = url or settings.redis_url
        self._enabled = settings.redis_enabled if enabled is None else enabled
        self._client: Any | None = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def connect(self) -> bool:
        if not self._enabled:
            logger.info("redis disabled by configuration")
            return False
        try:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                self._url, encoding="utf-8", decode_responses=True
            )
            await self._client.ping()
            self._available = True
            logger.info("redis connected")
        except Exception as exc:
            self._available = False
            self._client = None
            logger.warning("redis unavailable, continuing without cache: %s", exc)
        return self._available

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
        self._client = None
        self._available = False

    async def ping(self) -> bool:
        if not self._available or self._client is None:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            self._available = False
            return False

    async def get_json(self, key: str) -> dict[str, Any] | None:
        if not self._available or self._client is None:
            return None
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            logger.debug("redis get failed for %s: %s", key, exc)
            self._available = False
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    async def set_json(self, key: str, value: dict[str, Any], ttl: int) -> bool:
        if not self._available or self._client is None:
            return False
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=max(1, ttl))
            return True
        except Exception as exc:
            logger.debug("redis set failed for %s: %s", key, exc)
            self._available = False
            return False

    async def delete(self, key: str) -> None:
        if not self._available or self._client is None:
            return
        try:
            await self._client.delete(key)
        except Exception:
            pass

    async def info(self) -> dict[str, Any]:
        if not self._available or self._client is None:
            return {"available": False}
        try:
            payload = await self._client.info()
            return {
                "available": True,
                "used_memory_human": payload.get("used_memory_human"),
                "connected_clients": payload.get("connected_clients"),
                "uptime_in_seconds": payload.get("uptime_in_seconds"),
            }
        except Exception:
            return {"available": False}


def username_cache_key(username: str, kind: str = "basic") -> str:
    return f"username:check:{kind}:{username.lower()}"
