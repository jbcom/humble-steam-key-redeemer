"""Tests for the Humble browser session."""

from __future__ import annotations

from humble_steam_key_redeemer.humble._browser import _is_humble_host, _is_humble_url


class TestHostChecks:
    """A substring match would treat a lookalike domain as Humble."""

    def test_humble_hosts_are_recognized(self):
        for host in ("humblebundle.com", "www.humblebundle.com", ".humblebundle.com"):
            assert _is_humble_host(host)

    def test_lookalike_domains_are_rejected(self):
        """These are what a substring check would wrongly accept."""
        for host in (
            "humblebundle.com.attacker.net",
            "nothumblebundle.com",
            "evil-humblebundle.com",
        ):
            assert not _is_humble_host(host)

    def test_urls_are_judged_by_host_not_text(self):
        assert _is_humble_url("https://www.humblebundle.com/home/library")
        # The string appears, but the host is the attacker's.
        assert not _is_humble_url("https://attacker.net/?next=humblebundle.com")
