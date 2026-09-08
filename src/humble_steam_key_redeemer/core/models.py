"""Database models for keys and redemption attempts.

Replaces the append-only CSV files the tool previously used. CSV was doing
double duty as both report and state, which made it the source of two
problems: fields containing commas, quotes, or newlines corrupted the file,
and values beginning with ``=``, ``+``, ``-`` or ``@`` were interpreted as
formulas when the file was opened in a spreadsheet.

A database keeps state; CSV export remains available as a *report*, where
values are escaped on the way out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


class KeyState(StrEnum):
    """Lifecycle state of a Humble key."""

    UNREVEALED = "unrevealed"
    REVEALED = "revealed"
    ATTEMPTED = "attempted"
    REDEEMED = "redeemed"
    ALREADY_OWNED = "already_owned"
    FAILED = "failed"
    SKIPPED = "skipped"


class KeyRecord(SQLModel, table=True):
    """A key entry from a Humble order.

    Attributes:
        gamekey: Humble order identifier.
        machine_name: Humble's stable internal name for the entry.
        human_name: Display title as shown by Humble.
        key_type: Platform the key targets (``steam``, ``gog``, ...).
        steam_app_id: Steam application id, when Humble reports one.
        redeemed_key_val: The revealed key, once Humble has released it.
        state: Current lifecycle state.
    """

    __tablename__ = "keys"

    id: int | None = Field(default=None, primary_key=True)
    gamekey: str = Field(index=True)
    machine_name: str = Field(index=True)
    human_name: str
    key_type: str | None = Field(default=None, index=True)
    steam_app_id: int | None = Field(default=None, index=True)
    redeemed_key_val: str | None = Field(default=None)
    # Position of the entry within its Humble order; required when asking
    # Humble to reveal a key from a multi-key bundle entry.
    key_index: int | None = Field(default=None)
    is_gift: bool = False
    is_expired: bool = False
    state: KeyState = Field(default=KeyState.UNREVEALED, index=True)
    matched_app_id: int | None = None
    matched_app_name: str | None = None
    match_score: int | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @property
    def is_steam(self) -> bool:
        """Whether this entry is a Steam key."""
        return (self.key_type or "").lower() == "steam" or self.steam_app_id is not None

    @property
    def is_revealed(self) -> bool:
        """Whether Humble has released the key value."""
        return bool(self.redeemed_key_val)


class RedemptionAttempt(SQLModel, table=True):
    """One attempt to redeem a key on Steam.

    Recording every attempt, rather than only the final state, means a rerun
    can tell "not tried yet" apart from "tried and rejected", which is what
    keeps the tool from spending its scarce failure budget twice on the same
    dead key.
    """

    __tablename__ = "redemption_attempts"

    id: int | None = Field(default=None, primary_key=True)
    key_id: int = Field(foreign_key="keys.id", index=True)
    result_code: int
    result_name: str
    detail: str
    succeeded: bool = Field(index=True)
    granted_items: str | None = None
    attempted_at: datetime = Field(default_factory=_utcnow)


__all__ = ["KeyRecord", "KeyState", "RedemptionAttempt"]
