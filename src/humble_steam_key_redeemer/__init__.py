"""Redeem Humble Bundle keys on Steam, skipping games you already own.

The package is organized around three boundaries:

- :mod:`humble_steam_key_redeemer.humble` drives Humble Bundle through a real
  browser, because Humble exposes no public API.
- Steam access (authentication, ownership, redemption) comes from
  ``vendor_fabric.steam`` rather than being reimplemented here.
- :mod:`humble_steam_key_redeemer.core` holds the engine that decides which
  keys are worth spending a redemption attempt on, plus the local store.

Usage:
    from humble_steam_key_redeemer import Settings, RedeemerStore

    settings = Settings()
    store = RedeemerStore(settings.database_path)
"""

from __future__ import annotations

__version__ = "1.0.0"

from humble_steam_key_redeemer.core import (
    KeyRecord,
    MatchDecision,
    OwnershipMatcher,
    RedeemerStore,
    RedemptionAttempt,
)
from humble_steam_key_redeemer.settings import Settings

__all__ = [
    "KeyRecord",
    "MatchDecision",
    "OwnershipMatcher",
    "RedeemerStore",
    "RedemptionAttempt",
    "Settings",
    "__version__",
]
