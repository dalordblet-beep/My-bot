"""Smoke-test the MTProto bot-session pool without starting the whole bot.

Logs every configured extra bot session (``MTPROTO_BOT_SESSIONS``) in with its
own token - no phone number involved - resolves one probe username through
each, and reports which sessions are alive. Useful after adding tokens or when
searches start reporting throttling.

Usage (from the project root):
    python scripts/check_pool.py [probe_username]

The probe username defaults to ``telegram`` (always occupied), so the check
costs exactly one ``contacts.resolveUsername`` per session.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.utils.logging_setup import get_logger  # noqa: E402

logger = get_logger(__name__)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check the MTProto bot-session pool")
    parser.add_argument("username", nargs="?", default="telegram")
    args = parser.parse_args()

    try:
        from telethon.errors import (
            FloodWaitError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
            UsernameOccupiedError,
        )
        from telethon.tl.functions.account import CheckUsernameRequest
        from telethon.tl.functions.contacts import ResolveUsernameRequest
    except Exception:
        print("telethon is not installed - run pip install -r requirements.txt")
        return 2

    if not settings.mtproto_configured:
        print("API_ID / API_HASH are not configured - nothing to check")
        return 2

    tokens = settings.bot_session_tokens
    if not tokens:
        print("MTPROTO_BOT_SESSIONS is empty - the pool is just the main session")
        return 0

    from telethon import TelegramClient

    print(
        f"checking {len(tokens)} extra session(s) with probe username "
        f"'{args.username}'..."
    )
    ok = 0
    for index, token in enumerate(tokens, start=2):
        name = f"{settings.mtproto_session}-p{index}"
        client = None
        try:
            client = TelegramClient(name, settings.api_id, settings.api_hash)
            await client.start(bot_token=token)
            if not await client.is_user_authorized():
                print(f"[{name}] NOT authorised")
                continue
            me = await client.get_me()
            handle = getattr(me, "username", None) or "?"
            try:
                await client(ResolveUsernameRequest(args.username))
                verdict = "resolved"
            except UsernameNotOccupiedError:
                verdict = "not_occupied (free)"
            except UsernameOccupiedError:
                verdict = "occupied"
            except UsernameInvalidError:
                verdict = "invalid (unassignable)"
            print(f"[{name}] @{handle} -> '{args.username}': {verdict}  OK")
            ok += 1
        except FloodWaitError as exc:
            print(f"[{name}] FLOOD WAIT {exc.seconds}s - Telegram limited it already")
        except Exception as exc:
            print(f"[{name}] FAILED: {type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    print(f"\n{ok}/{len(tokens)} bot session(s) ready")

    # ---------------------------------------------------------- user session
    # The claimability gate: without it occupied/reserved/cooldown names get
    # reported as free. Report exactly what a deployment is missing.
    from app.telegram import mtproto as mtproto_module

    user_found = False
    for name in settings.user_session_names:
        if not name:
            continue
        path = mtproto_module._session_file(name)
        if not path.exists():
            continue
        client = None
        try:
            client = TelegramClient(str(path), settings.api_id, settings.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                print(f"[user:{path}] NOT authorised - re-login required")
                continue
            me = await client.get_me()
            handle = getattr(me, "username", None) or "?"
            try:
                verdict = await client(CheckUsernameRequest(args.username))
                gate = "CLAIMABLE" if verdict else "unassignable/occupied"
            except UsernameInvalidError:
                gate = "unassignable (USERNAME_INVALID)"
            except FloodWaitError as exc:
                gate = f"FLOOD WAIT {exc.seconds}s - gate temporarily down"
            print(f"[user:{path}] @{handle} -> '{args.username}': {gate}  OK")
            user_found = True
        except Exception as exc:
            print(f"[user:{path}] FAILED: {type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    if user_found:
        print("claimability gate: ON")
    else:
        print(
            "claimability gate: OFF - no user session found! This is why "
            "occupied/reserved names get reported as free. Copy "
            f"{settings.user_session_names[0]}.session next to the code and "
            "restart."
        )
    return 0 if ok == len(tokens) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
