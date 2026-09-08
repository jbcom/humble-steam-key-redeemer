"""Tests for the Steam gateway adapter."""

from __future__ import annotations

import pytest
from vendor_fabric.steam import SteamSession

from humble_steam_key_redeemer.settings import Settings
from humble_steam_key_redeemer.steam import VendorFabricSteamGateway, save_session


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
    settings = Settings(state_dir=tmp_path / "state")
    settings.ensure_state_dir()
    return settings


class FakeConnector:
    """Stand-in for vendor-fabric's SteamConnector."""

    def __init__(self, *, authenticated: bool = True) -> None:
        self._authenticated = authenticated
        self.restored: SteamSession | None = None
        self.owned_calls = 0
        self.closed = False

    def restore_session(self, session: SteamSession) -> None:
        self.restored = session

    def is_authenticated(self) -> bool:
        return self._authenticated

    def list_owned_apps(self) -> dict[int, str]:
        self.owned_calls += 1
        return {620: "Portal 2"}

    def redeem_key(self, key: str) -> dict[str, object]:
        return {"success": True, "result": None, "detail": "ok", "items": [key]}

    def close(self) -> None:
        self.closed = True


class TestSessionRestore:
    def test_restores_a_valid_session(self, settings):
        save_session(
            SteamSession(steam_id="1", access_token="a", refresh_token="r"),
            settings.steam_session_path,
        )
        connector = FakeConnector(authenticated=True)
        gateway = VendorFabricSteamGateway(settings, connector)

        assert gateway.restore()
        assert connector.restored is not None

    def test_returns_false_without_a_saved_session(self, settings):
        gateway = VendorFabricSteamGateway(settings, FakeConnector())
        assert not gateway.restore()

    def test_discards_a_stale_session(self, settings):
        """A rejected session must be removed, not reused into confusing failures."""
        save_session(
            SteamSession(steam_id="1", access_token="a", refresh_token="r"),
            settings.steam_session_path,
        )
        gateway = VendorFabricSteamGateway(settings, FakeConnector(authenticated=False))

        assert not gateway.restore()
        assert not settings.steam_session_path.exists()


class TestGatewayOperations:
    def test_owned_apps_are_fetched_once(self, settings):
        """The app list is large; refetching it per key would be wasteful."""
        connector = FakeConnector()
        gateway = VendorFabricSteamGateway(settings, connector)

        gateway.list_owned_apps()
        gateway.list_owned_apps()

        assert connector.owned_calls == 1

    def test_owned_app_ids_are_integers(self, settings):
        gateway = VendorFabricSteamGateway(settings, FakeConnector())
        assert all(isinstance(key, int) for key in gateway.list_owned_apps())

    def test_redeem_delegates_to_the_connector(self, settings):
        gateway = VendorFabricSteamGateway(settings, FakeConnector())
        assert gateway.redeem_key("AAAAA-BBBBB-CCCCC")["success"] is True

    def test_context_manager_closes_the_connector(self, settings):
        connector = FakeConnector()
        with VendorFabricSteamGateway(settings, connector):
            pass
        assert connector.closed


class TestAccountScopedRestore:
    """Activations are irreversible, so the wrong account must never be used."""

    def test_a_session_for_another_account_is_not_reused(self, settings):
        save_session(
            SteamSession(steam_id="1", access_token="a", refresh_token="r"),
            settings.steam_session_path,
            "alice",
        )
        gateway = VendorFabricSteamGateway(settings, FakeConnector())

        assert not gateway.restore(account_name="bob")

    def test_a_matching_account_is_reused(self, settings):
        save_session(
            SteamSession(steam_id="1", access_token="a", refresh_token="r"),
            settings.steam_session_path,
            "alice",
        )
        gateway = VendorFabricSteamGateway(settings, FakeConnector())

        assert gateway.restore(account_name="Alice")  # case-insensitive

    def test_no_requested_account_reuses_any_session(self, settings):
        save_session(
            SteamSession(steam_id="1", access_token="a", refresh_token="r"),
            settings.steam_session_path,
            "alice",
        )
        gateway = VendorFabricSteamGateway(settings, FakeConnector())

        assert gateway.restore()
