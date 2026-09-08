"""Tests for the command-line interface."""

from __future__ import annotations

import csv

import pytest
from typer.testing import CliRunner

from humble_steam_key_redeemer import __version__
from humble_steam_key_redeemer.cli import app
from humble_steam_key_redeemer.core import KeyRecord, KeyState, RedeemerStore, RedemptionEngine

runner = CliRunner()


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
    return tmp_path / "state"


def _seed(state_dir) -> RedeemerStore:
    store = RedeemerStore(state_dir / "redeemer.db")
    store.upsert_keys(
        [
            KeyRecord(
                gamekey="order1",
                machine_name="portal2",
                human_name="Portal 2",
                key_type="steam",
                steam_app_id=620,
                redeemed_key_val="AAAAA-BBBBB-CCCCC",
                state=KeyState.REVEALED,
            ),
            KeyRecord(
                gamekey="order1",
                machine_name="gog_game",
                human_name="A GOG Game",
                key_type="gog",
            ),
        ]
    )
    return store


class TestTopLevel:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_help_lists_commands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in ("sync", "redeem", "status", "export", "login", "logout"):
            assert command in result.stdout


class TestStatus:
    def test_reports_empty_database(self, state_dir):
        result = runner.invoke(app, ["status", "--state-dir", str(state_dir)])
        assert result.exit_code == 0
        assert "No keys stored" in result.stdout

    def test_summarizes_stored_keys(self, state_dir):
        _seed(state_dir)
        result = runner.invoke(app, ["status", "--state-dir", str(state_dir)])
        assert result.exit_code == 0
        assert "revealed" in result.stdout


class TestExport:
    def test_writes_a_csv(self, state_dir, tmp_path):
        _seed(state_dir)
        destination = tmp_path / "out.csv"

        result = runner.invoke(app, ["export", str(destination), "--state-dir", str(state_dir)])

        assert result.exit_code == 0
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        assert rows[0][0] == "human_name"
        assert len(rows) == 3

    def test_steam_only_filters(self, state_dir, tmp_path):
        _seed(state_dir)
        destination = tmp_path / "steam.csv"

        result = runner.invoke(
            app, ["export", str(destination), "--state-dir", str(state_dir), "--steam-only"]
        )

        assert result.exit_code == 0
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == 2


class TestRedeem:
    def test_reports_nothing_to_do_on_an_empty_database(self, state_dir):
        result = runner.invoke(app, ["redeem", "--state-dir", str(state_dir)])
        assert result.exit_code == 0
        assert "Nothing to redeem" in result.stdout

    def test_dry_run_requires_a_steam_session(self, state_dir):
        """Ownership cannot be checked without signing in, so this must fail loudly."""
        _seed(state_dir)
        result = runner.invoke(app, ["redeem", "--state-dir", str(state_dir), "--dry-run"])
        assert result.exit_code == 1

    def test_dry_run_redeems_nothing(self, state_dir, monkeypatch):
        _seed(state_dir)

        class FakeGateway:
            def __init__(self, *_args, **_kwargs) -> None:
                self.redeemed: list[str] = []

            def restore(self) -> bool:
                return True

            def list_owned_apps(self) -> dict[int, str]:
                return {}

            def redeem_key(self, key: str) -> dict[str, object]:  # pragma: no cover - must not run
                raise AssertionError("--dry-run must not contact Steam")

            def __enter__(self):
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr("humble_steam_key_redeemer.cli._app.VendorFabricSteamGateway", FakeGateway)

        result = runner.invoke(app, ["redeem", "--state-dir", str(state_dir), "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run" in result.stdout


class TestLogout:
    def test_reports_when_nothing_is_stored(self, state_dir):
        result = runner.invoke(app, ["logout", "--state-dir", str(state_dir)])
        assert result.exit_code == 0
        assert "No saved sessions" in result.stdout

    def test_removes_saved_sessions(self, state_dir):
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "humble-session.json").write_text("{}", encoding="utf-8")
        (state_dir / "steam-session.json").write_text("{}", encoding="utf-8")

        result = runner.invoke(app, ["logout", "--state-dir", str(state_dir)])

        assert result.exit_code == 0
        assert not (state_dir / "humble-session.json").exists()
        assert not (state_dir / "steam-session.json").exists()


class TestRevealWiring:
    """`--reveal` must actually reach the engine."""

    @staticmethod
    def _patch_gateway(monkeypatch):
        class FakeGateway:
            def __init__(self, *_a, **_k) -> None:
                self.redeemed: list[str] = []

            def restore(self) -> bool:
                return True

            def list_owned_apps(self) -> dict[int, str]:
                return {}

            def redeem_key(self, key: str) -> dict[str, object]:
                self.redeemed.append(key)
                return {"success": True, "result": None, "detail": "ok", "items": []}

            def __enter__(self):
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr("humble_steam_key_redeemer.cli._app.VendorFabricSteamGateway", FakeGateway)

    def _unrevealed(self, state_dir):
        store = RedeemerStore(state_dir / "redeemer.db")
        store.upsert_keys(
            [
                KeyRecord(
                    gamekey="order1",
                    machine_name="unrevealed",
                    human_name="Unrevealed Game",
                    key_type="steam",
                )
            ]
        )
        return store

    def test_without_reveal_the_key_is_skipped(self, state_dir, monkeypatch):
        self._patch_gateway(monkeypatch)
        self._unrevealed(state_dir)

        result = runner.invoke(app, ["redeem", "--state-dir", str(state_dir), "--yes"])

        assert result.exit_code == 0
        assert "unrevealed and will be skipped" in result.stdout

    def test_with_reveal_the_engine_receives_a_callback(self, state_dir, monkeypatch):
        """Previously --reveal was accepted but never wired up, so it silently did nothing."""
        self._patch_gateway(monkeypatch)
        self._unrevealed(state_dir)

        captured: dict[str, object] = {}
        real_redeem = RedemptionEngine.redeem

        def spy(self, plan, **kwargs):
            captured["reveal"] = kwargs.get("reveal")
            return real_redeem(self, plan, **kwargs)

        monkeypatch.setattr(RedemptionEngine, "redeem", spy)
        monkeypatch.setattr(
            "humble_steam_key_redeemer.cli._app.HumbleBrowser",
            lambda _settings: _FakeBrowserCtx(),
        )
        monkeypatch.setattr(
            "humble_steam_key_redeemer.cli._app.HumbleClient",
            lambda _browser: _FakeHumbleClient(),
        )

        result = runner.invoke(app, ["redeem", "--state-dir", str(state_dir), "--yes", "--reveal"])

        assert result.exit_code == 0
        assert captured["reveal"] is not None


class _FakeBrowserCtx:
    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakeHumbleClient:
    def reveal_key(self, _record) -> str:
        return "ZZZZZ-YYYYY-XXXXX"
