"""Match Humble titles against an owned Steam library.

Humble and Steam rarely spell a title identically — "Game GOTY" against
"Game: Game of the Year Edition", trademark symbols, differing punctuation —
so ownership is decided by fuzzy comparison rather than equality.

Getting this wrong is expensive in both directions. A missed match spends one
of Steam's ten hourly *failed* activations on a game the account already owns;
a false match silently skips a key that could have been redeemed.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process, utils


@dataclass(frozen=True, slots=True)
class MatchDecision:
    """The outcome of comparing one title against the owned library.

    Attributes:
        app_id: Steam application id of the best candidate, if any.
        app_name: Name of that application.
        score: Similarity score from 0 to 100.
        confident: Whether the score clears the confirmation threshold.
    """

    app_id: int | None
    app_name: str | None
    score: int
    confident: bool

    @property
    def matched(self) -> bool:
        """Whether any candidate cleared the match threshold."""
        return self.app_id is not None


class OwnershipMatcher:
    """Decides whether a Humble title is already owned on Steam.

    Args:
        owned: Mapping of Steam app id to application name.
        threshold: Score above which a title counts as a candidate match.
        confirm_threshold: Score at or above which a match needs no review.
    """

    def __init__(
        self,
        owned: dict[int, str],
        *,
        threshold: int = 70,
        confirm_threshold: int = 95,
    ) -> None:
        """Build a matcher over an owned library."""
        self._owned = dict(owned)
        self._threshold = threshold
        self._confirm_threshold = confirm_threshold
        # rapidfuzz matches against a parallel list, so keep ids aligned.
        self._app_ids = list(self._owned)
        self._names = [self._owned[app_id] for app_id in self._app_ids]

    def match(self, title: str, *, steam_app_id: int | None = None) -> MatchDecision:
        """Find the best owned application matching ``title``.

        A Steam app id reported by Humble is authoritative and short-circuits
        the fuzzy comparison entirely.

        Args:
            title: Humble display title.
            steam_app_id: Steam app id from Humble, when present.

        Returns:
            The best :class:`MatchDecision`; unmatched when nothing clears
            the threshold.
        """
        if steam_app_id is not None and steam_app_id in self._owned:
            return MatchDecision(
                app_id=steam_app_id,
                app_name=self._owned[steam_app_id],
                score=100,
                confident=True,
            )

        if not title or not self._names:
            return MatchDecision(None, None, 0, confident=False)

        # `default_process` lowercases and strips punctuation, so casing and
        # trademark noise do not depress the score.
        #
        # token_set_ratio treats a subset as perfect — "Portal" scores 100
        # against "Portal 2" — so it is used only to gather candidates. The
        # winner is then chosen by token_sort_ratio, which penalizes the extra
        # words and so prefers "Portal" itself when the account owns both.
        candidates = process.extract(
            title,
            self._names,
            scorer=fuzz.token_set_ratio,
            processor=utils.default_process,
            score_cutoff=self._threshold,
            limit=None,
        )
        if not candidates:
            return MatchDecision(None, None, 0, confident=False)

        name, _score, index = max(
            candidates,
            key=lambda item: (
                fuzz.token_sort_ratio(title, item[0], processor=utils.default_process),
                item[1],
            ),
        )
        refined = int(fuzz.token_sort_ratio(title, name, processor=utils.default_process))
        if refined < self._threshold:
            # The candidate only cleared the subset-tolerant score. Reporting a
            # match here would skip the key as owned on the strength of a score
            # the caller already deemed too low.
            return MatchDecision(None, None, refined, confident=False)

        return MatchDecision(
            app_id=self._app_ids[index],
            app_name=name,
            score=refined,
            confident=refined >= self._confirm_threshold,
        )

    def candidates(self, title: str, *, limit: int = 5) -> list[MatchDecision]:
        """Return the closest owned applications for manual review.

        Args:
            title: Humble display title.
            limit: Maximum number of candidates.

        Returns:
            Candidate matches, best first.
        """
        if not title or not self._names:
            return []

        results = process.extract(
            title,
            self._names,
            scorer=fuzz.token_set_ratio,
            processor=utils.default_process,
            score_cutoff=self._threshold,
            limit=limit,
        )
        return [
            MatchDecision(
                app_id=self._app_ids[index],
                app_name=name,
                score=int(score),
                confident=int(score) >= self._confirm_threshold,
            )
            for name, score, index in results
        ]


__all__ = ["MatchDecision", "OwnershipMatcher"]
