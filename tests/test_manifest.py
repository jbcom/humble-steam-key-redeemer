"""Tests for the extension manifest.

Chrome fails quietly here. A file that does not exist, a permission that was
never declared, an icon at the wrong size — none of these raise anything; the
extension just does less than it should, and only a person loading it notices.

These assert the manifest against what the code actually does, so the two
cannot drift apart unseen.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest

EXTENSION = Path(__file__).resolve().parents[1] / "extension"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((EXTENSION / "manifest.json").read_text())


@pytest.fixture(scope="module")
def background() -> str:
    return (EXTENSION / "background.js").read_text()


class TestReferences:
    def test_every_referenced_file_exists(self, manifest):
        """Chrome does not complain; it simply fails to load."""
        referenced = {
            manifest["background"]["service_worker"],
            manifest["action"]["default_popup"],
            *manifest.get("icons", {}).values(),
            *manifest["action"].get("default_icon", {}).values(),
        }

        missing = sorted(name for name in referenced if not (EXTENSION / name).is_file())
        assert missing == []

    def test_each_icon_is_the_size_it_claims(self, manifest):
        """One file reused at four sizes is the usual shortcut, and it looks it."""
        for declared, name in manifest["icons"].items():
            header = (EXTENSION / name).read_bytes()[16:24]
            width, height = struct.unpack(">II", header)
            assert (width, height) == (int(declared), int(declared)), name


class TestPermissions:
    """A permission the code uses but does not declare fails silently."""

    def test_apis_the_worker_calls_are_declared(self, manifest, background):
        declared = set(manifest["permissions"])

        for api, permission in [
            ("chrome.alarms.", "alarms"),
            ("chrome.scripting.", "scripting"),
            ("chrome.tabs.", "tabs"),
            ("connectNative", "nativeMessaging"),
        ]:
            if api in background:
                assert permission in declared, f"{api} needs {permission!r}"

    def test_every_origin_fetched_is_permitted(self, manifest, background):
        """A cross-origin fetch from an isolated world needs the grant."""
        hosts = {
            re.sub(r"^https://", "", pattern).split("/")[0].lstrip("*.")
            for pattern in manifest["host_permissions"]
        }

        for url in re.findall(r'fetch\(\s*"(https://[^"]+)"', background):
            host = url.split("/")[2]
            assert any(host == h or host.endswith(f".{h}") for h in hosts), url

    def test_nothing_is_declared_that_is_never_used(self, manifest, background):
        """Unused permissions are what store review rejects extensions over."""
        popup = (EXTENSION / "popup.js").read_text()
        code = background + popup

        uses = {
            "alarms": "chrome.alarms.",
            "scripting": "chrome.scripting.",
            "tabs": "chrome.tabs.",
            "nativeMessaging": "connectNative",
            "cookies": "chrome.cookies.",
            "storage": "chrome.storage.",
        }

        for permission in manifest["permissions"]:
            marker = uses.get(permission)
            assert marker is not None, f"unrecognized permission {permission!r}"
            assert marker in code, f"{permission!r} is declared but never used"


class TestManifestV3:
    def test_it_is_manifest_v3(self, manifest):
        assert manifest["manifest_version"] == 3

    def test_it_uses_a_service_worker_not_background_scripts(self, manifest):
        assert "service_worker" in manifest["background"]
        assert "scripts" not in manifest["background"]

    def test_host_permissions_are_separate_from_permissions(self, manifest):
        """Mixing them is the usual V2 habit, and silently grants nothing."""
        assert not any(p.startswith("http") for p in manifest["permissions"])

    def test_no_origin_is_broader_than_the_sites_it_drives(self, manifest):
        """A wildcard host is the fastest way to fail store review."""
        for pattern in manifest["host_permissions"]:
            assert pattern.startswith("https://"), pattern
            assert "humblebundle.com" in pattern or "steam" in pattern, pattern
