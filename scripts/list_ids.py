"""Print every Telegram ID this bot needs, ready to paste into .env.

Usage
-----
    python scripts/list_ids.py

Requires API_ID / API_HASH (and a session - it will ask you to log in the first
time, same as scripts/login_mtproto.py).

Output:
  * your own numeric user id        -> ADMIN_IDS
  * every channel you can post in   -> REQUIRED_CHANNEL_ID / _USERNAME
  * every group you are in          -> REQUIRED_CHAT_ID / _USERNAME

Remember: the bot itself must be an administrator of the channel/chat,
otherwise Telegram refuses getChatMember and the access gate cannot work.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.utils.logging_setup import setup_logging  # noqa: E402


def _kind(entity) -> str:
    name = type(entity).__name__
    if name == "Channel":
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    if name == "Chat":
        return "group"
    if name == "User":
        return "user"
    return "unknown"


def _username(entity) -> str:
    value = getattr(entity, "username", None)
    return f"@{value}" if value else "-"


async def main() -> int:
    setup_logging("WARNING")

    if not settings.mtproto_configured:
        print(
            "API_ID / API_HASH are not set.\n"
            "Get them at https://my.telegram.org -> API development tools,\n"
            "then put them in .env and run this script again."
        )
        return 2

    try:
        from telethon import TelegramClient
    except ImportError:
        print("Telethon is not installed. Run: pip install -r requirements.txt")
        return 3

    client = TelegramClient(settings.mtproto_session, settings.api_id, settings.api_hash)
    await client.start()
    me = await client.get_me()

    print()
    print("=" * 66)
    print("YOUR ACCOUNT")
    print("=" * 66)
    print(f"  id       : {me.id}")
    print(f"  username : {_username(me)}")
    print(f"  name     : {me.first_name or ''}")
    print()
    print(f"  -> ADMIN_IDS={me.id}")
    print()

    channels: list[tuple[int, str, str]] = []
    groups: list[tuple[int, str, str]] = []

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        kind = _kind(entity)
        if kind in ("channel", "supergroup"):
            channels.append((dialog.id, dialog.name or "", _username(entity)))
        elif kind == "group":
            groups.append((dialog.id, dialog.name or "", _username(entity)))

    def dump(title: str, rows: list[tuple[int, str, str]], env_id: str, env_user: str) -> None:
        print("=" * 66)
        print(title)
        print("=" * 66)
        if not rows:
            print("  (nothing found)")
            print()
            return
        for chat_id, name, username in sorted(rows, key=lambda row: row[1].lower()):
            print(f"  {name}")
            print(f"    id       : {chat_id}")
            print(f"    username : {username}")
            print(f"    {env_id}={chat_id}")
            if username != "-":
                print(f"    {env_user}={username.lstrip('@')}")
            print()

    dump("CHANNELS  (post in / administer)", channels, "REQUIRED_CHANNEL_ID", "REQUIRED_CHANNEL_USERNAME")
    dump("GROUPS    (your chat)", groups, "REQUIRED_CHAT_ID", "REQUIRED_CHAT_USERNAME")

    print("=" * 66)
    print("NEXT STEPS")
    print("=" * 66)
    print("  1. Add the bot to that channel/chat as an ADMINISTRATOR.")
    print("  2. Paste the REQUIRED_* values above into .env.")
    print("  3. Leave REQUIRED_CHANNEL_* empty to skip the channel step,")
    print("     and REQUIRED_CHAT_* empty to skip the chat step.")
    print()

    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
