"""Session-file lookup: the uploaded user session must be found whether the
bot's working directory is the project root or somewhere else entirely.

This is the deployment failure behind "the bot reports reserved/cooldown
names as free": the session file exists somewhere on the host, but the bot
process only looked in its own working directory.
"""

from __future__ import annotations

from pathlib import Path

from app.telegram import mtproto as mtproto_module


def test_session_file_found_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "username_scanner_user.session").write_bytes(b"sqlite")

    found = mtproto_module._session_file("username_scanner_user", root=tmp_path / "elsewhere")

    assert found == tmp_path / "username_scanner_user.session"
    assert found.exists()


def test_session_file_found_in_the_project_root(tmp_path, monkeypatch):
    """The operator drops the file next to the code; the process runs elsewhere."""
    monkeypatch.chdir(tmp_path)  # working directory has nothing
    root = tmp_path / "project"
    root.mkdir()
    (root / "username_scanner_user.session").write_bytes(b"sqlite")

    found = mtproto_module._session_file("username_scanner_user", root=root)

    assert found == root / "username_scanner_user.session"
    assert found.exists()


def test_session_file_falls_back_to_the_relative_name_when_absent(tmp_path, monkeypatch):
    """Nothing found anywhere: return the conventional name (it will not exist,
    and start_user skips it - with the log now saying where it looked)."""
    monkeypatch.chdir(tmp_path)

    found = mtproto_module._session_file("username_scanner_user", root=tmp_path / "nope")

    assert found == (tmp_path / "username_scanner_user.session").resolve()
    assert not found.exists()


# ---------------------------------------------------- env-var session (PaaS)
import base64  # noqa: E402

from app.config import settings  # noqa: E402


def test_env_var_session_is_materialised_to_disk(tmp_path, monkeypatch):
    """Container hostings wipe /app on restart: the session file travels as
    the MTPROTO_USER_SESSION_DATA env var and is written out at startup."""
    monkeypatch.chdir(tmp_path)
    payload = b"SQLite session bytes"
    monkeypatch.setattr(
        settings, "mtproto_user_session_data", base64.b64encode(payload).decode()
    )

    mtproto_module.MtprotoClient._materialise_session_data()

    written = tmp_path / "username_scanner_user.session"
    assert written.exists()
    assert written.read_bytes() == payload


def test_a_real_session_file_wins_over_the_env_var(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "username_scanner_user.session").write_bytes(b"real file")
    monkeypatch.setattr(
        settings, "mtproto_user_session_data", base64.b64encode(b"env bytes").decode()
    )

    mtproto_module.MtprotoClient._materialise_session_data()

    assert (tmp_path / "username_scanner_user.session").read_bytes() == b"real file"


def test_invalid_env_var_session_is_ignored_without_crashing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "mtproto_user_session_data", "not-base64-###")

    mtproto_module.MtprotoClient._materialise_session_data()

    assert not (tmp_path / "username_scanner_user.session").exists()
