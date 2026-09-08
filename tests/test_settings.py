"""Tests for configuration and session handling."""

from __future__ import annotations

import json

import pytest
from vendor_fabric.steam import SteamSession

from humble_steam_key_redeemer.settings import Settings
from humble_steam_key_redeemer.steam import load_session, save_session


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
    return Settings(state_dir=tmp_path / "state")


class TestSettings:
    def test_paths_live_under_the_state_directory(self, settings):
        assert settings.database_path.parent == settings.state_dir
        assert settings.humble_session_path.parent == settings.state_dir
        assert settings.steam_session_path.parent == settings.state_dir

    def test_state_directory_is_owner_only(self, settings):
        """Session files in it are bearer credentials."""
        created = settings.ensure_state_dir()
        assert created.stat().st_mode & 0o777 == 0o700

    def test_environment_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HSKR_MATCH_THRESHOLD", "85")
        monkeypatch.setenv("HSKR_STATE_DIR", str(tmp_path))
        assert Settings().match_threshold == 85

    def test_thresholds_are_bounded(self):
        with pytest.raises(ValueError, match="less than or equal to 100"):
            Settings(match_threshold=101)

    def test_home_is_expanded(self):
        assert "~" not in str(Settings(state_dir="~/somewhere").state_dir)


class TestSteamSessionStorage:
    def test_session_round_trips(self, settings):
        session = SteamSession(
            steam_id="76561197960287930",
            access_token="access",
            refresh_token="refresh",
            cookies={"store.steampowered.com": {"sessionid": "abc"}},
        )
        save_session(session, settings.steam_session_path)
        restored = load_session(settings.steam_session_path)

        assert restored is not None
        assert restored.steam_id == session.steam_id
        assert restored.session_id("store.steampowered.com") == "abc"

    def test_session_file_is_owner_only(self, settings):
        session = SteamSession(steam_id="1", access_token="a", refresh_token="r")
        path = save_session(session, settings.steam_session_path)
        assert path.stat().st_mode & 0o777 == 0o600

    def test_missing_session_returns_none(self, settings):
        assert load_session(settings.steam_session_path) is None

    def test_corrupt_session_returns_none_rather_than_raising(self, settings):
        """A half-written file must mean "sign in again", not a crash."""
        settings.ensure_state_dir()
        settings.steam_session_path.write_text("{not json", encoding="utf-8")
        assert load_session(settings.steam_session_path) is None

    def test_incomplete_session_returns_none(self, settings):
        settings.ensure_state_dir()
        settings.steam_session_path.write_text(json.dumps({"steam_id": "1"}), encoding="utf-8")
        assert load_session(settings.steam_session_path) is None
