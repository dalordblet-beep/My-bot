"""Show the pending join requests of every required subscription.

The onboarding gate lets a user through when they have *joined* a required
channel. When the channel is private and join requests are approved by hand, a
user who has already sent a request is still not a member - so the gate counts a
pending request as a subscription too. Reading that request queue is what this
script verifies, per channel.

    python scripts/check_join_requests.py

WHY IT INSISTS THE BOT IS STOPPED
---------------------------------
Reading the queue needs the **user** session, and Telegram invalidates an auth
key that is used from two IP addresses at the same time - permanently, taking
the claimability gate down with it:

    AuthKeyDuplicatedError: ... used under two different IP addresses
    simultaneously, and can no longer be used.

That is not theoretical; it has happened once here. So the script refuses to run
while a bot holds the single-instance lock on this machine, and it warns about a
bot running elsewhere, which it cannot see. Stop the bot first - it takes a few
seconds to restart.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.subscriptions import required_subs  # noqa: E402
from app.telegram.mtproto import _session_file, bot_running_locally  # noqa: E402
from app.utils.logging_setup import setup_logging  # noqa: E402

WARNING = (
    "!! Telegram kills a session used from two IP addresses at once, and the\n"
    "!! claimability gate dies with it. Make sure the bot is NOT running\n"
    "!! anywhere (this machine or a hosting) before continuing."
)


async def _user_client():
    """Open the user session - the ONLY one that can read join requests.

    ``messages.getChatInviteImporters`` is refused to bots outright
    (``BotMethodInvalidError`` - verified live), exactly like
    ``account.checkUsername``, so the request queue is readable only by a real
    account. That account has to be an administrator of the channel.
    """
    from telethon import TelegramClient

    for name in settings.user_session_names:
        if not name:
            continue
        path = _session_file(name)
        if not path.exists():
            continue
        client = TelegramClient(str(path), settings.api_id, settings.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            continue
        return client, path
    return None, None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check the join-request queues")
    parser.add_argument(
        "--force", action="store_true",
        help="run even though a bot is running on this machine (dangerous)",
    )
    args = parser.parse_args()

    setup_logging()

    if bot_running_locally() and not args.force:
        print(
            "A bot is running on this machine and holds the session.\n"
            "Stop it, then run this again (or pass --force if you are sure).\n\n"
            f"{WARNING}"
        )
        return 3
    print(WARNING)
    print()

    subs = required_subs()
    if not subs:
        print("no required subscriptions configured - nothing to check")
        return 0

    from telethon.tl.functions.messages import GetChatInviteImportersRequest
    from telethon.tl.types import InputUserEmpty

    client, path = await _user_client()
    if client is None:
        print(
            "No user session available. Reading join requests needs a real "
            "account:\n  python scripts/login_user_steps.py send <phone>"
        )
        return 2

    try:
        me = await client.get_me()
        print(f"session: {path}  ->  @{getattr(me, 'username', '?')} (user account)\n")
        for sub in subs:
            if not sub.configured:
                print(f"[{sub.key}] not configured - skipped")
                continue
            ref = sub.chat_id or (f"@{sub.username}" if sub.username else "")
            try:
                peer = await client.get_input_entity(ref)
            except Exception as exc:
                print(f"[{sub.key}] cannot resolve {ref}: {type(exc).__name__}: {exc}")
                continue
            try:
                result = await client(
                    GetChatInviteImportersRequest(
                        peer=peer, offset_date=None,
                        offset_user=InputUserEmpty(), limit=100, requested=True,
                    )
                )
            except Exception as exc:
                print(
                    f"[{sub.key}] {ref}: CANNOT READ REQUESTS "
                    f"({type(exc).__name__}: {exc})"
                    "\n    -> this account is probably not an administrator of "
                    "that chat, so join requests cannot be counted."
                )
                continue

            importers = list(result.importers or [])
            print(
                f"[{sub.key}] {ref}: OK - {len(importers)} pending request(s)"
            )
            for importer in importers[:5]:
                print(f"    user_id={importer.user_id}")
    finally:
        await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
