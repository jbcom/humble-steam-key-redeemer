const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const redeemButton = document.getElementById("redeem");
const revealBox = document.getElementById("reveal");
const buttons = [
  document.getElementById("sync"),
  document.getElementById("dry-run"),
  redeemButton,
];

// Redeeming is irreversible and spends a limited hourly budget, so the button
// arms on the first click and acts on the second. A modal would block every
// later message the extension tries to handle, so it is not an option here.
let armed = false;

function disarm() {
  armed = false;
  redeemButton.textContent = "Redeem on Steam";
  redeemButton.classList.remove("armed");
}

function show(text, cls) {
  statusEl.textContent = text;
  statusEl.className = cls ?? "";
}

/** Render a reply, preferring a readable summary over raw JSON. */
function report(reply) {
  outputEl.hidden = false;

  if (reply && typeof reply === "object") {
    if (Array.isArray(reply.attempts)) {
      const lines = [`${reply.attempts.length} to attempt, ${reply.skipped ?? 0} skipped`];
      for (const attempt of reply.attempts) lines.push(`  • ${attempt.title}`);
      if (reply.uncertain?.length) {
        lines.push("", "Not certain you own these:");
        for (const item of reply.uncertain) {
          // The match goes on its own line: an arrow that wraps leaves the
          // matched title looking like a separate entry.
          lines.push(`  ? ${item.title}`);
          lines.push(`      matched: ${item.matched ?? "unknown"}`);
        }
      }
      outputEl.textContent = lines.join("\n");
      return;
    }
    if (typeof reply.keys === "number") {
      outputEl.textContent =
        `${reply.keys} entries from ${reply.orders ?? "?"} orders\n` +
        `${reply.steam_keys ?? 0} Steam keys (${reply.revealed ?? 0} revealed)`;
      return;
    }
  }

  outputEl.textContent = typeof reply === "string" ? reply : JSON.stringify(reply, null, 2);
}

async function send(action, extra = {}) {
  buttons.forEach((button) => (button.disabled = true));
  show("Working…");

  try {
    const response = await chrome.runtime.sendMessage({ action, ...extra });
    if (response?.ok && response.reply?.ok !== false) {
      show("Done.", "ok");
      report(response.reply);
    } else {
      show(response?.error ?? response?.reply?.error ?? "Something went wrong.", "bad");
    }
  } catch (error) {
    // Delivery itself can fail — a terminated service worker, a closed port —
    // and that rejects rather than returning {ok: false}.
    show(String(error.message || error), "bad");
  } finally {
    // Always, or a failure leaves the popup stuck on "Working…" for good.
    buttons.forEach((button) => (button.disabled = false));
    disarm();
  }
}

(async () => {
  const response = await chrome.runtime.sendMessage({ action: "status" });
  if (!response?.ok) {
    show(response?.error ?? "Could not reach the extension.", "bad");
    return;
  }

  const { humble, steam } = response.reply ?? {};
  if (humble && steam) {
    show("Signed in to Humble and Steam.", "ok");
    buttons.forEach((button) => (button.disabled = false));
    // Revealing goes through Humble, so the choice only appears once both
    // sites are reachable.
    document.getElementById("reveal-row").hidden = false;
    return;
  }

  // Importing only needs Humble; previewing needs Steam for ownership.
  const missing = [!humble && "Humble", !steam && "Steam"].filter(Boolean).join(" and ");
  show(`Not signed in to ${missing}. Open the site and sign in.`, "bad");
  document.getElementById("sync").disabled = !humble;
})();

document.getElementById("sync").addEventListener("click", () => send("sync"));
document.getElementById("dry-run").addEventListener("click", () => send("preview"));

redeemButton.addEventListener("click", () => {
  if (!armed) {
    armed = true;
    redeemButton.textContent = revealBox.checked
      ? "Click again to redeem and reveal"
      : "Click again to redeem";
    redeemButton.classList.add("armed");
    show("This cannot be undone. Click again to go ahead.", "bad");
    return;
  }
  send("redeem", { reveal: revealBox.checked });
});

// Changing what the run would do disarms it, so a click cannot carry over
// from the choice that preceded it.
revealBox.addEventListener("change", disarm);
