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
