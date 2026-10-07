"""Check usernames from the command line, using the exact same engine as the bot.

Usage
-----
    python scripts/check_username.py durov
    python scripts/check_username.py @durov https://t.me/telegram moged

Prints one line per username with the resolved status and the source that
produced it. Useful for confirming the engine works before blaming the bot.
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
from app.collectible.checker import CollectibleChecker  # noqa: E402
from app.config import settings  # noqa: E402
from app.telegram.mtproto import mtproto_client  # noqa: E402
from app.telegram.username_checker import UsernameChecker  # noqa: E402
from app.utils.enums import CheckStatus  # noqa: E402

LABELS = {
    CheckStatus.AVAILABLE: "AVAILABLE",
    CheckStatus.OCCUPIED: "OCCUPIED ",
    CheckStatus.INVALID: "INVALID  ",
    CheckStatus.UNKNOWN: "UNKNOWN  ",
    CheckStatus.RATE_LIMITED: "RATE-LTD ",
    CheckStatus.ERROR: "ERROR    ",
}


async def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    if not settings.bot_token:
        print("BOT_TOKEN is not set in .env")
        return 3

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    cache = CacheService(enabled=False)
    await cache.connect()

    if settings.mtproto_configured:
        ready = await mtproto_client.start()
        print(f"mtproto: {'authorised' if ready else 'not authorised (Bot API fallback)'}")
    else:
        print("mtproto: not configured (Bot API only)")
    print(f"bot api availability fallback: {settings.allow_bot_api_availability}")
    print()

    checker = UsernameChecker(cache=cache, bot=bot)
    collectible = CollectibleChecker()

    for raw in argv:
        basic = await checker.check_basic_username(raw, use_cache=False)
        line = f"{LABELS.get(basic.status, '?')} @{basic.username or raw}"
        details = [f"source={basic.source}"]
        if basic.entity_type:
            details.append(f"type={basic.entity_type}")
        if basic.title:
            details.append(f"title={basic.title!r}")
        if basic.reason:
            details.append(f"reason={basic.reason}")
        print(f"{line:34} {' '.join(details)}  ({basic.duration_ms} ms)")

        coll = await collectible.check_collectible_username(raw)
        print(f"{'':34} collectible: {coll.status.value}"
              + (f" ({coll.reason})" if coll.reason else ""))

    await checker.close()
    await collectible.close()
    await mtproto_client.stop()
    await cache.close()
    await bot.session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
