const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const buttons = [document.getElementById("sync"), document.getElementById("dry-run")];

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
          lines.push(`  ? ${item.title} → ${item.matched ?? "?"}`);
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

async function send(action) {
  buttons.forEach((button) => (button.disabled = true));
  show("Working…");

  const response = await chrome.runtime.sendMessage({ action });
  if (response?.ok && response.reply?.ok !== false) {
    show("Done.", "ok");
    report(response.reply);
  } else {
    show(response?.error ?? response?.reply?.error ?? "Something went wrong.", "bad");
  }

  buttons.forEach((button) => (button.disabled = false));
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
    return;
  }

  // Importing only needs Humble; previewing needs Steam for ownership.
  const missing = [!humble && "Humble", !steam && "Steam"].filter(Boolean).join(" and ");
  show(`Not signed in to ${missing}. Open the site and sign in.`, "bad");
  document.getElementById("sync").disabled = !humble;
})();

document.getElementById("sync").addEventListener("click", () => send("sync"));
document.getElementById("dry-run").addEventListener("click", () => send("preview"));
