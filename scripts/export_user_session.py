"""Export the user session file as base64 for container hostings.

Container hostings (Bothost and friends) run the bot in an /app that is
wiped on restart, and uploading files into it is awkward. Instead the
session file travels as the ``MTPROTO_USER_SESSION_DATA`` environment
variable: run this script on the machine where the session lives, copy the
resulting one-line string, and paste it into the hosting's env-var editor.

The base64 string IS full access to the account - treat it like a password.

Usage (from the project root):
    python scripts/export_user_session.py
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.telegram.mtproto import _session_file  # noqa: E402


def main() -> int:
    name = settings.user_session_names[0] if settings.user_session_names else "username_scanner_user"
    path = _session_file(name)
    if not path.exists():
        print(f"Session file not found: {path.resolve()}")
        print("Log in first: python scripts/login_user_steps.py send <phone>")
        return 2

    data = path.read_bytes()
    encoded = base64.b64encode(data).decode()
    out = Path("user_session_base64.txt")
    out.write_text(encoded, encoding="ascii")

    print(f"Session: {path.resolve()} ({len(data)} bytes)")
    print(f"Encoded: {out.resolve()} ({len(encoded)} chars)")
    print()
    print("Next steps:")
    print("  1. Open the hosting panel -> Environment variables.")
    print("  2. Add a variable named MTPROTO_USER_SESSION_DATA")
    print("     with the full contents of user_session_base64.txt as the value.")
    print("  3. Restart the bot. The gate report in the startup log must say")
    print("     'user session pool ready (1 account(s)) - claimability on'.")
    print()
    print("The string is full access to the account - treat it like a password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
