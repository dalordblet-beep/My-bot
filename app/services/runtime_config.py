"""Runtime-tunable settings.

A safe, whitelisted subset of configuration can be changed from the admin panel
without touching `.env` or restarting. Secrets (BOT_TOKEN, API_HASH) are never
part of this set.

Values are loaded from the ``bot_settings`` table at startup and cached in
memory; :meth:`RuntimeConfig.refresh` reloads them.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import repository as repo
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


def _as_int(value: str) -> int:
    return int(value.strip())


def _as_str(value: str) -> str:
    return value.strip()


# key -> (parser, human label, settings attribute used as fallback)
OVERRIDABLE: dict[str, tuple[Callable[[str], Any], str, str]] = {
    "required_channel_id": (_as_int, "Required channel id", "required_channel_id"),
    "required_channel_username": (_as_str, "Required channel username", "required_channel_username"),
    "required_channel_invite_url": (_as_str, "Channel invite link", "required_channel_invite_url"),
    "required_chat_id": (_as_int, "Required chat id", "required_chat_id"),
    "required_chat_username": (_as_str, "Required chat username", "required_chat_username"),
    "required_chat_invite_url": (_as_str, "Chat invite link", "required_chat_invite_url"),
    "required_subscriptions": (
        _as_str, "Required subscriptions (JSON)", "required_subscriptions"
    ),
    "max_search_results": (_as_int, "Max search results", "max_search_results"),
    "cache_ttl": (_as_int, "Cache TTL (s)", "cache_ttl"),
    "captcha_ttl": (_as_int, "CAPTCHA TTL (s)", "captcha_ttl"),
    "max_captcha_attempts": (_as_int, "CAPTCHA attempts", "max_captcha_attempts"),
    "max_concurrent_checks": (_as_int, "Concurrent checks", "max_concurrent_checks"),
    "trap_interval": (_as_int, "Trap check interval (s)", "trap_interval"),
    "support_username": (_as_str, "Support contact", "support_username"),
}


class RuntimeConfig:
    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}

    async def load(self, session: AsyncSession) -> None:
        try:
            stored = await repo.all_bot_settings(session)
        except Exception as exc:
            logger.warning("could not load runtime overrides: %s", exc)
            return

        parsed: dict[str, Any] = {}
        for key, raw in stored.items():
            if key not in OVERRIDABLE:
                continue
            parser = OVERRIDABLE[key][0]
            try:
                parsed[key] = parser(raw)
            except (ValueError, TypeError):
                logger.warning("ignoring invalid override %s=%r", key, raw)
        self._overrides = parsed
        if parsed:
            logger.info("runtime overrides loaded: %s", ", ".join(sorted(parsed)))

    def get(self, key: str) -> Any:
        if key in self._overrides:
            return self._overrides[key]
        _, _, attr = OVERRIDABLE[key]
        return getattr(settings, attr)

    async def set(self, session: AsyncSession, key: str, raw_value: str) -> Any:
        if key not in OVERRIDABLE:
            raise KeyError(f"{key} is not overridable")
        parser = OVERRIDABLE[key][0]
        value = parser(raw_value)
        await repo.set_bot_setting(session, key, str(value))
        self._overrides[key] = value
        return value

    async def reset(self, session: AsyncSession, key: str) -> None:
        await repo.set_bot_setting(session, key, "")
        self._overrides.pop(key, None)

    # ---- typed accessors used across the codebase -------------------------
    @property
    def required_channel_id(self) -> int:
        return int(self.get("required_channel_id") or 0)

    @property
    def required_channel_username(self) -> str:
        return str(self.get("required_channel_username") or "")

    @property
    def required_channel_invite_url(self) -> str:
        return str(self.get("required_channel_invite_url") or "")

    @property
    def required_chat_id(self) -> int:
        return int(self.get("required_chat_id") or 0)

    @property
    def required_chat_username(self) -> str:
        return str(self.get("required_chat_username") or "")

    @property
    def required_chat_invite_url(self) -> str:
        return str(self.get("required_chat_invite_url") or "")

    @property
    def required_subscriptions(self) -> str:
        return str(self.get("required_subscriptions") or "")

    @property
    def max_search_results(self) -> int:
        return int(self.get("max_search_results"))

    @property
    def cache_ttl(self) -> int:
        return int(self.get("cache_ttl"))

    @property
    def captcha_ttl(self) -> int:
        return int(self.get("captcha_ttl"))

    @property
    def max_captcha_attempts(self) -> int:
        return int(self.get("max_captcha_attempts"))

    @property
    def max_concurrent_checks(self) -> int:
        return int(self.get("max_concurrent_checks"))

    @property
    def trap_interval(self) -> int:
        # Guard against a nonsensical override: the watcher must never spin,
        # but it also must not be so slow that the feature looks broken.
        return max(15, min(3600, int(self.get("trap_interval"))))

    @property
    def support_username(self) -> str:
        return str(self.get("support_username") or "mogeds2").lstrip("@")

    @property
    def channel_configured(self) -> bool:
        return bool(self.required_channel_id or self.required_channel_username)

    @property
    def chat_configured(self) -> bool:
        return bool(self.required_chat_id or self.required_chat_username)

    @property
    def subscriptions_configured(self) -> bool:
        return bool(self.required_subscriptions.strip()) or self.channel_configured or self.chat_configured

    def snapshot(self) -> dict[str, Any]:
        return {key: self.get(key) for key in OVERRIDABLE}


runtime = RuntimeConfig()
