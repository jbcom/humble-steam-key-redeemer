"""Adapter between vendor-fabric's Steam connector and the redemption engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from vendor_fabric.steam import SteamConnector, SteamSession

if TYPE_CHECKING:
    from humble_steam_key_redeemer.settings import Settings


@dataclass(frozen=True, slots=True)
class SteamCredentials:
    """Credentials for a Steam sign-in.

    Attributes:
        account_name: Steam account name, not the display name.
        password: Account password.
        steam_guard_code: Steam Guard code, when already known.
    """

    account_name: str
    password: str
    steam_guard_code: str | None = None


def save_session(session: SteamSession, path: Path, account_name: str | None = None) -> Path:
    """Persist a Steam session to disk.

    The session tokens are bearer credentials that survive Steam Guard, so the
    file is written with owner-only permissions.

    Args:
        session: The session to store.
        path: Destination path.
        account_name: Account the session belongs to, so a later run can tell
            whether a saved session matches the account being asked for.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(
        json.dumps(
            {
                "steam_id": session.steam_id,
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "cookies": session.cookies,
                "account_name": account_name,
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def session_account(path: Path) -> str | None:
    """Return the account name a saved session belongs to, if recorded.

    Args:
        path: Session file path.

    Returns:
        The account name, or ``None`` when absent or unreadable.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = payload.get("account_name")
    return str(name) if isinstance(name, str) and name else None


def load_session(path: Path) -> SteamSession | None:
    """Load a previously saved Steam session.

    A missing, unreadable, or malformed file means "sign in again" rather than
    an error, so an interrupted write cannot lock the user out of the tool.

    Args:
        path: Session file path.

    Returns:
        The stored session, or ``None`` when unavailable.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SteamSession(
            steam_id=str(payload["steam_id"]),
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            cookies=dict(payload.get("cookies") or {}),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


class VendorFabricSteamGateway:
    """Engine-facing wrapper around :class:`vendor_fabric.steam.SteamConnector`.

    Args:
        settings: Runtime configuration, used for the session path.
        connector: An existing connector, mainly for testing.
    """

    def __init__(self, settings: Settings, connector: SteamConnector | None = None) -> None:
        self._settings = settings
        self._connector = connector or SteamConnector()
        self._owned: dict[int, str] | None = None

    @property
    def connector(self) -> SteamConnector:
        """The underlying vendor-fabric connector."""
        return self._connector

    def restore(self, account_name: str | None = None) -> bool:
        """Reuse a saved session when one is still valid.

        Args:
            account_name: When given, the saved session is only reused if it
                belongs to this account. Activations are irreversible, so a
                session for a different account must never be used silently.

        Returns:
            ``True`` when an existing session was restored and accepted.
        """
        session = load_session(self._settings.steam_session_path)
        if session is None:
            return False

        if account_name is not None:
            saved = session_account(self._settings.steam_session_path)
            if saved is not None and saved.casefold() != account_name.casefold():
                return False
        self._connector.restore_session(session)
        if self._connector.is_authenticated():
            return True
        # A stale session is worse than none: it produces confusing failures
        # deeper in the run, so drop it.
        self._settings.steam_session_path.unlink(missing_ok=True)
        return False

    def authenticate(self, credentials: SteamCredentials) -> None:
        """Sign in to Steam and persist the resulting session.

        Args:
            credentials: The credentials to sign in with.
        """
        connector = SteamConnector(
            account_name=credentials.account_name,
            password=credentials.password,
            steam_guard_code=credentials.steam_guard_code,
        )
        session = connector.authenticate()
        self._connector = connector
        save_session(session, self._settings.steam_session_path, credentials.account_name)

    # ----------------------------------------------------- SteamGateway API

    def list_owned_apps(self) -> dict[int, str]:
        """Return owned Steam applications, fetched once per run.

        Returns:
            Mapping of application id to name.
        """
        if self._owned is None:
            self._owned = {int(k): str(v) for k, v in self._connector.list_owned_apps().items()}
        return self._owned

    def redeem_key(self, key: str) -> dict[str, Any]:
        """Redeem one product key.

        Args:
            key: The Steam product key.

        Returns:
            The connector's result mapping.
        """
        return dict(self._connector.redeem_key(key))

    def close(self) -> None:
        """Release the connector's HTTP client."""
        self._connector.close()

    def __enter__(self) -> Self:
        """Enter a context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the connector on exit."""
        self.close()


__all__ = [
    "SteamCredentials",
    "VendorFabricSteamGateway",
    "load_session",
    "save_session",
    "session_account",
]
