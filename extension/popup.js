const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const buttons = [document.getElementById("sync"), document.getElementById("dry-run")];

function show(text, cls) {
  statusEl.textContent = text;
  statusEl.className = cls ?? "";
}

function report(reply) {
  outputEl.hidden = false;
  outputEl.textContent = typeof reply === "string" ? reply : JSON.stringify(reply, null, 2);
}

async function send(action) {
  buttons.forEach((b) => (b.disabled = true));
  show("Working…");
  const response = await chrome.runtime.sendMessage({ action });
  if (response?.ok) {
    show("Done.", "ok");
    report(response.reply);
  } else {
    show(response?.error ?? "Something went wrong.", "bad");
  }
  buttons.forEach((b) => (b.disabled = false));
}

(async () => {
  const response = await chrome.runtime.sendMessage({ action: "status" });
  if (response?.ok && response.signedIn) {
    show("Signed in to Humble.", "ok");
    buttons.forEach((b) => (b.disabled = false));
  } else {
    show("Not signed in. Open humblebundle.com and sign in.", "bad");
  }
})();

document.getElementById("sync").addEventListener("click", () => send("sync"));
document.getElementById("dry-run").addEventListener("click", () => send("dry-run"));
