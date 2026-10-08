"""Application entry point.

    python -m app.main
"""

from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand

from app.bot.routers import all_routers
from app.bot.middlewares.access_guard import AccessGuardMiddleware
from app.bot.middlewares.database import DatabaseMiddleware, UserContextMiddleware
from app.bot.middlewares.errors import ErrorMiddleware
from app.cache.redis_cache import CacheService
from app.collectible.checker import CollectibleChecker
from app.config import settings
from app.database.database import dispose_db, init_db, session_scope
from app.services.captcha import CaptchaService
from app.services.runtime_config import runtime
from app.services.search_queue import SearchQueue
from app.services.daily_drop import DailyDropService
from app.telegram.mtproto import mtproto_client
from app.search.traps import TrapWatcher
from app.telegram.username_checker import UsernameChecker
from app.utils.buildinfo import build_stamp
from app.utils.logging_setup import get_logger, setup_logging
from app.utils.singleton import AlreadyRunning, SingleInstance

logger = get_logger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Start / main menu"),
    BotCommand(command="check", description="Check a username"),
    BotCommand(command="search", description="Generate and scan usernames"),
    BotCommand(command="history", description="Your recent searches"),
    BotCommand(command="settings", description="Preferences"),
    BotCommand(command="help", description="Help"),
    BotCommand(command="admin", description="Admin panel"),
]


def build_dispatcher(cache: CacheService, checker: UsernameChecker,
                     collectible_checker: CollectibleChecker,
                     captcha_service: CaptchaService,
                     search_queue: SearchQueue) -> Dispatcher:
    dp = Dispatcher()

    dp["cache_service"] = cache
    dp["checker"] = checker
    dp["collectible_checker"] = collectible_checker
    dp["captcha_service"] = captcha_service
    dp["search_queue"] = search_queue

    # outer middlewares (first registered = outermost)
    dp.update.outer_middleware(ErrorMiddleware())
    dp.update.outer_middleware(DatabaseMiddleware())
    dp.update.outer_middleware(UserContextMiddleware())

    # access gate for every user-facing event
    guard = AccessGuardMiddleware(captcha_service)
    dp.message.middleware(guard)
    dp.callback_query.middleware(guard)

    for router in all_routers():
        dp.include_router(router)

    return dp


async def run() -> None:
    setup_logging()

    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set. Fill in .env before starting.")
        raise SystemExit(2)

    logger.info("starting username_scanner (build %s)", build_stamp())

    lock = SingleInstance(settings.bot_token)
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        logger.error(
            "%s\n"
            "  Telegram allows only one polling process per bot token.\n"
            "  If you see an older interface flicker back, that is this: a second\n"
            "  copy is still running with stale code. Close it (Ctrl+C in its\n"
            "  window, or kill the stray python process) and start again.",
            exc,
        )
        raise SystemExit(5)

    cache = CacheService()
    await cache.connect()

    if not await init_db():
        logger.error(
            "PostgreSQL is unreachable. Check DATABASE_URL and that the database is running."
        )
        raise SystemExit(3)

    async with session_scope() as session:
        await runtime.load(session)
        # Apply admin-editable bot customisation (button colours, label renames).
        from app.bot.keyboards.base import apply_button_theme
        from app.services.i18n import refresh_custom_labels

        apply_button_theme(runtime.button_theme)
        refresh_custom_labels()

    if settings.mtproto_configured:
        ready = await mtproto_client.start()
        if not ready:
            logger.warning(
                "MTProto is configured but not authorised - availability checks will "
                "return UNKNOWN until you run scripts/login_mtproto.py"
            )
        # Optional: a real user session lets the engine call account.checkUsername,
        # the only way to tell a claimable name from one Telegram refuses to
        # assign. Absent, the engine stays best-effort.
        await mtproto_client.start_user()
    else:
        logger.warning("MTProto is not configured - basic availability checks are limited")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    checker = UsernameChecker(cache=cache, bot=bot)
    collectible_checker = CollectibleChecker()
    captcha_service = CaptchaService(cache)

    # Searches run through a queue so a user never waits on Telegram pacing, and
    # so the safe request rate holds no matter how many people press Run at once.
    search_queue = SearchQueue(bot, checker, collectible_checker, workers=1)
    daily_drop = DailyDropService(bot, search_queue)

    dp = build_dispatcher(cache, checker, collectible_checker, captcha_service, search_queue)

    try:
        await bot.set_my_commands(COMMANDS)
    except Exception as exc:
        logger.warning("could not set bot commands: %s", exc)

    watcher = TrapWatcher(
        bot,
        checker,
        collectible_checker,
        interval=float(runtime.trap_interval),
        per_check_delay=max(1.0, float(settings.request_delay)),
        tick=1.0,
    )
    watcher.start()
    logger.info("trap watcher running=%s interval=%ss", watcher.running, runtime.trap_interval)

    search_queue.start()
    logger.info("search queue running=%s", search_queue.running)

    daily_drop.start()
    logger.info("daily drop running=%s", daily_drop.running)

    logger.info("bot is up, polling")
    try:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except TelegramUnauthorizedError:
            logger.error("Telegram rejected BOT_TOKEN. Check it in .env.")
            raise SystemExit(4)
        except Exception as exc:
            logger.warning("could not drop webhook: %s", exc)

        try:
            await dp.start_polling(bot)
        except TelegramUnauthorizedError:
            logger.error("Telegram rejected BOT_TOKEN. Check it in .env.")
            raise SystemExit(4)
    finally:
        logger.info("shutting down")
        await search_queue.stop()
        await daily_drop.stop()
        await watcher.stop()
        lock.release()
        await checker.close()
        await mtproto_client.stop()
        await collectible_checker.close()
        await cache.close()
        await dispose_db()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code not in (None, 0):
            sys.exit(exc.code)
        logger.info("stopped")


if __name__ == "__main__":
    main()
