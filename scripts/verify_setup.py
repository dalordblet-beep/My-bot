"""Verify that .env is actually usable, before starting the bot.

Usage
-----
    python scripts/verify_setup.py

Checks, in order:
  1. BOT_TOKEN is valid (getMe)
  2. PostgreSQL / SQLite is reachable and the schema can be created
  3. Redis is reachable (optional - never fatal)
  4. The bot can see the required channel and is an administrator there
  5. The bot can see the required chat and is an administrator there
  6. Configured admins are actually members, so the gate will let them through
  7. MTProto credentials are present (optional - availability accuracy)

Exit codes: 0 = all good, 1 = something must be fixed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402

from app.cache.redis_cache import CacheService  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.database import dispose_db, init_db, session_scope  # noqa: E402
from app.services.runtime_config import runtime  # noqa: E402
from app.telegram.bot_api import build_chat_ref, get_membership  # noqa: E402

OK = "  [ok]  "
BAD = "  [FAIL]"
WARN = "  [warn]"


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def ok(self, message: str) -> None:
        print(f"{OK} {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        print(f"{BAD} {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print(f"{WARN} {message}")

    def title(self, message: str) -> None:
        print()
        print("-" * 68)
        print(message)
        print("-" * 68)


def masked(token: str) -> str:
    if len(token) < 12:
        return "***"
    return f"{token[:10]}...{token[-4:]}"


async def check_bot(report: Report) -> Bot | None:
    report.title("1. BOT TOKEN")
    if not settings.bot_token:
        report.fail("BOT_TOKEN is empty")
        return None

    print(f"       token: {masked(settings.bot_token)}")
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        me = await bot.get_me()
    except Exception as exc:
        report.fail(f"Telegram rejected the token: {exc}")
        await bot.session.close()
        return None

    report.ok(f"authorised as @{me.username} (id={me.id}, name={me.first_name})")
    return bot


async def check_database(report: Report) -> None:
    report.title("2. DATABASE")
    print(f"       url: {settings.database_url.split('@')[-1]}")

    if await init_db():
        report.ok("connected, schema created/verified")
    else:
        report.fail("unreachable - check DATABASE_URL")

    async with session_scope() as s:
        await runtime.load(s)
    report.ok("runtime overrides loaded")


async def check_redis(report: Report) -> None:
    report.title("3. REDIS")
    cache = CacheService()
    if await cache.connect():
        report.ok("connected - caching enabled")
    elif settings.redis_enabled:
        report.warn("unavailable - the bot will run without cache")
    else:
        report.ok("disabled in .env - running without cache")
    await cache.close()


async def check_resource(
    report: Report,
    bot: Bot,
    *,
    label: str,
    chat_id: int,
    username: str,
    invite_url: str,
    admin_ids: set[int],
) -> None:
    report.title(label)
    configured = bool(chat_id or username)
    if not configured:
        report.ok("not configured - this step is skipped")
        return

    ref = build_chat_ref(chat_id, username)
    print(f"       ref: {ref}")

    try:
        chat = await bot.get_chat(chat_id=ref)
    except Exception as exc:
        report.fail(f"cannot read the chat: {exc}")
        print("              -> the bot must be added to it as an administrator")
        return

    kind = getattr(chat.type, "value", chat.type)
    title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or "-"
    report.ok(f"visible: {title} ({kind}, id={chat.id})")

    if invite_url:
        report.ok(f"invite link from .env: {invite_url}")
    elif getattr(chat, "invite_link", None):
        report.ok(f"invite link from Telegram: {chat.invite_link}")
    elif username:
        report.ok(f"public link: https://t.me/{username.lstrip('@')}")
    else:
        report.warn(
            "no invite link available - set REQUIRED_*_INVITE_URL so the "
            "join button appears"
        )

    me = await bot.get_me()
    bot_status = await get_membership(bot, ref, me.id)
    if bot_status.grants_access:
        report.ok(f"bot membership: {bot_status.value}")
    else:
        report.fail(
            f"bot membership: {bot_status.value} - the bot MUST be an "
            "administrator, otherwise membership checks fail"
        )

    for admin_id in sorted(admin_ids):
        status = await get_membership(bot, ref, admin_id)
        if status.grants_access:
            report.ok(f"admin {admin_id}: {status.value}")
        else:
            report.warn(
                f"admin {admin_id}: {status.value} - this admin will be asked "
                "to join before reaching the menu"
            )


async def check_mtproto(report: Report) -> None:
    report.title("7. MTPROTO")
    if not settings.mtproto_configured:
        report.warn(
            "API_ID / API_HASH are not set - availability falls back to the "
            "Bot API (ALLOW_BOT_API_AVAILABILITY controls that)"
        )
        return

    report.ok(f"credentials present (API_ID={settings.api_id})")

    session_file = Path(f"{settings.mtproto_session}.session")
    if session_file.exists():
        report.ok(f"session file found: {session_file.name}")
    else:
        report.warn(
            "no session file yet - run 'python scripts/login_mtproto.py' once "
            "to authorise it (needs your phone + login code)"
        )

    if settings.allow_bot_api_availability:
        report.ok("Bot API fallback for AVAILABLE is enabled")
    else:
        report.warn(
            "ALLOW_BOT_API_AVAILABILITY=false - free usernames will show as "
            "UNKNOWN until the MTProto session is authorised"
        )


async def main() -> int:
    report = Report()

    print("=" * 68)
    print("username_scanner - setup verification")
    print("=" * 68)

    bot = await check_bot(report)
    await check_database(report)
    await check_redis(report)

    if bot is not None:
        admin_ids = settings.admin_id_set
        await check_resource(
            report,
            bot,
            label="4. REQUIRED CHANNEL",
            chat_id=settings.required_channel_id,
            username=settings.required_channel_username,
            invite_url=settings.required_channel_invite_url,
            admin_ids=admin_ids,
        )
        await check_resource(
            report,
            bot,
            label="5. REQUIRED CHAT",
            chat_id=settings.required_chat_id,
            username=settings.required_chat_username,
            invite_url=settings.required_chat_invite_url,
            admin_ids=admin_ids,
        )
        await check_admins(report, bot, admin_ids)
        await bot.session.close()

    await check_mtproto(report)
    await dispose_db()

    report.title("RESULT")
    if report.failures:
        print(f"  {report.failures} problem(s) must be fixed.")
        print("  The bot will start, but the gate may not work correctly.")
        return 1
    print("  Everything checks out. Start the bot:  python -m app.main")
    if report.warnings:
        print(f"  ({report.warnings} warning(s) - not fatal)")
    return 0


async def check_admins(report: Report, bot: Bot, admin_ids: set[int]) -> None:
    report.title("6. ADMIN IDS")
    if not admin_ids:
        report.warn("ADMIN_IDS is empty - nobody can open /admin")
        return
    for admin_id in sorted(admin_ids):
        try:
            chat = await bot.get_chat(admin_id)
            report.ok(f"{admin_id} -> @{chat.username or '-'}")
        except Exception as exc:
            report.warn(f"{admin_id}: could not resolve ({exc})")
    print("       Note: an admin must press /start once for the privilege to apply.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
