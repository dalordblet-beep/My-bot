"""Two-step, non-interactive USER login for the assignability check.

``login_mtproto.py --user`` prompts for a phone and then a code on stdin, which
does not work from a non-interactive shell. The code arrives inside the Telegram
app, so the login is split into separate commands:

    python scripts/login_user_steps.py send +79991234567   # sends the code
    python scripts/login_user_steps.py sign 12345          # completes the login
    python scripts/login_user_steps.py password <pw>       # only if 2FA is on

State (phone + phone_code_hash) is kept in ``_user_login_state.json`` and removed
once the login succeeds. The session is written to ``MTPROTO_USER_SESSION``
(default ``username_scanner_user``), which the bot loads automatically on start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.utils.logging_setup import setup_logging  # noqa: E402

STATE = Path(__file__).resolve().parent.parent / "_user_login_state.json"

# Which session file this run writes. Overridable with --name, so a pool of
# checker accounts can be created (list them in MTPROTO_USER_SESSIONS).
_SESSION_NAME = settings.mtproto_user_session


def _client():
    from telethon import TelegramClient

    return TelegramClient(_SESSION_NAME, settings.api_id, settings.api_hash)


async def send(phone: str) -> int:
    client = _client()
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        STATE.write_text(json.dumps({"phone": phone, "hash": sent.phone_code_hash}))
        print(f"CODE_SENT phone={phone}")
    except Exception as exc:
        print(f"SEND_FAILED {type(exc).__name__}: {exc}")
        return 2
    finally:
        await client.disconnect()
    return 0


async def sign(code: str) -> int:
    from telethon.errors import SessionPasswordNeededError

    if not STATE.exists():
        print("NO_STATE run 'send <phone>' first")
        return 2
    state = json.loads(STATE.read_text())
    client = _client()
    await client.connect()
    try:
        try:
            await client.sign_in(
                phone=state["phone"], code=code, phone_code_hash=state["hash"]
            )
        except SessionPasswordNeededError:
            print("NEEDS_2FA")
            return 3
        me = await client.get_me()
        print(f"SIGNED_IN as {getattr(me, 'username', None) or me.id} bot={getattr(me, 'bot', None)}")
    except Exception as exc:
        print(f"SIGN_FAILED {type(exc).__name__}: {exc}")
        return 4
    finally:
        await client.disconnect()
    STATE.unlink(missing_ok=True)
    return 0


async def password(pw: str) -> int:
    client = _client()
    await client.connect()
    try:
        await client.sign_in(password=pw)
        me = await client.get_me()
        print(f"SIGNED_IN as {getattr(me, 'username', None) or me.id} bot={getattr(me, 'bot', None)}")
    except Exception as exc:
        print(f"PW_FAILED {type(exc).__name__}: {exc}")
        return 4
    finally:
        await client.disconnect()
    STATE.unlink(missing_ok=True)
    return 0


def main(argv: list[str]) -> int:
    global _SESSION_NAME
    setup_logging("WARNING")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", default=settings.mtproto_user_session,
        help="session base name (default: MTPROTO_USER_SESSION). Put it BEFORE the command.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send")
    s.add_argument("phone")
    g = sub.add_parser("sign")
    g.add_argument("code")
    w = sub.add_parser("password")
    w.add_argument("pw")
    args = parser.parse_args(argv)
    _SESSION_NAME = args.name

    if args.cmd == "send":
        return asyncio.run(send(args.phone))
    if args.cmd == "sign":
        return asyncio.run(sign(args.code))
    return asyncio.run(password(args.pw))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
