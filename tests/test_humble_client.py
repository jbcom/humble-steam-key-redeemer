"""Tests for the Humble client's request layer."""

from __future__ import annotations

import pytest

from humble_steam_key_redeemer.core import KeyRecord
from humble_steam_key_redeemer.humble import HumbleAPIError, HumbleClient


class FakeBrowser:
    """Records what would be sent to the page, without running one."""

    def __init__(self, responses: list[object] | None = None, csrf: str | None = "token") -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, object]] = []
        self.visited: list[str] = []
        self._csrf = csrf

    def goto(self, url: str) -> None:
        self.visited.append(url)

    def evaluate(self, script: str, argument: object = None) -> object:
        self.calls.append((script, argument))
        if not self.responses:
            return None
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def cookie(self, name: str) -> str | None:
        return self._csrf if name == "csrf_cookie" else None


class TestLoginState:
    def test_reports_signed_in(self):
        client = HumbleClient(FakeBrowser([True]))
        assert client.is_logged_in()

    def test_reports_signed_out(self):
        client = HumbleClient(FakeBrowser([False]))
        assert not client.is_logged_in()


class TestOrders:
    def test_lists_order_keys(self):
        client = HumbleClient(FakeBrowser([["order1", "order2"]]))
        assert client.order_keys() == ["order1", "order2"]

    def test_wraps_failures(self):
        client = HumbleClient(FakeBrowser([RuntimeError("network down")]))
        with pytest.raises(HumbleAPIError, match="Could not list Humble orders"):
            client.order_keys()

    def test_details_are_fetched_in_batches(self):
        """One unbounded request over a large library gets throttled."""
        browser = FakeBrowser([[{"gamekey": "a"}], [{"gamekey": "b"}]])
        client = HumbleClient(browser)

        details = client.order_details([f"order{index}" for index in range(25)])

        assert len(browser.calls) == 2
        assert len(details) == 2

    def test_details_pass_gamekeys_as_data(self):
        """Gamekeys must cross into the page as an argument, never as script text."""
        browser = FakeBrowser([[]])
        client = HumbleClient(browser)

        hostile = "'; globalThis.pwned = 1; var x='"
        client.order_details([hostile])

        _script, argument = browser.calls[0]
        assert argument == [hostile]


class TestPost:
    def test_sends_payload_and_csrf_as_data(self):
        browser = FakeBrowser([{"status": 200, "body": {"success": True}}])
        client = HumbleClient(browser)

        status, body = client.post("https://example.test/x", {"field": "value"})

        _script, argument = browser.calls[0]
        assert argument["payload"] == {"field": "value"}
        assert argument["csrf"] == "token"
        assert status == 200
        assert body == {"success": True}

    def test_missing_csrf_cookie_becomes_empty(self):
        browser = FakeBrowser([{"status": 200, "body": {}}], csrf=None)
        client = HumbleClient(browser)

        client.post("https://example.test/x", {})

        assert browser.calls[0][1]["csrf"] == ""


class TestReveal:
    @staticmethod
    def _record() -> KeyRecord:
        return KeyRecord(
            gamekey="order1",
            machine_name="portal2",
            human_name="Portal 2",
            key_type="steam",
            key_index=3,
        )

    def test_returns_the_revealed_key(self):
        browser = FakeBrowser([{"status": 200, "body": {"success": True, "key": "AAAAA-BBBBB-CCCCC"}}])
        assert HumbleClient(browser).reveal_key(self._record()) == "AAAAA-BBBBB-CCCCC"

    def test_sends_the_key_index(self):
        """Multi-key entries need the index or Humble reveals the wrong one."""
        browser = FakeBrowser([{"status": 200, "body": {"success": True, "key": "A"}}])
        HumbleClient(browser).reveal_key(self._record())
        assert browser.calls[0][1]["payload"]["keyindex"] == "3"

    def test_reports_humble_errors(self):
        browser = FakeBrowser([{"status": 200, "body": {"error_msg": "Already revealed"}}])
        with pytest.raises(HumbleAPIError, match="Already revealed"):
            HumbleClient(browser).reveal_key(self._record())

    def test_reports_http_failures(self):
        browser = FakeBrowser([{"status": 500, "body": None}])
        with pytest.raises(HumbleAPIError, match="HTTP 500"):
            HumbleClient(browser).reveal_key(self._record())

    def test_reports_declined_reveals(self):
        browser = FakeBrowser([{"status": 200, "body": {"success": False}}])
        with pytest.raises(HumbleAPIError, match="declined"):
            HumbleClient(browser).reveal_key(self._record())

    def test_missing_key_value_returns_none(self):
        browser = FakeBrowser([{"status": 200, "body": {"success": True}}])
        assert HumbleClient(browser).reveal_key(self._record()) is None
