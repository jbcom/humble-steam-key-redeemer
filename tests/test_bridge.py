"""Tests for the Chrome native messaging bridge."""

from __future__ import annotations

import io
import json
import struct

import pytest

from humble_steam_key_redeemer.bridge import (
    NATIVE_HOST_NAME,
    BridgeError,
    handle_message,
    install_manifest,
    read_message,
    run_host,
    write_message,
)
from humble_steam_key_redeemer.core import KeyRecord, KeyState, RedeemerStore
from humble_steam_key_redeemer.settings import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
    settings = Settings(state_dir=tmp_path / "state")
    settings.ensure_state_dir()
    return settings


def _framed(message: dict) -> bytes:
    """Encode a message the way Chrome frames one."""
    payload = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def _seed(settings: Settings, *records: KeyRecord) -> RedeemerStore:
    store = RedeemerStore(settings.database_path)
    store.upsert_keys(records)
    return store


def _key(name: str, index: int, **overrides) -> KeyRecord:
    values = {
        "gamekey": "order1",
        "machine_name": f"machine{index}",
        "human_name": name,
        "key_type": "steam",
        "redeemed_key_val": f"AAAA{index}-BBBBB-CCCCC",
        "state": KeyState.REVEALED,
    }
    values.update(overrides)
    return KeyRecord(**values)


class TestFraming:
    """Chrome frames each message with a little-endian length prefix."""

    def test_round_trip(self):
        out = io.BytesIO()
        write_message(out, {"ok": True})
        assert read_message(io.BytesIO(out.getvalue())) == {"ok": True}

    def test_closed_stream_returns_none(self):
        assert read_message(io.BytesIO(b"")) is None

    def test_truncated_payload_is_rejected(self):
        with pytest.raises(BridgeError, match="ended early"):
            read_message(io.BytesIO(struct.pack("<I", 100) + b"short"))

    def test_oversized_message_is_rejected(self):
        """A bogus length must not drive a huge allocation."""
        with pytest.raises(BridgeError, match="exceeds the maximum"):
            read_message(io.BytesIO(struct.pack("<I", 2**31)))

    def test_non_json_payload_is_rejected(self):
        payload = b"not json"
        with pytest.raises(BridgeError, match="not valid JSON"):
            read_message(io.BytesIO(struct.pack("<I", len(payload)) + payload))

    def test_non_object_payload_is_rejected(self):
        payload = json.dumps([1, 2]).encode()
        with pytest.raises(BridgeError, match="JSON object"):
            read_message(io.BytesIO(struct.pack("<I", len(payload)) + payload))


class TestDispatch:
    def test_unknown_command_is_reported(self, settings):
        reply = handle_message({"command": "nope"}, settings)
        assert reply["ok"] is False
        assert "nope" in reply["error"]

    def test_status_reports_the_database(self, settings):
        _seed(settings, _key("Portal 2", 1, steam_app_id=620))
        reply = handle_message({"command": "status"}, settings)
        assert reply == {
            "ok": True,
            "keys": 1,
            "steam_keys": 1,
            "pending": 1,
            "database": str(settings.database_path),
        }

    def test_an_exception_becomes_a_reply(self, settings):
        """The extension needs an answer, not a traceback down the pipe."""
        reply = handle_message({"command": "sync", "orders": "not-a-list"}, settings)
        assert reply["ok"] is False


SYNC_ORDER = {
    "gamekey": "order1",
    "tpkd_dict": {
        "all_tpks": [
            {
                "machine_name": "portal2",
                "human_name": "Portal 2",
                "key_type": "steam",
                "steam_app_id": 620,
                "redeemed_key_val": "AAAAA-BBBBB-CCCCC",
            }
        ]
    },
}


class TestSync:
    def test_orders_are_imported(self, settings):
        reply = handle_message({"command": "sync", "orders": [SYNC_ORDER]}, settings)
        assert reply["ok"] is True
        assert reply["keys"] == 1
        assert reply["steam_keys"] == 1
        assert reply["revealed"] == 1

    def test_missing_orders_are_reported(self, settings):
        reply = handle_message({"command": "sync"}, settings)
        assert reply["ok"] is False
        assert "orders" in reply["error"]


class TestPlan:
    def test_owned_games_are_not_attempted(self, settings):
        """The browser reads ownership; the decision is still made here."""
        _seed(settings, _key("Portal 2", 1, steam_app_id=620))

        reply = handle_message({"command": "plan", "owned": {"620": "Portal 2"}}, settings)

        assert reply["ok"] is True
        assert reply["attempts"] == []
        assert reply["skipped"] == 1

    def test_unowned_games_are_attempted(self, settings):
        _seed(settings, _key("Celeste", 1))

        reply = handle_message({"command": "plan", "owned": {}}, settings)

        assert [attempt["title"] for attempt in reply["attempts"]] == ["Celeste"]
        assert reply["attempts"][0]["key"] == "AAAA1-BBBBB-CCCCC"

    def test_unrevealed_keys_need_an_explicit_reveal(self, settings):
        """Revealing forfeits the gift link, so it is never implicit."""
        _seed(settings, _key("Celeste", 1, redeemed_key_val=None, state=KeyState.UNREVEALED))

        without = handle_message({"command": "plan", "owned": {}}, settings)
        assert without["attempts"] == []

        with_reveal = handle_message({"command": "plan", "owned": {}, "reveal": True}, settings)
        assert len(with_reveal["attempts"]) == 1
        assert with_reveal["attempts"][0]["reveal"]["machineName"] == "machine1"

    def test_the_configured_cap_is_applied(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
        settings = Settings(state_dir=tmp_path / "state", max_redemptions_per_run=2)
        settings.ensure_state_dir()
        _seed(settings, _key("A", 1), _key("B", 2), _key("C", 3))

        reply = handle_message({"command": "plan", "owned": {}}, settings)

        assert len(reply["attempts"]) == 2

    def test_missing_ownership_is_reported(self, settings):
        reply = handle_message({"command": "plan"}, settings)
        assert reply["ok"] is False
        assert "owned" in reply["error"]


class TestRecord:
    def _stored_key(self, settings):
        store = _seed(settings, _key("Celeste", 1))
        return store, store.all_keys()[0]

    def test_a_success_is_recorded(self, settings):
        store, key = self._stored_key(settings)

        reply = handle_message(
            {"command": "record", "result": {"id": key.id, "result": {"success": 1}}},
            settings,
        )

        assert reply["state"] == KeyState.REDEEMED.value
        assert store.all_keys()[0].state is KeyState.REDEEMED

    def test_already_owned_is_classified(self, settings):
        store, key = self._stored_key(settings)

        handle_message(
            {
                "command": "record",
                "result": {"id": key.id, "result": {"success": 0, "purchase_result_details": 9}},
            },
            settings,
        )

        assert store.all_keys()[0].state is KeyState.ALREADY_OWNED

    def test_a_rate_limit_leaves_the_key_eligible(self, settings):
        """A rate limit is not a verdict, so the key must stay retryable."""
        store, key = self._stored_key(settings)

        handle_message(
            {
                "command": "record",
                "result": {"id": key.id, "result": {"success": 0, "purchase_result_details": 53}},
            },
            settings,
        )

        assert store.all_keys()[0].state is KeyState.REVEALED
        assert len(store.pending_keys()) == 1

    def test_an_unknown_key_is_reported(self, settings):
        self._stored_key(settings)
        reply = handle_message(
            {"command": "record", "result": {"id": 9999, "result": {"success": 1}}}, settings
        )
        assert reply["ok"] is False


class TestFinish:
    def test_counts_are_summarized(self, settings):
        _seed(settings, _key("A", 1))

        reply = handle_message(
            {
                "command": "finish",
                "results": [
                    {"id": 1, "result": {"success": 1}},
                    {"id": 2, "result": {"success": 0, "purchase_result_details": 53}},
                ],
            },
            settings,
        )

        assert reply["attempted"] == 2
        assert reply["redeemed"] == 1
        assert reply["rate_limited"] is True


class TestHostLoop:
    def test_messages_are_served_until_the_stream_closes(self, settings, monkeypatch):
        monkeypatch.setenv("HSKR_STATE_DIR", str(settings.state_dir))
        stdin = io.BytesIO(_framed({"command": "status"}))
        stdout = io.BytesIO()

        run_host(stdin, stdout)

        reply = read_message(io.BytesIO(stdout.getvalue()))
        assert reply["ok"] is True

    def test_a_malformed_frame_ends_the_loop_with_an_error(self, settings):
        stdin = io.BytesIO(struct.pack("<I", 2**31))
        stdout = io.BytesIO()

        run_host(stdin, stdout)

        reply = read_message(io.BytesIO(stdout.getvalue()))
        assert reply["ok"] is False


class TestManifest:
    def test_the_manifest_names_the_extension(self, tmp_path, monkeypatch):
        """Chrome only starts a host that names the calling extension."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        path = install_manifest("abcdefghijklmnopabcdefghijklmnop")

        manifest = json.loads(path.read_text())
        assert manifest["name"] == NATIVE_HOST_NAME
        assert manifest["type"] == "stdio"
        assert manifest["allowed_origins"] == ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"]

    def test_the_launcher_is_executable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        path = install_manifest("abcdefghijklmnopabcdefghijklmnop")

        launcher = tmp_path / json.loads(path.read_text())["path"].split(str(tmp_path))[-1].lstrip("/")
        assert launcher.stat().st_mode & 0o111


class TestPlanGuards:
    """The browser path must not be the lenient one."""

    def test_a_gift_link_never_reaches_the_browser(self, settings):
        """Sending one spends one of about ten failed activations an hour."""
        store = _seed(
            settings,
            _key("Celeste", 1, redeemed_key_val="https://www.humblebundle.com/gift?key=abc"),
        )

        reply = handle_message({"command": "plan", "owned": {}}, settings)

        assert reply["attempts"] == []
        assert store.all_keys()[0].state is KeyState.SKIPPED

    def test_unrevealed_keys_are_counted_as_skipped(self, settings):
        """Zero attempts and zero skipped would hide why nothing happened."""
        _seed(settings, _key("Celeste", 1, redeemed_key_val=None, state=KeyState.UNREVEALED))

        reply = handle_message({"command": "plan", "owned": {}}, settings)

        assert reply["attempts"] == []
        assert reply["skipped"] == 1
        assert reply["unrevealed"] == 1


class TestInFlight:
    def test_a_key_is_marked_before_steam_sees_it(self, settings):
        """A crash mid-activation must not offer the key up again."""
        store = _seed(settings, _key("Celeste", 1))
        key = store.all_keys()[0]

        reply = handle_message({"command": "attempting", "id": key.id}, settings)

        assert reply["state"] == KeyState.ATTEMPTED.value
        assert store.all_keys()[0].state is KeyState.ATTEMPTED
        # Terminal, so a rerun surfaces it rather than silently retrying.
        assert store.pending_keys() == []

    def test_a_key_that_never_reached_steam_stays_eligible(self, settings):
        """Nothing was spent, so it is still worth attempting."""
        store = _seed(settings, _key("Celeste", 1))
        key = store.all_keys()[0]
        handle_message({"command": "attempting", "id": key.id}, settings)

        reply = handle_message(
            {
                "command": "finish",
                "results": [],
                "failures": [{"id": key.id, "detail": "no sessionid cookie"}],
            },
            settings,
        )

        assert reply["attempted"] == 0
        assert reply["failed_before_steam"] == 1
        assert store.all_keys()[0].state is KeyState.REVEALED
        assert len(store.pending_keys()) == 1
