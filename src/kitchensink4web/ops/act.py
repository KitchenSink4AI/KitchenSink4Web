"""The acting surface's shared machinery: resolve, approve, dispatch, verify.

DESIGN 3.5, 5.4, 5.7. Phase 4's tools (`click`, `type_text`, `fill_form`,
`press_keys`, `scroll`, `wait_for`) do NOT implement policy and do NOT invent
their own resolution. They DESCRIBE an action to this module, which:

1. **Resolves the target against the LIVE page, every time.** A stored session
   ref goes through the rebind ladder (`anchors/ladder.py`) run over a FRESH
   extraction, so a ref always acts on the element it resolves to right now or
   refuses. A page that swaps its "Continue" button for a "Delete everything"
   button between a read and a click cannot be clicked wrong: the fingerprint
   no longer matches and the ladder refuses rather than acting on first match.
   Live selectors (css, xpath, text, role+name, testid, coordinate, nth,
   describe) resolve deterministically and refuse with the candidate list when
   more than one matches, never acting on first match.

2. **Routes every mutating action through the ONE policy choke point**
   (`policy/engine.approve`): read-only grade, credential blindness, origin
   policy, 429 backoff, loop detection, the budget charge, and the confirmation
   gate last. Phase 4 wires no MRTR round-trip, so a gated class (form submit,
   payment) FAILS CLOSED: the gate asks and nothing executes until a human
   answers through a channel this build does not yet carry. That is the design.

3. **Dispatches TRUSTED input through the driver, never synthesised DOM
   events.** Modern React handlers check `event.isTrusted` and silently no-op on
   a synthetic click (corpus B's `trusted-btn`), so a JS-synthesised click is
   the exact silent-false-success this product argues against. Playwright's
   input path dispatches real trusted input, which is why the acting tools go
   through it and never through `page.evaluate` click synthesis.

4. **Verifies the OUTCOME** (DESIGN 5.7). Every action reports what actually
   changed: navigation, focus, the target's own state, or a DOM mutation. An
   action Playwright could not land (an overlay intercepting the point, a
   target that never stops moving) raises an honest refusal naming a recovery.
   An action that landed but changed nothing observable returns
   `effect: "none-observed"` WITH a warning. Nothing returns a bare ok.

This module imports from `policy` and `anchors` and `projection`; it is `ops`,
so that direction is allowed. It never imports playwright at module scope: it
takes page-like handles the engine already holds.
"""

from __future__ import annotations

from ..anchors import Outcome, ladder
from ..errors import (AmbiguousLocation, BadParams, ModalBlocked, StaleAnchor,
                      TargetChanged, TargetNotFound, Timeout)
from ..policy import credentials
from ..projection import extract

# --------------------------------------------------------------- selectors

#: Location grammar (DESIGN 9). Exactly ONE selector group per call; the
#: role-plus-name pair is one group. `shadow` and `exact` are modifiers, not
#: selectors, so they may ride alongside the one selector.
#:
#: AUDIT 2026-09-06 (field log 2 item 1; confirmed independently by the shadow
#: spike the same day) found that `frame` and `shadow` were both DEAD grammar:
#: `selector_of` stripped them and nothing anywhere read them, so a caller who
#: wrote one got a silent no-op instead of a refusal. The traversal build the
#: same day resolved both, in opposite directions.
#:
#: `shadow` is now REAL. The resolver reaches into open shadow roots by
#: default, and `shadow: False` turns that off for a call, which is the escape
#: hatch on a page where piercing is expensive or ambiguous. Closed roots stay
#: unreachable whatever the modifier says.
#:
#: `frame` is GONE. Reaching into an iframe is not the same machinery: the
#: resolver runs in ONE execution context, and a frame has its own, so
#: supporting it means routing every branch through the driver's frame layer
#: rather than reusing the shadow sweep. It was not free, so it is not
#: pretended: `{'frame': ...}` now REFUSES with the selector list instead of
#: being stripped, because dead grammar that silently strips is worse than an
#: honest absence.
_LADDER_KEYS = ("ref", "region", "form", "table")
_LIVE_KEYS = ("css", "xpath", "testid", "coordinate", "nth", "describe",
              "text", "anchor")
_MODIFIERS = ("shadow", "exact")


def selector_of(location: dict | None) -> tuple[str, object]:
    """Return the one selector group in a location object, or refuse.

    Inherited house rule (DESIGN 9): every positional call carries exactly one
    selector, and multiple matches REFUSE with every candidate rather than
    acting on the first. Two selectors at once, or none, is a `BAD_PARAMS`."""
    if not location or not isinstance(location, dict):
        raise BadParams(
            "this action needs a location: a ref from a read, or a selector "
            "such as {'css': ...}, {'text': ...}, {'role': ..., 'name': ...}, "
            "{'testid': ...}, or {'coordinate': {'x': .., 'y': ..}}.")
    present = [k for k in location
               if k not in _MODIFIERS and location.get(k) not in (None, "")]
    # role+name is one selector group.
    groups: list[str] = []
    if "role" in present or "name" in present:
        groups.append("role_name")
        present = [k for k in present if k not in ("role", "name")]
    for key in present:
        if key in _LADDER_KEYS:
            groups.append("ref")
        elif key in _LIVE_KEYS:
            groups.append(key)
        elif key == "frame":
            raise BadParams(
                "there is no 'frame' modifier. It was accepted and silently "
                "ignored until 2026-09-06; nothing in this build reaches "
                "into an iframe, so the key refuses now rather than looking "
                "like it worked. Read the page: the completeness block lists "
                "every iframe it found and says which are same-origin.")
        else:
            raise BadParams(
                f"location key {key!r} is not a selector. The selectors are "
                f"ref/region/form/table, css, xpath, text, role+name, testid, "
                f"nth, describe, coordinate; shadow/exact are modifiers.")
    groups = list(dict.fromkeys(groups))
    if len(groups) != 1:
        raise BadParams(
            f"a location carries exactly one selector; this one carries "
            f"{sorted(groups) or 'none'}. Two selectors at once are refused "
            f"rather than resolved by precedence, because guessing which one "
            f"you meant is how the wrong element gets acted on.")
    group = groups[0]
    if group == "ref":
        key = next(k for k in _LADDER_KEYS if location.get(k))
        return "ref", location[key]
    if group == "role_name":
        return "role_name", location
    return group, location[group]


# ---------------------------------------------------------- the live resolver

#: One in-page resolver for every selector the rebind ladder does not own. It
#: refuses ambiguity (more than one visible match) with the candidate list and
#: returns nearest misses on zero, so a miss is a one-turn recovery. It mints a
#: ref into the same `window.__ks4web_refs` map the projection uses, so a
#: resolved element is reached exactly the way a read-minted ref is.
_RESOLVE_JS = r"""
(opts) => {
  const loc = opts.location || {};
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };
  const map = (window.__ks4web_refs instanceof Map)
    ? window.__ks4web_refs : (window.__ks4web_refs = new Map());
  // Open-shadow-root targeting (2026-09-06). Default ON, so an element the
  // page view can SEE is an element this resolver can reach; `shadow: false`
  // in the location opts out. The root list is built once and reused by every
  // selector branch below.
  // Built LAZILY: discovering roots costs a document-wide sweep, and the
  // commonest resolution by far is `loc.ref`, which reads the map and queries
  // nothing. The acting path pays for this only when it actually searches.
  const SHADOW_ON = !(loc && loc.shadow === false);
  let rootList = null;
  function roots() {
    if (rootList) return rootList;
    rootList = [];
    if (SHADOW_ON) {
      (function sweep(root) {
        for (const el of root.querySelectorAll('*')) {
          if (el.shadowRoot) { rootList.push(el.shadowRoot); sweep(el.shadowRoot); }
        }
      })(document);
    }
    return rootList;
  }
  function queryAll(sel) {
    const out = Array.from(document.querySelectorAll(sel));
    for (const root of roots()) for (const el of root.querySelectorAll(sel)) out.push(el);
    return out;
  }
  // THE SHADOW BOUNDARY HOP: the top child of a shadow root has
  // `parentElement === null`, so a plain climb sees no hidden ancestor and
  // lets content under a display:none host through the visible filter. It
  // runs unconditionally, because a ref minted anywhere can arrive here.
  function up(n) {
    if (!n) return null;
    if (n.parentElement) return n.parentElement;
    const r = n.getRootNode && n.getRootNode();
    return (r && r.host) ? r.host : null;
  }
  function byId(el, id) {
    const r = el.getRootNode ? el.getRootNode() : document;
    if (r && typeof r.getElementById === 'function') return r.getElementById(id);
    return document.getElementById(id);
  }
  const styleCache = new Map();
  const cs = (el) => { let v = styleCache.get(el); if (v === undefined) { v = getComputedStyle(el); styleCache.set(el, v); } return v; };
  function hiddenAnywhere(el) {
    for (let n = el; n && n !== document.documentElement; n = up(n)) {
      if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return true;
      if (n.hasAttribute && n.hasAttribute('hidden')) return true;
      const s = cs(n);
      if (s.display === 'none' || s.visibility === 'hidden') return true;
      if (parseFloat(s.opacity) === 0) return true;
    }
    return false;
  }
  const TAG_ROLE = { A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox',
    SUMMARY: 'button', OPTION: 'option', IMG: 'img', TABLE: 'table' };
  const INPUT_ROLE = { checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button',
    reset: 'button', image: 'button', range: 'slider', file: 'file-input', search: 'searchbox',
    email: 'textbox', password: 'textbox', text: 'textbox', tel: 'textbox', url: 'textbox', number: 'spinbutton' };
  function roleOf(el) {
    const ex = el.getAttribute && el.getAttribute('role');
    if (ex) return ex.trim().split(/\s+/)[0];
    if (el.tagName === 'INPUT') return INPUT_ROLE[(el.type || 'text').toLowerCase()] || 'textbox';
    if (el.tagName === 'A') return el.hasAttribute('href') ? 'link' : 'generic';
    if (/^H[1-6]$/.test(el.tagName)) return 'heading';
    return TAG_ROLE[el.tagName] || 'generic';
  }
  const NAME_FROM_CONTENT = new Set(['button', 'link', 'heading', 'tab', 'menuitem',
    'option', 'checkbox', 'radio', 'switch', 'cell', 'columnheader', 'rowheader', 'gridcell', 'treeitem']);
  function nameOf(el, role) {
    const al = squash(el.getAttribute && el.getAttribute('aria-label'));
    if (al) return al;
    const lb = el.getAttribute && el.getAttribute('aria-labelledby');
    if (lb) { const t = byId(el, lb.trim().split(/\s+/)[0]); if (t) { const s = squash(t.textContent); if (s) return s; } }
    try { if (el.labels && el.labels.length) { const s = squash(Array.from(el.labels).map(l => l.textContent).join(' ')); if (s) return s; } } catch (e) {}
    if (el.tagName === 'INPUT') {
      const type = (el.type || '').toLowerCase();
      if ((type === 'submit' || type === 'button' || type === 'reset') && typeof el.value === 'string') return squash(el.value);
      const ph = el.getAttribute('placeholder'); if (squash(ph)) return squash(ph);
      return '';
    }
    if (el.tagName === 'IMG') return squash(el.getAttribute('alt'));
    if (NAME_FROM_CONTENT.has(role)) return squash(el.textContent);
    return squash(el.getAttribute && el.getAttribute('title'));
  }
  function pathOf(el) {
    if (el.tagName !== 'A') return null;
    try { const u = new URL(el.href, location.href);
      return u.origin !== location.origin ? u.origin + u.pathname : (u.pathname + u.search + u.hash); }
    catch (e) { return el.getAttribute('href'); }
  }
  const INTERACTIVE = 'a[href],button,input,select,textarea,summary,[role],[onclick],[tabindex]:not([tabindex="-1"])';

  let cands = [], how = '';
  try {
    if (loc.ref) { const el = map.get(loc.ref); cands = (el && el.isConnected) ? [el] : []; how = 'ref'; }
    else if (loc.css) { cands = queryAll(loc.css); how = 'css'; }
    else if (loc.xpath) {
      // The one selector that stays in the light DOM: `document.evaluate` has
      // no defined behaviour across a shadow boundary.
      const it = document.evaluate(loc.xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      for (let i = 0; i < it.snapshotLength; i++) { const n = it.snapshotItem(i); if (n.nodeType === 1) cands.push(n); }
      how = 'xpath';
    }
    else if (loc.testid) { cands = queryAll('[data-testid]').filter(e => e.getAttribute('data-testid') === String(loc.testid)); how = 'testid'; }
    else if (loc.coordinate) {
      // A point over a component hits the HOST, and clicking the host is not
      // clicking the control the user pointed at. Each open root gets asked
      // the same question until the answer stops changing.
      let el = document.elementFromPoint(loc.coordinate.x, loc.coordinate.y);
      for (let i = 0; el && el.shadowRoot && i < 32; i++) {
        const inner = el.shadowRoot.elementFromPoint(loc.coordinate.x, loc.coordinate.y);
        if (!inner || inner === el) break;
        el = inner;
      }
      cands = el ? [el] : []; how = 'coordinate';
    }
    else if (loc.nth) {
      const all = queryAll(INTERACTIVE).filter(e => roleOf(e) === loc.nth.role);
      const el = all[loc.nth.index]; cands = el ? [el] : []; how = 'nth';
    }
    else if (loc.role || loc.name) {
      const wantRole = loc.role ? String(loc.role).toLowerCase() : null;
      const wantName = loc.name ? String(loc.name).toLowerCase() : null;
      cands = queryAll(INTERACTIVE).filter(el => {
        const r = roleOf(el); if (wantRole && r !== wantRole) return false;
        if (wantName) { const nm = nameOf(el, r).toLowerCase(); return loc.exact ? nm === wantName : nm.indexOf(wantName) >= 0; }
        return true;
      });
      how = 'role+name';
    }
    else if (loc.text) {
      // `text` means visible text, not just the accessible name: a <div
      // onclick> button (corpus B's `divbtn`) has no accessible name at all,
      // and only its text and its handler give it away. So the haystack is
      // the accessible name PLUS the element's own bounded textContent.
      const needle = String(loc.text).toLowerCase();
      cands = queryAll(INTERACTIVE).filter(el => {
        const nm = nameOf(el, roleOf(el)).toLowerCase();
        const tx = squash(el.textContent).slice(0, 200).toLowerCase();
        return loc.exact ? (nm === needle || tx === needle)
          : (nm.indexOf(needle) >= 0 || tx.indexOf(needle) >= 0);
      });
      how = 'text';
    }
    else if (loc.describe) {
      const words = String(loc.describe).toLowerCase().split(/\s+/).filter(Boolean);
      const scored = [];
      for (const el of queryAll(INTERACTIVE)) {
        const r = roleOf(el);
        const hay = (nameOf(el, r) + ' ' + r + ' ' + (el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('title') || '')).toLowerCase();
        let sc = 0; for (const w of words) if (hay.indexOf(w) >= 0) sc++;
        if (sc) scored.push([sc, el]);
      }
      const best = scored.length ? Math.max.apply(null, scored.map(s => s[0])) : 0;
      cands = scored.filter(s => s[0] === best).map(s => s[1]);
      how = 'describe';
    }
  } catch (e) { return { error: String(e && e.message || e), how: how }; }

  // Visible only, except a coordinate hit which is a point on the page.
  if (how !== 'coordinate') cands = cands.filter(el => el && el.nodeType === 1 && !hiddenAnywhere(el));
  const uniq = []; const seen = new Set();
  for (const el of cands) { if (!seen.has(el)) { seen.add(el); uniq.push(el); } }

  function describe(el) {
    const r = roleOf(el);
    // Fall back to the element's own bounded text when it has no accessible
    // name, so a <div onclick> candidate reads as its label rather than as
    // "(unnamed)" in an ambiguity refusal.
    let nm = nameOf(el, r);
    if (!nm) nm = squash(el.textContent).slice(0, 80);
    return { role: r, name: clip(nm, 80), path: pathOf(el) };
  }

  if (uniq.length === 1) {
    const el = uniq[0];
    const ref = 'x' + (window.__ks4web_seq = (window.__ks4web_seq || 0) + 1);
    map.set(ref, el);
    const d = describe(el);
    const r = d.role;
    const formEl = el.form || el.closest('form');
    const inForm = !!formEl;
    // Effective submission type, the SAME rule the extractor applies (C1):
    // a <button> with a missing or invalid type is a submit button per the
    // HTML spec ('button'/'reset' opt out), with the default-submit case
    // scoped to buttons inside a form. Reading only the raw attribute here
    // left a typeless in-form button unclassified on the live path.
    let type = '';
    if (el.tagName === 'INPUT') {
      type = (el.type || 'text').toLowerCase();
    } else if (el.tagName === 'BUTTON') {
      const rawType = (el.getAttribute('type') || '').trim().toLowerCase();
      if (rawType === 'button' || rawType === 'reset') type = rawType;
      else if (rawType === 'submit') type = 'submit';
      else type = inForm ? 'submit' : rawType;
    }
    const ac = (el.getAttribute && el.getAttribute('autocomplete') || '').toLowerCase();
    // The landmark climb, a compact mirror of the extractor's, so a
    // live-resolved element's anchor registers under the SAME keys a read
    // would give it and the session map hands back the same ref for the
    // same element whichever way it was reached.
    const LM_TAG = { HEADER: 'banner', NAV: 'navigation', MAIN: 'main',
      ASIDE: 'complementary', FOOTER: 'contentinfo', FORM: 'form',
      SECTION: 'region', DIALOG: 'dialog' };
    const LM_ROLE = new Set(['banner', 'navigation', 'main', 'complementary',
      'contentinfo', 'form', 'region', 'search', 'dialog', 'alertdialog',
      'tablist']);
    function lmFrom(n) {
      if (!n) return { kind: 'document', label: '' };
      const explicit = (n.getAttribute && n.getAttribute('role') || '')
        .trim().split(/\s+/)[0];
      const kind = (explicit && LM_ROLE.has(explicit)) ? explicit
        : LM_TAG[n.tagName];
      if (kind) {
        const label = squash(n.getAttribute('aria-label'))
          || squash(n.getAttribute('name'))
          || (n.getAttribute('aria-labelledby')
              ? squash((byId(n,
                  n.getAttribute('aria-labelledby').split(/\s+/)[0])
                  || {}).textContent)
              : '');
        if (!(n.tagName === 'SECTION' && !label)) {
          return { kind: kind, label: label };
        }
      }
      return lmFrom(up(n));
    }
    const lm = lmFrom(up(el));
    const pageKey = location.origin + location.pathname + location.hash;
    return { count: 1, how: how, ref: ref, role: r, name: d.name, path: d.path,
      tag: el.tagName, type: type, autocomplete: ac, secret: (type === 'password'),
      in_form: inForm, form_action: formEl ? (formEl.getAttribute('action') || '') : '',
      page_key: pageKey,
      anchor: { page_key: pageKey, role: r, name: d.name,
        landmark: lm.kind, landmark_label: lm.label,
        attr_id: el.id || '',
        attr_testid: (el.getAttribute && el.getAttribute('data-testid')) || '',
        attr_name: (el.getAttribute && el.getAttribute('name')) || '' } };
  }
  if (uniq.length > 1) return { count: uniq.length, how: how, candidates: uniq.slice(0, 12).map(describe) };

  // Zero: nearest misses by name, so a miss is a one-turn recovery.
  const near = [];
  if (loc.text || loc.name || loc.describe || loc.role) {
    const needle = String(loc.text || loc.name || loc.describe || '').toLowerCase();
    const seenN = new Set();
    for (const el of queryAll(INTERACTIVE)) {
      const r = roleOf(el); const nm = nameOf(el, r); if (!nm || seenN.has(nm)) continue;
      let sc = 0; for (const w of needle.split(/\s+/)) if (w && nm.toLowerCase().indexOf(w) >= 0) sc++;
      if (sc) { seenN.add(nm); near.push({ role: r, name: clip(nm, 60), score: sc }); }
      if (near.length > 60) break;
    }
    near.sort((a, b) => b.score - a.score); near.length = Math.min(near.length, 6);
  }
  return { count: 0, how: how, nearest: near };
}
"""

#: Capture the page's observable state around an action, so the OUTCOME can be
#: verified rather than assumed (DESIGN 5.7). A MutationObserver catches a DOM
#: change even where nothing else moves; url, activeElement, and the target's
#: own state (value / checked / aria-expanded) catch the rest.
_OBSERVE_JS = r"""
(opts) => {
  const map = window.__ks4web_refs instanceof Map ? window.__ks4web_refs : null;
  const el = (map && opts.ref) ? map.get(opts.ref) : null;
  window.__ks4web_act = window.__ks4web_act || {};
  const token = 'w' + (window.__ks4web_actseq = (window.__ks4web_actseq || 0) + 1);
  const rec = { mutated: false };
  try {
    rec.obs = new MutationObserver(() => { rec.mutated = true; });
    rec.obs.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  } catch (e) {}
  window.__ks4web_act[token] = rec;
  function sig(node) { if (!node || node === document.body || node === document.documentElement) return '(body)';
    const id = node.id ? '#' + node.id : ''; const nm = (node.getAttribute && node.getAttribute('aria-label')) || (node.textContent || '').slice(0, 30);
    return (node.tagName || '?') + id + '|' + (nm || '').replace(/\s+/g, ' ').trim(); }
  const t = el ? { value: ('value' in el) ? String(el.value).slice(0, 200) : null,
    checked: (typeof el.checked === 'boolean') ? el.checked : null,
    expanded: el.getAttribute ? el.getAttribute('aria-expanded') : null,
    focused: document.activeElement === el } : null;
  return { token: token, url: location.href, active: sig(document.activeElement), target: t };
}
"""

_AFTER_JS = r"""
(opts) => {
  const store = window.__ks4web_act || {};
  const rec = store[opts.token]; let mutated = false;
  if (rec) { mutated = !!rec.mutated; try { rec.obs && rec.obs.disconnect(); } catch (e) {} delete store[opts.token]; }
  const map = window.__ks4web_refs instanceof Map ? window.__ks4web_refs : null;
  const el = (map && opts.ref) ? map.get(opts.ref) : null;
  function sig(node) { if (!node || node === document.body || node === document.documentElement) return '(body)';
    const id = node.id ? '#' + node.id : ''; const nm = (node.getAttribute && node.getAttribute('aria-label')) || (node.textContent || '').slice(0, 30);
    return (node.tagName || '?') + id + '|' + (nm || '').replace(/\s+/g, ' ').trim(); }
  const t = el ? { value: ('value' in el) ? String(el.value).slice(0, 200) : null,
    checked: (typeof el.checked === 'boolean') ? el.checked : null,
    expanded: el.getAttribute ? el.getAttribute('aria-expanded') : null,
    focused: document.activeElement === el } : null;
  return { mutated: mutated, url: location.href, active: sig(document.activeElement), target: t };
}
"""

#: How long to let a MutationObserver flush after a trusted action before
#: reading the outcome. A React setState re-render lands async, so a same-tick
#: read would miss it and report a false none-observed.
_SETTLE_MS = 80


# ----------------------------------------------------------- descriptors

def anchor_of(resolved: dict) -> dict:
    """The durable anchor descriptor for a resolved target, for the audit
    trail and for saved workflows (DESIGN 3.5: the two places anchors
    surface). A ladder-resolved unit carries its minted anchor whole; a
    live-resolved unit contributes what the live resolver measured, which is
    poorer (no landmark, no stable attributes) and still re-resolvable
    through the role+name tiers."""
    unit = resolved.get("unit") or {}
    stored = unit.get("anchor")
    if isinstance(stored, dict) and stored:
        return dict(stored)
    return {k: v for k, v in {
        "role": unit.get("role"),
        "name": unit.get("name"),
        "page_key": unit.get("page_key"),
        "attr_testid": unit.get("attr_testid") or unit.get("testid"),
        "attr_id": unit.get("attr_id"),
        "attr_name": unit.get("attr_name"),
    }.items() if v not in (None, "")}


def anchor_id_of(anchor: dict) -> str:
    """A short stable id for an anchor descriptor, minted for the audit
    record and the workflow file. Content-derived, so the same element gets
    the same id across sessions."""
    import hashlib
    import json as _json
    basis = _json.dumps(
        {k: anchor.get(k) for k in ("role", "name", "page_key", "landmark",
                                    "landmark_label", "attr_testid",
                                    "attr_id", "attr_name")},
        sort_keys=True)
    return "a" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:6]


def target_descriptor(unit: dict) -> dict:
    """Flatten a resolved unit (ladder or live) into the fields the credential
    check and the gate fingerprint read. One shape for both paths."""
    a = unit.get("anchor") or {}
    return {
        "role": unit.get("role") or a.get("role"),
        "name": unit.get("name") or a.get("name"),
        "label": unit.get("name") or a.get("name"),
        "page_key": unit.get("page_key") or a.get("page_key"),
        "landmark": a.get("landmark"),
        "landmark_label": a.get("landmark_label"),
        "href": unit.get("href"),
        "action": unit.get("form_action") or unit.get("action"),
        "secret": unit.get("secret"),
        "payment": unit.get("payment"),
        "type": unit.get("type"),
        "autocomplete": unit.get("autocomplete"),
    }


def action_class_for(desc: dict, *, submitting: bool = False) -> str | None:
    """The gated class for an action on this target, or None. A submit-typed
    control and an explicit form submission are `form_submit`; a payment-shaped
    field is `payment_form`. Everything else acts without a gate (DESIGN 5.4)."""
    if credentials.is_payment_field(desc):
        return "payment_form"
    if submitting or (desc.get("type") or "").lower() == "submit":
        return "form_submit"
    return None


# ------------------------------------------------------------- resolution

async def resolve(sess, record, location: dict, *, tool: str,
                  acting: bool = True) -> dict:
    """Resolve one location to a live element handle, refusing rather than
    guessing. Returns a dict carrying the handle, the descriptor, the gate
    fingerprint source, and the rebind resolution outcome ('ok'/'rebound').

    A stored session ref goes through the rebind ladder over a FRESH extraction,
    so the resolution is against the page as it is right now; every other
    selector resolves live and refuses on more than one visible match.

    `acting=False` marks a read-shaped caller (a screenshot of an element):
    reads may proceed on a reported rebind where an acting call refuses."""
    group, value = selector_of(location)

    if group == "ref":
        return await _resolve_ref(sess, record, value, tool=tool,
                                  acting=acting)
    return await _resolve_live(sess, record, location, tool=tool)


def _material_name_change(old: str | None, new: str | None) -> bool:
    """A name change a human would notice: compared case-folded and
    whitespace-squashed, so 'Save ' vs 'save' is cosmetic and 'Save' vs
    'Delete account' is material."""
    def norm(s):
        return " ".join(str(s or "").split()).casefold()
    return norm(old) != norm(new)


async def _resolve_ref(sess, record, ref: str, *, tool: str,
                       acting: bool = True) -> dict:
    entry = sess.element_map.entries.get(ref)
    if entry is None:
        # NOT a session ref, and that is the end of it. This branch used to
        # fall back to the raw in-page map, which resolves a key to whatever
        # element happens to hold it with no fingerprint, no staleness check,
        # and no ladder: a positional lookup wearing a ref's clothes. The
        # 2026-09-05 field misdirect investigation closed it: every ref an
        # action accepts rides the session map and the rebind ladder, or the
        # call refuses. Nothing the tools return hands out in-page-only ids
        # any more (find_elements and live-selector resolutions both absorb
        # into the session map), so anything landing here is a stale quote
        # or an invention, and acting on it by position is exactly the
        # wrong-element defect the ladder exists to prevent.
        raise TargetNotFound(
            f"{ref!r} was never minted in this session. Refs are minted "
            f"only by a read in this session; call get_page_view(page="
            f"{record.handle!r}) or find_elements and use the ref they "
            f"return.")

    data = await extract(record.page)
    outcome = ladder.resolve(sess.element_map, ref, data, record.handle)
    verdict = outcome["outcome"]
    if verdict in (Outcome.OK, Outcome.REBOUND):
        unit = outcome["unit"]
        node_ref = unit.get("ref")
        handle = await _handle(record.page, node_ref)
        if handle is None:
            raise StaleAnchor(
                f"{ref!r} resolved to an element that is no longer in the DOM. "
                f"Re-read the page and use the ref it returns.")
        rebound = None
        if verdict == Outcome.REBOUND:
            # H2 (gauntlet 2026-09-06): a stable attribute key (testid, id,
            # named control) reassigned to a SAME-ROLE element whose
            # accessible name materially changed is the volatile-id theft
            # shape with the role kept. A hostile page fully controls its
            # own testids, so on an ACTING path this is a refusal, not a
            # warning: the caller reasoned about the old name and the click
            # would land on the new one. A re-read updates the map (the key
            # re-binds to the renamed element and the payload shows its
            # current name), after which the ref resolves cleanly. Reads
            # still proceed with the rebind reported.
            tier = str(outcome.get("tier") or "")
            old_name = (entry.anchor or {}).get("name")
            new_name = unit.get("name")
            if (acting and tier.startswith("fingerprint (")
                    and _material_name_change(old_name, new_name)):
                raise TargetChanged(
                    f'{ref!r} still carries its stable attribute key, but '
                    f'the element wearing that key is no longer what you '
                    f'read: it was {entry.anchor.get("role")} '
                    f'"{old_name}" and is now {unit.get("role")} '
                    f'"{new_name}". Acting on a renamed control through a '
                    f'reused key is how the wrong element gets clicked, so '
                    f'nothing was done. Re-read the page (get_page_view or '
                    f'find_elements) and act on the ref that read returns '
                    f'if the renamed control is really the one you want.')
            rebound = (f'{ref} was rebound: {outcome.get("was")} -> '
                       f'{outcome.get("now")} (tier {outcome.get("tier")})')
        return {"handle": handle, "node_ref": node_ref, "session_ref": ref,
                "unit": unit,
                "descriptor": target_descriptor(unit),
                "resolution": "rebound" if verdict == Outcome.REBOUND else "ok",
                "rebound": rebound}
    # Every non-proceeding outcome is a typed, recovery-naming refusal.
    if verdict == Outcome.MODAL:
        raise ModalBlocked(
            f'a dialog ({outcome.get("dialog")}) is open and blocks '
            f'interaction. {outcome.get("recovery")}')
    if verdict == Outcome.AMBIGUOUS:
        raise AmbiguousLocation(
            f'{ref!r} no longer resolves to one element ({outcome.get("tier")}): '
            f'{_candidate_text(outcome.get("candidates"))}. '
            f'{outcome.get("recovery")}')
    if verdict == Outcome.BAD_PARAMS:
        raise BadParams(
            f'{ref!r} belongs to page {outcome.get("minted_on")}, not '
            f'{record.handle}. {outcome.get("recovery")}')
    if verdict == Outcome.NOT_FOUND:
        raise TargetNotFound(f'{ref!r}: {outcome.get("recovery")}')
    # STALE
    raise StaleAnchor(
        f'{ref!r} does not resolve on this page any more '
        f'(reason: {outcome.get("reason")}; was {outcome.get("was")}). '
        f'{outcome.get("recovery")}')


async def _resolve_live(sess, record, location: dict, *, tool: str) -> dict:
    if "anchor" in location:
        raise BadParams(
            "the {'anchor': ...} selector addresses a durable anchor id, which "
            "surfaces only in audit records and saved workflows (DESIGN 3.5). "
            "Address a live element by ref, css, text, role+name, or testid; "
            "anchor-driven replay runs through run_workflow, which re-resolves "
            "stored anchors itself.")
    found = await record.page.evaluate(_RESOLVE_JS, {"location": location})
    if found.get("error"):
        raise BadParams(
            f'the selector did not resolve: {found["error"]}. Check the css or '
            f'xpath syntax, or address the element by ref from a read.')
    count = found.get("count", 0)
    if count == 1:
        handle = await _handle(record.page, found["ref"])
        if handle is None:
            raise StaleAnchor(
                "the element left the DOM between resolving it and acting on "
                "it. Re-read the page and try again.")
        unit = dict(found)
        # Absorb the resolved element into the SESSION map, so the ref this
        # action reports (`target.ref`) is one the ladder can re-resolve.
        # Before the field misdirect fix, action results surfaced the bare
        # in-page 'x' id, and a caller reusing it rode a raw positional
        # lookup instead of the ladder. The anchor came from the resolver's
        # own landmark climb, so an element the page view already minted
        # registers under the same keys and keeps the same session ref.
        session_ref = None
        if unit.get("anchor"):
            import time as _time
            shim_unit = {"ref": found["ref"], "anchor": unit["anchor"],
                         "role": unit.get("role"), "name": unit.get("name"),
                         "state": ""}
            shim = {"identity": {"url": record.page.url,
                                 "page_key": found.get("page_key", "")},
                    "affordances": [shim_unit], "regions": [],
                    "headings": [], "forms": [], "tables": []}
            sess.element_map.absorb(
                shim, record.handle, sess.reads.mint_token(record.handle),
                ts=_time.strftime("%Y-%m-%dT%H:%M:%S"), scope="resolve")
            session_ref = shim_unit["ref"]
        return {"handle": handle, "node_ref": found["ref"],
                "session_ref": session_ref, "unit": unit,
                "descriptor": target_descriptor(unit), "resolution": "ok",
                "rebound": None}
    if count and count > 1:
        raise AmbiguousLocation(
            f'{count} visible elements match ({found.get("how")}); no tool acts '
            f'on first match. Candidates: '
            f'{_candidate_text(found.get("candidates"))}. Narrow the selector, '
            f'or read the page and use a ref.')
    misses = found.get("nearest") or []
    hint = (" Nearest by name: " + _candidate_text(misses)) if misses else \
        " No near misses either; the target may be inside an iframe, a " \
        "closed shadow root, or content that has not rendered yet. Open " \
        "shadow roots were searched."
    raise TargetNotFound(
        f'nothing visible matches this selector ({found.get("how")}).{hint}')


async def _handle(page, node_ref: str):
    # The isConnected check matters: a detached element still answers
    # `as_element()`, and acting on it either fails late with a driver
    # timeout or, worse, lands on nothing while reporting motion.
    jsh = await page.evaluate_handle(
        "r => { const el = window.__ks4web_refs && window.__ks4web_refs"
        ".get(r); return (el && el.isConnected) ? el : null; }",
        node_ref)
    element = jsh.as_element()
    if element is None:
        await jsh.dispose()
        return None
    return element


def _candidate_text(candidates) -> str:
    if not candidates:
        return "(none)"
    bits = []
    for c in candidates[:8]:
        label = f'{c.get("role", "?")} "{c.get("name") or "(unnamed)"}"'
        if c.get("path"):
            label += f' {c["path"]}'
        bits.append(label)
    return "; ".join(bits)


# --------------------------------------------------------- verified outcomes

async def observe(page, node_ref: str | None) -> dict:
    return await page.evaluate(_OBSERVE_JS, {"ref": node_ref})


async def verify(page, node_ref: str | None, before: dict) -> dict:
    """Diff the page's observable state across the action and name the effect.

    Returns `{effect, details, none_observed}`. `effect` is a short verb where
    something changed and `"none-observed"` where nothing did, and the caller
    surfaces the none-observed case as a warning rather than a bare ok.

    A verification probe that dies because the ACTION navigated the page
    (execution context destroyed, frame detached) is the action SUCCEEDING,
    not failing, so that case reports `navigated` honestly instead of
    leaking a driver string; the field test caught exactly this on a
    press_keys Enter that raced its own navigation."""
    try:
        await page.wait_for_timeout(_SETTLE_MS)
        after = await page.evaluate(_AFTER_JS,
                                    {"ref": node_ref, "token": before["token"]})
    except Exception as exc:
        text = str(exc).lower()
        if ("execution context was destroyed" in text
                or "frame was detached" in text
                or "navigation" in text):
            url_now = None
            try:
                url_now = page.url
            except Exception:
                pass
            detail = (f'navigated: {before["url"]} -> {url_now}'
                      if url_now and url_now != before["url"]
                      else "the page navigated or re-rendered while the "
                           "outcome was being read; the action itself "
                           "completed")
            return {"effect": "navigated", "details": [detail],
                    "none_observed": False}
        raise
    changes: list[str] = []
    effect = None
    if after["url"] != before["url"]:
        changes.append(f'navigated: {before["url"]} -> {after["url"]}')
        effect = effect or "navigated"
    b_t, a_t = before.get("target"), after.get("target")
    if b_t and a_t:
        if b_t.get("value") != a_t.get("value"):
            changes.append(f'value: {a_t.get("value")!r}')
            effect = effect or "value-changed"
        if b_t.get("checked") != a_t.get("checked"):
            changes.append(f'checked: {a_t.get("checked")}')
            effect = effect or "state-changed"
        if b_t.get("expanded") != a_t.get("expanded"):
            changes.append(f'aria-expanded: {a_t.get("expanded")}')
            effect = effect or "state-changed"
        if b_t.get("focused") != a_t.get("focused") and a_t.get("focused"):
            changes.append("focus moved to the target")
            effect = effect or "focus-moved"
    if before.get("active") != after.get("active"):
        changes.append(f'active element: {after.get("active")}')
        effect = effect or "focus-moved"
    if after.get("mutated"):
        changes.append("the DOM changed")
        effect = effect or "dom-changed"
    if changes:
        return {"effect": effect or "changed", "details": changes,
                "none_observed": False}
    return {
        "effect": "none-observed",
        "details": [],
        "none_observed": True,
        "warning": (
            "the action was dispatched as trusted input and the driver "
            "reported no error, but nothing observable changed: no navigation, "
            "no focus move, no target-state change, and no DOM mutation. The "
            "handler may have ignored it, or the effect may be one this check "
            "does not see. Verify with get_page_view before building on it."),
    }


# -------------------------------------------------------- driver dispatch

def wrap_driver_error(exc: Exception, *, what: str, timeout_ms: int) -> Exception:
    """Turn a Playwright actionability failure into an honest, typed refusal.

    An overlay intercepting the point and a target that never stops moving both
    surface from Playwright as a timeout after it retries actionability, so both
    become a `TIMEOUT` naming the likely cause and a recovery rather than a bare
    ok. The driver's own detail is kept, trimmed, because it often names the
    intercepting element outright."""
    detail = str(exc).splitlines()[0][:200]
    lowered = str(exc).lower()
    if "not attached" in lowered or "detached" in lowered:
        # The element left the DOM between resolution and dispatch. That is
        # a staleness fact, not a timeout, and the recovery is a re-read.
        return StaleAnchor(
            f"the target left the DOM while {what} was executing (the page "
            f"re-rendered under the action). Nothing was dispatched to a "
            f"different element. Re-read the page or repeat the call so the "
            f"ref re-resolves against the page as it is now. Driver detail: "
            f"{detail}.")
    if "intercepts pointer events" in lowered:
        cause = ("another element is on top of the target and intercepting the "
                 "click (an overlay, a cookie banner, or a modal). ")
    elif "not stable" in lowered or "stable" in lowered:
        cause = ("the target never stopped moving, so it never became "
                 "clickable (an animation with no still frame). ")
    else:
        cause = ""
    return Timeout(
        f"{what} did not complete within {timeout_ms} ms: {cause}the browser "
        f"is still usable. Driver detail: {detail}. Verify the page with "
        f"get_page_view, dismiss any overlay, or raise timeout_ms.")
