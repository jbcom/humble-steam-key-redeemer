"""Tests for the extension's popup.

The popup is the only part a person drives by hand, and it broke twice in
review without anyone noticing: it sent an action the background did not
register, and it read the sign-in state from the wrong shape. Both were
invisible until someone clicked. This runs its real source against a fake DOM
so the same class of break fails here instead.

Node is required. Where it is missing these skip rather than fail, so the
suite still runs for someone working only on the Python side.
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


def _run_popup(reply: dict, *, status: dict, click: str | None = None) -> dict:
    """Load popup.js against a fake DOM and report what it rendered.

    Args:
        reply: What the background returns for the clicked action.
        status: What it returns for the initial status check.
        click: Element id to click, if any.

    Returns:
        The resulting state of the popup's elements.
    """
    harness = textwrap.dedent("""
        const fs = require("fs");

        function el(id) {
          return {
            id, textContent: "", className: "", hidden: true, disabled: false,
            checked: false, _handlers: {},
            classList: { _c: new Set(), add(n) { this._c.add(n); }, remove(n) { this._c.delete(n); } },
            addEventListener(event, fn) { this._handlers[event] = fn; },
          };
        }

        const nodes = {};
        for (const id of ["status", "output", "sync", "dry-run", "redeem", "reveal", "reveal-row"]) {
          nodes[id] = el(id);
        }

        const sent = [];
        global.document = { getElementById: (id) => nodes[id] };
        global.chrome = { runtime: { sendMessage: async (message) => {
          sent.push(message);
          return message.action === "status" ? STATUS : REPLY;
        } } };

        eval(fs.readFileSync(SOURCE, "utf8"));

        setTimeout(async () => {
          if (CLICK) await nodes[CLICK]._handlers.click();
          console.log(JSON.stringify({
            status: nodes.status.textContent,
            statusClass: nodes.status.className,
            output: nodes.output.textContent,
            outputHidden: nodes.output.hidden,
            revealRowHidden: nodes["reveal-row"].hidden,
            redeemLabel: nodes.redeem.textContent,
            sent,
          }));
        }, 20);
    """)

    script = (
        f"const SOURCE = {json.dumps(str(EXTENSION / 'popup.js'))};\n"
        f"const STATUS = {json.dumps(status)};\n"
        f"const REPLY = {json.dumps(reply)};\n"
        f"const CLICK = {json.dumps(click)};\n" + harness
    )

    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


SIGNED_IN = {"ok": True, "reply": {"humble": True, "steam": True}}

PLAN = {
    "ok": True,
    "reply": {
        "attempts": [{"title": "Celeste"}, {"title": "Outer Wilds"}],
        "skipped": 214,
        "uncertain": [{"title": "The Witcher 3 GOTY", "matched": "The Witcher 3"}],
    },
}


class TestSignInState:
    def test_being_signed_in_enables_the_actions(self):
        state = _run_popup(PLAN, status=SIGNED_IN)
        assert "Signed in" in state["status"]
        assert state["revealRowHidden"] is False

    def test_being_signed_out_says_which_site(self):
        signed_out = {"ok": True, "reply": {"humble": True, "steam": False}}
        state = _run_popup(PLAN, status=signed_out)
        assert "Steam" in state["status"]
        assert state["statusClass"] == "bad"


class TestPreview:
    def test_the_plan_is_rendered_readably(self):
        """Not raw JSON: this is the screen a person decides from."""
        state = _run_popup(PLAN, status=SIGNED_IN, click="dry-run")

        assert state["status"] == "Done."
        assert state["outputHidden"] is False
        assert "2 to attempt, 214 skipped" in state["output"]
        assert "Celeste" in state["output"]
        assert "The Witcher 3 GOTY" in state["output"]

    def test_it_sends_the_action_the_background_registers(self):
        """It once sent `dry-run`, which the background did not know."""
        state = _run_popup(PLAN, status=SIGNED_IN, click="dry-run")
        assert [message["action"] for message in state["sent"]] == ["status", "preview"]


class TestRedeeming:
    def test_the_first_click_only_arms(self):
        """Redeeming is irreversible, so one stray click must not start it."""
        state = _run_popup(PLAN, status=SIGNED_IN, click="redeem")

        assert [message["action"] for message in state["sent"]] == ["status"]
        assert "Click again" in state["redeemLabel"]
        assert "cannot be undone" in state["status"]


class TestFailures:
    def test_a_reported_failure_is_shown(self):
        failed = {"ok": False, "error": "Not signed in to Steam."}
        state = _run_popup(failed, status=SIGNED_IN, click="dry-run")

        assert state["status"] == "Not signed in to Steam."
        assert state["statusClass"] == "bad"
