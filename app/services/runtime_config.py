"""Runtime-tunable settings.

A safe, whitelisted subset of configuration can be changed from the admin panel
without touching `.env` or restarting. Secrets (BOT_TOKEN, API_HASH) are never
part of this set.

Values are loaded from the ``bot_settings`` table at startup and cached in
memory; :meth:`RuntimeConfig.refresh` reloads them.
"""

from __future__ import annotations

import json
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


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _as_json(value: str) -> dict:
    """Parse a JSON object; empty input is treated as an empty override."""
    text = (value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("expected a JSON object")
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


# key -> (parser, human label, settings attribute used as fallback)
OVERRIDABLE: dict[str, tuple[Callable[[str], Any], str, str]] = {
    # --- bot customisation (edited from the admin panel) -----------------
    "welcome_message": (_as_str, "Welcome message (/start text)", "welcome_message"),
    "custom_labels": (
        _as_json,
        'Button labels JSON, e.g. {"btn.search":"Find names"}',
        "custom_labels",
    ),
    "button_theme": (
        _as_json,
        'Button theme JSON, e.g. {"primary":"success"}',
        "button_theme",
    ),
    "unlimited_search": (_as_bool, "Unlimited search attempts (free bot)", "unlimited_search"),
    # --- required subscriptions (managed via the Subscriptions tab) ------
    "required_subscriptions": (
        _as_str, "Required subscriptions (JSON)", "required_subscriptions"
    ),
    # --- operational tuning ----------------------------------------------
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
        entry = OVERRIDABLE.get(key)
        if entry is not None:
            _, _, attr = entry
            return getattr(settings, attr)
        # Keys retired from the admin panel (legacy channel/chat ids) still
        # resolve from settings so the fallback keeps working.
        return getattr(settings, key)

    def override(self, key: str) -> Any:
        """Return the admin-set override for ``key``, or None if unset."""
        return self._overrides.get(key)

    async def set(self, session: AsyncSession, key: str, raw_value: str) -> Any:
        if key not in OVERRIDABLE:
            raise KeyError(f"{key} is not overridable")
        parser = OVERRIDABLE[key][0]
        value = parser(raw_value)
        if isinstance(value, (dict, list)):
            stored = json.dumps(value, ensure_ascii=False)
        else:
            stored = str(value)
        await repo.set_bot_setting(session, key, stored)
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

    # ---- bot customisation (admin panel) ---------------------------------
    @property
    def welcome_message(self) -> str:
        return str(self.get("welcome_message") or "").strip()

    @property
    def custom_labels(self) -> dict:
        return self._json_value("custom_labels")

    @property
    def button_theme(self) -> dict:
        return self._json_value("button_theme")

    @property
    def unlimited_search(self) -> bool:
        val = self.get("unlimited_search")
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes", "on", "y")
        return bool(val)

    def _json_value(self, key: str) -> dict:
        """Parse a JSON-object override whether it is stored raw or pre-parsed."""
        val = self.get(key)
        if isinstance(val, dict):
            return val
        raw = val or ""
        if not isinstance(raw, str):
            raw = str(raw)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

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
