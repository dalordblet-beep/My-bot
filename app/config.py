"""Application configuration.

All runtime configuration lives here. Secrets (BOT_TOKEN, API_HASH) are read
from the environment / `.env` file and are never editable from Telegram.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Set

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _split_csv(raw: str) -> List[str]:
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


class Settings(BaseSettings):
    """Environment-backed settings.

    Complex values (lists / dicts) are declared as strings and exposed through
    helper properties so that plain comma separated values keep working inside
    `.env` without JSON quoting.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- core -------------------------------------------------------------
    bot_token: str = ""
    api_id: int = 0
    api_hash: str = ""
    mtproto_session: str = "username_scanner_session"
    # Optional SECOND session: a real *user* account (phone login) used only for
    # the user-only ``account.checkUsername``. That method is the single source
    # that can tell a genuinely claimable name from one Telegram answers
    # ``not_occupied`` for but then refuses to assign (reserved / cooldown /
    # anti-abuse) - the false "free" that a bot session cannot avoid. Leave the
    # file absent to disable; create it with ``scripts/login_mtproto.py --user``.
    mtproto_user_session: str = "username_scanner_user"
    # Optional POOL of extra user sessions (comma separated base names). One
    # account cannot carry every user's checks without hitting FloodWait, so a
    # pool lets the engine rotate: a session that is rate-limited is parked and
    # the next one is used. Empty means "just the single session above".
    # Create each with: python scripts/login_mtproto.py --user --name <base>
    mtproto_user_sessions: str = ""
    # Optional image sent next to the main menu (welcome / home). Set to an
    # absolute path of a local .jpg/.png. Left empty or pointing at a missing
    # file to send no image. Overridable via the MENU_IMAGE_PATH env var.
    menu_image_path: str = (
        "C:\\Users\\GaboEB\\.workbuddy-ai\\clipboard-images\\"
        "clipboard-2026-10-07T23-27-55-228Z-a5ea59d1.jpg"
    )

    database_url: str = (
        "postgresql+asyncpg://scanner:scanner@localhost:5432/username_scanner"
    )
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True

    # --- access -----------------------------------------------------------
    admin_ids: str = ""
    required_channel_id: int = 0
    required_channel_username: str = ""
    # Public t.me/+... links for private resources, so the join button can
    # point somewhere even when the channel has no username.
    required_channel_invite_url: str = ""
    required_chat_id: int = 0
    required_chat_username: str = ""
    required_chat_invite_url: str = ""
    # Any number of required subscriptions as a JSON list, e.g.
    # [{"key": "main", "title": "Main channel", "id": -100..., "invite_url": "https://t.me/+..."}]
    # When empty the legacy REQUIRED_CHANNEL_* / REQUIRED_CHAT_* pair is used, so
    # an existing .env keeps working without changes.
    required_subscriptions: str = ""

    # --- bot customisation (all edited live from the admin panel) --------
    # Welcome text shown on /start. Empty = built-in default.
    welcome_message: str = ""
    # JSON map of i18n key -> custom text, e.g. {"btn.search": "Find names"}.
    custom_labels: str = "{}"
    # JSON map of semantic role -> Telegram style, e.g. {"primary": "success"}.
    button_theme: str = "{}"
    # Free, unlimited bot: keep scanning until a free name is found.
    unlimited_search: bool = True

    # --- captcha ----------------------------------------------------------
    captcha_ttl: int = 300
    captcha_verification_ttl: int = 86400
    max_captcha_attempts: int = 3
    # How long a proven channel/chat membership is trusted before re-checking.
    membership_recheck_ttl: int = 300

    # --- scanning ---------------------------------------------------------
    max_search_results: int = 500
    max_concurrent_checks: int = 5
    # Seconds between authoritative Telegram calls. Telegram does not publish
    # its limits, but production evidence for auth.resolveUsername points at
    # roughly 20-30 calls per account per minute before multi-hour FloodWaits
    # begin. 3.0s == 20/min, which is the conservative default used by the
    # telethon-floodgate production stack. Lowering this WILL get the account
    # banned - 0.35s is 171/min, ~6x over the escalation threshold.
    request_delay: float = 3.0
    floodwait_safety_margin: int = 3
    # How long an OCCUPIED verdict is trusted, in seconds. A taken name rarely
    # frees up, and a stale "taken" can only cause a miss - never a false
    # "free" - so this is safe to keep long. It is the single biggest saving on
    # Telegram quota, because the same names get re-checked constantly.
    verdict_occupied_ttl: int = 86400
    # How long an AVAILABLE verdict is trusted. Deliberately short: somebody can
    # claim the name within minutes, and a stale "free" would be a lie.
    verdict_free_ttl: int = 60
    # When True the bot will treat "chat not found" from the Bot API as a
    # definitive AVAILABLE. Telegram does not guarantee that, so it is off by
    # default and availability requires an MTProto user session.
    allow_bot_api_availability: bool = False

    # --- cache ------------------------------------------------------------
    cache_ttl: int = 120

    # --- collectible ------------------------------------------------------
    # Support contact (without @). The support button opens a chat with them.
    support_username: str = "mogeds2"
    # How often the trap watcher re-checks every watched username, in seconds.
    # Telegram has no "username released" event, so this is the worst-case
    # delay between a name freeing up and the user being told about it.
    trap_interval: int = 15

    fragment_enabled: bool = True
    fragment_timeout: float = 8.0

    # --- misc -------------------------------------------------------------
    log_level: str = "INFO"
    default_language: str = "en"
    # JSON map: {"search": "5368324170671202286", ...}. Empty by default
    # because invented ids break messages. See EmojiRenderer.
    custom_emoji_ids: str = ""

    # --- derived ----------------------------------------------------------
    @property
    def admin_id_set(self) -> Set[int]:
        ids: Set[int] = set()
        for chunk in _split_csv(self.admin_ids):
            try:
                ids.add(int(chunk))
            except ValueError:
                continue
        return ids

    @property
    def emoji_id_map(self) -> Dict[str, str]:
        raw = self.custom_emoji_ids.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(k): str(v) for k, v in parsed.items() if str(v).strip()}

    @property
    def mtproto_configured(self) -> bool:
        return bool(self.api_id and self.api_hash)

    @property
    def user_session_names(self) -> List[str]:
        """Every user-session base name to try, single session first."""
        names = _split_csv(self.mtproto_user_sessions)
        if self.mtproto_user_session and self.mtproto_user_session not in names:
            names.insert(0, self.mtproto_user_session)
        return names

    @property
    def channel_configured(self) -> bool:
        return bool(self.required_channel_id or self.required_channel_username)

    @property
    def chat_configured(self) -> bool:
        return bool(self.required_chat_id or self.required_chat_username)

    def dump_public(self) -> Dict[str, Any]:
        """Safe subset for the admin "System" screen. Never leaks secrets."""
        return {
            "max_search_results": self.max_search_results,
            "max_concurrent_checks": self.max_concurrent_checks,
            "cache_ttl": self.cache_ttl,
            "captcha_ttl": self.captcha_ttl,
            "captcha_verification_ttl": self.captcha_verification_ttl,
            "max_captcha_attempts": self.max_captcha_attempts,
            "mtproto_configured": self.mtproto_configured,
            "channel_configured": self.channel_configured,
            "chat_configured": self.chat_configured,
            "fragment_enabled": self.fragment_enabled,
            "allow_bot_api_availability": self.allow_bot_api_availability,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
