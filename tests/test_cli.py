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

            def restore(self, account_name: str | None = None) -> bool:
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

            def restore(self, account_name: str | None = None) -> bool:
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
            lambda _browser, _timeout=0: _FakeHumbleClient(),
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
    def __init__(self, logged_in: bool = True) -> None:
        self._logged_in = logged_in

    def is_logged_in(self) -> bool:
        return self._logged_in

    def reveal_key(self, _record) -> str:
        return "ZZZZZ-YYYYY-XXXXX"


class TestRevealRequiresHumbleSession:
    """A fresh page is about:blank, so the reveal fetch would lose cookies."""

    def test_reveal_aborts_when_not_signed_in(self, state_dir, monkeypatch):
        TestRevealWiring._patch_gateway(monkeypatch)
        store = RedeemerStore(state_dir / "redeemer.db")
        store.upsert_keys(
            [KeyRecord(gamekey="o", machine_name="u", human_name="Unrevealed", key_type="steam")]
        )
        monkeypatch.setattr("humble_steam_key_redeemer.cli._app.HumbleBrowser", lambda _s: _FakeBrowserCtx())
        monkeypatch.setattr(
            "humble_steam_key_redeemer.cli._app.HumbleClient",
            lambda _b, _timeout=0: _FakeHumbleClient(logged_in=False),
        )

        result = runner.invoke(app, ["redeem", "--state-dir", str(state_dir), "--yes", "--reveal"])

        assert result.exit_code == 1


class TestBrowserCommand:
    """`hskr browser` is the agent-facing path, so its output is the whole UI."""

    def test_an_unknown_action_is_refused(self, state_dir):
        result = runner.invoke(app, ["browser", "wipe-everything", "--state-dir", str(state_dir)])

        assert result.exit_code == 1
        assert "Unknown browser action" in result.output

    def test_a_silent_browser_says_what_to_check(self, state_dir):
        """The common cause is a stale extension id, so the error names it."""
        result = runner.invoke(app, ["browser", "status", "--state-dir", str(state_dir), "--timeout", "1"])

        assert result.exit_code == 1
        assert "did not respond" in result.output
        assert "extension-id" in result.output

    def test_a_reported_failure_exits_nonzero(self, state_dir, monkeypatch):
        """An agent has to be able to tell a failed run from a finished one."""
        monkeypatch.setattr(
            "humble_steam_key_redeemer.cli._app.run_command",
            lambda *a, **k: {"ok": False, "error": "Not signed in to Steam."},
        )
        result = runner.invoke(app, ["browser", "redeem", "--state-dir", str(state_dir)])

        assert result.exit_code == 1
        assert "Not signed in to Steam." in result.output


class TestBrowserOutput:
    """Every count the bridge reports has to reach the person reading it."""

    def _render(self, state_dir, monkeypatch, reply: dict) -> str:
        monkeypatch.setattr(
            "humble_steam_key_redeemer.cli._app.run_command",
            lambda *a, **k: {"ok": True, "reply": reply},
        )
        result = runner.invoke(app, ["browser", "preview", "--state-dir", str(state_dir)])
        assert result.exit_code == 0
        return result.output

    def test_unrevealed_keys_are_explained(self, state_dir, monkeypatch):
        """Otherwise a library of them reports 0 to attempt and no reason."""
        output = self._render(state_dir, monkeypatch, {"attempts": [], "skipped": 12, "unrevealed": 12})

        assert "0" in output
        assert "unrevealed" in output
        assert "--reveal" in output

    def test_capped_uncertain_matches_say_how_many_were_left_out(self, state_dir, monkeypatch):
        output = self._render(
            state_dir,
            monkeypatch,
            {
                "attempts": [{"title": "Celeste"}],
                "skipped": 0,
                "uncertain": [{"title": "A", "matched": "B"}],
                "uncertain_total": 30,
            },
        )

        assert "29 more" in output

    def test_failures_before_steam_are_not_counted_as_attempts(self, state_dir, monkeypatch):
        """They spent no activation, so folding them in would mislead."""
        output = self._render(
            state_dir,
            monkeypatch,
            {"attempted": 3, "redeemed": 3, "failed_before_steam": 2, "pending": 5},
        )

        assert "3 redeemed" in output
        assert "never reached Steam" in output


class TestBrowserSummaries:
    """Each reply shape the bridge sends has to render as something readable."""

    def _render(self, state_dir, monkeypatch, reply: dict, action: str = "sync") -> str:
        monkeypatch.setattr(
            "humble_steam_key_redeemer.cli._app.run_command",
            lambda *a, **k: {"ok": True, "reply": reply},
        )
        result = runner.invoke(app, ["browser", action, "--state-dir", str(state_dir)])
        assert result.exit_code == 0
        return result.output

    def test_an_import_reports_what_it_found(self, state_dir, monkeypatch):
        output = self._render(
            state_dir,
            monkeypatch,
            {"orders": 47, "keys": 310, "steam_keys": 288, "revealed": 12},
        )

        assert "310" in output
        assert "47" in output
        assert "288" in output

    def test_an_unfamiliar_shape_still_prints_rather_than_vanishing(self, state_dir, monkeypatch):
        """A reply this does not recognise must not render as nothing."""
        output = self._render(state_dir, monkeypatch, {"humble": True, "steam": False}, "status")

        assert "humble" in output
        assert "steam" in output


class TestRecheck:
    """Two states are terminal on purpose, and both can be reached wrongly."""

    def _store(self, state_dir, **overrides) -> RedeemerStore:
        store = RedeemerStore(state_dir / "redeemer.db")
        values = {
            "gamekey": "order1",
            "machine_name": "celeste",
            "human_name": "Celeste",
            "key_type": "steam",
            "redeemed_key_val": "AAAAA-BBBBB-CCCCC",
            "state": KeyState.SKIPPED,
        }
        values.update(overrides)
        store.upsert_keys([KeyRecord(**values)])
        return store

    def test_a_key_skipped_in_error_comes_back(self, state_dir):
        """A validator that improves must not leave its old rejections stranded."""
        store = self._store(state_dir)

        result = runner.invoke(app, ["recheck", "--state-dir", str(state_dir)])

        assert result.exit_code == 0
        assert "Celeste" in result.output
        assert store.all_keys()[0].state is KeyState.REVEALED

    def test_a_gift_link_stays_skipped(self, state_dir):
        """Sending one spends one of about ten failed activations an hour."""
        store = self._store(state_dir, redeemed_key_val="https://www.humblebundle.com/gift?key=abc")

        runner.invoke(app, ["recheck", "--state-dir", str(state_dir)])

        assert store.all_keys()[0].state is KeyState.SKIPPED

    def test_a_non_steam_key_is_left_alone(self, state_dir):
        """Real libraries hold Desura, Uplay and console keys of the same shape.

        Returning one to the pending pool claims it is worth an activation it
        can never win.
        """
        store = self._store(
            state_dir,
            machine_name="farcry3",
            human_name="Far Cry 3",
            key_type="uplay",
            redeemed_key_val="TL3L-HKNL-CLRK-9VV6",
        )

        result = runner.invoke(app, ["recheck", "--state-dir", str(state_dir)])

        assert "Nothing to recheck" in result.output
        assert store.all_keys()[0].state is KeyState.SKIPPED

    def test_an_attempted_key_is_left_alone_by_default(self, state_dir):
        """Steam may have accepted it; a silent retry would spend a failure."""
        store = self._store(state_dir, state=KeyState.ATTEMPTED)

        result = runner.invoke(app, ["recheck", "--state-dir", str(state_dir)])

        assert "Nothing to recheck" in result.output
        assert store.all_keys()[0].state is KeyState.ATTEMPTED

    def test_an_attempted_key_comes_back_when_asked(self, state_dir):
        store = self._store(state_dir, state=KeyState.ATTEMPTED)

        runner.invoke(app, ["recheck", "--attempted", "--state-dir", str(state_dir)])

        assert store.all_keys()[0].state is KeyState.REVEALED
