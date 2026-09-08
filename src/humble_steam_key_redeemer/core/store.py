"""Persistent store for keys and redemption attempts.

The database is the tool's memory across runs. It answers the question that
decides whether a key is worth an activation attempt: has this key already
been tried, and what did Steam say?
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from humble_steam_key_redeemer.core.models import KeyRecord, KeyState, RedemptionAttempt

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


# Values a spreadsheet would evaluate as a formula rather than display as text.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")

# Steam's rate-limit result code. An attempt that hit the limit never reached
# a verdict, so the key stays eligible; every other outcome is settled.
RATE_LIMITED_CODE = 53


def csv_safe(value: object) -> str:
    """Neutralize a value for CSV export.

    Titles come from Humble and are not trusted input. A cell beginning with
    ``=``, ``+``, ``-`` or ``@`` is executed as a formula by Excel, LibreOffice
    and Sheets, so such values are prefixed with an apostrophe to force text.

    Args:
        value: Any cell value.

    Returns:
        A string safe to place in a spreadsheet cell.
    """
    if value is None:
        return ""
    text = str(value)
    if text[:1] in _FORMULA_LEADERS:
        return "'" + text
    return text


class RedeemerStore:
    """SQLite-backed store of keys and redemption attempts.

    Args:
        path: Database file path. Parent directories are created.
    """

    def __init__(self, path: Path) -> None:
        """Open (creating if needed) the database at ``path``."""
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._engine = create_engine(f"sqlite:///{self._path}", echo=False)

        # SQLite does not enforce foreign keys unless asked to, per connection.
        @event.listens_for(self._engine, "connect")
        def _fk_on(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        SQLModel.metadata.create_all(self._engine)
        self._path.chmod(0o600)

    @property
    def path(self) -> Path:
        """Path to the database file."""
        return self._path

    def session(self) -> Session:
        """Open a new database session.

        ``expire_on_commit`` is disabled so records stay readable after the
        session closes. Otherwise every attribute access on a returned record
        tries to reload from a session that no longer exists.
        """
        return Session(self._engine, expire_on_commit=False)

    # ------------------------------------------------------------------ keys

    def upsert_keys(self, records: Iterable[KeyRecord]) -> int:
        """Insert or update key records, keyed by Humble's identifiers.

        Humble's ``(gamekey, machine_name)`` pair is stable across runs, so
        re-importing an order updates existing rows instead of duplicating
        them and losing their redemption history.

        Args:
            records: Key records to store.

        Returns:
            The number of records written.
        """
        # Materialize the incoming values first. A previously-committed
        # instance is detached from its session, and reading its attributes
        # inside a new one raises DetachedInstanceError.
        incoming = [
            (
                record,
                record.model_dump(exclude={"id", "created_at", "updated_at"}),
            )
            for record in records
        ]

        written = 0
        with self.session() as session:
            for _record, values in incoming:
                existing = session.exec(
                    select(KeyRecord).where(
                        KeyRecord.gamekey == values["gamekey"],
                        KeyRecord.machine_name == values["machine_name"],
                    )
                ).first()

                if existing is None:
                    session.add(KeyRecord(**values))
                else:
                    # Preserve local decisions; refresh what Humble owns.
                    existing.human_name = values["human_name"]
                    existing.key_type = values["key_type"]
                    existing.steam_app_id = values["steam_app_id"]
                    existing.is_gift = values["is_gift"]
                    existing.is_expired = values["is_expired"]
                    if values["redeemed_key_val"]:
                        existing.redeemed_key_val = values["redeemed_key_val"]
                        if existing.state is KeyState.UNREVEALED:
                            existing.state = KeyState.REVEALED
                    existing.updated_at = datetime.now(UTC)
                    session.add(existing)
                written += 1
            session.commit()
        return written

    def all_keys(self) -> Sequence[KeyRecord]:
        """Return every stored key."""
        with self.session() as session:
            return list(session.exec(select(KeyRecord)).all())

    def steam_keys(self) -> list[KeyRecord]:
        """Return stored keys that target Steam."""
        return [key for key in self.all_keys() if key.is_steam]

    def pending_keys(self) -> list[KeyRecord]:
        """Return Steam keys that are still worth attempting.

        Excludes keys already redeemed, already owned, or previously attempted
        and rejected, so a rerun does not spend Steam's failure budget on
        outcomes already known.
        """
        with self.session() as session:
            # A rate-limited attempt is the one failure worth retrying; every
            # other recorded outcome is settled and must not be repeated.
            settled = {
                attempt.key_id
                for attempt in session.exec(select(RedemptionAttempt)).all()
                if attempt.result_code != RATE_LIMITED_CODE
            }
            # ATTEMPTED means a previous run reached Steam but never recorded
            # the verdict. Steam may have accepted the key, so retrying could
            # spend a failure on a key that already worked; surface it instead.
            terminal = {
                KeyState.REDEEMED,
                KeyState.ALREADY_OWNED,
                KeyState.SKIPPED,
                KeyState.ATTEMPTED,
            }
            return [
                key
                for key in session.exec(select(KeyRecord)).all()
                if key.is_steam and key.state not in terminal and key.id not in settled
            ]

    def update_key(self, record: KeyRecord) -> None:
        """Persist changes to a key record.

        Args:
            record: The record to save.
        """
        record.updated_at = datetime.now(UTC)
        with self.session() as session:
            session.add(record)
            session.commit()

    # ------------------------------------------------------------- attempts

    def record_attempt(self, attempt: RedemptionAttempt) -> RedemptionAttempt:
        """Store one redemption attempt.

        Args:
            attempt: The attempt to record.

        Returns:
            The stored attempt, with its assigned id.
        """
        with self.session() as session:
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
        return attempt

    def attempts_for(self, key_id: int) -> list[RedemptionAttempt]:
        """Return every recorded attempt for a key.

        Args:
            key_id: The key's database id.
        """
        with self.session() as session:
            return list(
                session.exec(select(RedemptionAttempt).where(RedemptionAttempt.key_id == key_id)).all()
            )

    # --------------------------------------------------------------- export

    def export_csv(self, destination: Path, *, steam_only: bool = False) -> Path:
        """Write stored keys to a CSV report.

        Uses :mod:`csv` for quoting so titles containing commas, quotes or
        newlines round-trip correctly, and neutralizes formula-leading values.

        Args:
            destination: Output file path.
            steam_only: Restrict the report to Steam keys.

        Returns:
            The path written.
        """
        columns = [
            "human_name",
            "key_type",
            "steam_app_id",
            "redeemed_key_val",
            "is_gift",
            "is_expired",
            "state",
            "matched_app_name",
            "match_score",
        ]
        keys = self.steam_keys() if steam_only else list(self.all_keys())

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for key in keys:
                writer.writerow([csv_safe(getattr(key, column, None)) for column in columns])
        return destination


__all__ = ["RedeemerStore", "csv_safe"]
