"""Tests for parsing Humble order payloads."""

from __future__ import annotations

from humble_steam_key_redeemer.core import KeyState
from humble_steam_key_redeemer.humble import iter_tpkds, to_key_records

ORDER = {
    "gamekey": "order1",
    "product": {"human_name": "Some Bundle"},
    "tpkd_dict": {
        "all_tpks": [
            {
                "machine_name": "portal2_steam",
                "human_name": "Portal 2",
                "key_type": "steam",
                "steam_app_id": 620,
                "redeemed_key_val": "AAAAA-BBBBB-CCCCC",
                "keyindex": 0,
            },
            {
                "machine_name": "witcher_gog",
                "human_name": "The Witcher 3",
                "key_type": "gog",
                "keyindex": 1,
            },
        ]
    },
}


class TestIterTpkds:
    def test_finds_nested_entries(self):
        """Humble nests key entries differently across bundle generations."""
        assert len(iter_tpkds(ORDER)) == 2

    def test_ignores_payloads_without_entries(self):
        assert iter_tpkds({"gamekey": "x", "product": {"category": "bundle"}}) == []

    def test_handles_deeply_nested_lists(self):
        payload = {"a": [{"b": [{"machine_name": "m", "human_name": "H"}]}]}
        assert len(iter_tpkds(payload)) == 1


class TestToKeyRecords:
    def test_converts_entries(self):
        records = to_key_records([ORDER])
        assert len(records) == 2

    def test_identifies_steam_keys(self):
        records = {record.machine_name: record for record in to_key_records([ORDER])}
        assert records["portal2_steam"].is_steam
        assert not records["witcher_gog"].is_steam

    def test_marks_revealed_state(self):
        records = {record.machine_name: record for record in to_key_records([ORDER])}
        assert records["portal2_steam"].state is KeyState.REVEALED
        assert records["witcher_gog"].state is KeyState.UNREVEALED

    def test_captures_key_index_for_reveal(self):
        """Revealing a key from a multi-key entry requires its index."""
        records = {record.machine_name: record for record in to_key_records([ORDER])}
        assert records["witcher_gog"].key_index == 1

    def test_deduplicates_across_orders(self):
        records = to_key_records([ORDER, ORDER])
        assert len(records) == 2

    def test_multi_key_entries_take_the_first_value(self):
        """Some entries report a list of keys rather than a single string."""
        payload = {
            "gamekey": "order2",
            "tpkd_dict": {
                "all_tpks": [
                    {
                        "machine_name": "multi",
                        "human_name": "Multi Key Game",
                        "key_type": "steam",
                        "redeemed_key_val": ["AAAAA-BBBBB-CCCCC", "DDDDD-EEEEE-FFFFF"],
                    }
                ]
            },
        }
        record = to_key_records([payload])[0]
        assert record.redeemed_key_val == "AAAAA-BBBBB-CCCCC"

    def test_non_string_key_values_are_discarded(self):
        payload = {
            "gamekey": "order3",
            "tpkd_dict": {
                "all_tpks": [
                    {
                        "machine_name": "odd",
                        "human_name": "Odd Game",
                        "key_type": "steam",
                        "redeemed_key_val": {"unexpected": "shape"},
                    }
                ]
            },
        }
        record = to_key_records([payload])[0]
        assert record.redeemed_key_val is None
        assert record.state is KeyState.UNREVEALED

    def test_entries_without_a_machine_name_are_ignored(self):
        payload = {"gamekey": "x", "tpkd_dict": {"all_tpks": [{"human_name": "No machine name"}]}}
        assert to_key_records([payload]) == []


MULTI_KEY_ORDER = {
    "gamekey": "order9",
    "tpkd_dict": {
        "all_tpks": [
            {
                "machine_name": "multi",
                "human_name": "Multi Key Game",
                "key_type": "steam",
                "redeemed_key_val": ["AAAAA-BBBBB-CCCCC", "DDDDD-EEEEE-FFFFF"],
            }
        ]
    },
}


class TestMultiKeyEntries:
    """Each code in a multi-key entry is a separately redeemable product."""

    def test_every_code_is_kept(self):
        """Dropping the extras would silently lose redeemable keys."""
        records = to_key_records([MULTI_KEY_ORDER])
        assert sorted(r.redeemed_key_val for r in records) == [
            "AAAAA-BBBBB-CCCCC",
            "DDDDD-EEEEE-FFFFF",
        ]

    def test_each_code_gets_a_distinct_identity(self):
        records = to_key_records([MULTI_KEY_ORDER])
        assert len({r.machine_name for r in records}) == 2

    def test_reimport_does_not_duplicate(self):
        assert len(to_key_records([MULTI_KEY_ORDER, MULTI_KEY_ORDER])) == 2
