"""Show the pending join requests of every required subscription.

The onboarding gate lets a user through when they have *joined* a required
channel. When the channel is private and join requests are approved by hand, a
user who has already sent a request is still not a member - so the gate has to
look at the request queue as well. That only works when the bot is an
administrator of the chat, which is exactly what this script reports.

Usage (from the project root):
    python scripts/check_join_requests.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.subscriptions import required_subs  # noqa: E402
from app.telegram.mtproto import _session_file  # noqa: E402
from app.utils.logging_setup import setup_logging  # noqa: E402


async def _session_copy(base: str):
    """A throwaway copy of a session - the live bot holds the original open."""
    path = _session_file(base)
    if not path.exists():
        return None, None
    working = path.with_name(f"{path.stem}__probe.session")
    for suffix in ("", "-journal", "-wal", "-shm"):
        source = Path(f"{path}{suffix}")
        if source.exists():
            shutil.copyfile(source, Path(f"{working}{suffix}"))
    return path, working


async def _bot_client():
    from telethon import TelegramClient

    _, working = await _session_copy(settings.mtproto_session)
    if working is None:
        return None, None
    client = TelegramClient(str(working), settings.api_id, settings.api_hash)
    await client.start(bot_token=settings.bot_token)
    return client, working


async def _user_client():
    """The user session: the ONLY one that can read join requests.

    ``messages.getChatInviteImporters`` is refused to bots outright
    (BotMethodInvalidError - verified live), exactly like account.checkUsername,
    so the request queue is readable only by a real account. That account has to
    be an administrator of the channel.
    """
    from telethon import TelegramClient

    for name in settings.user_session_names:
        if not name:
            continue
        _, working = await _session_copy(name)
        if working is None:
            continue
        client = TelegramClient(str(working), settings.api_id, settings.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            _drop(working)
            continue
        return client, working
    return None, None


def _drop(working) -> None:
    if working is None:
        return
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            Path(f"{working}{suffix}").unlink()
        except OSError:
            pass


async def main() -> int:
    setup_logging()

    from telethon.tl.functions.messages import GetChatInviteImportersRequest
    from telethon.tl.types import InputUserEmpty

    subs = required_subs()
    if not subs:
        print("no required subscriptions configured - nothing to check")
        return 0

    client, working = await _user_client()
    if client is None:
        print(
            "No user session available. Reading join requests needs a real "
            "account:\n  python scripts/login_user_steps.py send <phone>"
        )
        return 2

    try:
        me = await client.get_me()
        print(f"session: @{getattr(me, 'username', '?')} (user account)\n")
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
                        peer=peer, offset_date=datetime(1970, 1, 1),
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
                + (" (showing up to 5)" if importers else "")
            )
            for importer in importers[:5]:
                print(f"    user_id={importer.user_id}")
    finally:
        await client.disconnect()
        _drop(working)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
