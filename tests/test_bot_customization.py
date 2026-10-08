"""Admin-editable bot customisation: welcome text, button labels and theme.

These are the "real settings" the panel exposes instead of the legacy
channel-id fields: everything here is stored in runtime config and applied
live without a restart.
"""

from __future__ import annotations

import json

import pytest
from aiogram.enums import ButtonStyle

from app.bot import texts
from app.bot.keyboards import base
from app.database import repository as repo
from app.services import i18n
from app.services.runtime_config import runtime


@pytest.fixture
def clean_overrides():
    """Isolate runtime overrides and the i18n label cache per test."""
    saved = dict(runtime._overrides)
    saved_labels = dict(i18n._LABEL_OVERRIDES)
    yield
    runtime._overrides.clear()
    runtime._overrides.update(saved)
    i18n._LABEL_OVERRIDES.clear()
    i18n._LABEL_OVERRIDES.update(saved_labels)


def test_custom_labels_rename_any_key(clean_overrides):
    runtime._overrides["custom_labels"] = {"btn.search": "Find names!"}
    i18n.refresh_custom_labels()
    assert i18n.t("en", "btn.search") == "Find names!"
    # Other keys are untouched.
    assert i18n.t("en", "btn.back") != "btn.back"


def test_custom_labels_support_placeholders(clean_overrides):
    runtime._overrides["custom_labels"] = {"gate.subs.generic": "Join {n}"}
    i18n.refresh_custom_labels()
    assert i18n.t("en", "gate.subs.generic", n=2) == "Join 2"


def test_welcome_message_override(clean_overrides):
    runtime._overrides["welcome_message"] = "Hi {name}, welcome aboard!"
    user = type("U", (), {"first_name": "Ivan", "username": None})()
    assert texts.welcome("en", user) == "Hi Ivan, welcome aboard!"


def test_welcome_message_without_placeholder(clean_overrides):
    runtime._overrides["welcome_message"] = "Static greeting"
    user = type("U", (), {"first_name": "Ivan", "username": None})()
    assert texts.welcome("en", user) == "Static greeting"


def test_button_theme_remaps_roles(clean_overrides):
    base.apply_button_theme({"primary": "success", "danger": "danger"})
    assert base._THEME["primary"] is ButtonStyle.SUCCESS
    assert base._THEME["success"] is ButtonStyle.SUCCESS
    assert base._THEME["danger"] is ButtonStyle.DANGER
    assert base._THEME["neutral"] is None


def test_button_theme_invalid_values_fall_back(clean_overrides):
    base.apply_button_theme({"primary": "nonsense", "success": 42})
    assert base._THEME["primary"] is ButtonStyle.PRIMARY
    assert base._THEME["success"] is ButtonStyle.SUCCESS


async def test_runtime_set_stores_json_and_reads_back(clean_overrides, monkeypatch):
    stored: dict[str, str] = {}

    async def fake_set_bot_setting(session, key, value):
        stored[key] = value

    monkeypatch.setattr(repo, "set_bot_setting", fake_set_bot_setting)
    value = await runtime.set(None, "custom_labels", '{"btn.search":"Find!"}')
    assert value == {"btn.search": "Find!"}
    # Persisted as JSON, not a Python dict repr.
    assert json.loads(stored["custom_labels"]) == {"btn.search": "Find!"}
    assert runtime.custom_labels == {"btn.search": "Find!"}
    assert runtime.button_theme == {}


def test_unlimited_search_flag(clean_overrides, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "unlimited_search", True)
    assert runtime.unlimited_search is True
    monkeypatch.setattr(settings, "unlimited_search", False)
    assert runtime.unlimited_search is False
