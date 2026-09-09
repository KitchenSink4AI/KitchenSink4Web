/*
 * The Chromium shim. LOADED ONLY IN THE MV3 BUILD.
 *
 * `background.js` and `content.js` were written against Firefox's `browser.*`
 * promise API and were proven against a real Firefox over three phases. The
 * cheapest way to break that would be to rewrite their call sites for Chrome.
 * So instead this file publishes a `browser` global on Chromium that answers
 * the calls those two files actually make, and Firefox never loads it at all.
 *
 * It handles exactly three differences, which is the whole list for the API
 * surface this extension uses:
 *
 * 1. THE GLOBAL. Chrome has `chrome`, Firefox has `browser`. Chrome's MV3
 *    APIs already return promises when no callback is passed, so most
 *    namespaces pass straight through untouched.
 *
 * 2. SCRIPT INJECTION. MV2's `tabs.executeScript(tabId, {file, frameId})`
 *    became MV3's `scripting.executeScript({target: {tabId, frameIds}, files})`.
 *    Different name, different shape, same act. Adapted below, with the MV2
 *    signature kept so the caller does not change.
 *
 * 3. THE MISSING REJECTION. Chrome's promise APIs reject, but a few paths
 *    resolve and leave the reason in `chrome.runtime.lastError` instead.
 *    `toFrameWaiting` in background.js recovers from exactly one such reason
 *    ("Receiving end does not exist") and it recovers by catching, so a
 *    lastError that never became a rejection would turn a recoverable
 *    condition into a silent wrong answer. `sendMessage` is wrapped to
 *    convert it.
 *
 * What this file deliberately does NOT do is paper over the MV3 service
 * worker lifecycle. That is a real behavioural difference, not a naming one,
 * and pretending otherwise in a shim would hide it. See the report.
 */

(function () {
  'use strict';

  // Firefox: already correct, nothing to do. This early return is what makes
  // the file safe to load anywhere, including a Firefox build that someday
  // lists it by mistake.
  if (typeof globalThis.browser !== "undefined" && globalThis.browser && globalThis.browser.runtime) {
    return;
  }

  const c = globalThis.chrome;
  if (!c || !c.runtime) {
    // No extension APIs at all. Nothing useful to publish, and a half-built
    // shim would fail later with a confusing name.
    return;
  }

  function lastErrorOf() {
    const err = c.runtime.lastError;
    return err ? new Error(err.message || String(err)) : null;
  }

  // `tabs.sendMessage`, MV2 signature, with lastError promoted to a rejection.
  function sendMessage(tabId, message, options) {
    return new Promise(function (resolve, reject) {
      try {
        c.tabs.sendMessage(tabId, message, options || {}, function (response) {
          const err = lastErrorOf();
          if (err) { reject(err); return; }
          resolve(response);
        });
      } catch (err) {
        reject(err);
      }
    });
  }

  // MV2's shape on the outside, MV3's `scripting` on the inside. `frameId`
  // is always supplied by our caller and is 0 for the top frame; the MV3 API
  // wants it in a list.
  function executeScript(tabId, details) {
    const target = { tabId: tabId };
    if (details && typeof details.frameId === "number") {
      target.frameIds = [details.frameId];
    }
    const injection = { target: target };
    if (details && details.file) {
      injection.files = [details.file];
    }
    return c.scripting.executeScript(injection);
  }

  const tabs = {
    get: function (tabId) { return c.tabs.get(tabId); },
    query: function (info) { return c.tabs.query(info); },
    update: function (tabId, props) { return c.tabs.update(tabId, props); },
    reload: function (tabId, props) { return c.tabs.reload(tabId, props); },
    goBack: function (tabId) { return c.tabs.goBack(tabId); },
    goForward: function (tabId) { return c.tabs.goForward(tabId); },
    captureVisibleTab: function (windowId, options) {
      return c.tabs.captureVisibleTab(windowId, options);
    },
    sendMessage: sendMessage,
    executeScript: executeScript,
    onRemoved: c.tabs.onRemoved,
  };

  globalThis.browser = {
    runtime: c.runtime,
    storage: c.storage,
    webNavigation: c.webNavigation,
    tabs: tabs,
  };
})();
