"""Create extra MTProto bot sessions through BotFather, automatically.

Why this exists
---------------
Every Telegram account carries its own rate limit for the authoritative
availability check, so the number of *accounts* the bot can rotate through is
the hard ceiling on how many names it can verify. Bot accounts are free and need
no phone number - they only need to be created in BotFather. Doing that by hand
twenty times is tedious, so this drives the conversation for you using the user
session the bot already has.

What it does
------------
For each bot: sends ``/newbot`` to @BotFather, supplies a display name and a
username, reads the token out of the reply, and (unless ``--no-apply``) appends
it to ``MTPROTO_BOT_SESSIONS`` in ``.env``. The bot picks the new sessions up on
its next restart - each one is a fresh account with its own quota.

Usage (from the project root)
-----------------------------
    python scripts/create_bot_sessions.py --count 10
    python scripts/create_bot_sessions.py --count 5 --no-apply   # just print

The script is deliberately conservative: it paces itself, it retries a taken
username with a new one, and it stops immediately on a FloodWait from BotFather
rather than pushing the account into a longer limit.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.telegram.mtproto import _session_file, bot_running_locally  # noqa: E402
from app.utils.logging_setup import setup_logging  # noqa: E402

BOTFATHER = "BotFather"
# How long to wait for BotFather to answer one step of the dialogue.
REPLY_TIMEOUT = 30.0
# Seconds between steps. BotFather answers "too many attempts" if the dialogue
# is rushed, and each retry costs more time than simply waiting did.
STEP_DELAY = 4.0
# BotFather's token shape: <digits>:<35-ish chars>.
TOKEN_RE = re.compile(r"\b(\d{6,12}:[A-Za-z0-9_-]{30,40})\b")
# A username BotFather rejected because somebody already has it.
TAKEN_HINTS = ("sorry", "already taken", "is already", "too long", "invalid")
# "Sorry, too many attempts. Please try again in 8 seconds."
THROTTLE_RE = re.compile(r"too many attempts.*?(\d+)\s*second", re.IGNORECASE)


def _load_user_client():
    """The *user* session - BotFather only talks to real accounts, not bots.

    The session file is opened directly, with no copy: a copy carries the same
    auth key, and Telegram invalidates a key used from two IP addresses at the
    same time (``AuthKeyDuplicatedError``) - permanently, taking the claimability
    gate with it. That is why ``main()`` refuses to run while a bot is up.
    """
    from telethon import TelegramClient

    for name in settings.user_session_names:
        if not name:
            continue
        path = _session_file(name)
        if not path.exists():
            continue
        return TelegramClient(str(path), settings.api_id, settings.api_hash), path
    return None, None


async def _ask(client, text: str, timeout: float = REPLY_TIMEOUT) -> str:
    """Send one line to BotFather and return its next message.

    Polling the last message rather than installing an event handler keeps the
    dialogue strictly sequential, which is what BotFather expects.
    """
    previous = await client.get_messages(BOTFATHER, limit=1)
    last_id = previous[0].id if previous else 0

    await client.send_message(BOTFATHER, text)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        messages = await client.get_messages(BOTFATHER, limit=1)
        if messages and messages[0].id != last_id:
            return (messages[0].text or "").strip()
    return ""


def _candidate_username(base: str, index: int) -> str:
    """A plausible, unlikely-to-collide bot username (must end in 'bot')."""
    stem = re.sub(r"[^a-z0-9_]", "", base.lower())[:12] or "check"
    suffix = "".join(random.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(4))
    return f"{stem}_{suffix}{index}bot"


async def create_one(client, index: int, base: str) -> str | None:
    """Run the whole /newbot dialogue once. Returns the token, or None.

    BotFather throttles a rushed dialogue ("Sorry, too many attempts"), and that
    answer arrives in the middle of the conversation rather than at a clean
    point, so the whole dialogue is retried after the delay it asks for.
    """
    display = f"{base} checker {index}"

    for round_number in range(3):
        reply = await _ask(client, "/newbot")

        throttle = THROTTLE_RE.search(reply)
        if throttle:
            wait = int(throttle.group(1)) + 3
            print(f"  ~ BotFather asked to wait {wait}s, retrying")
            await asyncio.sleep(wait)
            continue
        if "name" not in reply.lower() and "alright" not in reply.lower():
            print(f"  ! unexpected reply to /newbot: {reply[:120]!r}")

        await asyncio.sleep(STEP_DELAY)
        reply = await _ask(client, display)
        if "username" not in reply.lower():
            print(f"  ! unexpected reply to the display name: {reply[:120]!r}")
            await asyncio.sleep(STEP_DELAY)
            continue

        # Up to five username attempts: BotFather refuses taken ones.
        for attempt in range(5):
            candidate = _candidate_username(base, index + attempt)
            await asyncio.sleep(STEP_DELAY)
            reply = await _ask(client, candidate)

            token = TOKEN_RE.search(reply)
            if token:
                print(f"  + @{candidate} -> token received")
                return token.group(1)

            if THROTTLE_RE.search(reply):
                print("  ~ BotFather throttled mid-dialogue, restarting it")
                await asyncio.sleep(STEP_DELAY)
                break
            if any(hint in reply.lower() for hint in TAKEN_HINTS):
                print(f"  ~ @{candidate} refused, trying another")
                continue
            print(f"  ! no token in reply: {reply[:160]!r}")
            return None
        await asyncio.sleep(STEP_DELAY)
    return None


def _append_tokens(tokens: list[str]) -> str:
    """Add the tokens to MTPROTO_BOT_SESSIONS in .env, preserving the rest."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return "no .env found - nothing applied"

    lines = env_path.read_text(encoding="utf-8").splitlines()
    existing: list[str] = []
    key_index = None
    for position, line in enumerate(lines):
        if line.strip().startswith("MTPROTO_BOT_SESSIONS"):
            key_index = position
            _, _, value = line.partition("=")
            existing = [chunk.strip() for chunk in value.split(",") if chunk.strip()]
            break

    merged = existing + [token for token in tokens if token not in existing]
    new_line = "MTPROTO_BOT_SESSIONS=" + ",".join(merged)

    if key_index is None:
        lines.append(new_line)
    else:
        lines[key_index] = new_line
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f".env updated: {len(existing)} -> {len(merged)} bot session(s)"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Create MTProto bot sessions via BotFather")
    parser.add_argument("--count", type=int, default=10, help="how many bots to create")
    parser.add_argument("--base", default="moged", help="username stem for the new bots")
    parser.add_argument("--no-apply", action="store_true", help="print tokens, do not touch .env")
    parser.add_argument(
        "--force", action="store_true",
        help="run even though a bot is running on this machine (dangerous)",
    )
    args = parser.parse_args()

    setup_logging()

    # Telegram invalidates an auth key used from two IPs at once - permanently.
    # That kills the claimability gate, so refuse rather than risk it.
    if bot_running_locally() and not args.force:
        print(
            "A bot is running on this machine and holds the user session.\n"
            "Stop it first, then run this again (or pass --force if you are sure).\n"
            "Telegram invalidates a session used from two IP addresses at once,\n"
            "and the claimability gate dies with it."
        )
        return 3

    client, working = _load_user_client()
    if client is None:
        print(
            "No user session found. BotFather only talks to real accounts, so log "
            "one in first:\n  python scripts/login_user_steps.py send <phone>"
        )
        return 2

    print(f"using user session {working}")
    await client.connect()
    if not await client.is_user_authorized():
        print("that session is not authorised - re-run the login steps")
        await client.disconnect()
        return 2

    from telethon.errors import FloodWaitError

    tokens: list[str] = []
    try:
        for index in range(1, args.count + 1):
            print(f"[{index}/{args.count}] creating a bot...")
            try:
                token = await create_one(client, index, args.base)
            except FloodWaitError as exc:
                # Stop at once: pushing on only lengthens the limit.
                print(f"BotFather rate-limited this account for {exc.seconds}s - stopping here")
                break
            if token:
                tokens.append(token)
            await asyncio.sleep(STEP_DELAY * 2)
    finally:
        await client.disconnect()
        _drop_working_copy(working)

    print(f"\ncreated {len(tokens)} bot session(s)")
    for token in tokens:
        print(f"  {token}")

    if tokens and not args.no_apply:
        print(_append_tokens(tokens))
        print("restart the bot to put the new sessions to work")
    return 0 if tokens else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
