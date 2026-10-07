"""FSM states."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class UsernameStates(StatesGroup):
    waiting_username = State()
    waiting_search_seed = State()
    waiting_search_count = State()


class AdminStates(StatesGroup):
    waiting_user_query = State()
    waiting_ban_reason = State()
    waiting_restrict_reason = State()
    waiting_custom_restrict = State()
    waiting_note = State()
    waiting_setting_value = State()
    waiting_privilege_target = State()


class CaptchaStates(StatesGroup):
    solving = State()


class FinderStates(StatesGroup):
    """Search wizard inputs."""

    waiting_mask = State()
    waiting_score = State()
    waiting_watch = State()
    waiting_bulk = State()


class BattleStates(StatesGroup):
    """Username battle inputs."""

    waiting_left = State()
    waiting_right = State()
