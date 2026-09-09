/*
 * KS4Web extension background script.
 *
 * Owns four things: the persistent native messaging port, the tab commands,
 * the in-browser half of the security posture, and the on-demand injection
 * of the projection bundle.
 *
 * The security posture here is DEFENCE IN DEPTH and nothing more. The
 * authority on whether an action may happen is the Python policy choke
 * point, which every Lane C tool goes through exactly as every Playwright
 * lane tool does. What is enforced here is the smaller set of claims the
 * browser is the only one in a position to make: that a command arrived for
 * an origin the session consented to, that commands are not arriving faster
 * than a human-driven session could produce them, and that every one of them
 * is written down.
 */

const NATIVE_HOST = "ks4web";

// The documented native-messaging ceiling is 1 MB app->extension and 4 GB
// extension->app. Phase 1 MEASURED this direction to 64 MB unchunked with no
// ceiling found, so chunking is a fallback rather than the plan: `maxChunk: 0`
// disables it and the default is a margin below the folklore number.
const DEFAULT_MAX_CHUNK = 768 * 1024;

// Past this many characters a reply is gzipped before it goes on the wire.
// Below it the compression costs more than it saves.
const COMPRESS_OVER = 64 * 1024;

// The rate limit, as a token bucket. A human driving a browser does not
// issue forty commands a second; a runaway agent loop does, and this is the
// only place in the system that can see the browser-side rate at all.
const RATE_CAPACITY = 40;
const RATE_REFILL_PER_S = 20;

// The audit ring. Every command and its target URL, oldest dropped first.
const AUDIT_MAX = 500;

let port = null;
let reconnectDelay = 250;
let bucket = RATE_CAPACITY;
let bucketAt = Date.now();

// Origins this session consented to, pushed from Python. `null` means the
// session has not configured the gate yet, and nothing page-facing runs
// until it has: an empty set and an unconfigured one are different states
// and only one of them is "allow nothing".
let consented = null;

// tabId:frameId strings whose document already holds the bundle. Cleared per
// frame on every committed navigation, because a new document has a new
// isolated world and a ref registry that no longer exists.
const injected = new Set();

const audit = [];

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
    // A dropped pipe means a new Python process on the next connect, and a
    // new process has consented to nothing. Keeping the old set would let a
    // second server inherit the first one's approvals.
    consented = null;
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

// ------------------------------------------------------------------ replying

async function gzipText(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  const buffer = await new Response(stream).arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  }
  return btoa(binary);
}

/*
 * Send a result back, gzipping it when it is large and splitting it across
 * chunk frames when it is still large after that. The receiver reassembles
 * the STRING and parses once, so a chunked reply and a whole one carry
 * byte-identical payloads.
 */
async function reply(id, result, params) {
  const maxChunk = params && params.maxChunk;
  const allowGzip = !(params && params.gzip === false);
  let text = JSON.stringify(result);
  let encoding = null;
  if (allowGzip && text.length >= COMPRESS_OVER) {
    try {
      const packed = await gzipText(text);
      // Only when it actually helps. A payload that is already compressed
      // (a data: URI full of PNG) comes out bigger, and shipping the bigger
      // one to be able to say the feature is on is not an optimisation.
      if (packed.length < text.length) {
        text = packed;
        encoding = "gzip+base64";
      }
    } catch (err) {
      encoding = null;
    }
  }
  const limit = maxChunk === 0 ? Infinity : (maxChunk || DEFAULT_MAX_CHUNK);
  if (encoding === null && text.length <= limit) {
    post({ id: id, result: result });
    return;
  }
  if (text.length <= limit) {
    post({ id: id, encoded: { encoding: encoding, data: text } });
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
        encoding: encoding,
      },
    });
  }
}

function replyError(id, code, message) {
  post({ id: id, error: { code: code, message: message } });
}

// ------------------------------------------------------------- the guardrails

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

function originOf(url) {
  try {
    return new URL(url).origin;
  } catch (err) {
    return null;
  }
}

/*
 * The per-domain consent gate. The Python ladder is the authority and asks
 * the human; this is the browser-side copy of the answer, so a command that
 * somehow reached the pipe for an origin nobody approved does not touch the
 * page. `*` is the wildcard a session sets when the human approved the lane
 * rather than a list.
 */
function consentRefusal(url) {
  if (consented === null) {
    return "[COPY PENDING] consent-not-configured refusal text";
  }
  if (consented.has("*")) {
    return null;
  }
  const origin = originOf(url);
  if (origin && consented.has(origin)) {
    return null;
  }
  return "[COPY PENDING] origin-not-consented refusal text: " + String(origin);
}

function rateRefusal() {
  const now = Date.now();
  bucket = Math.min(RATE_CAPACITY, bucket + ((now - bucketAt) / 1000) * RATE_REFILL_PER_S);
  bucketAt = now;
  if (bucket < 1) {
    return "[COPY PENDING] rate-limit refusal text";
  }
  bucket -= 1;
  return null;
}

function note(method, url, outcome) {
  audit.push({ at: Date.now(), method: method, url: url || null, outcome: outcome });
  while (audit.length > AUDIT_MAX) {
    audit.shift();
  }
  // Best effort and deliberately not awaited: the log is for a human reading
  // it later, and a storage write that fails must not fail the command.
  try {
    browser.storage.local.set({ ks4webAudit: audit.slice(-AUDIT_MAX) });
  } catch (err) {
    /* the in-memory ring is still the answer to audit.read */
  }
}

// --------------------------------------------------------------- tab plumbing

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

function frameKey(tabId, frameId) {
  return tabId + ":" + frameId;
}

async function ensureBundle(tabId, frameId) {
  const key = frameKey(tabId, frameId);
  if (injected.has(key)) {
    return false;
  }
  await browser.tabs.executeScript(tabId, {
    file: "/projection.bundle.js",
    frameId: frameId,
    runAt: "document_end",
  });
  injected.add(key);
  return true;
}

browser.webNavigation.onCommitted.addListener((details) => {
  injected.delete(frameKey(details.tabId, details.frameId));
});

// The SPA half. A history push does not commit a navigation and does not
// replace the document, so the bundle and the ref registry both survive it;
// what does NOT survive is the caller's belief about what is on the page.
// The event is relayed so the Python side can invalidate its refs, which is
// the same thing it does on a real navigation.
browser.webNavigation.onHistoryStateUpdated.addListener((details) => {
  post({
    event: "navigation",
    kind: "history",
    tabId: details.tabId,
    frameId: details.frameId,
    url: details.url,
  });
});

browser.tabs.onRemoved.addListener((tabId) => {
  for (const key of Array.from(injected)) {
    if (key.startsWith(tabId + ":")) {
      injected.delete(key);
    }
  }
});

/*
 * Send a message to ONE frame. frameId is always explicit, and the default is
 * the top frame: `all_frames` is true in the manifest, so every frame has a
 * listener, and a sendMessage without a frameId resolves with whichever one
 * answers first. A page with one ad iframe would return the ad.
 */
async function toFrame(tabId, frameId, message) {
  return await browser.tabs.sendMessage(tabId, message, { frameId: frameId });
}

/*
 * Everything that touches a page goes through here: the scheme refusal, the
 * consent gate, the rate limit, the bundle injection, and then the message.
 */
async function pageCommand(method, params) {
  const tab = await resolveTab(params);
  const frameId = typeof params.frameId === "number" ? params.frameId : 0;
  const refused = schemeRefusal(tab.url);
  if (refused) {
    note(method, tab.url, "refused:scheme");
    throw { code: "REFUSED_SCHEME", message: "[COPY PENDING] refusal text for scheme " + refused };
  }
  const denied = consentRefusal(tab.url);
  if (denied) {
    note(method, tab.url, "refused:consent");
    throw { code: "ORIGIN_NOT_CONSENTED", message: denied };
  }
  const throttled = rateRefusal();
  if (throttled) {
    note(method, tab.url, "refused:rate");
    throw { code: "RATE_LIMITED", message: throttled };
  }
  let injectedNow = false;
  if (method === "page.evaluate" || method === "page.act") {
    injectedNow = await ensureBundle(tab.id, frameId);
  }
  let sent = await toFrame(tab.id, frameId, { method: method, params: params });
  if (sent && sent.error && sent.error.code === "BUNDLE_MISSING" && !injectedNow) {
    // The frame kept its listener across a navigation the injection tracker
    // did not see. Re-inject once and retry; a second BUNDLE_MISSING is a
    // real failure and travels as one.
    injected.delete(frameKey(tab.id, frameId));
    await ensureBundle(tab.id, frameId);
    sent = await toFrame(tab.id, frameId, { method: method, params: params });
  }
  if (sent && sent.error) {
    note(method, tab.url, "error:" + sent.error.code);
    throw sent.error;
  }
  note(method, tab.url, "ok");
  sent.result.tabId = tab.id;
  sent.result.frameId = frameId;
  return sent.result;
}

/*
 * Navigation, and it waits for the load rather than returning the moment the
 * URL is set. `tabs.update` resolves immediately, so a caller that read the
 * page next would read the OLD document about a third of the time.
 */
async function navigate(params) {
  const tab = await resolveTab(params);
  const url = params.url;
  const refused = schemeRefusal(url);
  if (refused) {
    note("page.navigate", url, "refused:scheme");
    throw { code: "REFUSED_SCHEME", message: "[COPY PENDING] refusal text for scheme " + refused };
  }
  const denied = consentRefusal(url);
  if (denied) {
    note("page.navigate", url, "refused:consent");
    throw { code: "ORIGIN_NOT_CONSENTED", message: denied };
  }
  const throttled = rateRefusal();
  if (throttled) {
    note("page.navigate", url, "refused:rate");
    throw { code: "RATE_LIMITED", message: throttled };
  }
  const timeoutMs = params.timeoutMs || 30000;
  const waitUntil = params.waitUntil || "complete";
  const settled = new Promise((resolve) => {
    let done = false;
    const finish = (how) => {
      if (done) {
        return;
      }
      done = true;
      browser.webNavigation.onCompleted.removeListener(onCompleted);
      browser.webNavigation.onDOMContentLoaded.removeListener(onDom);
      clearTimeout(timer);
      resolve(how);
    };
    const onCompleted = (d) => {
      if (d.tabId === tab.id && d.frameId === 0) {
        finish("complete");
      }
    };
    const onDom = (d) => {
      if (d.tabId === tab.id && d.frameId === 0 && waitUntil === "domcontentloaded") {
        finish("domcontentloaded");
      }
    };
    const timer = setTimeout(() => finish("timeout"), timeoutMs);
    browser.webNavigation.onCompleted.addListener(onCompleted);
    browser.webNavigation.onDOMContentLoaded.addListener(onDom);
  });
  const t0 = Date.now();
  if (params.action === "reload") {
    await browser.tabs.reload(tab.id);
  } else if (params.action === "back") {
    await browser.tabs.goBack(tab.id);
  } else if (params.action === "forward") {
    await browser.tabs.goForward(tab.id);
  } else {
    await browser.tabs.update(tab.id, { url: url });
  }
  const how = await settled;
  injected.delete(frameKey(tab.id, 0));
  const after = await browser.tabs.get(tab.id);
  note("page.navigate", after.url, how === "timeout" ? "timeout" : "ok");
  return {
    tabId: tab.id,
    url: after.url,
    title: after.title,
    settled: how,
    elapsedMs: Date.now() - t0,
    // Stated rather than implied: an extension cannot see the HTTP status of
    // a top-level navigation without the webRequest machinery, and this
    // build does not ask for that permission. A caller that needs the status
    // has a lane that can give it one.
    status: null,
  };
}

async function screenshot(params) {
  const tab = await resolveTab(params);
  const denied = consentRefusal(tab.url);
  if (denied) {
    note("page.screenshot", tab.url, "refused:consent");
    throw { code: "ORIGIN_NOT_CONSENTED", message: denied };
  }
  const format = params.format === "jpeg" ? "jpeg" : "png";
  const options = { format: format };
  if (format === "jpeg" && typeof params.quality === "number") {
    options.quality = params.quality;
  }
  const dataUrl = await browser.tabs.captureVisibleTab(tab.windowId, options);
  note("page.screenshot", tab.url, "ok");
  const comma = dataUrl.indexOf(",");
  return {
    tabId: tab.id,
    url: tab.url,
    format: format,
    // The viewport and only the viewport. captureVisibleTab is what an
    // extension has; a full-page capture would be a scroll-and-stitch, and
    // stitching pixels and calling the result a screenshot of the page is a
    // claim this build does not make.
    scope: "viewport",
    base64: comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl,
  };
}

// ------------------------------------------------------------- the dispatcher

async function dispatch(method, params) {
  if (method === "bg.ping") {
    return {
      pong: true,
      host: NATIVE_HOST,
      extensionId: browser.runtime.id,
      at: Date.now(),
      consentConfigured: consented !== null,
    };
  }
  if (method === "bg.tabs") {
    const tabs = await browser.tabs.query({});
    return {
      tabs: tabs.map((t) => ({ id: t.id, url: t.url, title: t.title, active: t.active })),
    };
  }
  if (method === "bg.frames") {
    const tab = await resolveTab(params);
    const frames = await browser.webNavigation.getAllFrames({ tabId: tab.id });
    return {
      tabId: tab.id,
      frames: frames.map((f) => ({
        frameId: f.frameId,
        parentFrameId: f.parentFrameId,
        url: f.url,
      })),
    };
  }
  if (method === "consent.set") {
    // The Python ladder decided; this records the decision browser-side.
    // Replacing rather than merging is deliberate: a session that narrows
    // its consent has to be able to narrow it.
    consented = new Set(Array.isArray(params.origins) ? params.origins : []);
    note("consent.set", null, "ok");
    return { origins: Array.from(consented) };
  }
  if (method === "consent.get") {
    return { configured: consented !== null, origins: consented ? Array.from(consented) : [] };
  }
  if (method === "audit.read") {
    const limit = typeof params.limit === "number" ? params.limit : 100;
    return { entries: audit.slice(-limit), total: audit.length, capacity: AUDIT_MAX };
  }
  if (method === "page.navigate") {
    return await navigate(params);
  }
  if (method === "page.screenshot") {
    return await screenshot(params);
  }
  if (method === "page.read" || method === "page.evaluate" || method === "page.act"
      || method === "page.ready" || method === "diag.payload") {
    return await pageCommand(method, params);
  }
  throw { code: "UNKNOWN_METHOD", message: "[COPY PENDING] unknown method text: " + String(method) };
}

async function onNativeMessage(msg) {
  if (!msg || typeof msg !== "object" || typeof msg.id === "undefined") {
    return;
  }
  const id = msg.id;

  // A BATCH is one round trip for several commands. The steps run in order
  // and a failed step does not stop the ones after it: the caller asked for
  // several answers and gets several answers, each with its own outcome,
  // rather than a partial success it has to reconstruct.
  if (Array.isArray(msg.batch)) {
    const results = [];
    for (const step of msg.batch) {
      try {
        results.push({ result: await dispatch(step.method, step.params || {}) });
      } catch (err) {
        results.push({
          error: (err && err.code)
            ? err
            : { code: "EXECUTION_FAILED", message: String((err && err.message) || err) },
        });
      }
    }
    await reply(id, { batch: results }, msg.params || {});
    return;
  }

  try {
    const result = await dispatch(msg.method, msg.params || {});
    await reply(id, result, msg.params || {});
  } catch (err) {
    if (err && err.code) {
      replyError(id, err.code, err.message);
    } else {
      replyError(id, "EXECUTION_FAILED", String((err && err.message) || err));
    }
  }
}

connect();
