/*
 * KS4Web extension content script (Phase 1 proof of concept).
 *
 * Declared in the manifest at document_idle, so it is already listening when
 * a command arrives and costs nothing at command time. Phase 1 implements
 * one real read plus one diagnostic; the accessibility-tree walk, the
 * budget logic and the acting surface are Phase 2 and Phase 3.
 */

(function () {
  if (window.__ks4webContentLoaded) {
    return;
  }
  window.__ks4webContentLoaded = true;

  /*
   * Password values are never read. Phase 1 reads innerText, which cannot
   * contain an input's value at all, so the guarantee holds structurally
   * rather than by filtering. The field census below reports that the
   * elements EXIST and carries the placeholder value the spec fixes, which
   * is what a caller needs in order to decide what to do next.
   */
  function passwordCensus() {
    const fields = [];
    const nodes = document.querySelectorAll('input[type="password"]');
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      fields.push({
        name: el.getAttribute("name") || null,
        id: el.id || null,
        value: "[PROTECTED]",
      });
    }
    return fields;
  }

  function readPage() {
    const t0 = performance.now();
    const text = document.body ? document.body.innerText : "";
    return {
      url: location.href,
      title: document.title,
      text: text,
      chars: text.length,
      // The whole reason this architecture exists instead of a debugging
      // port. Reported on every read so the claim stays checkable rather
      // than remaining an argument made once in a design document.
      webdriver: navigator.webdriver === true,
      passwordFields: passwordCensus(),
      frame: window === window.top ? "top" : "child",
      readMs: Math.round((performance.now() - t0) * 1000) / 1000,
    };
  }

  /*
   * Returns a payload of a requested size. This exists to MEASURE the real
   * extension-to-native message ceiling on this platform, which the research
   * left as a documented number nobody had checked on Windows.
   */
  function diagPayload(params) {
    const bytes = Math.max(0, (params && params.bytes) || 0);
    const unit = "ks4web-diagnostic-payload-";
    let filler = "";
    while (filler.length < bytes) {
      filler += unit;
    }
    filler = filler.slice(0, bytes);
    return { bytes: filler.length, filler: filler, webdriver: navigator.webdriver === true };
  }

  browser.runtime.onMessage.addListener(function (msg) {
    try {
      if (!msg || typeof msg !== "object") {
        return Promise.resolve({ error: { code: "BAD_MESSAGE", message: "[COPY PENDING] malformed message text" } });
      }
      if (msg.method === "page.read") {
        return Promise.resolve({ result: readPage() });
      }
      if (msg.method === "diag.payload") {
        return Promise.resolve({ result: diagPayload(msg.params) });
      }
      return Promise.resolve({
        error: { code: "UNKNOWN_METHOD", message: "[COPY PENDING] unknown method text: " + String(msg.method) },
      });
    } catch (err) {
      return Promise.resolve({
        error: { code: "EXECUTION_FAILED", message: String((err && err.message) || err) },
      });
    }
  });
})();
