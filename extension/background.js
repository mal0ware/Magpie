// Magpie Bridge service worker.
//
// Holds a WebSocket to the local Magpie daemon and, when asked, runs
// Instagram's own saved-feed request from inside a logged-in instagram.com
// tab. No debugger and no tab groups, so it works in any Chromium browser
// (Chrome, Edge, Brave, Vivaldi, Opera GX).
//
// If it had to open that tab itself, it closes it again: when Magpie says it
// is done ("release"), or after the tab has sat unused for two minutes. A tab
// you opened is never closed.
//
// It reads the saved feed, and it can unsave a post when Magpie names one
// (the Unsave button). It makes one request per message from the daemon, never
// retries, and hands the raw outcome (status, final URL, body) back so the
// Python side decides whether to stop.

const DAEMON_URL = "ws://127.0.0.1:19877/ext";
const IG_APP_ID = "936619743392459";
const SAVED_FEED = "https://www.instagram.com/api/v1/feed/saved/posts/";
const UNSAVE = (id) => `https://www.instagram.com/api/v1/web/save/${id}/unsave/`;
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 15000;
const VERSION = chrome.runtime.getManifest().version;
const OWNED_TAB_IDLE_MS = 2 * 60 * 1000;

let ws = null;
let reconnectDelay = RECONNECT_MIN_MS;

function log(...args) {
  console.log("[magpie-bridge]", ...args);
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(DAEMON_URL);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    reconnectDelay = RECONNECT_MIN_MS;
    ws.send(JSON.stringify({ role: "ext", version: VERSION }));
    log("connected to daemon");
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    // Keep-alive: replying resets the service-worker idle timer.
    if (msg.type === "ping") {
      try { ws.send(JSON.stringify({ type: "pong" })); } catch (e) {}
      return;
    }
    if (typeof msg.id === "undefined" || !msg.action) return;

    const reply = { id: msg.id };
    try {
      reply.data = await handleCommand(msg.action, msg.params || {});
      reply.ok = true;
    } catch (e) {
      reply.ok = false;
      reply.error = e && e.message ? e.message : String(e);
    }
    try { ws.send(JSON.stringify(reply)); } catch (e) {}
  };

  ws.onclose = () => { scheduleReconnect(); };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

function scheduleReconnect() {
  setTimeout(connect, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
}

async function handleCommand(action, params) {
  if (action === "saved") {
    const tabId = await ensureInstagramTab();
    return await igRequest(tabId, params.max_id
      ? SAVED_FEED + "?max_id=" + encodeURIComponent(params.max_id) : SAVED_FEED, "GET");
  }
  if (action === "unsave") {
    if (!/^\d{5,25}$/.test(String(params.media_id || ""))) throw new Error("bad media id");
    const tabId = await ensureInstagramTab();
    return await igRequest(tabId, UNSAVE(params.media_id), "POST");
  }
  if (action === "release") {
    return { closed: await closeOwnedTab() };
  }
  if (action === "ping") {
    return { pong: true, version: VERSION };
  }
  throw new Error("unknown action: " + action);
}

// The tab this extension opened itself, if any: {id, used}. Kept in session
// storage so it survives the service worker being put to sleep.
//
// Until the extension is reloaded after an update, the browser still applies
// the old manifest, which has no "storage" permission. Then this falls back to
// a plain variable, so a sync keeps working either way.
const session = chrome.storage && chrome.storage.session;
let ownedInMemory = null;

async function getOwned() {
  if (!session) return ownedInMemory;
  const got = await session.get("ownedTab");
  return got.ownedTab || null;
}

async function setOwned(id) {
  const owned = id == null ? null : { id, used: Date.now() };
  if (!session) ownedInMemory = owned;
  else if (owned) await session.set({ ownedTab: owned });
  else await session.remove("ownedTab");
}

// Close the tab we opened. Returns whether there was one to close.
async function closeOwnedTab() {
  const owned = await getOwned();
  if (!owned) return false;
  await setOwned(null);
  try {
    await chrome.tabs.remove(owned.id);
    return true;
  } catch (e) {
    return false; // already closed by hand
  }
}

async function closeOwnedTabIfIdle() {
  const owned = await getOwned();
  if (owned && Date.now() - owned.used > OWNED_TAB_IDLE_MS) await closeOwnedTab();
}

// Find (or open, in the background) an instagram.com tab and return its id.
async function ensureInstagramTab() {
  const tabs = await chrome.tabs.query({ url: "https://www.instagram.com/*" });
  const owned = await getOwned();
  if (owned && tabs.some((t) => t.id === owned.id)) await setOwned(owned.id); // still in use
  const ready = tabs.find((t) => t.status === "complete");
  if (ready) return ready.id;
  if (tabs.length > 0 && tabs[0].id != null) {
    await waitForTabComplete(tabs[0].id);
    return tabs[0].id;
  }
  const created = await chrome.tabs.create({
    url: "https://www.instagram.com/",
    active: false,
  });
  await setOwned(created.id); // ours to close again
  await waitForTabComplete(created.id);
  return created.id;
}

// If you start using the tab we opened, it is yours: stop tracking it.
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const owned = await getOwned();
  if (owned && owned.id === tabId) await setOwned(null);
});

function waitForTabComplete(tabId, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    let done = false;
    const finish = (fn, arg) => {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(timer);
      fn(arg);
    };
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") finish(resolve);
    };
    const timer = setTimeout(
      () => finish(reject, new Error("timed out loading instagram.com")), timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        return finish(reject, new Error(chrome.runtime.lastError.message));
      }
      if (tab && tab.status === "complete") finish(resolve);
    });
  });
}

// One request to Instagram's own web API. Runs in the page's ISOLATED
// world: same origin as instagram.com, so the session cookies ride along
// exactly as they do for the site's own JavaScript.
async function igRequest(tabId, url, method) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    args: [url, method, IG_APP_ID],
    func: async (url, method, appId) => {
      const out = { page_url: location.href, logged_in: /(?:^|;\s*)ds_user_id=\d+/.test(document.cookie) };
      const headers = { "X-IG-App-ID": appId, "X-Requested-With": "XMLHttpRequest" };
      const csrf = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
      if (csrf) headers["X-CSRFToken"] = csrf[1];
      try {
        const claim = sessionStorage.getItem("www-claim-v2");
        if (claim) headers["X-IG-WWW-Claim"] = claim;
      } catch (e) {}
      if (method === "POST") headers["Content-Type"] = "application/x-www-form-urlencoded";
      try {
        const res = await fetch(url, { method, headers, credentials: "include" });
        out.status = res.status;
        out.url = res.url;
        out.redirected = res.redirected;
        const text = await res.text();
        try {
          out.body = JSON.parse(text);
        } catch (e) {
          out.body = null;
          out.snippet = text.slice(0, 200);
        }
      } catch (e) {
        out.fetch_error = String(e);
      }
      return out;
    },
  });
  const result = results && results[0] ? results[0].result : null;
  if (!result) throw new Error("no result from the instagram.com tab");
  return result;
}

// Connect on install/startup; an alarm re-checks the socket so the worker
// finds the daemon again after either side restarts.
chrome.runtime.onInstalled.addListener(() => connect());
chrome.runtime.onStartup.addListener(() => connect());
chrome.alarms.create("magpie-bridge-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== "magpie-bridge-keepalive") return;
  connect();
  closeOwnedTabIfIdle();
});

connect();
