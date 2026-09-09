/*
 * KS4Web extension content script.
 *
 * Declared in the manifest at document_idle, so it is already listening when
 * a command arrives and costs nothing at command time. It stays SMALL on
 * purpose: the projection bundle it runs is 300 KB and is injected on demand
 * by the background script, so a page nobody reads never parses it.
 *
 * The two things this file does that matter:
 *
 * 1. `page.evaluate` runs a script from the bundle BY NAME. There is no eval
 *    here and no `unsafe-eval` in the manifest: the native host can ask for
 *    one of five scripts the extension shipped, and anything else is refused
 *    with the name it asked for. A wire that could carry source would be a
 *    remote-code-execution shape with a native messaging host on the other
 *    end of it.
 *
 * 2. `page.act` performs one action on one ref, and refuses when the element
 *    the ref names is gone. It never decides WHETHER to act; that decision
 *    was made in Python, at the same policy choke point every other lane
 *    goes through, before this message was sent.
 *
 * PASSWORD VALUES ARE NOT BLOCKED HERE, and that is the strong version
 * rather than the weak one. The reads run `extract.js`, which computes
 * `value_state: 'never-read'` for a secret field and never touches
 * `el.value` on one, so there is no filter to forget to apply and no second
 * implementation to drift. The census below reports that the fields EXIST.
 */

(function () {
  if (window.__ks4webContentLoaded) {
    return;
  }
  window.__ks4webContentLoaded = true;

  const BUNDLE_KEY = "__ks4webScripts";
  const STATE_KEY = "__ks4webState";

  /*
   * Password values are never read. The reads run the projection, which
   * computes `value_state: 'never-read'` for a secret field; this census is
   * the cheap structural answer for `page.read`, which returns innerText and
   * cannot contain an input value at all.
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

  // ---------------------------------------------------------- the projection

  function scripts() {
    return window[BUNDLE_KEY] || null;
  }

  function state() {
    return window[STATE_KEY] || null;
  }

  /*
   * Run one bundled script. `params.script` is a NAME, never source.
   *
   * The absence of the bundle is its own error rather than an exception with
   * a stack in it: the background script is what injects the bundle, and the
   * only way to be here without one is an injection that failed, which is a
   * fact the Python side can act on (re-inject and retry) instead of a
   * message it can only print.
   */
  function runScript(params) {
    const table = scripts();
    if (!table) {
      return { error: { code: "BUNDLE_MISSING", message: "the projection bundle is not in this document" } };
    }
    const name = params && params.script;
    const fn = Object.prototype.hasOwnProperty.call(table, name) ? table[name] : null;
    if (typeof fn !== "function") {
      return {
        error: {
          code: "UNKNOWN_SCRIPT",
          message: "[COPY PENDING] unknown projection script text: " + String(name),
        },
      };
    }
    const t0 = performance.now();
    const result = fn((params && params.arg) || {});
    return {
      result: {
        data: result,
        readMs: Math.round((performance.now() - t0) * 1000) / 1000,
        url: location.href,
        webdriver: navigator.webdriver === true,
      },
    };
  }

  // --------------------------------------------------------------- the acting

  function elementFor(ref) {
    const st = state();
    if (!st) {
      return null;
    }
    return st.refs.get(ref) || null;
  }

  /*
   * The native property-descriptor write. React, Vue and Angular all track a
   * control's value through the prototype setter, so assigning `el.value`
   * directly leaves the framework's own copy stale and the page behaves as
   * though nothing was typed. Calling the prototype setter and then firing
   * the two events is the pattern every serious form filler converges on.
   */
  function setValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : (el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype);
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setEditable(el, value) {
    el.focus();
    el.textContent = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /*
   * One action on one element. The decision to act was made in Python at the
   * policy choke point; what happens here is the dispatch and the honest
   * account of what the page did afterwards.
   */
  function act(params) {
    const ref = params && params.ref;
    const el = elementFor(ref);
    if (!el) {
      return { error: { code: "STALE_REF", message: "[COPY PENDING] stale ref text: " + String(ref) } };
    }
    if (!el.isConnected) {
      return { error: { code: "STALE_REF", message: "[COPY PENDING] detached element text: " + String(ref) } };
    }
    const action = params.action;
    const before = { url: location.href, title: document.title };
    try {
      if (action === "click") {
        el.click();
      } else if (action === "focus") {
        el.focus();
      } else if (action === "type" || action === "fill") {
        if (el.isContentEditable) {
          setEditable(el, String(params.value === undefined ? "" : params.value));
        } else {
          el.focus();
          setValue(el, String(params.value === undefined ? "" : params.value));
        }
      } else if (action === "check") {
        if (el.checked !== !!params.value) {
          el.click();
        }
      } else if (action === "select") {
        setValue(el, String(params.value === undefined ? "" : params.value));
      } else if (action === "submit") {
        // requestSubmit runs validation and fires the submit event, which is
        // what a real button press does; form.submit() skips both. The
        // fallback is for a form the page has no submitter on.
        const form = el.form || (el.tagName === "FORM" ? el : el.closest("form"));
        if (!form) {
          return { error: { code: "NO_FORM", message: "[COPY PENDING] no form text: " + String(ref) } };
        }
        // THE SUBMITTER IS ONLY EVER A SUBMIT CONTROL. requestSubmit throws
        // outright on anything else, and the element this act arrives on is
        // usually the FIELD rather than the button: typing into a search box
        // and pressing Enter is implicit form submission, which has no
        // submitter at all. Passing the field would turn the oldest submit
        // path on the web into a TypeError.
        const type = (el.type || "").toLowerCase();
        const isSubmitter = el !== form
          && (type === "submit" || type === "image"
              || (el.tagName === "BUTTON" && type !== "button" && type !== "reset"));
        if (typeof form.requestSubmit === "function") {
          form.requestSubmit(isSubmitter ? el : undefined);
        } else {
          form.submit();
        }
      } else {
        return {
          error: { code: "UNKNOWN_ACTION", message: "[COPY PENDING] unknown action text: " + String(action) },
        };
      }
    } catch (err) {
      return { error: { code: "EXECUTION_FAILED", message: String((err && err.message) || err) } };
    }
    return {
      result: {
        action: action,
        ref: ref,
        before: before,
        after: { url: location.href, title: document.title },
        // isTrusted is false for every event dispatched here and this build
        // says so rather than implying otherwise. The prior-art research
        // found no major detector gating on it alone; that is a claim about
        // the field, not a guarantee, and reporting it keeps it checkable.
        isTrusted: false,
        webdriver: navigator.webdriver === true,
      },
    };
  }

  // ------------------------------------------------------------- the masking

  const MASK_STYLE_ID = "__ks4web_mask";

  /*
   * Paint over the secret and payment fields before a capture, and count
   * them so the Python side can fail closed.
   *
   * The SELECTOR COMES FROM PYTHON and is `capture.MASK_CSS`, the same
   * string the Playwright lane hands its own masking. It is a selector, not
   * code, so nothing here compiles anything; what it buys is that the fields
   * a screenshot hides cannot drift between the two lanes.
   *
   * The mask is a black box drawn by CSS rather than a value the script
   * reads and blanks. Reading the value to blank it would be the one thing
   * this whole surface promises not to do.
   */
  function mask(params) {
    const selector = params && params.selector;
    if (typeof selector !== "string" || !selector) {
      return { error: { code: "BAD_MESSAGE", message: "[COPY PENDING] mask selector text" } };
    }
    let count = 0;
    try {
      count = document.querySelectorAll(selector).length;
    } catch (err) {
      return { error: { code: "BAD_MESSAGE", message: String((err && err.message) || err) } };
    }
    unmask();
    if (count) {
      const style = document.createElement("style");
      style.id = MASK_STYLE_ID;
      style.textContent = selector
        + "{color:transparent !important;background:#000 !important;"
        + "text-shadow:none !important;caret-color:transparent !important;"
        + "-webkit-text-security:disc !important;}";
      (document.head || document.documentElement).appendChild(style);
    }
    return { result: { masked: count, selector: selector } };
  }

  function unmask() {
    const existing = document.getElementById(MASK_STYLE_ID);
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }
    return { result: { masked: 0 } };
  }

  /*
   * Whether this document is ready to be read, and why not when it is not.
   * The SPA answer, in the one place both the read path and the navigation
   * path can ask for it.
   */
  function readiness() {
    return {
      readyState: document.readyState,
      url: location.href,
      title: document.title,
      hasBody: !!document.body,
      bundle: !!scripts(),
    };
  }

  browser.runtime.onMessage.addListener(function (msg) {
    try {
      if (!msg || typeof msg !== "object") {
        return Promise.resolve({ error: { code: "BAD_MESSAGE", message: "[COPY PENDING] malformed message text" } });
      }
      if (msg.method === "page.read") {
        return Promise.resolve({ result: readPage() });
      }
      if (msg.method === "page.evaluate") {
        return Promise.resolve(runScript(msg.params || {}));
      }
      if (msg.method === "page.act") {
        return Promise.resolve(act(msg.params || {}));
      }
      if (msg.method === "page.ready") {
        return Promise.resolve({ result: readiness() });
      }
      if (msg.method === "page.mask") {
        return Promise.resolve(mask(msg.params || {}));
      }
      if (msg.method === "page.unmask") {
        return Promise.resolve(unmask());
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
