"""Core domain logic: data models, ownership matching, and local storage.

This layer is deliberately free of both Humble and Steam specifics so it can
be tested without a browser or a network connection.
"""

from __future__ import annotations

from humble_steam_key_redeemer.core.engine import (
    PlanEntry,
    RedemptionEngine,
    RedemptionPlan,
    RunSummary,
    SteamGateway,
)
from humble_steam_key_redeemer.core.matching import MatchDecision, OwnershipMatcher
from humble_steam_key_redeemer.core.models import KeyRecord, KeyState, RedemptionAttempt
from humble_steam_key_redeemer.core.store import RedeemerStore, csv_safe

__all__ = [
    "KeyRecord",
    "KeyState",
    "MatchDecision",
    "OwnershipMatcher",
    "PlanEntry",
    "RedeemerStore",
    "RedemptionAttempt",
    "RedemptionEngine",
    "RedemptionPlan",
    "RunSummary",
    "SteamGateway",
    "csv_safe",
]
