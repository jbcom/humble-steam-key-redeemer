"""Tests for the extension's redemption loop.

The handlers it calls are each tested in ``test_bridge.py``, but the order it
calls them in is its own logic and is where three review findings lived: a key
was not marked in flight before Steam saw it, a transport failure was recorded
as a Steam verdict, and a nested rate-limit code was missed so the run carried
on submitting during a cooldown.

None of that is reachable from Python, so the real ``background.js`` runs here
under node against a fake ``chrome`` — asserting the sequence of calls, which
is the thing that was wrong.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

EXTENSION = Path(__file__).resolve().parents[1] / "extension"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Steam's code for "you are going too fast", which must end the run.
RATE_LIMITED = 53


def _redeem(plan: dict, steam: list[dict], *, reveal: bool = False, humble: list | None = None) -> dict:
    """Run the extension's redeem loop and report what it did.

    Args:
        plan: What `plan` returns to the loop.
        steam: One response per redemption attempt, in order.
        reveal: Whether revealing is permitted.
        humble: One response per reveal attempt, in order.

    Returns:
        The calls made to hskr, and the payload `finish` received.
    """
    harness = textwrap.dedent("""
        const fs = require("fs");

        const asked = [];       // every command sent to hskr, in order
        const submitted = [];   // every key sent to Steam, in order
        let steamLeft = [...STEAM];
        let humbleLeft = [...HUMBLE];

        // Enough of chrome for the loop: a tab always exists, and injected
        // functions are replaced by the canned responses above.
        global.chrome = {
          tabs: { query: async () => [{ id: 1 }], create: async () => ({ id: 1 }) },
          scripting: { executeScript: async ({ func, args }) => {
            const name = func.toString();
            // Order matters: "registerkey" is a substring of
            // "ajaxregisterkey", so the redemption check has to come first or
            // the sign-in branch swallows every attempt.
            if (name.includes("ajaxregisterkey")) {
              submitted.push(args[0]);
              return [{ result: steamLeft.shift() ?? { error: "no response queued" } }];
            }
            if (name.includes("humbler/redeemkey")) {
              return [{ result: humbleLeft.shift() ?? { error: "no reveal queued" } }];
            }
            if (name.includes("dynamicstore/userdata")) return [{ result: { apps: {} } }];
            if (name.includes("account/registerkey")) return [{ result: { signedIn: true } }];
            if (name.includes("home/library")) return [{ result: { signedIn: true } }];
            return [{ result: {} }];
          } },
          runtime: {
            connectNative: () => port,
            onMessage: { addListener() {} },
            onStartup: { addListener() {} },
            onInstalled: { addListener() {} },
          },
          alarms: { create() {}, onAlarm: { addListener() {} } },
        };
        global.crypto = { randomUUID: () => "id-" + asked.length };

        // The long-lived port hskr answers over.
        const listeners = [];
        const port = {
          postMessage(message) {
            asked.push(message);
            const reply = message.command === "plan" ? PLAN : { ok: true };
            // Answer asynchronously, the way the real host does.
            setTimeout(() => listeners.forEach((fn) => fn({ replyTo: message.replyTo, reply })), 0);
          },
          onMessage: { addListener: (fn) => listeners.push(fn), removeListener() {} },
          onDisconnect: { addListener() {}, removeListener() {} },
        };

        const source = fs.readFileSync(SOURCE, "utf8");
        // The file ends by connecting; evaluating it defines everything first.
        eval(source);

        redeem({ reveal: REVEAL }).then(() => {
          console.log(JSON.stringify({
            commands: asked.map((a) => a.command),
            submitted,
            finish: asked.find((a) => a.command === "finish") ?? null,
          }));
        }).catch((error) => {
          console.log(JSON.stringify({ error: String(error.message || error) }));
        });
    """)

    script = (
        f"const SOURCE = {json.dumps(str(EXTENSION / 'background.js'))};\n"
        f"const PLAN = {json.dumps(plan)};\n"
        f"const STEAM = {json.dumps(steam)};\n"
        f"const HUMBLE = {json.dumps(humble or [])};\n"
        f"const REVEAL = {json.dumps(reveal)};\n" + harness
    )

    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def _plan(*attempts: dict) -> dict:
    return {"ok": True, "attempts": list(attempts)}


def _ok(**body) -> dict:
    return {"status": 200, "body": {"success": 1, **body}}


class TestOrder:
    def test_a_key_is_announced_before_steam_sees_it(self):
        """Out of order, a crash mid-activation loses the fact it was tried."""
        result = _redeem(_plan({"id": 7, "key": "AAAAA-BBBBB-CCCCC"}), [_ok()])

        commands = result["commands"]
        assert commands.index("attempting") < commands.index("record")
        assert result["submitted"] == ["AAAAA-BBBBB-CCCCC"]

    def test_each_verdict_is_recorded_as_it_happens(self):
        """A terminated worker must lose at most the key in flight."""
        result = _redeem(
            _plan({"id": 1, "key": "K1"}, {"id": 2, "key": "K2"}),
            [_ok(), _ok()],
        )

        assert result["commands"] == [
            "plan",
            "attempting",
            "record",
            "attempting",
            "record",
            "finish",
        ]


class TestRateLimit:
    def test_a_top_level_code_ends_the_run(self):
        result = _redeem(
            _plan({"id": 1, "key": "K1"}, {"id": 2, "key": "K2"}),
            [{"status": 200, "body": {"success": 0, "purchase_result_details": RATE_LIMITED}}, _ok()],
        )

        assert result["submitted"] == ["K1"]

    def test_a_nested_code_ends_the_run_too(self):
        """Reading only the top level meant submitting through a cooldown."""
        nested = {
            "status": 200,
            "body": {"success": 0, "purchase_receipt_info": {"result_detail": RATE_LIMITED}},
        }
        result = _redeem(_plan({"id": 1, "key": "K1"}, {"id": 2, "key": "K2"}), [nested, _ok()])

        assert result["submitted"] == ["K1"]


class TestFailuresThatNeverReachedSteam:
    def test_a_transport_failure_is_not_a_verdict(self):
        """Recording one would settle the key on an answer Steam never gave."""
        result = _redeem(
            _plan({"id": 1, "key": "K1"}),
            [{"error": "No Steam sessionid cookie; sign in to Steam first."}],
        )

        assert "record" not in result["commands"]
        assert result["finish"]["results"] == []
        assert [f["id"] for f in result["finish"]["failures"]] == [1]

    def test_a_refused_reveal_is_not_an_attempt(self):
        """Counting it would overstate the activation budget the run spent."""
        result = _redeem(
            _plan({"id": 1, "reveal": {"machineName": "m", "gamekey": "g", "keyIndex": 0}}),
            [],
            reveal=True,
            humble=[{"status": 500, "body": None}],
        )

        assert result["submitted"] == []
        assert result["finish"]["results"] == []
        assert len(result["finish"]["failures"]) == 1
