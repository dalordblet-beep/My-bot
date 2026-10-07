"""Structured logging setup.

Secrets (BOT_TOKEN, API_HASH, session strings, passwords) are never logged.
"""

from __future__ import annotations

import logging
import sys

from app.config import settings

REDACTED_KEYS = (
    "token",
    "api_hash",
    "password",
    "secret",
    "session",
    "phone",
    "authorization",
)


class SecretRedactionFilter(logging.Filter):
    """Blunt but effective: scrub obvious secret values from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        lowered = message.lower()
        for key in REDACTED_KEYS:
            if key in lowered and settings.api_hash and settings.api_hash in message:
                record.msg = message.replace(settings.api_hash, "***")
                record.args = ()
        if settings.bot_token and settings.bot_token in str(record.msg):
            record.msg = str(record.msg).replace(settings.bot_token, "***")
            record.args = ()
        return True


def setup_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(SecretRedactionFilter())

    root.addHandler(handler)
    root.setLevel((level or settings.log_level).upper())

    # Telethon and aiohttp are chatty at DEBUG.
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
