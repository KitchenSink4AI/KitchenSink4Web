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

import time

from .. import pagedata as _pagedata
from ..anchors import Outcome, ladder
from ..errors import (AmbiguousLocation, BadParams, ModalBlocked, StaleAnchor,
                      TargetChanged, TargetNotFound, Timeout)
from ..policy import consent, credentials, submissions
from ..projection import extract, instrument

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
#: `frame` came BACK, as a modifier and with the machinery under it (the
#: same-origin frame build, 2026-09-06). The shadow build removed it rather
#: than fake it, and its reasoning was right: a frame has its own execution
#: context and the shadow sweep cannot reach one. What changed is that the
#: resolver now runs PER FRAME, in the frame's own realm, through the
#: driver's frame layer, so `{'css': '#pay', 'frame': 'if2'}` narrows the
#: search to one frame's document.
#:
#: It narrows and never widens. A live selector already searches every
#: SAME-ORIGIN frame on the page and refuses ambiguity across the union of
#: them, because a page that embeds its checkout in a frame should not need
#: the caller to know that; `frame` is how a caller says which of two
#: identical widgets they meant. A cross-origin frame is refused by name.
_LADDER_KEYS = ("ref", "region", "form", "table")
_LIVE_KEYS = ("css", "xpath", "testid", "coordinate", "nth", "describe",
              "text", "anchor")
_MODIFIERS = ("shadow", "exact", "frame")


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
        else:
            raise BadParams(
                f"location key {key!r} is not a selector. The selectors are "
                f"ref/region/form/table, css, xpath, text, role+name, testid, "
                f"nth, describe, coordinate; shadow/exact/frame are "
                f"modifiers.")
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
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_VISIBILITY@@
// @@KS4WEB_PAYMENT@@
// @@KS4WEB_ACTIVATION@@
// @@KS4WEB_CONSENT@@
  const loc = opts.location || {};
  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };
  const map = KS.refs;
  // Open-shadow-root targeting (2026-09-06). Default ON, so an element the
  // page view can SEE is an element this resolver can reach; `shadow: false`
  // in the location opts out. The root list is built once and reused by every
  // selector branch below.
  // Built LAZILY: discovering roots costs a document-wide sweep, and the
  // commonest resolution by far is `loc.ref`, which reads the map and queries
  // nothing. The acting path pays for this only when it actually searches.
  const SHADOW_ON = !(loc && loc.shadow === false);
  // The recursion is `ksOpenRoots`, the one deep walk spliced in from
  // `visibility.js`, and not a private copy: the copies of this drifted, and
  // the occlusion scan's copy (a flat `querySelectorAll`) is what re-attack 2
  // put a lid behind.
  let rootList = null;
  function roots() {
    if (rootList) return rootList;
    rootList = SHADOW_ON ? ksOpenRoots(document, null) : [];
    return rootList;
  }
  function queryAll(sel) {
    const out = Array.from(document.querySelectorAll(sel));
    for (const root of roots()) for (const el of root.querySelectorAll(sel)) out.push(el);
    return out;
  }
  // The shadow-boundary hop and the whole hidden-technique set come from the
  // ONE shared source spliced in above, so the resolver, the search, the
  // projection, and the prose read cannot disagree about what a human sees.
  const up = ksUp;
  const cs = ksCS;
  function byId(el, id) {
    const r = el.getRootNode ? el.getRootNode() : document;
    if (r && typeof r.getElementById === 'function') return r.getElementById(id);
    return document.getElementById(id);
  }
  function hiddenAnywhere(el) { return ksHiddenAnywhere(el) !== null; }
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
    const ref = 'x' + (KS.seq = (KS.seq || 0) + 1);
    map.set(ref, el);
    KS.refof.set(el, ref);
    const d = describe(el);
    const r = d.role;
    const formEl = ksFormOf(el);
    const inForm = !!formEl;
    // Effective submission type from `ksSubmitTypeOf`, which is the one
    // copy of that rule (the extractor, this resolver, and the focused
    // descriptor reader had three). A <button> with a missing or invalid
    // type is a submit button per the HTML spec, with the default-submit
    // case scoped to buttons inside a form.
    const type = ksSubmitTypeOf(el, inForm) || '';
    const ac = (el.getAttribute && el.getAttribute('autocomplete') || '').toLowerCase();
    const panGroup = ksPanGroup(el);
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
      form_payment: ksFormPayment(formEl),
      // THE FORM CENSUS (consent ladder, 2026-09-07). Facts only: the
      // effective method, whether any field in `form.elements` classifies
      // secret, the file and enctype facts, the structural signals, the
      // default submitter's name, and the checkbox labels, all squashed.
      // `policy/submissions.py` owns what those names MEAN.
      form_census: ksFormCensus(formEl),
      page_age_declared: ksAgeDeclared(),
      payment: ksPaymentField(el),
      pattern: (el.getAttribute && el.getAttribute('pattern')) || '',
      inputmode: (el.getAttribute && el.getAttribute('inputmode')) || '',
      placeholder: (el.getAttribute && el.getAttribute('placeholder')) || '',
      editable: !!el.isContentEditable,
      pan_shape: ksPanShape('value' in el ? el.value : ''),
      pan_group_size: panGroup ? panGroup.size : null,
      pan_group_digits: panGroup ? panGroup.digits : null,
      pan_group_first: panGroup ? panGroup.first : null,
      pan_group_min: panGroup ? panGroup.min : null,
      pan_group_region: panGroup ? panGroup.region : null,
      // WHICH ELEMENT DOES THIS CLICK ACTIVATE (re-attack 2, C1). A label
      // forwards its activation to the control it labels, and a node with no
      // activation behaviour delegates to the nearest ancestor that has one,
      // so the classifier gets the delegate's submission facts alongside the
      // touched element's own.
      activates: ksDelegatedActivation(el),
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
// @@KS4WEB_INSTRUMENT@@
  const map = KS.refs;
  const el = opts.ref ? map.get(opts.ref) : null;
  const token = 'w' + (KS.actseq = (KS.actseq || 0) + 1);
  const rec = { mutated: false };
  try {
    rec.obs = new MutationObserver(() => { rec.mutated = true; });
    rec.obs.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  } catch (e) {}
  KS.act[token] = rec;
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
// @@KS4WEB_INSTRUMENT@@
  const store = KS.act;
  const rec = store[opts.token]; let mutated = false;
  if (rec) { mutated = !!rec.mutated; try { rec.obs && rec.obs.disconnect(); } catch (e) {} delete store[opts.token]; }
  const el = opts.ref ? KS.refs.get(opts.ref) : null;
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

#: Every injected source in this module goes through the same splice the
#: projection's scripts do: the instrument prelude, so nothing load-bearing
#: sits in a page-writable global, and the one hidden-detection source, so the
#: acting path's idea of "visible" is the read's idea of "visible".
_RESOLVE_JS = instrument(_RESOLVE_JS)
_OBSERVE_JS = instrument(_OBSERVE_JS)
_AFTER_JS = instrument(_AFTER_JS)


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
        # The identifiers the server-side payment re-derivation reads. The
        # in-page rule already looked at these; the Python side could not,
        # because the descriptor dropped them on the way out, so a
        # caller-supplied descriptor could omit `payment` and be believed
        # (R3, 2026-09-06). Same shape as `is_secret_field`: the flag is a
        # hint and the identifiers are the evidence.
        "attr_id": unit.get("attr_id") or a.get("attr_id"),
        "attr_name": unit.get("attr_name") or a.get("attr_name"),
        "pattern": unit.get("pattern"),
        "inputmode": unit.get("inputmode"),
        "placeholder": unit.get("placeholder"),
        # The PAN-shape and split-group MEASUREMENTS, which only the page can
        # take: whether the field shows a card-number shape, and how many
        # short numeric boxes share its group. `pan_shape` travels as a
        # boolean and never as the string it was derived from, because that
        # string can BE a card number and the audit record must not carry one.
        "pan_shape": unit.get("pan_shape"),
        "pan_group_size": unit.get("pan_group_size"),
        "pan_group_digits": unit.get("pan_group_digits"),
        "pan_group_first": unit.get("pan_group_first"),
        "pan_group_min": unit.get("pan_group_min"),
        "pan_group_region": unit.get("pan_group_region"),
        # The element the browser ACTIVATES when this one is clicked, when it
        # is not this one. A label's control, or the button a clicked span
        # sits inside (re-attack 2, C1).
        "activates": unit.get("activates"),
        # Multi-line-ness, which is what decides whether Enter is an implicit
        # submission (C2). The descriptor carried `tag` on some paths and not
        # others, so the classifier could not ask.
        "tag": unit.get("tag"),
        "editable": unit.get("editable"),
        # Form membership travels with the descriptor because the submission
        # classifier needs it: Enter is only a submission inside a form. The
        # extractor spells it `form`, the live resolver spells it `in_form`,
        # and the classifier should not have to know which path it came from.
        "in_form": (unit.get("in_form") if unit.get("in_form") is not None
                    else unit.get("form")),
        # Whether the FORM this control belongs to carries a payment field
        # anywhere in it, which is what `payment_form` has always claimed to
        # be about.
        "form_payment": unit.get("form_payment"),
        # THE FORM CENSUS, which is what lets the classifier say WHICH KIND
        # of submission this is instead of only "a form was submitted". The
        # facts are computed in-page beside `ksFormPayment`; the vocabulary
        # that reads them lives in `policy/submissions.py`.
        "form_census": unit.get("form_census"),
        # The page's own age declaration, relayed and never judged.
        "page_age_declared": unit.get("page_age_declared"),
    }


#: THE SUBMIT-BUTTON STATES, and this list is the whole class rather than the
#: instances anyone happened to think of. HTML defines exactly three ways an
#: element is a submit button: `<input type=submit>`, `<input type=image>`,
#: and a `<button>` whose type attribute is missing or invalid (only `button`
#: and `reset` opt out). The third is folded in upstream -- the extractor and
#: the live resolver both compute an effective `type` of `submit` for an
#: in-form typeless button -- so by the time a descriptor reaches the
#: classifier the whole class is these two strings.
#:
#: The re-attack (2026-09-06, R1) went through `type=image`, which is the
#: submit button with a picture on it and has been in the language since
#: HTML 2.0. Clicking one submitted a checkout form carrying a live card
#: number with no gate computed at all, because the classifier compared
#: `type == "submit"` against the ONE instance rather than testing the class.
#: `type=image` also POSTs its click coordinates, so it is if anything the
#: more consequential of the two.
SUBMIT_TYPES = frozenset({"submit", "image"})


def is_native_submitter(desc: dict) -> bool:
    """Whether ACTIVATING this control natively submits the form it is in."""
    return (desc.get("type") or "").strip().lower() in SUBMIT_TYPES


def activation_delegate(desc: dict) -> dict:
    """The submission facts of the element the browser ACTUALLY activates.

    THE PRIOR QUESTION (re-attack 2, C1). R1 widened the submit test from one
    instance to HTML's three submit states, and left untouched the question
    that comes before it: between the element the tool touches and the element
    that acts, is there a step? There is, and HTML names it. A `<label>` runs
    label activation behaviour and forwards the click to `label.control`; a
    node with no activation behaviour of its own delegates up to the nearest
    ancestor that has one. `<label for=go>Continue</label>` over an off-screen
    submit button is an ordinary styling pattern, and clicking it submitted a
    form holding a live card number with no class computed at all, because a
    label is neither a payment field nor a submitter.

    The page-side rule is `ksDelegatedActivation` in `activation.js`, one
    implementation spliced into every consumer. It returns FACTS -- the
    delegate's type, form membership, and whether that form carries a card
    field -- and the classifier below reads them exactly as it reads the
    touched element's own, so a delegated click cannot reach a gate a direct
    click would miss and cannot skip one either. An empty dict where nothing
    is delegated keeps every caller free of a null check."""
    delegate = desc.get("activates")
    return delegate if isinstance(delegate, dict) else {}


def action_class_for(desc: dict, *, submitting: bool = False) -> str | None:
    """THE SUBMISSION AND PAYMENT CLASSIFIER. One function, and every path that
    can submit a form or write a payment-shaped field calls it.

    A submit-typed control and an explicit form submission are `form_submit`;
    a payment-shaped field is `payment_form`, and payment wins, so a card
    field inside a batch gates the batch as payment rather than as a plain
    submit. Everything else acts without a gate (DESIGN 5.4).

    Gauntlet 2 (2026-09-06) found this reached from two of the six acting
    tools. `fill_form` passed `action_class=None` and only asked the
    credential layer per field, so a `cc-number` field took the write ungated
    while the read printed `[payment-shaped: gated]` beside it (C1). And
    `press_keys` passed no class at all, so Enter in a form -- implicit form
    submission, the oldest submit path on the web -- submitted anything,
    payment or account deletion, with no gate computed (H1). The gate was
    never broken; two tools were outside it. `test_gate_parity.py` now pins
    all four write paths to the same verdict on the same fixture, so a fifth
    path cannot be added that quietly skips this."""
    # WRITING a payment-shaped field is `payment_form` wherever it happens.
    if credentials.is_payment_field(desc):
        return "payment_form"
    # And so is writing one THROUGH something else: a click on a label whose
    # control is a card field lands in the card field.
    delegate = activation_delegate(desc)
    if delegate and credentials.is_payment_field(delegate):
        return "payment_form"
    if submitting or is_native_submitter(desc) or is_native_submitter(delegate):
        # And SUBMITTING is judged by the form, not by the control that
        # triggered it, because the submission is the moment the card number
        # leaves. Reading payment as a field-only property split the four
        # write paths apart on one fixture: filling `#cc` classified
        # `payment_form` while clicking that same form's Sign-in button --
        # the call that actually sends the number -- classified the weaker
        # `form_submit`. Escalation is scoped to submissions on purpose: a
        # checkout page has an email field and a postcode field too, and
        # gating every keystroke in the form because a card field shares it
        # would make the gate the thing people route around.
        #
        # The form is the DELEGATE'S form where the click is delegated: a
        # label parked outside the <form> tag still submits the form its
        # control belongs to.
        payment_form = desc.get("form_payment") or delegate.get("form_payment")
        if payment_form:
            return "payment_form"
        return submission_class_for(desc, delegate)
    return None


def submission_class_for(desc: dict, delegate: dict | None = None) -> str:
    """WHICH KIND of submission this is, once payment has already lost.

    `form_submit` used to be the answer for everything from a library
    catalog query to a "Delete account" button, which is the author's whole
    complaint about the approval system: one class, one prompt, one sentence,
    fired on research the granted mode already implied consent for. The
    class is the consent unit, so the class has to be finer than "a form was
    submitted".

    Returns one of `credential_submit`, `destructive_submit`, `legal_assent`,
    `broadcast_submit`, or the residual `form_submit`. The residual is NOT
    the same as ungated: `policy/consent.py` decides its tier, and a
    query-shaped GET submission is in-grade there under both scopes while a
    POST residual asks under `research`.

    The vocabulary lives in `policy/submissions.py` and the facts come from
    the in-page census, so a delegated click reads the DELEGATE'S form, which
    is the form that actually submits."""
    census = consent.census_of(desc)
    if not census and isinstance(delegate, dict):
        census = delegate.get("form_census") or {}
    found = submissions.classify(
        census, desc.get("name"), (delegate or {}).get("name"))
    return found[0] if found else "form_submit"


#: Keys that submit a form implicitly. Enter in a single-line control inside a
#: form is a submission per the HTML spec; Ctrl+Enter is the near-universal
#: convention in a textarea, where a bare Enter inserts a newline instead.
_SUBMIT_KEYS = ("enter", "numpadenter", "return")


#: Keys that ACTIVATE whatever holds focus. Space is the other half of the
#: keyboard's activation contract and always has been: a focused `<button>`
#: fires its click on Space, and if that button is a submit control the form
#: goes. The Enter family is in both tuples because Enter both activates a
#: focused button AND submits implicitly from a text field, which are two
#: different mechanisms reaching the same place.
_ACTIVATION_KEYS = ("space", " ", "spacebar", "enter", "numpadenter", "return")


def _base_and_mods(keys: str | None) -> tuple[str, set[str]]:
    parts = [p.strip().lower() for p in str(keys or "").split("+") if p.strip()]
    if not parts:
        return "", set()
    return parts[-1], set(parts[:-1])


def submits_by_key(keys: str | None) -> bool:
    """Whether this key or chord is an IMPLICIT form submission in a form
    context: Enter pressed in a single-line control."""
    base, modifiers = _base_and_mods(keys)
    if base not in _SUBMIT_KEYS:
        return False
    # Shift+Enter is the newline convention, not a submission; Alt+Enter is a
    # platform chord. Ctrl/Meta+Enter and a bare Enter both submit.
    return not (modifiers & {"shift", "alt"})


def activates_by_key(keys: str | None) -> bool:
    """Whether this key or chord ACTIVATES the focused control."""
    base, modifiers = _base_and_mods(keys)
    if base not in _ACTIVATION_KEYS:
        return False
    # The same two exclusions, for the same reasons one key along: Shift+Space
    # scrolls up and Alt+Space opens a window menu, and neither presses the
    # button under the cursor.
    return not (modifiers & {"shift", "alt"})


#: Controls where Enter INSERTS A NEWLINE instead of submitting. HTML scopes
#: implicit submission to a form's single-line text controls, which is what
#: `submits_by_key`'s own docstring said and what nothing implemented: Enter
#: in a `<textarea>` gated as a submission the browser never performs
#: (re-attack 2, C2). A confirmation prompt for pressing Enter in a comment
#: box is the erosion DESIGN names -- a gate that fires where nothing happens
#: is a gate people learn to click through.
_MULTILINE_TAGS = frozenset({"TEXTAREA"})


def is_single_line(desc: dict) -> bool:
    """Whether Enter in this control is an implicit form submission.

    Unknown is SINGLE-LINE on purpose. A global `press_keys(keys='Enter')`
    carries no location and the focused-descriptor reader may return nothing
    at all, and defaulting a missing tag to multi-line would drop the gate on
    exactly the call that has the least information about where the keystroke
    lands."""
    if (desc.get("tag") or "").strip().upper() in _MULTILINE_TAGS:
        return False
    return not desc.get("editable")


def key_submits(keys: str | None, desc: dict) -> bool:
    """Whether pressing `keys` against THIS descriptor submits its form.

    TWO MECHANISMS, and the re-attack (2026-09-06, R2) rode the second one
    past a gate written only for the first. `submits_by_key` describes
    IMPLICIT submission -- Enter in a text control -- which is what the gate
    knew about. ACTIVATION is the other one: a submit button that holds focus
    is pressed by Space exactly as it is pressed by a click, so
    `press_keys(keys='Space')` with no location at all submitted a "Delete
    account" form while the same call with Enter refused correctly. The class
    that carries the harm is the NATIVE SUBMITTER, not the key, so the key
    only has to be an activation and the descriptor has to be one of these.

    Shift+Enter stays a newline in a text context, because both halves
    exclude it.
    """
    if not desc or not desc.get("in_form"):
        return False
    if submits_by_key(keys) and is_single_line(desc):
        return True
    # The activation branch is deliberately still open to a textarea: Enter
    # does not submit from one, but the branch is about what holds FOCUS being
    # a submit button, and nothing about that changes with the tag.
    return activates_by_key(keys) and (is_native_submitter(desc)
                                       or is_native_submitter(
                                           activation_delegate(desc)))


#: What the live element says about itself RIGHT NOW: the field-type flip
#: (gauntlet 2 M6) resolves a descriptor while the field is `type=text`, then
#: the page's own focus handler turns it into `type=password` under the
#: keystrokes. Classification has to be re-taken against the focused element,
#: not against the descriptor that was true a moment earlier.
_LIVE_FIELD_JS = r"""
(el) => {
// @@KS4WEB_VISIBILITY@@
// @@KS4WEB_PAYMENT@@
// @@KS4WEB_ACTIVATION@@
// @@KS4WEB_CONSENT@@
  const f = ksFormOf(el);
  const grp = ksPanGroup(el);
  return {
    tag: el.tagName,
    type: (el.type || '').toLowerCase(),
    autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
    name: (el.getAttribute('aria-label') || el.getAttribute('name')
           || el.getAttribute('placeholder') || '').slice(0, 80),
    attr_id: el.id || '',
    attr_name: (el.getAttribute('name') || ''),
    pattern: (el.getAttribute('pattern') || ''),
    inputmode: (el.getAttribute('inputmode') || ''),
    placeholder: (el.getAttribute('placeholder') || ''),
    editable: !!el.isContentEditable,
    pan_shape: ksPanShape('value' in el ? el.value : ''),
    pan_group_size: grp ? grp.size : null,
    pan_group_digits: grp ? grp.digits : null,
    pan_group_first: grp ? grp.first : null,
    pan_group_min: grp ? grp.min : null,
    pan_group_region: grp ? grp.region : null,
    in_form: !!f,
    action: (f && f.getAttribute('action')) || '',
    payment: ksPaymentField(el),
    form_payment: ksFormPayment(f),
    // Re-taken with the rest (gauntlet 2 M6): a focus handler that flips a
    // field to `type=password` flips the form's census with it.
    form_census: ksFormCensus(f),
    page_age_declared: ksAgeDeclared(),
    activates: ksDelegatedActivation(el),
    // THE CLOAK, RE-CHECKED AFTER FOCUS AND IN THE SAME JS TURN (A7). See
    // `recheck_at_write`: the caller focuses, the focus handler runs
    // synchronously, and this reads the verdict the focus itself produced.
    cloak: ksCloakReason(el)
  };
}
"""


_LIVE_FIELD_JS = instrument(_LIVE_FIELD_JS)


async def live_field(page, handle) -> dict:
    """Read the target's own current type and autocomplete off the page."""
    try:
        return await page.evaluate(_LIVE_FIELD_JS, handle)
    except Exception:
        return {}


async def recheck_at_write(page, handle, desc: dict, *, tool: str) -> dict:
    """Re-classify the FOCUSED element immediately before a write, and refuse
    a secret field however it got that way.

    The order matters and is the whole fix for M6: focus first, because the
    flip is a focus handler, then read the type, then decide. A field that
    was `type=text` at resolution and is `type=password` under the cursor
    refuses exactly like a field that declared itself honestly, and nothing
    has been typed when it does.

    CALL IT AFTER `policy.approve`, never before. Focusing an element is
    something the page can observe, and the ladder's stated order puts the
    read-only grade and the origin policy ahead of anything that touches the
    page at all. Every argument this needs (form membership, whether the form
    holds a payment field) already rides the descriptor, so the submission
    class is computable without focusing and the two steps do not have to be
    reordered to fit."""
    try:
        await handle.focus()
    except Exception:
        pass                        # a control that cannot focus cannot flip
    live = await live_field(page, handle)
    if not live:
        return desc
    # THE CLOAK, RE-CHECKED AFTER THE FOCUS THIS FUNCTION CAUSED (A7). The
    # occlusion verdict used to be taken once, at resolution, and the focus
    # above is an event the page observes -- the docstring below says so in
    # its own words -- so a `focus` handler that drops an opaque lid over the
    # control opened a window between the only check and the write. The lid
    # was present at the keystroke, witnessed by the page's own listener. The
    # re-check already re-derived everything else here; occlusion was simply
    # not among the keys it merged.
    _refuse_cloak_verdict(
        await _arbitrate(page, handle, live.get("cloak")), tool)
    merged = dict(desc)
    for key in ("type", "autocomplete", "in_form", "action", "attr_id",
                "attr_name", "pattern", "inputmode", "form_payment",
                "payment", "form_census", "page_age_declared"):
        if live.get(key) not in (None, ""):
            merged[key] = live[key]
    merged["secret"] = None         # re-derived from the live type, not reused
    if not live.get("payment"):
        # Only CLEARED when the live read says no, so the server-side
        # re-derivation gets the same fresh start the secret check gets. A
        # stale True from a descriptor resolved before a field flipped is
        # exactly the M6 shape one classification along.
        merged["payment"] = None
    credentials.refuse_secret_write(merged, tool)
    return merged


# ------------------------------------------------------------- resolution


def _frames_path(ref):
    from ..engine import frames as _frames

    return _frames.path(ref)


async def _frame_context(record, fid: str, *, tool: str, ref: str | None):
    """The execution context one frame's refs resolve in, or a refusal.

    Every refusal here is a TARGET-level fact rather than a bad call: the
    frame the ref was minted in has gone, or has navigated somewhere this
    build will not follow, or sits past the depth cap. None of them is
    recoverable by retrying, and none of them is ever resolved by falling
    back to the main document, which is the silent retargeting the whole
    ladder exists to prevent."""
    from ..engine import frames as _frames

    tree = await _frames.ladder(record)
    found = _frames.find(tree, fid)
    if found is None:
        raise StaleAnchor(
            f'{ref or "this location"} lives in frame {fid}, and that frame '
            f'is no longer on {record.handle}. A frame that the page removed '
            f'takes every ref minted inside it with it. Re-read the page '
            f'(get_page_view) and use the refs it returns.')
    if not found.entered:
        # `label()` carries the frame's own `title` attribute, which the
        # embedding page writes, so the line rides the envelope (gauntlet 4,
        # G4-08). The sandbox half of the same label was already validated
        # token-by-token (gauntlet 3, F3); the title half was not.
        raise TargetChanged(
            f'frame {fid} is on the page and this build will not enter it: '
            f'{found.why_not}. Nothing was done, because acting through the '
            f'main document instead would be acting on a different element '
            f'than the one you addressed.\n'
            + _pagedata.wrap_line(f'it is now {found.label()}',
                                  url=record.page.url))
    return found


def context_of(resolved: dict, record) -> object:
    """The page-like object an action must dispatch through.

    An element inside a frame is focused, probed, and armed in ITS OWN
    realm: the cloak check has to see the frame's own overlays, and the
    focus check has to read the frame's own activeElement. Falling back to
    the page for a frame element would ask the wrong document both
    questions."""
    return resolved.get("context") or record.page


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
    return await _resolve_live(sess, record, location, tool=tool,
                               acting=acting)


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

    # The pin (2026-09-06): the in-page id this ref last resolved to, handed
    # to the extractor so an element `find_elements` located PAST the
    # 300-affordance return cap is in the list the ladder searches. Without
    # it, a ref minted for the 301st control on a page refused STALE on every
    # action, which made the flagship read-then-search-then-act pairing fail
    # on exactly the large pages it exists for. The ladder's matching is
    # unchanged; only the candidate list is complete now.
    pin = (sess.element_map.node_refs.get(record.handle) or {}).get(ref)
    # THE REALM. A ref carries its frame (`if2e5`), and the fresh extraction
    # the ladder resolves against has to come from the SAME document the ref
    # was minted in. Re-extracting the main page for a frame ref would hand
    # the ladder a document that does not contain the element and produce a
    # confident STALE on a control that is sitting right there. A main-frame
    # ref takes the same path it always did, with no frame work at all.
    context = record.page
    occlusion_chain: list = []
    if entry.frame:
        home = await _frame_context(record, entry.frame, tool=tool, ref=ref)
        context = home.frame
        occlusion_chain = _frames_path(home)
    data = await extract(context, pin=pin)
    outcome = ladder.resolve(sess.element_map, ref, data, record.handle)
    verdict = outcome["outcome"]
    if verdict in (Outcome.OK, Outcome.REBOUND):
        unit = outcome["unit"]
        node_ref = unit.get("ref")
        handle = await _handle(context, node_ref)
        if handle is None:
            raise StaleAnchor(
                f"{ref!r} resolved to an element that is no longer in the DOM. "
                f"Re-read the page and use the ref it returns.")
        # The live resolver filters cloaked candidates out before they can be
        # chosen; the REF path has no such filter, so an element that was
        # visible when the ref was minted and is invisible now gets the same
        # answer here (gauntlet 2 H2).
        if acting:
            await refuse_if_cloaked(context, handle, tool=tool,
                                    chain=occlusion_chain,
                                    shooter=record.page)
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
                # Both names are page-authored, and the new one is authored
                # by the page that just renamed the control under a reused
                # key, so they ride the envelope too (gauntlet 4, G4-08).
                raise TargetChanged(
                    f'{ref!r} still carries its stable attribute key, but '
                    f'the element wearing that key is no longer what you '
                    f'read. Acting on a renamed control through a reused key '
                    f'is how the wrong element gets clicked, so nothing was '
                    f'done. Re-read the page (get_page_view or '
                    f'find_elements) and act on the ref that read returns '
                    f'if the renamed control is really the one you want.\n'
                    + _pagedata.wrap_line(
                        f'it was {entry.anchor.get("role")} "{old_name}" and '
                        f'is now {unit.get("role")} "{new_name}"',
                        url=record.page.url))
            rebound = (f'{ref} was rebound: {outcome.get("was")} -> '
                       f'{outcome.get("now")} (tier {outcome.get("tier")})')
        return {"handle": handle, "node_ref": node_ref, "session_ref": ref,
                "unit": unit, "context": context, "frame": entry.frame,
                "chain": occlusion_chain,
                "descriptor": target_descriptor(unit),
                "resolution": "rebound" if verdict == Outcome.REBOUND else "ok",
                "rebound": rebound}
    # Every non-proceeding outcome is a typed, recovery-naming refusal.
    if verdict == Outcome.MODAL:
        # The modal's name is whatever the page called it, so it rides the
        # labeled envelope rather than sitting bare in a sentence the server
        # appears to be making.
        raise ModalBlocked(
            f'a page-drawn modal is open and blocks interaction, so nothing '
            f'was done. {outcome.get("recovery")}. '
            + _pagedata.wrap_line(f'modal: {outcome.get("dialog")}',
                                  url=record.page.url))
    if verdict == Outcome.AMBIGUOUS:
        # THE CANDIDATE NAMES RIDE THE ENVELOPE (gauntlet 4, G4-08), like the
        # modal name above them and like `find_elements` and `find_and_act`
        # already do with the identical strings. An accessible name is
        # page-authored, up to eight of them land in this sentence, and this
        # is the direct `click` path — the most-used one in the product.
        raise AmbiguousLocation(
            f'{ref!r} no longer resolves to one element '
            f'({outcome.get("tier")}). Candidates:\n'
            + _pagedata.wrap_line(
                _candidate_text(outcome.get("candidates")),
                url=record.page.url)
            + f'\n{outcome.get("recovery")}')
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


async def _resolve_live(sess, record, location: dict, *, tool: str,
                        acting: bool = True) -> dict:
    if "anchor" in location:
        raise BadParams(
            "the {'anchor': ...} selector addresses a durable anchor id, which "
            "surfaces only in audit records and saved workflows (DESIGN 3.5). "
            "Address a live element by ref, css, text, role+name, or testid; "
            "anchor-driven replay runs through run_workflow, which re-resolves "
            "stored anchors itself.")
    # THE SWEEP. The main document plus every same-origin frame, unless the
    # location names one frame, in which case that frame and nothing else.
    # Ambiguity is judged across the UNION: two matches in two frames are two
    # matches, and acting on whichever document answered first is exactly the
    # first-match behaviour this resolver refuses everywhere else.
    from ..engine import frames as _frames

    named = (location or {}).get("frame")
    targets: list = []
    chains: dict = {}
    if named:
        home = await _frame_context(record, str(named), tool=tool, ref=None)
        targets = [(home.fid, home.frame)]
        chains[home.fid] = _frames_path(home)
    else:
        targets = [("", record.page)]
        tree = await _frames.ladder(record)
        for fr in _frames.entered(tree):
            if not fr.is_main:
                targets.append((fr.fid, fr.frame))
                chains[fr.fid] = _frames.path(fr)
    found = None
    per_frame: list = []
    for fid, target in targets:
        try:
            got = await target.evaluate(_RESOLVE_JS, {"location": location})
        except Exception:
            continue                 # a frame that navigated mid-resolution
        if got.get("error"):
            if found is None:
                found = got
            continue
        per_frame.append((fid, target, got))
        if found is None or found.get("error"):
            found = got
    if found is None:
        raise TargetNotFound(
            "no document on this page could be searched for that selector: "
            "every frame this build may enter went away while resolving it. "
            "Re-read the page and try again.")
    if found.get("error"):
        raise BadParams(
            f'the selector did not resolve: {found["error"]}. Check the css or '
            f'xpath syntax, or address the element by ref from a read.')
    count = sum(g.get("count", 0) for _, _, g in per_frame)
    hits = [(fid, target, g) for fid, target, g in per_frame
            if g.get("count", 0)]
    fid, target = "", record.page
    if len(hits) == 1:
        # ONE realm answered, so it is the one every branch below speaks
        # about. Without this rebind the single-realm ambiguity refusal below
        # listed the candidates of whichever document answered FIRST, which on
        # a framed page is a document with no matches at all: the count said
        # two and the candidate list said none.
        fid, target, found = hits[0]
    if count > 1 and len(hits) > 1:
        # Candidates from several realms. The refusal names the frame each one
        # is in, because "two buttons called Pay" reads very differently once
        # you know one of them is in an embedded widget.
        candidates = []
        for fid, _, g in hits:
            for cand in (g.get("candidates") or []):
                candidates.append({**cand,
                                   "where": fid or "the main document"})
        raise AmbiguousLocation(
            f'{count} visible elements match ({found.get("how")}) across '
            f'{len(hits)} document(s) on this page; no tool acts on first '
            f'match, and a frame boundary is not a tie-break. Candidates:\n'
            + _pagedata.wrap_line(_candidate_text(candidates),
                                  url=record.page.url)
            + '\nNarrow with {"frame": "ifN"}, or read the page and use a '
              'ref.')
    if count == 1:
        handle = await _handle(target, found["ref"])
        if handle is None:
            raise StaleAnchor(
                "the element left the DOM between resolving it and acting on "
                "it. Re-read the page and try again.")
        # The resolver's own candidate filter already drops every STYLED cloak
        # (it shares `visibility.js` with the read), so this adds exactly one
        # technique: OCCLUSION, which is computed on the acting path only
        # because it costs a page scan (re-attack R4). Without this the live
        # selector path was the way around it: `click(location={'css': ...})`
        # on a button buried under an opaque panel.
        if acting:
            await refuse_if_cloaked(target, handle, tool=tool,
                                    chain=chains.get(fid) or [],
                                    shooter=record.page)
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
            shim = {"identity": {"url": found.get("url") or record.page.url,
                                 "page_key": found.get("page_key", "")},
                    "affordances": [shim_unit], "regions": [],
                    "headings": [], "forms": [], "tables": []}
            sess.element_map.absorb(
                shim, record.handle, sess.reads.mint_token(record.handle),
                ts=_time.strftime("%Y-%m-%dT%H:%M:%S"), scope="resolve",
                frame=fid)
            session_ref = shim_unit["ref"]
        return {"handle": handle, "node_ref": found["ref"],
                "session_ref": session_ref, "unit": unit,
                "context": target, "frame": fid,
                "chain": chains.get(fid) or [],
                "descriptor": target_descriptor(unit), "resolution": "ok",
                "rebound": None}
    if count and count > 1:
        raise AmbiguousLocation(
            f'{count} visible elements match ({found.get("how")}); no tool '
            f'acts on first match. Candidates:\n'
            + _pagedata.wrap_line(
                _candidate_text(found.get("candidates")),
                url=record.page.url)
            + '\nNarrow the selector, or read the page and use a ref.')
    # Nearest misses from EVERY realm swept, not only the first to answer.
    # The whole job of the list is to turn a dead end into one more turn, and
    # a page that put the control in a frame is exactly the case where the
    # main document has nothing near to offer.
    misses = []
    for _, _, g in per_frame:
        misses.extend(g.get("nearest") or [])
    misses = misses[:6]
    swept = len(targets)
    hint = ("\nNearest by name:\n"
            + _pagedata.wrap_line(_candidate_text(misses),
                                  url=record.page.url)) if misses else \
        (" No near misses either; the target may be inside a cross-origin "
         "iframe, a closed shadow root, or content that has not rendered "
         "yet. Open shadow roots were searched"
         + (f", and so were {swept - 1} same-origin frame(s)"
            if swept > 1 else "") + ".")
    raise TargetNotFound(
        f'nothing visible matches this selector ({found.get("how")}).{hint}')


_HANDLE_JS = instrument(r"""
(r) => {
// @@KS4WEB_INSTRUMENT@@
  const el = KS.refs.get(r);
  return (el && el.isConnected) ? el : null;
}
""")


async def _handle(page, node_ref: str):
    # THE FINAL HANDLE, and the one line gauntlet 2's H5 rode. It used to read
    # `window.__ks4web_refs`, a main-world global any page script could
    # replace: a `class Poisoned extends Map` returned the attacker's button
    # for every key, the trusted click landed there, and the result still
    # reported the name the model had asked for. The registry now lives in the
    # instrument channel's closure, which the page can neither read nor write,
    # so there is nothing here to poison.
    #
    # The isConnected check matters for the ordinary case: a detached element
    # still answers `as_element()`, and acting on it either fails late with a
    # driver timeout or, worse, lands on nothing while reporting motion.
    jsh = await page.evaluate_handle(_HANDLE_JS, node_ref)
    element = jsh.as_element()
    if element is None:
        await jsh.dispose()
        return None
    return element


#: The cloaking refusal (gauntlet 2 H2). An element that is laid out,
#: hit-testable, and dispatches trusted input while a human cannot see it is
#: not a target: a page that can steer the agent onto an invisible control has
#: the agent's trusted click. Named techniques only, because geometry is a
#: layout fact the driver scrolls to rather than a disguise.
_CLOAK_JS = instrument(r"""
(el) => {
// @@KS4WEB_VISIBILITY@@
  const r = ksCloakReason(el);
  return r ? { reason: r, why: KS_CLOAK_TECHNIQUES[r] } : null;
}
""")


#: THE ARMING PROBE (re-attack 2 A7, widened by re-attack 3 R3). Focus, let
#: the page's own queued work run, then take the cloak verdict, all inside one
#: round trip and immediately before the dispatch.
#:
#: A7 put the focus and the verdict in ONE JS TURN, so a handler that appends
#: a lid SYNCHRONOUSLY is caught by the very check its own handler triggered.
#: R3 walked through the difference between a turn and a window: a
#: `queueMicrotask` inside the focus handler runs after that turn's
#: synchronous body and before the dispatch, so the lid was up at the click
#: and down at the verdict, witnessed by the page's own click listener. A
#: `requestAnimationFrame` and a `MutationObserver` callback are the same
#: window one queue along, and it is deterministic rather than a timing race.
#:
#: So the probe now takes TWO verdicts. The first is A7's, unchanged, and it
#: still refuses the synchronous lid before anything else happens. Then it
#: yields exactly as far as the page can schedule without a timer -- one
#: animation frame, which drains the microtask queue on the way and puts the
#: frame's own callbacks behind it, and one task turn after that -- drops the
#: paint caches, and asks again. Nothing the focus handler queued is still
#: pending when the second verdict is read, and no page JS runs between that
#: verdict and the trusted input.
#:
#: `preventScroll` keeps the viewport where the verdict was taken. The
#: residual is stated rather than papered over and is now genuinely a TIMER: a
#: lid raised on `setTimeout(…, 40)`, or by the trusted click's own mousedown,
#: lands after any pre-dispatch check a driver can make.
#:
#: The frame wait carries a CEILING rather than a race, and the difference is
#: the whole reliability of the second verdict. A ceiling short enough to be a
#: normal outcome abandons the frame on any page whose renderer is cold: a
#: freshly loaded document takes 50-60ms to produce its first frame against a
#: 5-15ms steady state, so a 50ms cap lost the race on the first two loads out
#: of twelve and read its verdict before the lid was up. The ceiling exists
#: only for a page the browser has stopped animating -- a background tab, a
#: throttled renderer -- where the callback never comes at all and a probe
#: that hangs is worse than one that gives up. Whichever arrives first, the
#: probe still goes through one task turn afterward, so a `queueMicrotask` lid
#: is caught even where no frame is ever produced.
#: TWO FRAMES, NOT ONE (gauntlet 4, G4-09). One frame put the second verdict
#: in the SAME animation-frame batch as the lid the page's own `focus` handler
#: queued, behind it in callback order, which is enough to SEE the appended
#: node and is not enough for the browser to have painted it. That matters
#: because `occluded` is the one verdict the pixel arbiter re-decides against
#: the compositor: it photographs the control with the lid in the paint and
#: again with it out, and if the lid has not been composited yet the two
#: frames are identical, the arbiter clears a real occlusion, and the trusted
#: click lands on a control a human cannot see. The gauntlet measured that
#: miss at roughly one run in eight standalone and two in three inside its own
#: battery, where more browser churn shifts the timing — a cloak check whose
#: answer depends on how fast the machine is, which is the failure mode this
#: family exists to rule out. Yielding a second frame commits the first
#: frame's paint before anything is observed or photographed. The ceiling
#: covers the whole wait rather than each frame, and it is raised to keep the
#: same margin the one-frame version had over a cold renderer's 50-60ms first
#: frame; it is paid only where the browser has stopped producing frames at
#: all, and the task turn afterwards still catches a `queueMicrotask` lid on a
#: renderer that never animates.
_ARM_FRAME_CEILING_MS = 400

_ARM_JS = instrument(r"""
async (el) => {
// @@KS4WEB_VISIBILITY@@
  try { el.focus({ preventScroll: true }); } catch (e) {}
  let r = ksCloakReason(el);
  if (r) return { reason: r, why: KS_CLOAK_TECHNIQUES[r] };
  await new Promise(function (done) {
    let settled = false;
    const finish = function () {
      if (settled) return;
      settled = true;
      setTimeout(done, 0);
    };
    requestAnimationFrame(function () { requestAnimationFrame(finish); });
    setTimeout(finish, __KS_FRAME_CEILING__);
  });
  ksResetPaintCaches();
  r = ksCloakReason(el);
  return r ? { reason: r, why: KS_CLOAK_TECHNIQUES[r] } : null;
}
""".replace("__KS_FRAME_CEILING__", str(_ARM_FRAME_CEILING_MS)))


#: THE PIXEL ARBITER's three page-side steps (re-attack 3, R4). `prep` re-runs
#: the box math and, where it flags, tags the candidate lids and returns the
#: screen area a human would be looking at; `hide` installs the rules that take
#: those lids out of the paint; `release` undoes both. They are three calls
#: rather than one because a screenshot happens between them, and a screenshot
#: is a Python-side operation.
#: `prep` YIELDS A FRAME FIRST (gauntlet 4, G4-09). The arbiter's whole
#: method is a difference between two renders, so a lid the box math can
#: already see but the compositor has not painted yet reads as identical in
#: both photographs and clears an occlusion that is really there. One frame
#: before the shutter opens costs about 16ms on a path that is already
#: spending two screenshots, and it is only ever reached once the geometry
#: has flagged.
_PIXEL_PREP_JS = instrument(r"""
async (el) => {
// @@KS4WEB_VISIBILITY@@
  await new Promise(function (done) {
    let settled = false;
    const finish = function () { if (settled) return; settled = true; done(); };
    requestAnimationFrame(finish);
    setTimeout(finish, 250);
  });
  const p = ksPixelPrep(el);
  if (!p) return null;
  p.epoch = [document.documentElement.scrollWidth,
             document.documentElement.scrollHeight,
             Math.round(window.scrollX), Math.round(window.scrollY),
             document.getElementsByTagName('*').length].join(':');
  return p;
}
""")

_PIXEL_HIDE_JS = instrument(r"""
() => {
// @@KS4WEB_VISIBILITY@@
  return ksPixelHide();
}
""")

_PIXEL_RELEASE_JS = instrument(r"""
() => {
// @@KS4WEB_VISIBILITY@@
  return ksPixelRelease();
}
""")

#: How long the arbiter took, in milliseconds, most recent call first. The
#: cost of confirming a refusal against the compositor is a number this build
#: has to be able to state, so it is measured rather than estimated.
PIXEL_ARBITER_MS: list[float] = []


async def _pixel_confirms_occlusion(page, handle, *, shooter=None,
                                    offset=None) -> bool:
    """Ask the compositor whether the flagged lids actually conceal anything.

    Returns True when the control's own area renders DIFFERENTLY with the
    candidate lids in the paint than without them, which is what "something is
    on top of it" means in the only vocabulary that matters. Returns False
    when the two renders are byte-identical: the lids paint nothing over the
    control and a refusal would strip a working interface off a real page.

    A probe that cannot run CONFIRMS, because the box math has already flagged
    and a screenshot that fails is not evidence of innocence. The one honest
    exception is an area no screenshot can address -- a control scrolled
    entirely out of the viewport -- and geometry answers for that case before
    this one is reached.

    Cached per LAYOUT EPOCH: within one page state, the same clip and the same
    lid count give the same answer, and an acting call that resolves, arms,
    and re-checks would otherwise pay for three identical comparisons.
    """
    start = time.perf_counter()
    prep = None
    try:
        prep = await page.evaluate(_PIXEL_PREP_JS, handle)
        if not prep:
            return False                # the box math no longer flags
        cache = getattr(page, "_ks4web_pixel_cache", None)
        if cache is None:
            cache = {}
            try:
                page._ks4web_pixel_cache = cache
            except Exception:
                pass
        key = (prep["epoch"], prep["x"], prep["y"], prep["width"],
               prep["height"], prep["lids"])
        if key in cache:
            return cache[key]
        # A frame reports its rectangles in its OWN viewport and the camera is
        # the page's, so the clip is shifted down the frame chain before the
        # shutter opens. Without the shift the arbiter photographs a
        # rectangle in the page chrome, finds it identical in both renders,
        # and clears an occlusion that is really there.
        dx = (offset or {}).get("x", 0.0)
        dy = (offset or {}).get("y", 0.0)
        camera = shooter if shooter is not None else page
        clip = {"x": prep["x"] + dx, "y": prep["y"] + dy,
                "width": prep["width"], "height": prep["height"]}
        as_is = await camera.screenshot(clip=clip, animations="disabled")
        await page.evaluate(_PIXEL_HIDE_JS)
        without = await camera.screenshot(clip=clip, animations="disabled")
        verdict = as_is != without
        cache[key] = verdict
        return verdict
    except Exception:
        return True
    finally:
        if prep is not None:
            try:
                await page.evaluate(_PIXEL_RELEASE_JS)
            except Exception:
                pass
        PIXEL_ARBITER_MS.insert(0, (time.perf_counter() - start) * 1000)
        del PIXEL_ARBITER_MS[32:]


async def _arbitrate(page, handle, verdict, *, shooter=None, offset=None):
    """Let the compositor rule on an `occluded` verdict before it refuses.

    Every OTHER cloak technique is a property of the element itself -- its own
    opacity, its own filter, its own colour against its own background -- and
    the style already is the answer. `occluded` is the one verdict that is a
    claim about OTHER boxes, computed from their declared geometry and their
    declared alpha, and re-attack 3 showed both of those declarations diverging
    from what the browser paints in seven ordinary constructions. So this is
    the only verdict that gets a second opinion, and the second opinion is the
    rendering itself."""
    if not verdict:
        return verdict
    reason = verdict if isinstance(verdict, str) else verdict.get("reason")
    if reason != "occluded":
        return verdict
    if await _pixel_confirms_occlusion(page, handle, shooter=shooter,
                                       offset=offset):
        return verdict
    return None


def _refuse_cloak_verdict(verdict, tool: str) -> None:
    """One refusal text for every path that takes a cloak verdict."""
    if not verdict:
        return
    if isinstance(verdict, str):
        verdict = {"reason": verdict, "why": _CLOAK_WHY.get(verdict, verdict)}
    # THE CROSS-CHECK CLAIM IS NOW TRUE OF ONLY THE CASES IT HOLDS FOR
    # (hostile H-09). The sentence used to promise that "the read's
    # completeness block counts it as hidden interactive with the technique
    # named" for EVERY cloak verdict, and for an opaque panel over the whole
    # viewport it did not: per-element occlusion is computed on the acting
    # path, deliberately, for the cost reason `visibility.js` documents, so
    # a read taken a moment earlier listed the covered control and said
    # "unlisted affordances: none, every control is listed". A refusal that
    # advertises a cross-check the read demonstrably fails to produce is
    # worse than one that says nothing: it tells an agent to trust a block
    # that contradicts it.
    occluded = verdict.get("reason") == "occluded"
    where = (
        "The read surfaces do not compute per-element occlusion (it costs a "
        "page-wide scan and up to nine hit tests per control, on every "
        "read), so this verdict is the acting path's own. A read taken now "
        "names an opaque panel covering the viewport where there is one."
        if occluded else
        "The content is still readable through the labeled route, "
        "get_text(include_hidden=true), and the read's completeness block "
        "counts it as hidden interactive with the technique named.")
    raise TargetNotFound(
        f'{tool} will not act on this element: it is in the page and a human '
        f'cannot see it ({verdict["why"]}). A control that is invisible and '
        f'still clickable is how a page steers an agent onto something the '
        f'user never saw, so nothing was done. {where}')


#: The Python mirror of `KS_CLOAK_TECHNIQUES`, for the paths that receive a
#: bare reason string (the write-time re-check reads it off the live field
#: probe rather than running the cloak probe a second time).
_CLOAK_WHY = {
    "opacity-0": "its opacity is zero",
    "near-transparent": "its opacity is near zero",
    "filter-transparent": "a CSS filter reduces it to full transparency",
    "filter-blur": "a CSS filter blurs it past legibility",
    "transparent-text": "its foreground colour is transparent",
    "low-contrast": "its foreground colour matches its background",
    "content-visibility-hidden": "content-visibility:hidden stops it rendering",
    "details-collapsed": "it sits inside a collapsed <details>",
    "unslotted": "it is a light child of a component that never slotted it",
    "visibility-hidden": "visibility:hidden stops it rendering",
    "occluded": "an opaque panel is painted over it",
}


#: A hidden iframe hides everything in it, and nothing inside the frame can
#: know that. The frame-local scan asks the frame's own document about the
#: element's own styling and the frame's own overlays; this asks the PARENT
#: about the box the whole frame is painted into. Both halves are required:
#: an element can be perfectly visible in its frame's coordinate space while
#: the frame element itself sits under a full-page consent wall.
def _refuse_frame_chain(chain, tool: str) -> None:
    for fr in chain or ():
        if fr.hidden:
            raise TargetNotFound(
                f'{tool} will not act on this element: it is inside frame '
                f'{fr.fid}, and the frame itself is not visible to a human '
                f'({fr.hidden}). The element is laid out and clickable in '
                f'its own document, which is exactly how a page steers an '
                f'agent into a frame nobody can see, so nothing was done. '
                f'The content is still readable through the labeled route, '
                f'get_text(include_hidden=true).')


async def _refuse_if_frame_occluded(chain, *, tool: str, shooter) -> None:
    """Run the cloak verdict on every `<iframe>` element on the way down.

    OCCLUSION IS THE ONE VERDICT THE FRAME CANNOT COMPUTE FOR ITSELF. Every
    other technique is a property of the element and its own document, and the
    frame's own scan already answers those. A full-page consent wall dropped
    over an embedded checkout is a fact about the PARENT's boxes: inside the
    frame the button is laid out, hit-testable, and perfectly visible in its
    own coordinate space, and a click on it lands on the wall.

    Each hop is arbitrated by the compositor the same way a top-level
    occlusion is, with the clip shifted by the offset of the frame ABOVE the
    one being checked, because that is the viewport the box was measured in.
    """
    for fr in chain or ():
        parent = getattr(fr, "parent", None)
        if parent is None or not fr.node_ref:
            continue
        el = await _handle(parent.frame, fr.node_ref)
        if el is None:
            continue
        try:
            verdict = await parent.frame.evaluate(_CLOAK_JS, el)
        except Exception:
            continue                # a probe that cannot run never refuses
        verdict = await _arbitrate(parent.frame, el, verdict, shooter=shooter,
                                   offset=parent.offset)
        if verdict:
            why = verdict["why"] if isinstance(verdict, dict) else verdict
            raise TargetNotFound(
                f'{tool} will not act on this element: it is inside frame '
                f'{fr.fid}, and the frame itself is not visible to a human '
                f'({why}). Inside its own document the element is laid out '
                f'and clickable, which is the whole trick: the frame cannot '
                f'see what the page painted over it, so nothing was done. '
                f'The content is still readable through the labeled route, '
                f'get_text(include_hidden=true).')


async def refuse_if_cloaked(page, handle, *, tool: str, chain=(),
                            shooter=None) -> None:
    """Refuse to act on an element a human cannot see, naming the technique.

    The hidden route stays open: `get_text(include_hidden=True)` reports the
    content, and the completeness block counts the control. What closes is
    ACTING on it, which is the half a hostile page wants.

    `chain` is the frame chain from the main document down to this element's
    own frame. The visibility question crosses frame boundaries in one
    direction only: a parent can hide a child frame entirely and the child
    cannot tell, so the chain is checked as well as the frame-local styling.
    """
    _refuse_frame_chain(chain, tool)
    await _refuse_if_frame_occluded(chain, tool=tool,
                                    shooter=shooter or page)
    try:
        verdict = await page.evaluate(_CLOAK_JS, handle)
    except Exception:
        return                      # a probe that cannot run never refuses
    offset = chain[-1].offset if chain else None
    _refuse_cloak_verdict(
        await _arbitrate(page, handle, verdict, shooter=shooter,
                         offset=offset), tool)


async def arm_for_dispatch(page, handle, *, tool: str, resolved=None) -> None:
    """Focus the target and re-take the cloak verdict, in that order, in one
    JS turn, immediately before the input is dispatched.

    ORDER OF OPERATIONS, not a new scan (A7). The cloak check at resolution
    answers a question about the page as it was several round trips earlier,
    and the acting path's own focus is an event the page observes. Focusing
    HERE means the handler that raises a lid has raised it before the verdict
    is read, and a call that would have clicked an invisible button refuses
    instead. The focus is not extra exposure either: a trusted click focuses
    the control anyway, so this only moves the moment earlier than the check.

    `resolved` is the resolution this action came from. It carries the frame
    the element lives in, and an element inside a frame is armed in the
    FRAME's realm: focusing it through the page's document focuses nothing,
    and reading the cloak verdict from the wrong document reads the wrong
    page's overlays.
    """
    target = (resolved or {}).get("context") or page
    chain = (resolved or {}).get("chain") or ()
    _refuse_frame_chain(chain, tool)
    # The lid can go up between the resolution and the dispatch, and a lid
    # over the FRAME is the one a page raises when it wants the click to land
    # somewhere else, so this hop is re-taken here too rather than trusted
    # from several round trips ago.
    await _refuse_if_frame_occluded(chain, tool=tool, shooter=page)
    try:
        verdict = await target.evaluate(_ARM_JS, handle)
    except Exception:
        return                      # a probe that cannot run never refuses
    _refuse_cloak_verdict(
        await _arbitrate(target, handle, verdict, shooter=page,
                         offset=(chain[-1].offset if chain else None)), tool)


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
