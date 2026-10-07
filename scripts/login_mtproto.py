"""Create an authorised MTProto (Telethon) session.

Why you need this
-----------------
The Bot API cannot tell "free" apart from "reserved/deleted". Only MTProto
raises ``UsernameNotOccupiedError`` for a name nobody owns, which is what makes
a definitive AVAILABLE answer possible.

Usage
-----
    python scripts/login_mtproto.py

You will be asked for the phone number of the account and the login code.
The resulting ``*.session`` file is written next to the project root and must
never be committed (it is already in .gitignore).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.utils.logging_setup import get_logger, setup_logging  # noqa: E402

logger = get_logger("login_mtproto")


async def main() -> int:
    setup_logging("INFO")

    if not settings.mtproto_configured:
        print(
            "API_ID / API_HASH are not set.\n"
            "Get them at https://my.telegram.org -> API development tools, "
            "then put them in .env."
        )
        return 2

    try:
        from telethon import TelegramClient
    except ImportError:
        print("Telethon is not installed. Run: pip install -r requirements.txt")
        return 3

    client = TelegramClient(
        settings.mtproto_session, settings.api_id, settings.api_hash
    )

    print(f"Session file: {settings.mtproto_session}.session")
    print(
        "When asked for a phone number, enter it WITH the country code "
        "(e.g. +79991234567).\n"
        "Do NOT paste a bot token: that authorises a BOT, and Telegram blocks\n"
        "the dedicated account.checkUsername method for bots.\n"
        "The login code arrives inside the Telegram app, not by SMS.\n"
    )

    await client.start()
    me = await client.get_me()

    if me is None:
        print("Login did not complete.")
        await client.disconnect()
        return 4

    username = f"@{me.username}" if getattr(me, "username", None) else "(no username)"
    print(f"\nAuthorised as {me.first_name or ''} {username} (id={me.id})")

    if getattr(me, "bot", False):
        print(
            "\n[!] That session is a BOT, not a user account.\n"
            "    Availability checks still work through contacts.resolveUsername,\n"
            "    but account.checkUsername is user-only and stays unavailable.\n"
            "    For a full user session: delete the .session file and run this\n"
            "    script again, entering your PHONE NUMBER instead of a bot token."
        )
    else:
        print("You can now start the bot: python -m app.main")

    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
