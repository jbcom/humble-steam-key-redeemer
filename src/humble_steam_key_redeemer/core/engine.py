"""The redemption engine.

Decides which keys are worth an activation attempt and carries those attempts
out. The ordering is deliberate and is the whole point of the tool:

1. Skip anything already owned on Steam. Steam counts a duplicate as a
   *failure*, and failures are limited to roughly ten per hour against about
   fifty successes, so an unchecked run exhausts its budget on games the
   account already has.
2. Reveal on Humble only what is about to be redeemed, because revealing
   forfeits the ability to make a gift link and cannot be undone.
3. Stop at the first rate limit rather than retrying into a deeper cooldown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from humble_steam_key_redeemer.core.matching import MatchDecision, OwnershipMatcher
from humble_steam_key_redeemer.core.models import KeyRecord, KeyState, RedemptionAttempt

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from humble_steam_key_redeemer.core.store import RedeemerStore


RATE_LIMITED_CODE = 53
ALREADY_OWNED_CODES = frozenset({9, 15})


class SteamGateway(Protocol):
    """The Steam operations the engine depends on.

    Defined structurally so the engine can be exercised without a Steam
    account, and so the concrete connector stays swappable.
    """

    def list_owned_apps(self) -> dict[int, str]:
        """Return owned Steam applications by id."""
        ...

    def redeem_key(self, key: str) -> dict[str, object]:
        """Redeem one product key."""
        ...


@dataclass(slots=True)
class PlanEntry:
    """One key's disposition ahead of redemption.

    Attributes:
        record: The key under consideration.
        decision: Ownership match against the Steam library.
        skip_reason: Why the key will not be attempted, when applicable.
    """

    record: KeyRecord
    decision: MatchDecision
    skip_reason: str | None = None

    @property
    def will_attempt(self) -> bool:
        """Whether this key will be sent to Steam."""
        return self.skip_reason is None


@dataclass(slots=True)
class RedemptionPlan:
    """The set of decisions for a run.

    Attributes:
        entries: Every considered key, in input order.
    """

    entries: list[PlanEntry] = field(default_factory=list)

    @property
    def to_attempt(self) -> list[PlanEntry]:
        """Entries that will be attempted."""
        return [entry for entry in self.entries if entry.will_attempt]

    @property
    def skipped(self) -> list[PlanEntry]:
        """Entries that will be skipped."""
        return [entry for entry in self.entries if not entry.will_attempt]

    @property
    def uncertain(self) -> list[PlanEntry]:
        """Entries that matched an owned game without clearing confirmation.

        These are attempted rather than skipped, because a wrong skip wastes a
        redeemable key outright. They are surfaced so the reason for an
        "already owned" result is visible rather than surprising.
        """
        return [entry for entry in self.entries if entry.decision.matched and not entry.decision.confident]


@dataclass(slots=True)
class RunSummary:
    """Outcome counts for a completed run."""

    redeemed: int = 0
    already_owned: int = 0
    failed: int = 0
    skipped: int = 0
    rate_limited: bool = False


class RedemptionEngine:
    """Plans and performs Steam redemptions for Humble keys.

    Args:
        store: Local store of keys and attempts.
        steam: Steam gateway used for ownership and redemption.
    """

    def __init__(self, store: RedeemerStore, steam: SteamGateway) -> None:
        """Build an engine over a store and a Steam gateway."""
        self._store = store
        self._steam = steam

    def plan(
        self,
        records: Sequence[KeyRecord],
        *,
        match_threshold: int = 70,
        confirm_threshold: int = 95,
    ) -> RedemptionPlan:
        """Decide which keys are worth attempting.

        Args:
            records: Candidate keys.
            match_threshold: Score above which a title counts as owned.
            confirm_threshold: Score at or above which no review is needed.

        Returns:
            The resulting :class:`RedemptionPlan`.
        """
        owned = self._steam.list_owned_apps()
        matcher = OwnershipMatcher(
            owned,
            threshold=match_threshold,
            confirm_threshold=confirm_threshold,
        )

        plan = RedemptionPlan()
        seen: set[str] = set()

        for record in records:
            if not record.is_steam:
                plan.entries.append(
                    PlanEntry(record, MatchDecision(None, None, 0, confident=False), "not a Steam key")
                )
                continue

            # Two entries for the same game would burn a failure on the second.
            # Steam's app id is authoritative when Humble supplies it; two
            # differently-titled records for one app are still one game.
            identity = (
                f"appid:{record.steam_app_id}"
                if record.steam_app_id is not None
                else record.human_name.strip().casefold()
            )
            if identity in seen:
                plan.entries.append(
                    PlanEntry(record, MatchDecision(None, None, 0, confident=False), "duplicate in this run")
                )
                continue
            seen.add(identity)

            decision = matcher.match(record.human_name, steam_app_id=record.steam_app_id)
            # Only a confident match skips the key. A borderline one is
            # surfaced and still attempted: a wrong skip silently wastes a
            # redeemable key, while a wrong attempt costs one retryable
            # failure and reports precisely what happened.
            reason = "already owned on Steam" if decision.confident else None
            plan.entries.append(PlanEntry(record, decision, reason))

        return plan

    def redeem(
        self,
        plan: RedemptionPlan,
        *,
        reveal: Callable[[KeyRecord], str | None] | None = None,
        on_result: Callable[[KeyRecord, RedemptionAttempt], None] | None = None,
        limit: int = 0,
    ) -> RunSummary:
        """Attempt every key the plan selected.

        Args:
            plan: The plan to execute.
            reveal: Called to reveal a key that Humble has not released yet.
                When omitted, unrevealed keys are skipped.
            on_result: Called after each attempt, for progress reporting.
            limit: Maximum attempts; ``0`` means no limit.

        Returns:
            A :class:`RunSummary` of the run.
        """
        summary = RunSummary(skipped=len(plan.skipped))

        for entry in plan.to_attempt:
            if limit and (summary.redeemed + summary.already_owned + summary.failed) >= limit:
                break

            record = entry.record
            key_value = record.redeemed_key_val

            if not key_value:
                if reveal is None:
                    summary.skipped += 1
                    continue
                key_value = reveal(record)
                if not key_value:
                    summary.skipped += 1
                    continue
                record.redeemed_key_val = key_value
                record.state = KeyState.REVEALED
                self._store.update_key(record)

            # Mark the key in-flight before Steam sees it. If the process
            # dies mid-activation, the key is not silently offered up for a
            # second activation on the next run: it lands in ATTEMPTED and a
            # human decides, because Steam may well have accepted it.
            record.state = KeyState.ATTEMPTED
            self._store.update_key(record)

            outcome = self._steam.redeem_key(key_value)
            attempt = self._record(record, outcome)

            if on_result is not None:
                on_result(record, attempt)

            if attempt.result_code == RATE_LIMITED_CODE:
                summary.rate_limited = True
                break
            if attempt.succeeded:
                summary.redeemed += 1
            elif attempt.result_code in ALREADY_OWNED_CODES:
                summary.already_owned += 1
            else:
                summary.failed += 1

        return summary

    def _record(self, record: KeyRecord, outcome: dict[str, object]) -> RedemptionAttempt:
        """Persist one attempt and update the key's state."""
        result = outcome.get("result")
        code = int(getattr(result, "value", 0) or 0)
        succeeded = bool(outcome.get("success"))
        raw_items = outcome.get("items")
        items: list[str] = [str(item) for item in raw_items] if isinstance(raw_items, (list, tuple)) else []

        attempt = self._store.record_attempt(
            RedemptionAttempt(
                key_id=record.id or 0,
                result_code=code,
                result_name=str(getattr(result, "name", "UNKNOWN")),
                detail=str(outcome.get("detail", "")),
                succeeded=succeeded,
                granted_items=", ".join(items) if items else None,
            )
        )

        if succeeded:
            record.state = KeyState.REDEEMED
        elif code in ALREADY_OWNED_CODES:
            record.state = KeyState.ALREADY_OWNED
        elif code == RATE_LIMITED_CODE:
            # Never reached Steam's verdict, so the key is still eligible.
            record.state = KeyState.REVEALED if record.redeemed_key_val else KeyState.UNREVEALED
        else:
            record.state = KeyState.FAILED
        self._store.update_key(record)

        return attempt


__all__ = [
    "ALREADY_OWNED_CODES",
    "RATE_LIMITED_CODE",
    "PlanEntry",
    "RedemptionEngine",
    "RedemptionPlan",
    "RunSummary",
    "SteamGateway",
]
