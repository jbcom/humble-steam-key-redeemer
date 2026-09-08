// Drives Humble Bundle and Steam inside the tabs the user is already signed
// into, and reports results to the hskr command-line tool over native
// messaging.
//
// Acting in the user's own tabs is the point. Handing cookies to a separate
// automated browser means a second sign-in, a profile Chrome has locked, and a
// session that Steam and Humble both treat as a new device. Running here means
// every request carries the session the user already established.
//
// The extension is a transport and an executor, not a second brain: it fetches
// and posts, then hands raw payloads to hskr. Ownership matching, the key
// database, rate-limit accounting, and the decision of what is worth redeeming
// all stay in the Python implementation.

const HOST = "com.jbcom.hskr";
const HUMBLE = "https://www.humblebundle.com";
const STEAM = "https://store.steampowered.com";

// Humble throttles bursts of order lookups, so details are fetched in batches.
const ORDER_BATCH_SIZE = 20;

// Steam permits roughly 50 activations an hour but only about 10 failures, so
// a rate-limited response stops the run rather than deepening the cooldown.
const STEAM_RATE_LIMITED = 53;

/** Find a tab already open on an origin, or open one. */
async function tabFor(urlPrefix) {
  const [existing] = await chrome.tabs.query({ url: `${urlPrefix}/*` });
  if (existing) return existing;
  return chrome.tabs.create({ url: urlPrefix, active: false });
}

/**
 * Run a function in the page's own context.
 *
 * Arguments cross into the page over Chrome's structured channel rather than
 * being interpolated into source, so a title or key containing a quote is
 * inert data rather than executable text.
 */
async function inPage(tabId, fn, args = []) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: fn,
    args,
  });
  if (result?.result?.error) throw new Error(result.result.error);
  return result?.result;
}

// ---------------------------------------------------------------- Humble

async function humbleSignedIn() {
  // Checked from inside the page rather than the service worker: a service
  // worker fetch has no page origin, so it does not reliably carry the user's
  // session and reports a false "signed out".
  const tab = await tabFor(HUMBLE);
  const result = await inPage(tab.id, async () => {
    try {
      const response = await fetch("/home/library", {
        credentials: "include",
        redirect: "follow",
      });
      return { signedIn: response.ok && !response.redirected };
    } catch (error) {
      return { error: String(error.message || error) };
    }
  });
  return Boolean(result?.signedIn);
}

/** Read every order, in batches, from inside the Humble page. */
async function readOrders() {
  const tab = await tabFor(HUMBLE);
  return inPage(
    tab.id,
    async (batchSize) => {
      try {
        const listed = await fetch("/api/v1/user/order", { credentials: "include" });
        if (!listed.ok) return { error: `Humble returned HTTP ${listed.status}` };
        const gamekeys = (await listed.json()).map((o) => o.gamekey);

        const orders = [];
        for (let i = 0; i < gamekeys.length; i += batchSize) {
          for (const gamekey of gamekeys.slice(i, i + batchSize)) {
            const url = `/api/v1/order/${encodeURIComponent(gamekey)}?all_tpkds=true`;
            const detail = await fetch(url, { credentials: "include" });
            if (!detail.ok) {
              return { error: `Humble returned HTTP ${detail.status} for order ${gamekey}` };
            }
            orders.push(await detail.json());
          }
        }
        return { orders };
      } catch (error) {
        return { error: String(error.message || error) };
      }
    },
    [ORDER_BATCH_SIZE],
  );
}

/**
 * Reveal one key on Humble.
 *
 * Irreversible: revealing forfeits the ability to generate a gift link, which
 * is why hskr decides what to reveal and this only carries out the request.
 */
async function revealKey({ machineName, gamekey, keyIndex }) {
  const tab = await tabFor(HUMBLE);
  return inPage(
    tab.id,
    async (payload) => {
      try {
        const csrf = document.cookie.match(/csrf_cookie=([^;]+)/)?.[1] ?? "";
        const body = new FormData();
        body.append("keytype", payload.machineName);
        body.append("key", payload.gamekey);
        body.append("keyindex", String(payload.keyIndex ?? 0));

        const response = await fetch("/humbler/redeemkey", {
          method: "POST",
          credentials: "include",
          headers: csrf ? { "CSRF-Prevention-Token": decodeURIComponent(csrf) } : {},
          body,
        });
        const parsed = await response.json().catch(() => null);
        return { status: response.status, body: parsed };
      } catch (error) {
        return { error: String(error.message || error) };
      }
    },
    [{ machineName, gamekey, keyIndex }],
  );
}

// ----------------------------------------------------------------- Steam

async function steamSignedIn() {
  // Same reason as the Humble check: run it where the session lives.
  const tab = await tabFor(STEAM);
  const result = await inPage(tab.id, async () => {
    try {
      const response = await fetch("/account/registerkey", {
        credentials: "include",
        redirect: "manual",
      });
      return { signedIn: response.type === "opaqueredirect" ? false : response.ok };
    } catch (error) {
      return { error: String(error.message || error) };
    }
  });
  return Boolean(result?.signedIn);
}

/** Read the signed-in account's owned applications. */
async function readOwnedApps() {
  const tab = await tabFor(STEAM);
  return inPage(tab.id, async () => {
    try {
      const userdata = await (
        await fetch("/dynamicstore/userdata/", { credentials: "include" })
      ).json();
      // Applications only. Package ids are a separate namespace that happens
      // to share the integer space, so folding them in here would mark an
      // unowned application owned whenever its id collided with an owned
      // package number — and a game wrongly marked owned has its key silently
      // skipped.
      const owned = new Set(userdata.rgOwnedApps ?? []);
      if (owned.size === 0) return { apps: {} };

      // Names come from the account's own games list rather than a public
      // catalogue: `ISteamApps/GetAppList` was withdrawn and now returns 404,
      // and the replacement wants an API key this tool deliberately does not
      // have. This page is one request and it is already authenticated.
      //
      // Ownership by app id alone is enough whenever Humble supplied one; the
      // names are for the fuzzy title fallback, so an id with no name still
      // counts as owned.
      const apps = {};
      for (const id of owned) apps[id] = "";

      try {
        const games = await fetch("https://steamcommunity.com/my/games/?tab=all&xml=1", {
          credentials: "include",
        });
        if (games.ok) {
          const xml = await games.text();
          const pattern = /<appID>(\d+)<\/appID>\s*<name><!\[CDATA\[([\s\S]*?)\]\]><\/name>/g;
          for (const [, id, name] of xml.matchAll(pattern)) {
            if (owned.has(Number(id))) apps[Number(id)] = name.trim();
          }
        }
      } catch {
        // Names are an optimisation for fuzzy matching. Without them the app
        // ids still answer ownership for every key Humble tagged.
      }

      return { apps };
    } catch (error) {
      return { error: String(error.message || error) };
    }
  });
}

/** Redeem one product key on Steam. */
async function redeemKey(key) {
  const tab = await tabFor(STEAM);
  return inPage(
    tab.id,
    async (productKey) => {
      try {
        const sessionid = document.cookie.match(/sessionid=([^;]+)/)?.[1];
        if (!sessionid) return { error: "No Steam sessionid cookie; sign in to Steam first." };

        const body = new URLSearchParams({ product_key: productKey, sessionid });
        const response = await fetch("/account/ajaxregisterkey/", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body,
        });
        return { status: response.status, body: await response.json().catch(() => null) };
      } catch (error) {
        return { error: String(error.message || error) };
      }
    },
    [key],
  );
}

// ------------------------------------------------------------------ hskr

/**
 * Ask hskr what to do, handing it what the browser just read.
 *
 * This goes down the same long-lived port that carries instructions the other
 * way, rather than `sendNativeMessage`, which starts a *separate* host process
 * per call. Only the process holding this port is watching the request queue,
 * so a one-shot process would answer the question and leave an agent's
 * instruction unserved.
 */
async function askHskr(command, payload = {}) {
  const port = connectToHost();
  const id = crypto.randomUUID();

  return new Promise((resolve, reject) => {
    // Both listeners are removed on either outcome. A redeem run asks a
    // question per key, so listeners that outlived their question would
    // accumulate for the length of the run.
    const done = (settle, value) => {
      port.onMessage.removeListener(onMessage);
      port.onDisconnect.removeListener(onDisconnect);
      settle(value);
    };
    const onMessage = (message) => {
      if (message?.replyTo === id) done(resolve, message.reply);
    };
    const onDisconnect = () => done(reject, new Error("hskr disconnected"));

    port.onMessage.addListener(onMessage);
    port.onDisconnect.addListener(onDisconnect);
    port.postMessage({ replyTo: id, command, ...payload });
  });
}

/** Import the library: browser reads the orders, hskr stores and analyses them. */
async function sync() {
  if (!(await humbleSignedIn())) {
    throw new Error("Not signed in to Humble. Open humblebundle.com and sign in.");
  }
  const result = await readOrders();
  if (result?.error) throw new Error(result.error);
  return askHskr("sync", { orders: result.orders });
}

/** Ask hskr what it would redeem, using ownership read from the live session. */
async function preview() {
  if (!(await steamSignedIn())) {
    throw new Error("Not signed in to Steam. Open store.steampowered.com and sign in.");
  }
  const owned = await readOwnedApps();
  if (owned?.error) throw new Error(owned.error);
  return askHskr("plan", { owned: owned.apps });
}

/**
 * Redeem what hskr selects.
 *
 * hskr decides: it checks ownership, skips duplicates and non-keys, and stops
 * the run when Steam reports a rate limit. The extension only carries out the
 * individual requests and reports each verdict back.
 */
async function redeem({ reveal = false } = {}) {
  if (!(await steamSignedIn())) {
    throw new Error("Not signed in to Steam. Open store.steampowered.com and sign in.");
  }
  const owned = await readOwnedApps();
  if (owned?.error) throw new Error(owned.error);

  const plan = await askHskr("plan", { owned: owned.apps, reveal });
  if (!plan?.ok) throw new Error(plan?.error ?? "hskr could not build a plan");

  // A service worker can be terminated mid-run, so nothing is held only in
  // memory: each verdict is persisted through `record` as it happens, and hskr
  // marks the key settled. A terminated run therefore loses at most the key in
  // flight, and a rerun will not re-attempt anything already decided.
  //
  // `results` holds Steam verdicts only. Anything that never reached Steam —
  // a reveal Humble refused, a request that failed in transit — goes in
  // `failures`, because counting those as attempts would overstate how much of
  // the hourly activation budget the run actually spent.
  const results = [];
  const failures = [];

  for (const entry of plan.attempts ?? []) {
    let key = entry.key;

    if (!key && reveal && entry.reveal) {
      const revealed = await revealKey(entry.reveal);
      if (revealed?.error || revealed?.status !== 200) {
        failures.push({ id: entry.id, detail: revealed?.error ?? "Humble refused the reveal" });
        continue;
      }
      key = revealed.body?.key;
      if (!key) {
        failures.push({ id: entry.id, detail: "Humble returned no key" });
        continue;
      }
    }
    if (!key) continue;

    // Mark it in flight before Steam sees it. If anything here dies mid
    // activation, hskr surfaces the key rather than silently offering it up
    // for a second activation on the next run.
    await askHskr("attempting", { id: entry.id });

    const outcome = await redeemKey(key);

    // A transport failure is not a verdict from Steam. Recording one as
    // though it were would settle the key permanently, removing it from every
    // future plan on the strength of an error Steam never sent.
    if (outcome?.error || !outcome?.body) {
      failures.push({ id: entry.id, detail: outcome?.error ?? "Steam sent no response" });
      continue;
    }

    // Steam reports the code in either place depending on the response shape.
    // Reading only the top-level one means missing a rate limit and carrying
    // on submitting, which extends the cooldown rather than ending the run.
    const detail =
      outcome.body.purchase_result_details ??
      outcome.body.purchase_receipt_info?.result_detail ??
      null;
    results.push({ id: entry.id, key, status: outcome.status, result: outcome.body });

    // Report progress as it happens rather than only at the end.
    await askHskr("record", { result: results.at(-1) });

    if (detail === STEAM_RATE_LIMITED) break;
  }

  return askHskr("finish", { results, failures });
}

// --------------------------------------------------------------- routing

const ACTIONS = {
  status: async () => ({
    humble: await humbleSignedIn(),
    steam: await steamSignedIn(),
  }),
  sync,
  preview,
  redeem: (message) => redeem({ reveal: Boolean(message.reveal) }),
};

/** Run one action and normalize both outcomes into a reply. */
async function dispatch(message) {
  try {
    const action = ACTIONS[message.action];
    if (!action) throw new Error(`Unknown action: ${message.action}`);
    return { ok: true, reply: await action(message) };
  } catch (error) {
    return { ok: false, error: String(error.message || error) };
  }
}

// From the popup, when a person clicks a button.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  dispatch(message).then(sendResponse);
  return true; // keep the channel open for the async reply
});

// From hskr, when an agent or script runs a command.
//
// The popup is for a person; this is the same work driven from outside the
// browser, so an unattended run needs no one to click anything. hskr connects,
// sends the action, and the extension does the work in the user's tabs.
//
// Chrome only lets an extension connect to a native host, never the reverse, so
// the extension holds the port open and waits for instructions rather than
// polling or listening on a socket.
let commandPort = null;

/**
 * Open the long-lived port hskr sends instructions over.
 *
 * Throws when the native host is not registered, which is the common setup
 * mistake: Chrome will only start a host whose manifest names this extension,
 * so `hskr bridge --extension-id <ID>` has to have been run.
 */
function connectToHost() {
  if (commandPort) return commandPort;

  const port = chrome.runtime.connectNative(HOST);
  commandPort = port;

  port.onMessage.addListener(async (message) => {
    if (!message?.action) return;
    const reply = await dispatch(message);
    // Replies go back down the port the instruction arrived on. A redeem run
    // takes minutes, long enough for the port to have dropped and a new one to
    // have replaced it, and the agent waiting is attached to this one.
    port.postMessage({ requestId: message.requestId, ...reply });
  });

  port.onDisconnect.addListener(() => {
    if (commandPort === port) commandPort = null;
  });

  return port;
}

// Reconnect whenever the service worker starts, so the port is available
// without anyone opening the popup.
chrome.runtime.onStartup.addListener(connectToHost);
chrome.runtime.onInstalled.addListener(connectToHost);

// An open native port keeps the service worker alive, but nothing revives it
// once that port drops — hskr exited, Chrome restarted, or the worker was
// terminated before it ever connected. An alarm is the only wake-up a
// terminated service worker still gets, so it is what makes an agent's
// instruction land on a browser nobody has touched today.
const RECONNECT_ALARM = "hskr-reconnect";

chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) connectToHost();
});

connectToHost();
