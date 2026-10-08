"""The router list, in one place.

``main.py`` and the test fixtures must include exactly the same routers. Keeping
two hand-maintained lists is how a new router silently ends up untested - and
that is precisely how the search/profile/battle/support buttons ended up doing
nothing in the test environment while looking fine in production.
"""

from __future__ import annotations

from aiogram import Router

from app.bot.handlers import (
    admin as admin_handlers,
    battle as battle_handlers,
    captcha as captcha_handlers,
    collector as collector_handlers,
    extras as extras_handlers,
    finder as finder_handlers,
    history as history_handlers,
    language as language_handlers,
    profile as profile_handlers,
    search as search_handlers,
    settings as settings_handlers,
    start as start_handlers,
    subscription as subscription_handlers,
    support as support_handlers,
    username as username_handlers,
)

# Order matters: onboarding first, then features, then the legacy check modes.
ROUTER_MODULES = (
    start_handlers,
    language_handlers,
    captcha_handlers,
    subscription_handlers,
    admin_handlers,
    finder_handlers,
    collector_handlers,
    battle_handlers,
    profile_handlers,
    extras_handlers,
    support_handlers,
    username_handlers,
    search_handlers,
    history_handlers,
    settings_handlers,
)


def all_routers() -> list[Router]:
    return [module.router for module in ROUTER_MODULES]
