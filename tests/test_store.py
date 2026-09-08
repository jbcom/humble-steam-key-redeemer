"""Tests for the local store, including CSV export safety."""

from __future__ import annotations

import csv
import os

import pytest

from humble_steam_key_redeemer.core import KeyRecord, KeyState, RedeemerStore, RedemptionAttempt
from humble_steam_key_redeemer.core.store import csv_safe


@pytest.fixture
def store(tmp_path) -> RedeemerStore:
    return RedeemerStore(tmp_path / "test.db")


def _key(**overrides) -> KeyRecord:
    values = {
        "gamekey": "order1",
        "machine_name": "portal2_steam",
        "human_name": "Portal 2",
        "key_type": "steam",
        "steam_app_id": 620,
    }
    values.update(overrides)
    return KeyRecord(**values)


class TestPersistence:
    def test_database_is_owner_only(self, store):
        """Session and key data must not be world-readable."""
        assert store.path.stat().st_mode & 0o777 == 0o600

    def test_keys_round_trip(self, store):
        store.upsert_keys([_key()])
        stored = store.all_keys()
        assert len(stored) == 1
        assert stored[0].human_name == "Portal 2"

    def test_reimport_updates_rather_than_duplicates(self, store):
        """Humble's (gamekey, machine_name) pair identifies an entry."""
        store.upsert_keys([_key()])
        store.upsert_keys([_key(human_name="Portal 2 - Updated")])
        stored = store.all_keys()
        assert len(stored) == 1
        assert stored[0].human_name == "Portal 2 - Updated"

    def test_reimport_preserves_a_revealed_key(self, store):
        store.upsert_keys([_key(redeemed_key_val="AAAAA-BBBBB-CCCCC")])
        store.upsert_keys([_key()])
        assert store.all_keys()[0].redeemed_key_val == "AAAAA-BBBBB-CCCCC"

    def test_revealing_advances_state(self, store):
        store.upsert_keys([_key()])
        assert store.all_keys()[0].state is KeyState.UNREVEALED
        store.upsert_keys([_key(redeemed_key_val="AAAAA-BBBBB-CCCCC")])
        assert store.all_keys()[0].state is KeyState.REVEALED


class TestPendingSelection:
    def test_non_steam_keys_are_excluded(self, store):
        store.upsert_keys([_key(machine_name="gog_game", key_type="gog", steam_app_id=None)])
        assert store.pending_keys() == []

    def test_terminal_states_are_excluded(self, store):
        store.upsert_keys([_key(state=KeyState.REDEEMED)])
        assert store.pending_keys() == []

    def test_settled_failure_is_not_retried(self, store):
        """Retrying a known-bad key spends Steam's scarce failure budget."""
        store.upsert_keys([_key()])
        key = store.all_keys()[0]
        store.record_attempt(
            RedemptionAttempt(
                key_id=key.id, result_code=15, result_name="DUPLICATE", detail="", succeeded=False
            )
        )
        assert store.pending_keys() == []

    def test_rate_limited_attempt_stays_eligible(self, store):
        """A rate limit is not a verdict on the key, so it must be retried."""
        store.upsert_keys([_key()])
        key = store.all_keys()[0]
        store.record_attempt(
            RedemptionAttempt(
                key_id=key.id, result_code=53, result_name="RATE_LIMITED", detail="", succeeded=False
            )
        )
        assert len(store.pending_keys()) == 1

    def test_attempts_are_retrievable(self, store):
        store.upsert_keys([_key()])
        key = store.all_keys()[0]
        store.record_attempt(
            RedemptionAttempt(key_id=key.id, result_code=1, result_name="OK", detail="", succeeded=True)
        )
        assert len(store.attempts_for(key.id)) == 1


class TestCsvSafety:
    @pytest.mark.parametrize("payload", ["=cmd|'/c calc'!A1", "+1+1", "-2+3", "@SUM(A1)", "\tx", "\rx"])
    def test_formula_leaders_are_neutralized(self, payload):
        """A title from Humble must never execute when opened in a spreadsheet."""
        assert csv_safe(payload).startswith("'")

    @pytest.mark.parametrize("benign", ["Portal 2", "Half-Life 2", "", "Tom Clancy's Game"])
    def test_ordinary_titles_are_untouched(self, benign):
        assert csv_safe(benign) == benign

    def test_none_becomes_empty(self):
        assert csv_safe(None) == ""

    def test_export_quotes_commas_quotes_and_newlines(self, store, tmp_path):
        """These characters previously corrupted the exported file."""
        nasty = 'Weird, "Quoted"\nTitle'
        store.upsert_keys([_key(human_name=nasty)])

        destination = store.export_csv(tmp_path / "out.csv")
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))

        assert rows[0][0] == "human_name"
        assert rows[1][0] == nasty

    def test_export_can_filter_to_steam(self, store, tmp_path):
        store.upsert_keys([_key(), _key(machine_name="gog", key_type="gog", steam_app_id=None)])
        destination = store.export_csv(tmp_path / "steam.csv", steam_only=True)
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == 2  # header plus the single Steam key


class TestExportPermissions:
    def test_the_export_is_owner_only(self, store, tmp_path):
        """An export can contain revealed, unredeemed keys."""
        store.upsert_keys([_key(redeemed_key_val="AAAAA-BBBBB-CCCCC")])
        old = os.umask(0)
        try:
            destination = store.export_csv(tmp_path / "keys.csv")
        finally:
            os.umask(old)

        assert destination.stat().st_mode & 0o077 == 0
