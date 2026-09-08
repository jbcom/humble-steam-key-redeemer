"""Tests for ownership matching."""

from __future__ import annotations

import pytest

from humble_steam_key_redeemer.core import OwnershipMatcher

OWNED = {
    220: "Half-Life 2",
    400: "Portal",
    620: "Portal 2",
    292030: "The Witcher 3: Wild Hunt",
    413150: "Stardew Valley",
    367520: "Hollow Knight",
}


@pytest.fixture
def matcher() -> OwnershipMatcher:
    return OwnershipMatcher(OWNED)


class TestExactAndNearMatches:
    def test_exact_title(self, matcher):
        decision = matcher.match("Portal 2")
        assert decision.app_id == 620
        assert decision.confident

    def test_case_is_ignored(self, matcher):
        assert matcher.match("stardew valley").app_id == 413150

    def test_punctuation_is_ignored(self, matcher):
        assert matcher.match("The Witcher 3 Wild Hunt").app_id == 292030

    def test_prefers_the_closest_of_two_similar_titles(self, matcher):
        """ "Portal" must resolve to Portal, not Portal 2.

        token_set_ratio scores a subset as a perfect match, so ranking on it
        alone returns whichever similar title comes first. Choosing "Portal 2"
        here would skip a redeemable Portal key.
        """
        assert matcher.match("Portal").app_id == 400
        assert matcher.match("Portal 2").app_id == 620


class TestNonMatches:
    def test_unowned_title_does_not_match(self, matcher):
        decision = matcher.match("Celeste")
        assert not decision.matched
        assert decision.app_id is None

    def test_empty_title_does_not_match(self, matcher):
        assert not matcher.match("").matched

    def test_empty_library_does_not_match(self):
        assert not OwnershipMatcher({}).match("Portal 2").matched


class TestSteamAppId:
    def test_app_id_short_circuits_title_comparison(self, matcher):
        """Humble's app id is authoritative and beats any title similarity."""
        decision = matcher.match("Completely Unrelated Name", steam_app_id=620)
        assert decision.app_id == 620
        assert decision.score == 100
        assert decision.confident

    def test_unowned_app_id_falls_back_to_title(self, matcher):
        decision = matcher.match("Portal 2", steam_app_id=999999)
        assert decision.app_id == 620


class TestConfidence:
    def test_high_threshold_makes_partial_matches_unconfident(self):
        matcher = OwnershipMatcher(OWNED, threshold=50, confirm_threshold=99)
        decision = matcher.match("Half Life")
        assert decision.matched
        assert not decision.confident

    def test_candidates_are_returned_for_review(self, matcher):
        candidates = matcher.candidates("Portal")
        names = {candidate.app_name for candidate in candidates}
        assert {"Portal", "Portal 2"} <= names

    def test_candidates_empty_for_unowned(self, matcher):
        assert matcher.candidates("Celeste") == []
