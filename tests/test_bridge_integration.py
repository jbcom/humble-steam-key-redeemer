"""The agentic path, end to end, through a real host subprocess.

Everything else tests a piece: the queue, a handler, the extension's loop. This
runs the whole chain the way Chrome does — a host process started with only the
environment the launcher gives it, framed messages over its pipes, instructions
arriving from a separate caller — with only the extension played by the test.

It is the closest thing to the live run that does not need Chrome, and it is
what catches a break in the seams between the parts rather than inside them.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import threading
import time
from typing import Any

import pytest

from humble_steam_key_redeemer.bridge import run_command
from humble_steam_key_redeemer.settings import Settings

ORDER = {
    "gamekey": "order1",
    "tpkd_dict": {
        "all_tpks": [
            {
                "machine_name": "celeste",
                "human_name": "Celeste",
                "key_type": "steam",
                "redeemed_key_val": "AAAAA-BBBBB-CCCCC",
            },
            {
                "machine_name": "portal2",
                "human_name": "Portal 2",
                "key_type": "steam",
                "steam_app_id": 620,
                "redeemed_key_val": "DDDDD-EEEEE-FFFFF",
            },
            {
                "machine_name": "giftlink",
                "human_name": "Some Gift",
                "key_type": "steam",
                "redeemed_key_val": "https://www.humblebundle.com/gift?key=zzz",
            },
        ]
    },
}


class _Extension:
    """Plays the extension against a real host process.

    Answers instructions the way the extension would — by asking hskr a
    question and relaying the reply — so the host is exercised in both
    directions over the one pipe Chrome gives it.
    """

    def __init__(self, settings: Settings) -> None:
        self._process = subprocess.Popen(
            [sys.executable, "-m", "humble_steam_key_redeemer.bridge"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={"HSKR_STATE_DIR": str(settings.state_dir), "PATH": "/usr/bin:/bin"},
        )
        self.owned: dict[str, str] = {}
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message).encode()
        assert self._process.stdin is not None
        self._process.stdin.write(struct.pack("<I", len(payload)) + payload)
        self._process.stdin.flush()

    def _receive(self) -> dict[str, Any] | None:
        assert self._process.stdout is not None
        header = self._process.stdout.read(4)
        if len(header) < 4:
            return None
        (length,) = struct.unpack("<I", header)
        return json.loads(self._process.stdout.read(length))

    def _serve(self) -> None:
        while (message := self._receive()) is not None:
            action = message.get("action")
            if action == "sync":
                self._send({"command": "sync", "orders": [ORDER], "replyTo": "q"})
            elif action == "preview":
                self._send({"command": "plan", "owned": self.owned, "replyTo": "q"})
            else:
                continue

            answer = self._receive()
            if answer is None:
                continue
            # hskr wraps a question's answer as {replyTo, reply}; the extension
            # reports the outcome of an instruction as {requestId, ok, reply}.
            self._send(
                {
                    "requestId": message["requestId"],
                    "ok": True,
                    "reply": answer.get("reply", answer),
                }
            )

    def close(self) -> None:
        self._process.terminate()
        self._process.wait(timeout=10)


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    """A host subprocess with an extension attached, on a fresh state dir."""
    monkeypatch.delenv("HSKR_STATE_DIR", raising=False)
    settings = Settings(state_dir=tmp_path / "state")
    settings.ensure_state_dir()

    extension = _Extension(settings)
    time.sleep(0.3)  # let the host's queue watcher start
    try:
        yield settings, extension
    finally:
        extension.close()


class TestTheWholeChain:
    def test_a_library_imports_and_plans_correctly(self, bridge):
        """Sync then preview, exactly as an agent would run them."""
        settings, extension = bridge
        extension.owned = {"620": "Portal 2"}

        imported = run_command("sync", settings, timeout=30)
        assert imported["ok"] is True
        assert imported["reply"]["keys"] == 3

        planned = run_command("preview", settings, timeout=30)
        plan = planned["reply"]

        # Celeste is unowned and has a real key, so it is worth an attempt.
        # Portal 2 is already owned. The gift link is not a key at all, and
        # sending it would spend one of about ten failed activations an hour.
        assert [attempt["title"] for attempt in plan["attempts"]] == ["Celeste"]
        assert plan["skipped"] == 1

    def test_the_database_survives_between_commands(self, bridge):
        """Each command is a separate caller; the host holds the state."""
        settings, _ = bridge

        run_command("sync", settings, timeout=30)
        again = run_command("sync", settings, timeout=30)

        # Re-importing updates rather than duplicating.
        assert again["reply"]["keys"] == 3

    def test_an_unknown_instruction_never_leaves_the_caller_waiting(self, bridge):
        """A typo must fail immediately, not hang for the full timeout."""
        settings, _ = bridge

        started = time.monotonic()
        with pytest.raises(Exception, match="Unknown browser action"):
            run_command("synchronise", settings, timeout=30)

        assert time.monotonic() - started < 5
