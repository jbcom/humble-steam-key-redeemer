"""Configuration for the redeemer.

Settings resolve from, in order of precedence: explicit arguments, environment
variables prefixed ``HSKR_``, a ``.env`` file, then the defaults below.

State is kept under a single application directory rather than scattered
through the working directory, so running the tool from a different folder
does not silently start from an empty history.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_state_dir() -> Path:
    """Return the per-user state directory for the current platform."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif xdg := os.environ.get("XDG_STATE_HOME"):
        root = Path(xdg)
    else:
        root = Path.home() / ".local" / "state"
    return root / "humble-steam-key-redeemer"


class Settings(BaseSettings):
    """Runtime configuration.

    Attributes:
        state_dir: Directory holding the database and saved sessions.
        match_threshold: Similarity score above which a Humble title is
            considered to match an owned Steam app.
        confirm_threshold: Score at or above which a match is trusted without
            asking the user.
        headless: Whether the Humble browser runs without a visible window.
        browser_timeout_ms: Per-operation browser timeout in milliseconds.
        request_timeout: HTTP timeout in seconds.
        locale: Browser locale, which determines Humble's currency display.
    """

    model_config = SettingsConfigDict(
        env_prefix="HSKR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    state_dir: Path = Field(default_factory=_default_state_dir)

    # Ownership matching. Humble and Steam spell titles differently
    # ("Game GOTY" vs "Game: Game of the Year Edition"), so exact comparison
    # misses and a low bar produces false matches that skip redeemable keys.
    match_threshold: int = Field(default=70, ge=0, le=100)
    confirm_threshold: int = Field(default=95, ge=0, le=100)

    headless: bool = True
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    browser_timeout_ms: int = Field(default=60_000, gt=0)
    request_timeout: float = Field(default=30.0, gt=0)
    locale: str = "en-US"

    # Steam permits roughly 50 activations per hour but only 10 failures.
    # Stopping on a rate limit rather than retrying avoids deepening it.
    max_redemptions_per_run: int = Field(default=0, ge=0)

    @field_validator("state_dir")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        """Expand ``~`` and resolve the state directory."""
        return value.expanduser()

    @property
    def database_path(self) -> Path:
        """Path to the SQLite database of keys and redemption attempts."""
        return self.state_dir / "redeemer.db"

    @property
    def humble_session_path(self) -> Path:
        """Path to the stored Humble browser session."""
        return self.state_dir / "humble-session.json"

    @property
    def steam_session_path(self) -> Path:
        """Path to the stored Steam session."""
        return self.state_dir / "steam-session.json"

    def ensure_state_dir(self) -> Path:
        """Create the state directory with owner-only permissions.

        Session files are bearer credentials, so the directory is created
        as ``0700`` rather than inheriting a permissive umask.

        Returns:
            The state directory path.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.state_dir


__all__ = ["Settings"]
