"""Resolve symbolic emoji names to real Telegram custom-emoji ids.

Telegram custom emoji ids are opaque 64-bit numbers. An id that is not a real
custom emoji makes Telegram reject the *whole* message, so nothing here is
guessed: every candidate is validated with ``getCustomEmojiStickers`` before it
is written out.

Ids are looked up through the public search service at https://ehub.tg (the
backend of the open-source tg-emoji-hub project). That service is only used at
build time - the resolved ids are baked into ``CUSTOM_EMOJI_IDS``, so the bot
has no runtime dependency on it.

Usage
-----
    python scripts/find_emoji.py                  # resolve and print JSON
    python scripts/find_emoji.py --write          # also update .env
    python scripts/find_emoji.py --only search,fire
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.emoji import PLAIN  # noqa: E402

SEARCH_URL = "https://ehub.tg/api/v1/search"
TIMEOUT = 20

# symbolic name -> (search keyword, the standard emoji it must correspond to)
TARGETS: dict[str, tuple[str, str]] = {
    "search": ("magnifying glass", "\U0001F50E"),
    "seedling": ("seedling plant", "\U0001F331"),
    "gem": ("gem stone diamond", "\U0001F48E"),
    "fire": ("fire flame", "\U0001F525"),
    "bolt": ("high voltage lightning", "\u26A1"),
    "clock": ("clock", "\U0001F570\uFE0F"),
    "gear": ("gear settings", "\u2699\uFE0F"),
    "crown": ("crown king", "\U0001F451"),
    "check": ("check mark button", "\u2705"),
    "cross": ("cross mark", "\u274C"),
    "warn": ("warning sign", "\u26A0\uFE0F"),
    "shield": ("shield", "\U0001F6E1\uFE0F"),
    "channel": ("loudspeaker megaphone", "\U0001F4E3"),
    "chat": ("speech balloon", "\U0001F4AC"),
    "users": ("busts in silhouette people", "\U0001F465"),
    "person": ("bust in silhouette", "\U0001F464"),
    "ban": ("prohibited no entry", "\U0001F6AB"),
    "hourglass": ("hourglass", "\u231B"),
    "gift": ("wrapped gift present", "\U0001F381"),
    "chart": ("bar chart", "\U0001F4CA"),
    "wrench": ("tools", "\U0001F6E0\uFE0F"),
    "clipboard": ("clipboard", "\U0001F4CB"),
    "home": ("house home", "\U0001F3E0"),
    "back": ("arrow", "\u21A9\uFE0F"),
    "hammer": ("hammer", "\U0001F528"),
    "dove": ("dove", "\U0001F54A\uFE0F"),
    "broom": ("broom sweep", "\U0001F9F9"),
    "scroll": ("scroll", "\U0001F4DC"),
    "folder": ("folder", "\U0001F5C2\uFE0F"),
    "monitor": ("desktop computer monitor", "\U0001F5A5\uFE0F"),
    "pencil": ("pencil", "\U0001F4DD"),
    "receipt": ("receipt", "\U0001F9FE"),
    "refresh": ("counterclockwise arrows refresh", "\U0001F504"),
    "numbers": ("input numbers", "\U0001F522"),
    "satellite": ("satellite", "\U0001F4E1"),
    "shield_lock": ("security lock", "\U0001F510"),
    "ticket": ("ticket", "\U0001F39F\uFE0F"),
    "stopwatch": ("stopwatch", "\u23F1\uFE0F"),
    "lock": ("locked padlock", "\U0001F512"),
    "key": ("key", "\U0001F511"),
    "sparkle": ("sparkles", "\u2728"),
    "robot": ("robot", "\U0001F916"),
    "database": ("database", "\U0001F5C4\uFE0F"),
    "available": ("green circle", "\U0001F7E2"),
    "occupied": ("red circle", "\U0001F534"),
    "collectible": ("gem stone", "\U0001F48E"),
    "history": ("clock", "\U0001F570\uFE0F"),
    "arrow_left": ("left arrow back", "\u2B05\uFE0F"),
    "arrow_right": ("right arrow", "\u27A1\uFE0F"),
    "antenna": ("satellite", "\U0001F4E1"),
    "battle": ("crossed swords", "\u2694\uFE0F"),
    "trophy": ("trophy", "\U0001F3C6"),
    "bell": ("bell", "\U0001F514"),
    "target": ("direct hit target", "\U0001F3AF"),
    "filter": ("slider", "\U0001F39A\uFE0F"),
    "letters": ("input latin letters", "\U0001F524"),
    "question": ("question mark", "\u2753"),
    "envelope": ("envelope", "\u2709\uFE0F"),
    "rocket": ("rocket", "\U0001F680"),
    "star": ("star", "\u2B50"),
    "medal": ("sports medal", "\U0001F3C5"),
    "handshake": ("handshake", "\U0001F91D"),
    "info": ("information", "\u2139\uFE0F"),
    "calendar": ("calendar", "\U0001F4C5"),
    "id": ("identification card", "\U0001F194"),
    "tag": ("label tag", "\U0001F3F7\uFE0F"),
    "palette": ("artist palette", "\U0001F3A8"),
    "money": ("money bag", "\U0001F4B0"),
    "scales": ("balance scale", "\u2696\uFE0F"),
    "crown2": ("crown", "\U0001F451"),
    "sparkles2": ("sparkles", "\u2728"),
    "boom": ("collision", "\U0001F4A5"),
    "crossed": ("crossed swords", "\u2694\uFE0F"),
    "hourglass2": ("hourglass done", "\u231B"),
    "clipboard2": ("clipboard", "\U0001F4CB"),
    "pencil2": ("pencil", "\U0001F4DD"),
    "floppy": ("floppy disk save", "\U0001F4BE"),
    "wrench2": ("wrench", "\U0001F527"),
    "eye": ("eye", "\U0001F441\uFE0F"),
    "link": ("link", "\U0001F517"),
    "shield2": ("shield", "\U0001F6E1\uFE0F"),
}



def search(keyword: str, limit: int = 100) -> list[dict]:
    url = f"{SEARCH_URL}?q={urllib.parse.quote(keyword)}&limit={limit}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "username-scanner/1.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = json.load(response)
    return payload.get("data", {}).get("items", []) or []


def pick(items: list[dict], want: str) -> list[str]:
    """Candidate ids whose standard emoji matches, static ones first."""
    matches = [item for item in items if item.get("alt") == want]
    static = [item for item in matches if not item.get("is_animated")]
    ordered = static + [item for item in matches if item.get("is_animated")]
    seen: set[str] = set()
    ids: list[str] = []
    for item in ordered:
        emoji_id = str(item.get("custom_emoji_id") or "")
        if emoji_id and emoji_id not in seen:
            seen.add(emoji_id)
            ids.append(emoji_id)
    return ids


async def verify(bot: Bot, ids: list[str]) -> str | None:
    """Return the first id Telegram confirms as a real custom emoji."""
    for emoji_id in ids[:4]:
        try:
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=[emoji_id])
        except Exception:
            continue
        if stickers:
            return emoji_id
    return None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write the result into .env")
    parser.add_argument("--only", default="", help="comma separated subset of names")
    args = parser.parse_args()

    if not settings.bot_token:
        print("BOT_TOKEN is not set in .env")
        return 2

    only = {part.strip() for part in args.only.split(",") if part.strip()}
    targets = {k: v for k, v in TARGETS.items() if not only or k in only}

    bot = Bot(token=settings.bot_token)
    resolved: dict[str, str] = {}
    failed: list[str] = []

    try:
        for name, (keyword, want) in targets.items():
            if name not in PLAIN:
                continue
            try:
                candidates = pick(search(keyword), want)
            except Exception as exc:
                print(f"  [--]   {name:14} search failed: {type(exc).__name__}")
                failed.append(name)
                continue

            if not candidates:
                print(f"  [--]   {name:14} no {want} found for {keyword!r}")
                failed.append(name)
                continue

            emoji_id = await verify(bot, candidates)
            if emoji_id:
                resolved[name] = emoji_id
                print(f"  [ok]   {name:14} {want}  id={emoji_id}")
            else:
                print(f"  [--]   {name:14} candidates rejected by Telegram")
                failed.append(name)
    finally:
        await bot.session.close()

    print()
    print(f"resolved {len(resolved)} / {len(targets)}")
    if failed:
        print("unresolved:", ", ".join(failed))
    print()
    print("CUSTOM_EMOJI_IDS=" + json.dumps(resolved, ensure_ascii=False, separators=(",", ":")))

    if args.write:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines()
        payload = json.dumps(resolved, ensure_ascii=False, separators=(",", ":"))
        for index, line in enumerate(lines):
            if line.startswith("CUSTOM_EMOJI_IDS="):
                lines[index] = f"CUSTOM_EMOJI_IDS={payload}"
                break
        else:
            lines.append(f"CUSTOM_EMOJI_IDS={payload}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwritten to {env_path}")

    return 0 if resolved else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
