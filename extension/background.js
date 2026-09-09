/*
 * KS4Web extension background script (Phase 1 proof of concept).
 *
 * Owns exactly one thing: the persistent native messaging port. Firefox
 * launches the relay process on the first connectNative() call and keeps the
 * pipe open until we disconnect, which is the 100x-cheaper half of the
 * choice the performance research called out (connectNative vs a fresh
 * sendNativeMessage process per command).
 *
 * Commands arrive as JSON-RPC-shaped objects on that port. Anything that
 * needs a page goes out over browser.tabs.sendMessage to the pre-injected
 * content script; anything that does not is answered here, so a failing
 * round trip can be localised to a half.
 */

const NATIVE_HOST = "ks4web";

// The documented native-messaging ceiling is 1 MB app->extension and 4 GB
// extension->app, but the Browserpass bug (1573034) reported Windows
// failures well under 1 MB in the app->extension direction and was closed
// without a reproduction. We chunk OUR direction anyway at a margin below
// 1 MB, because the honest state of the evidence is "documented 4 GB,
// unverified in the field", and Phase 1 measures the real ceiling rather
// than trusting either number.
const DEFAULT_MAX_CHUNK = 768 * 1024;

let port = null;
let reconnectDelay = 250;

function connect() {
  try {
    port = browser.runtime.connectNative(NATIVE_HOST);
  } catch (err) {
    scheduleReconnect();
    return;
  }
  reconnectDelay = 250;
  port.onMessage.addListener(onNativeMessage);
  port.onDisconnect.addListener(() => {
    port = null;
    scheduleReconnect();
  });
}

function scheduleReconnect() {
  const delay = reconnectDelay;
  reconnectDelay = Math.min(reconnectDelay * 2, 10000);
  setTimeout(connect, delay);
}

function post(obj) {
  if (port) {
    port.postMessage(obj);
  }
}

/*
 * Send a result back, splitting it across chunk frames when the serialised
 * form is large. The receiver reassembles the STRING and parses once, so a
 * chunked response and a whole one carry byte-identical payloads.
 */
function reply(id, result, maxChunk) {
  const text = JSON.stringify(result);
  const limit = maxChunk === 0 ? Infinity : (maxChunk || DEFAULT_MAX_CHUNK);
  if (text.length <= limit) {
    post({ id: id, result: result });
    return;
  }
  const total = Math.ceil(text.length / limit);
  for (let seq = 0; seq < total; seq++) {
    post({
      id: id,
      chunk: {
        seq: seq,
        total: total,
        data: text.slice(seq * limit, (seq + 1) * limit),
      },
    });
  }
}

function replyError(id, code, message) {
  post({ id: id, error: { code: code, message: message } });
}

// about:, moz-extension: and the other privileged schemes are refused here
// rather than attempted and failed, because a content script is never
// injected into them and the resulting error would name the wrong cause.
const REFUSED_SCHEMES = ["about:", "moz-extension:", "chrome:", "resource:", "javascript:", "data:", "file:"];

function schemeRefusal(url) {
  const lowered = (url || "").toLowerCase();
  for (const scheme of REFUSED_SCHEMES) {
    if (lowered.startsWith(scheme)) {
      return scheme;
    }
  }
  return null;
}

async function resolveTab(params) {
  if (params && typeof params.tabId === "number") {
    return await browser.tabs.get(params.tabId);
  }
  const tabs = await browser.tabs.query({ active: true, lastFocusedWindow: true });
  if (tabs.length) {
    return tabs[0];
  }
  const any = await browser.tabs.query({ active: true });
  if (any.length) {
    return any[0];
  }
  throw new Error("no active tab");
}

async function onNativeMessage(msg) {
  if (!msg || typeof msg !== "object" || typeof msg.id === "undefined") {
    return;
  }
  const id = msg.id;
  const method = msg.method;
  const params = msg.params || {};
  const maxChunk = params.maxChunk;

  try {
    if (method === "bg.ping") {
      // Answered without touching a tab: proves the native messaging half
      // in isolation, so a page-side failure cannot be blamed on the pipe.
      reply(id, {
        pong: true,
        host: NATIVE_HOST,
        extensionId: browser.runtime.id,
        at: Date.now(),
      }, maxChunk);
      return;
    }

    if (method === "bg.tabs") {
      const tabs = await browser.tabs.query({});
      reply(id, {
        tabs: tabs.map((t) => ({ id: t.id, url: t.url, title: t.title, active: t.active })),
      }, maxChunk);
      return;
    }

    if (method === "page.read" || method === "diag.payload") {
      const tab = await resolveTab(params);
      const refused = schemeRefusal(tab.url);
      if (refused) {
        replyError(id, "REFUSED_SCHEME", "[COPY PENDING] refusal text for scheme " + refused);
        return;
      }
      // frameId is pinned to the top frame on purpose. all_frames is true in
      // the manifest, so every frame has a listener, and a sendMessage
      // without a frameId resolves with whichever one answers first: a page
      // with one ad iframe would return the ad. Reading child frames is a
      // Phase 2 command that names the frame it wants.
      const sent = await browser.tabs.sendMessage(tab.id, {
        method: method,
        params: params,
      }, { frameId: 0 });
      if (sent && sent.error) {
        replyError(id, sent.error.code, sent.error.message);
        return;
      }
      sent.result.tabId = tab.id;
      reply(id, sent.result, maxChunk);
      return;
    }

    replyError(id, "UNKNOWN_METHOD", "[COPY PENDING] unknown method text: " + String(method));
  } catch (err) {
    replyError(id, "EXECUTION_FAILED", String((err && err.message) || err));
  }
}

connect();
