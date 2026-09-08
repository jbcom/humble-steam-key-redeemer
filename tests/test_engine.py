"""Tests for the redemption engine."""

from __future__ import annotations

from enum import IntEnum

import pytest

from humble_steam_key_redeemer.core import (
    KeyRecord,
    KeyState,
    RedeemerStore,
    RedemptionEngine,
)


class Result(IntEnum):
    """Stand-in for the connector's redemption codes."""

    OK = 1
    ALREADY_OWNED = 9
    DUPLICATE = 15
    BAD_CODE = 14
    RATE_LIMITED = 53


class FakeSteam:
    """Scripted Steam gateway."""

    def __init__(self, owned: dict[int, str] | None = None, results: list[Result] | None = None) -> None:
        self.owned = owned or {}
        self.results = list(results or [])
        self.redeemed: list[str] = []

    def list_owned_apps(self) -> dict[int, str]:
        return self.owned

    def redeem_key(self, key: str) -> dict[str, object]:
        self.redeemed.append(key)
        result = self.results.pop(0) if self.results else Result.OK
        return {
            "success": result is Result.OK,
            "result": result,
            "detail": result.name,
            "items": ["A Game"] if result is Result.OK else [],
        }


@pytest.fixture
def store(tmp_path) -> RedeemerStore:
    return RedeemerStore(tmp_path / "engine.db")


def _seed(store: RedeemerStore, *records: KeyRecord) -> list[KeyRecord]:
    store.upsert_keys(records)
    return list(store.all_keys())


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


class TestPlanning:
    def test_owned_games_are_skipped(self, store):
        """Redeeming an owned game costs a failure, not just a wasted call."""
        records = _seed(store, _key("Portal 2", 1, steam_app_id=620))
        engine = RedemptionEngine(store, FakeSteam(owned={620: "Portal 2"}))

        plan = engine.plan(records)

        assert plan.to_attempt == []
        assert plan.skipped[0].skip_reason == "already owned on Steam"

    def test_unowned_games_are_attempted(self, store):
        records = _seed(store, _key("Celeste", 1))
        engine = RedemptionEngine(store, FakeSteam(owned={620: "Portal 2"}))

        assert len(engine.plan(records).to_attempt) == 1

    def test_duplicates_within_a_run_are_collapsed(self, store):
        records = _seed(store, _key("Celeste", 1), _key("Celeste", 2))
        engine = RedemptionEngine(store, FakeSteam())

        plan = engine.plan(records)

        assert len(plan.to_attempt) == 1
        assert plan.skipped[0].skip_reason == "duplicate in this run"

    def test_non_steam_keys_are_skipped(self, store):
        records = _seed(store, _key("GOG Game", 1, key_type="gog"))
        engine = RedemptionEngine(store, FakeSteam())

        assert engine.plan(records).skipped[0].skip_reason == "not a Steam key"

    def test_uncertain_matches_are_surfaced(self, store):
        """A wrong skip silently wastes a key, so borderline ones are listed."""
        records = _seed(store, _key("Half Life", 1))
        engine = RedemptionEngine(store, FakeSteam(owned={220: "Half-Life 2"}))

        plan = engine.plan(records, match_threshold=50, confirm_threshold=99)

        assert len(plan.uncertain) == 1


class TestRedemption:
    def test_successful_redemption_is_recorded(self, store):
        records = _seed(store, _key("Celeste", 1))
        steam = FakeSteam(results=[Result.OK])
        engine = RedemptionEngine(store, steam)

        summary = engine.redeem(engine.plan(records))

        assert summary.redeemed == 1
        assert store.all_keys()[0].state is KeyState.REDEEMED

    def test_already_owned_is_counted_separately(self, store):
        records = _seed(store, _key("Celeste", 1))
        engine = RedemptionEngine(store, FakeSteam(results=[Result.ALREADY_OWNED]))

        summary = engine.redeem(engine.plan(records))

        assert summary.already_owned == 1
        assert store.all_keys()[0].state is KeyState.ALREADY_OWNED

    def test_run_stops_at_a_rate_limit(self, store):
        """Continuing past a rate limit only extends the cooldown."""
        records = _seed(store, _key("A", 1), _key("B", 2), _key("C", 3))
        steam = FakeSteam(results=[Result.OK, Result.RATE_LIMITED, Result.OK])
        engine = RedemptionEngine(store, steam)

        summary = engine.redeem(engine.plan(records))

        assert len(steam.redeemed) == 2
        assert summary.rate_limited
        assert summary.redeemed == 1

    def test_rate_limited_key_is_not_marked_failed(self, store):
        records = _seed(store, _key("A", 1))
        engine = RedemptionEngine(store, FakeSteam(results=[Result.RATE_LIMITED]))

        engine.redeem(engine.plan(records))

        assert store.all_keys()[0].state is KeyState.REVEALED

    def test_limit_caps_attempts(self, store):
        records = _seed(store, _key("A", 1), _key("B", 2), _key("C", 3))
        steam = FakeSteam(results=[Result.OK, Result.OK, Result.OK])
        engine = RedemptionEngine(store, steam)

        engine.redeem(engine.plan(records), limit=2)

        assert len(steam.redeemed) == 2

    def test_unrevealed_keys_are_skipped_without_a_reveal_callback(self, store):
        records = _seed(store, _key("A", 1, redeemed_key_val=None, state=KeyState.UNREVEALED))
        steam = FakeSteam()
        engine = RedemptionEngine(store, steam)

        summary = engine.redeem(engine.plan(records))

        assert steam.redeemed == []
        assert summary.skipped == 1

    def test_reveal_callback_supplies_the_key(self, store):
        records = _seed(store, _key("A", 1, redeemed_key_val=None, state=KeyState.UNREVEALED))
        steam = FakeSteam(results=[Result.OK])
        engine = RedemptionEngine(store, steam)

        summary = engine.redeem(engine.plan(records), reveal=lambda _record: "ZZZZZ-YYYYY-XXXXX")

        assert steam.redeemed == ["ZZZZZ-YYYYY-XXXXX"]
        assert summary.redeemed == 1

    def test_progress_callback_receives_each_result(self, store):
        records = _seed(store, _key("A", 1), _key("B", 2))
        engine = RedemptionEngine(store, FakeSteam(results=[Result.OK, Result.BAD_CODE]))

        seen: list[str] = []
        engine.redeem(engine.plan(records), on_result=lambda record, _attempt: seen.append(record.human_name))

        assert seen == ["A", "B"]


class TestPlanIdentityAndConfidence:
    """Regressions for duplicate identity and threshold gating."""

    def test_same_app_id_under_different_titles_is_one_entry(self, store):
        """Two names for one app would otherwise cost a second activation."""
        records = _seed(
            store,
            _key("Game of the Year Edition", 1, steam_app_id=620),
            _key("Game GOTY", 2, steam_app_id=620),
        )
        engine = RedemptionEngine(store, FakeSteam())

        plan = engine.plan(records)

        assert len(plan.to_attempt) == 1
        assert plan.skipped[0].skip_reason == "duplicate in this run"

    def test_borderline_match_is_attempted_not_skipped(self, store):
        """A wrong skip wastes the key; a wrong attempt costs one failure."""
        records = _seed(store, _key("Half Life", 1))
        engine = RedemptionEngine(store, FakeSteam(owned={220: "Half-Life 2"}))

        plan = engine.plan(records, match_threshold=50, confirm_threshold=99)

        assert len(plan.to_attempt) == 1
        assert len(plan.uncertain) == 1

    def test_confident_match_is_still_skipped(self, store):
        records = _seed(store, _key("Portal 2", 1, steam_app_id=620))
        engine = RedemptionEngine(store, FakeSteam(owned={620: "Portal 2"}))

        plan = engine.plan(records)

        assert plan.to_attempt == []
        assert plan.skipped[0].skip_reason == "already owned on Steam"


class TestInterruptedActivation:
    """A crash between contacting Steam and recording the verdict."""

    def test_a_key_is_marked_in_flight_before_steam_sees_it(self, store):
        records = _seed(store, _key("A", 1))
        observed: list[KeyState] = []

        class CrashingSteam(FakeSteam):
            def redeem_key(self, key: str) -> dict[str, object]:
                observed.append(store.all_keys()[0].state)
                raise RuntimeError("process died mid-activation")

        engine = RedemptionEngine(store, CrashingSteam())
        with pytest.raises(RuntimeError):
            engine.redeem(engine.plan(records))

        assert observed == [KeyState.ATTEMPTED]

    def test_an_interrupted_key_is_not_silently_retried(self, store):
        """Steam may have accepted it, so a retry could spend a failure."""
        _seed(store, _key("A", 1, state=KeyState.ATTEMPTED))
        assert store.pending_keys() == []


class TestNonKeyValues:
    """Gift links share a field with real keys."""

    def test_a_gift_link_is_never_sent_to_steam(self, store):
        """Steam counts a malformed code as one of ten hourly failures."""
        records = _seed(
            store,
            _key("Gift Link Game", 1, redeemed_key_val="https://humblebundle.com/gift?key=abc"),
        )
        steam = FakeSteam()
        engine = RedemptionEngine(store, steam)

        summary = engine.redeem(engine.plan(records))

        assert steam.redeemed == []
        assert summary.skipped == 1
        assert store.all_keys()[0].state is KeyState.SKIPPED

    def test_a_well_formed_key_still_goes_through(self, store):
        records = _seed(store, _key("Real Game", 1, redeemed_key_val="AAAAA-BBBBB-CCCCC"))
        steam = FakeSteam(results=[Result.OK])
        engine = RedemptionEngine(store, steam)

        engine.redeem(engine.plan(records))

        assert steam.redeemed == ["AAAAA-BBBBB-CCCCC"]
