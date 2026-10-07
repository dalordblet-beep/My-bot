"""Single-instance guard.

Telegram allows only one consumer per bot token: a second polling process gets
``TelegramConflictError: terminated by other getUpdates request`` and, worse,
the two instances take turns answering. If one of them is running older code,
the user sees the interface flip between versions - which is exactly how a
"stale menu" appears at random.

Binding a loopback port is an atomic, self-releasing lock: it cannot go stale
after a crash, unlike a pid file. The port is derived from the bot token so two
different bots on the same machine do not collide.
"""

from __future__ import annotations

import hashlib
import socket

PORT_BASE = 47000
PORT_SPAN = 2000


class AlreadyRunning(RuntimeError):
    """Raised when another instance of this bot holds the lock."""


class SingleInstance:
    def __init__(self, key: str) -> None:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        self.port = PORT_BASE + (int.from_bytes(digest[:2], "big") % PORT_SPAN)
        self._socket: socket.socket | None = None

    def acquire(self) -> None:
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Deliberately NOT setting SO_REUSEADDR: on Windows that would let a
        # second process bind the same port and defeat the whole point.
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(1)
        except OSError as exc:
            sock.close()
            raise AlreadyRunning(
                f"another instance is already running (lock port {self.port})"
            ) from exc
        self._socket = sock

    def release(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
