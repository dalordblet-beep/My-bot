"""Create (or inspect) an MTProto (Telethon) session.

Note
----
The running bot **auto-authorises its own MTProto session as the bot** from
``BOT_TOKEN`` on every startup (see ``MtprotoClient.start``). For the default
availability checks that is all you need — no phone login, no code. This script
is therefore only for two things:

* ``--status`` — show which account the current session belongs to (and whether
  it is a bot).
* ``--force`` — replace the session with an interactive **user** login (phone
  number + code). A user session is only required if you specifically want to
  experiment with the user-only ``account.checkUsername``; the bot's availability
  engine uses ``contacts.resolveUsername``, which a bot session already provides.

Usage
-----
    python scripts/login_mtproto.py            # --status by default (no prompts)
    python scripts/login_mtproto.py --force    # delete the session and log in as a user
    python scripts/login_mtproto.py --status   # show which account the session belongs to

The resulting ``*.session`` file is written next to the project root and must
never be committed (it is already in .gitignore).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.utils.logging_setup import get_logger, setup_logging  # noqa: E402

logger = get_logger("login_mtproto")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Authorise the MTProto session used for availability checks.",
    )
    parser.add_argument(
        "--force", "--relogin", "--new",
        dest="force", action="store_true",
        help="delete the existing session file first, so Telegram asks again",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="print the account the current session belongs to and exit",
    )
    return parser.parse_args(argv)


def session_paths() -> list[Path]:
    """Telethon writes ``<name>.session`` plus a transient ``-journal`` file."""
    base = settings.mtproto_session
    return [Path(f"{base}.session"), Path(f"{base}.session-journal")]


def remove_session() -> list[str]:
    removed: list[str] = []
    for path in session_paths():
        try:
            if path.exists():
                path.unlink()
                removed.append(path.name)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            print(f"Could not remove {path.name}: {exc}")
    return removed


def describe(me) -> str:
    username = f"@{me.username}" if getattr(me, "username", None) else "(no username)"
    return f"{me.first_name or ''} {username} (id={me.id})".strip()


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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

    if args.status:
        client = TelegramClient(
            settings.mtproto_session, settings.api_id, settings.api_hash
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                print("No authorised session found.")
                return 1
            me = await client.get_me()
            print(f"Session: {settings.mtproto_session}.session")
            print(f"Authorised as {describe(me)}")
            if getattr(me, "bot", False):
                print(
                    "This is a BOT session: availability checks work through\n"
                    "contacts.resolveUsername, but account.checkUsername is\n"
                    "user-only and unavailable. Re-login with --force and a\n"
                    "PHONE NUMBER for a full user session."
                )
        finally:
            await client.disconnect()
        return 0

    if args.force:
        removed = remove_session()
        if removed:
            print(f"Removed old session: {', '.join(removed)}")
            print("Telegram will ask for the phone number and code again.\n")
        else:
            print("No existing session to remove - starting a fresh login.\n")
    else:
        existing = [path.name for path in session_paths() if path.exists()]
        if existing:
            print(
                "A session already exists, so Telegram will NOT ask again:\n"
                f"  {', '.join(existing)}\n\n"
                "To log in as a different account, run:\n"
                "  python scripts/login_mtproto.py --force\n"
                "To see which account it belongs to:\n"
                "  python scripts/login_mtproto.py --status\n"
            )

    client = TelegramClient(
        settings.mtproto_session, settings.api_id, settings.api_hash
    )

    print(f"Session file: {settings.mtproto_session}.session")
    print(
        "This path creates a USER session (phone + code). The running bot already\n"
        "logs in as the bot via BOT_TOKEN, so only do this if you specifically\n"
        "want a user session for account.checkUsername.\n"
        "When asked for a phone number, enter it WITH the country code "
        "(e.g. +79991234567).\n"
        "Do NOT paste a bot token here: the bot already holds that session, and\n"
        "Telegram blocks the dedicated account.checkUsername method for bots.\n"
        "The login code arrives inside the Telegram app, not by SMS.\n"
    )

    await client.start()
    me = await client.get_me()

    if me is None:
        print("Login did not complete.")
        await client.disconnect()
        return 4

    print(f"\nAuthorised as {describe(me)}")

    if getattr(me, "bot", False):
        print(
            "\n[!] That session is a BOT, not a user account.\n"
            "    Availability checks still work through contacts.resolveUsername,\n"
            "    but account.checkUsername is user-only and stays unavailable.\n"
            "    For a full user session: run this script with --force and enter\n"
            "    your PHONE NUMBER instead of a bot token."
        )
    else:
        print("You can now start the bot: python -m app.main")

    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
