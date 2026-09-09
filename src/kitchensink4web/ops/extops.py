"""The Lane C tool bodies: the same policy, over a different wire.

THE FIFTH PATH. `act.action_class_for`'s docstring names four write paths and
says a fifth cannot be added that quietly skips the classifier. This module
is that fifth path, and it is written to be held to the same pin: every
function here that changes anything computes its class through
`act.action_class_for` and routes it through the one `policy.engine.approve`,
with the same `ActionRequest` fields the Playwright tools fill in.

**Why this is a separate module rather than lane branches inside `lite.py`.**
The read path shares almost everything and the ACT path shares almost
nothing: `ops/act.py` resolves through Playwright JSHandles, arms an
occlusion probe against a live element handle, and dispatches through the
driver's trusted-input machinery, none of which exists on this lane. Threading
that through seven thousand lines would leave a reader unable to tell which
branch runs, and this layer's whole argument is that a reader can tell.

**What IS shared, and it is the part that matters.** The read runs the same
`extract.js` the other lanes run, absorbs into the same element map, renders
through the same projection, and classifies through the same functions over
the same units. The gate verdict on Lane C is not a second implementation
that agrees; it is the first implementation, called again.

**The honest gaps, named here and reported in the payloads:**

- No frame descent. Phase 2 reads the top frame; the frame ladder, the
  cross-origin count, and the same-origin stitch are not built for this lane
  and the completeness block says the ladder was not walked rather than
  reporting a page with no frames in it.
- No navigation status. The lane cannot see one (see
  `lanes.CAPABILITIES["navigation_status"]`), so it is None and the wall
  classifier reads the document instead.
- No dialog desk, no crash listener, no popup adoption. An extension is not
  told about any of the three.
"""

from __future__ import annotations

import time

from .. import anchors as _anchors
from .. import pagedata as _pagedata
from .. import projection as _projection
from ..engine import lanes
from ..errors import (BadParams, Conflict, LaneUnsupported,
                      TargetNotFound)
from ..extension import lane as _extlane
from ..policy import audit as _audit
from ..policy import engine as _policy
from ..projection import ENCODING_NAME as _ENCODING
from ..projection import RUNGS as _RUNGS
from ..projection import ntok as _ntok
from ..projection.render import VIEWS as _PROJECTION_VIEWS
from . import act as _actlib

#: The same scale `lite.get_page_view` applies, imported by value rather than
#: by reference so this module does not import `lite` (which imports this one
#: to dispatch). A test pins the two equal, because a Lane C `detail='full'`
#: that meant something different from a Lane A `detail='full'` would be the
#: quiet kind of lane difference this whole subsystem argues against.
DETAIL_SCALE = {"lite": 0.5, "standard": 1.0, "full": 2.0}


def is_extension(sess) -> bool:
    """Whether this session is Lane C. Asked at the top of every tool."""
    return getattr(getattr(sess, "spec", None), "engine", None) == "extension"


def _node_ref(sess, record_handle: str | None, ref: str) -> str | None:
    """The IN-PAGE id behind a session ref.

    Two different names for one element and the difference is load-bearing:
    `e12` is the sticky ref the caller holds across reads, and the node ref
    is the key the page's own registry answers to. The map keeps the pairing
    per page handle, merged across reads, and an act has to send the second
    one because the first means nothing inside the document.
    """
    table = sess.element_map.node_refs
    if record_handle is not None:
        return (table.get(record_handle) or {}).get(ref)
    for pairs in table.values():
        if ref in pairs:
            return pairs[ref]
    return None


def _page(record) -> _extlane.ExtensionPage:
    page = record.page
    if not isinstance(page, _extlane.ExtensionPage):     # pragma: no cover
        raise LaneUnsupported(
            f"{record.handle} is not an extension page; this call was routed "
            f"to the Lane C body for a session that is not on Lane C.")
    return page


# ------------------------------------------------------------------- reading


def _meta(sess, record, token: str, ts: str) -> dict:
    return {
        # NOT A NUMBER, AND NOT A ZERO. An extension cannot see the status of
        # a top-level navigation, so the field is an absence and the lane
        # table says why. A 200 written here would be the most expensive
        # single wrong value in the payload: every wall verdict downstream
        # reads it.
        "status": None,
        "load_state": getattr(record, "last_load_state", "load"),
        "lane": sess.spec.label,
        "page": record.handle,
        "read_token": token,
        "ts": ts,
        "partial": None,
    }


async def get_page_view(sess, record, *, view: str = "auto",
                        detail: str = "standard", location: dict | None = None,
                        budget_tokens: int = 5000, since: str | None = None,
                        mode: str = "auto") -> dict:
    """The cheap first read, over the extension.

    Same extractor, same ranker, same meter, same render ladder, same sticky
    refs. What differs is the transport and two honest absences in the
    completeness block."""
    if view not in _PROJECTION_VIEWS:
        raise BadParams(
            f"unknown view {view!r}. This build serves "
            f"{sorted(_PROJECTION_VIEWS)}.")
    if detail not in DETAIL_SCALE:
        raise BadParams(
            f"unknown detail {detail!r}; the levels are "
            f"{sorted(DETAIL_SCALE)}.")
    mode = (mode or "auto").strip().lower().replace("-", "_")
    if mode in ("all_affordances", "all", "prose_links"):
        mode = "links"
    if mode not in ("auto", "links"):
        raise BadParams(
            f"unknown mode {mode!r}: 'auto' (the default) or 'links'.")
    page = _page(record)
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=page.url, lane=sess.spec.label)
    budget = max(200, int(budget_tokens * DETAIL_SCALE[detail]))
    sess.bump("reads", page=record.handle)
    root = _scope_root(sess, location)
    token = sess.reads.mint_token(record.handle)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta = _meta(sess, record, token, ts)

    state: dict = {}

    def absorb(data: dict, frame: str = "") -> None:
        state["read"] = sess.element_map.absorb(
            data, record.handle, token, ts=ts, scope=root, frame=frame,
            into=state.get("read"))

    baseline = sess.reads.get(record.handle, since) if since else None
    if baseline is not None and baseline.scope != root:
        raise BadParams(
            f"since={since!r} was a "
            f"{'whole-page' if baseline.scope is None else 'scoped'} read and "
            f"this call is "
            f"{'whole-page' if root is None else 'scoped'}. A delta across "
            f"two different scopes would report everything outside the "
            f"narrower one as removed, which is a lie about the page rather "
            f"than a delta.")

    result = await _projection.read_page(page, meta, budget=budget, view=view,
                                         root=root, absorb=absorb, mode=mode)
    if isinstance(result, dict) and result.get("error"):
        raise TargetNotFound(
            f'location named {result.get("asked_for")!r} and that ref is not '
            f'on {record.handle} any more. Refs are invalidated by a '
            f'navigation and by a page close. Re-read the page and use the '
            f'ref it returns.')
    sess.reads.put(state["read"])
    record.touch(page.url)

    projection, page_note = _pagedata.wrap(result.text, url=page.url)
    payload = {
        "page": record.handle, "session": sess.session_id,
        "url": page.url, "lane": sess.spec.lane,
        "read_token": token,
        "scope": location if location else "whole page",
        "projection": projection,
        "page_data": page_note,
        "budget": {"used": result.tokens, "limit": budget,
                   "margin_held": result.meter.margin, "rung": result.rung,
                   "rungs": len(_RUNGS), "estimator": _ENCODING},
        "lane_notes": lane_notes(sess),
    }
    if page.webdriver is not None:
        # Phase 1's rule, kept: the claim the whole architecture rests on is
        # reported on every read rather than argued once in a design
        # document. A True here is a finding, not a formality.
        payload["webdriver"] = page.webdriver
    if baseline is not None:
        delta = _anchors.diff(baseline, state["read"])
        if delta["navigated"] and not sum(delta["stable"].values()):
            payload["delta"] = {
                "since": delta["since"], "read": delta["read"],
                "navigated": True, "stable": delta["stable"],
                "fell_back_to_full_read": True,
                "url_before": delta["url_before"],
                "url_after": delta["url_after"],
                "why": (f'the page navigated from {delta["url_before"]} to '
                        f'{delta["url_after"]} and no unit survived it, so a '
                        f'delta would cost more than the full read above.'),
            }
            return payload
        rendered = _anchors.render(delta, record.handle)
        payload["projection"], payload["page_data"] = _pagedata.wrap(
            rendered, url=page.url)
        payload["delta"] = {k: delta[k] for k in
                            ("since", "read", "navigated", "stable")}
        payload["budget"]["used"] = _ntok(rendered)
    return payload


#: The absences this lane carries, in one place so every payload says the
#: same thing and none of them says it twice. Read off the capability table
#: rather than written out again here, because a row that changed there and
#: not here would leave the payload making a claim the table contradicts.
def lane_notes(sess) -> dict:
    spec = sess.spec
    notes = {
        name: lanes.CAPABILITIES[name].get("message", "")
        for name in ("closed_shadow_count", "navigation_status",
                     "full_page_screenshot", "trusted_events")
        if lanes.capability(spec, name) != "ok"
    }
    notes["frames"] = (
        "this read covered the top frame only. Frame descent is not built "
        "for the extension lane yet, so the completeness block does not "
        "report a frame ladder rather than reporting an empty one."
    )
    return notes


def _scope_root(sess, location: dict | None) -> str | None:
    """A ref-shaped location, turned into the in-page id the extractor scopes
    on. The rest of the location grammar belongs to a search, which returns a
    ref, so the two compose."""
    if not location:
        return None
    ref = (location.get("ref") or location.get("region")
           or location.get("form") or location.get("table"))
    if not ref:
        raise BadParams(
            f"lane C scopes a read by ref: pass location={{'ref': 'e12'}} "
            f"using a ref a previous read returned. The role/name, text, "
            f"css, and xpath spellings are resolved by a search pass that is "
            f"not built for this lane yet. Got {sorted(location)}.")
    node_ref = _node_ref(sess, record_handle=None, ref=ref)
    if node_ref is None:
        raise TargetNotFound(
            f"{ref!r} is not a ref this session minted. Read the page and "
            f"use the refs it returns.")
    return node_ref


# -------------------------------------------------------------- navigating


async def navigate(sess, record, *, action: str = "goto",
                   url: str | None = None, wait_until: str = "load",
                   timeout_ms: int = 30000) -> dict:
    """Go somewhere, through the same choke point every other lane uses."""
    page = _page(record)
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=page.url, lane=sess.spec.label)
    action = (action or "goto").strip().lower()
    if action not in ("goto", "back", "forward", "reload"):
        raise BadParams(
            f"lane C navigates with 'goto', 'back', 'forward', or 'reload'. "
            f"'stop' and 'wait_for_load' are driver operations with no "
            f"extension equivalent; a navigate here waits for the load "
            f"before it returns, so there is nothing left to wait for. Got "
            f"{action!r}.")
    if action == "goto" and not url:
        raise BadParams("navigate(action='goto') needs a url.")
    before = page.url
    dest = url if action == "goto" else (
        page.url if action == "reload" else None)
    # THE CHOKE POINT, before the browser is touched: read-only grade limits,
    # the deny-first origin policy, the 429 backoff, loop detection, and the
    # navigation budget, in that order and with the same ActionRequest the
    # Playwright lane fills in.
    _policy.approve(_policy.ActionRequest(
        tool="navigate", kind="navigate", session=sess.session_id,
        page=record.handle, url=dest,
        args={"action": action, "url": url},
        summary=f"navigate({action}) to {dest or 'history'} on "
                f"{record.handle}."))
    if action == "goto":
        # THE BROWSER-SIDE SET WIDENS HERE AND NOWHERE ELSE: after the ladder
        # passed, before the navigation. That ordering is what makes the
        # extension's own consent list a record of decisions the human's
        # policy already made rather than a second policy nobody audits.
        await sess.contexts[record.context].context.allow_origin(url)
        outcome = await page.goto(url, wait_until=_wait_word(wait_until),
                                  timeout_ms=timeout_ms)
    else:
        outcome = await page.history(action, timeout_ms=timeout_ms)
    record.touch(page.url)
    record.last_load_state = wait_until
    record.last_status = None
    invalidated = None
    if page.url != before:
        invalidated = sess.invalidate_page(
            record.handle, f"the page navigated from {before}")
    sess.bump("navigations", page=record.handle)
    payload = {
        "page": record.handle, "session": sess.session_id,
        "lane": sess.spec.lane,
        "action": action, "url": page.url, "title": outcome.get("title"),
        "settled": outcome.get("settled"),
        "elapsed_ms": outcome.get("elapsedMs"),
        "status": None,
        "lane_notes": lane_notes(sess),
    }
    if outcome.get("settled") == "timeout":
        payload["partial"] = (
            f"the load did not settle within {timeout_ms} ms. The document "
            f"on screen may be incomplete, and a read of it will be a read "
            f"of whatever arrived.")
    if invalidated:
        payload["invalidated"] = invalidated
    return payload


def _wait_word(wait_until: str) -> str:
    """The driver's load-state vocabulary, mapped onto the extension's.

    `load` and `networkidle` both settle on webNavigation.onCompleted here,
    and `networkidle` is NOT silently promised: the extension has no idle
    signal, so asking for one gets the completed event and a note rather
    than a wait that never happens and a payload that claims it did."""
    word = (wait_until or "load").strip().lower()
    if word == "domcontentloaded":
        return "domcontentloaded"
    return "complete"


# ----------------------------------------------------------------- acting


class _Walk:
    """ONE extraction of the page, and every ref it can answer.

    The walk was always the expensive thing on this lane -- fifty of a
    sixty-eight millisecond read is the in-page pass -- and phase 2 spent one
    per ref per stage: a three-field `fill_form` walked the page nine times.
    It did not have to. `extract.js` returns the WHOLE page, capped at three
    hundred affordances plus whichever ref was pinned, so the walk that
    resolves one ref has already resolved the others; what was missing was a
    place to keep the answer.

    This is that place, and it is deliberately small and short-lived. It
    holds no policy, makes no decision, and lives for one tool call.
    """

    __slots__ = ("units", "digest")

    def __init__(self, data: dict, digest: str | None) -> None:
        self.digest = digest
        self.units: dict[str, dict] = {}
        # AFFORDANCES FIRST, and `forms[].fields` is deliberately not
        # searched: a text input is an affordance in its own right and
        # carries the whole descriptor the classifier reads (secret,
        # payment, the form census, the activation delegate), while the copy
        # nested inside a form carries a short summary and an unabsorbed ref.
        # Searching the summary would find the element and hand the gate a
        # thinner descriptor than the one every other lane classifies. The
        # first writer wins here for exactly that reason, so the iteration
        # order below is load-bearing rather than incidental.
        for kind in ("affordances", "forms"):
            for unit in data.get(kind) or []:
                ref = unit.get("ref")
                if ref and ref not in self.units:
                    self.units[ref] = {"unit": unit, "ref": ref,
                                       "node_ref": unit.get("node_ref"),
                                       "kind": kind}

    def get(self, ref: str) -> dict | None:
        return self.units.get(ref)


def _ref_of(sess, record, location: dict | None, *, tool: str) -> tuple:
    """The caller's ref and the in-page id behind it, or a refusal."""
    ref = (location or {}).get("ref")
    if not ref:
        raise BadParams(
            f"{tool} on lane C takes location={{'ref': 'e12'}}, using a ref a "
            f"previous read returned. The role/name, text, css, and xpath "
            f"spellings resolve through a live search pass that is not built "
            f"for this lane yet, so they refuse here rather than resolving "
            f"differently from the way they resolve everywhere else.")
    node_ref = _node_ref(sess, record.handle, ref)
    if node_ref is None:
        raise TargetNotFound(
            f"{ref!r} is not a ref this session minted. Read {record.handle} "
            f"and use the refs it returns.")
    return ref, node_ref


async def _walk(sess, record, *, pin: str | None, ref: str) -> _Walk:
    """Read the page RIGHT NOW, and keep the whole answer.

    A fresh extraction on purpose: the descriptor the gate fingerprints and
    the descriptor the classifier reads have to describe the element as it is
    at this instant, not as it was when the caller read the page. The
    extraction is pinned to the ref so an element past the extractor's
    300-affordance cap is still in the candidate list.
    """
    page = _page(record)
    token = sess.reads.mint_token(record.handle)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    data = await _projection.extract(page, pin=pin)
    if data.get("error"):
        raise TargetNotFound(
            f"{ref!r} is not on {record.handle} any more "
            f"({data.get('error')}). Refs are invalidated by a navigation and "
            f"by a page close; re-read the page.")
    sess.element_map.absorb(data, record.handle, token, ts=ts)
    return _Walk(data, page.last_digest)


def _pick(walk: _Walk, ref: str, record) -> dict:
    found = walk.get(ref)
    if found is not None:
        return found
    raise TargetNotFound(
        f"{ref!r} was minted on {record.handle} and the element it names is "
        f"not in a fresh read of the page. It may have been removed, or the "
        f"page may have replaced it with a different element carrying the "
        f"same words; either way nothing was done.")


async def _resolve(sess, record, location: dict | None, *, tool: str) -> dict:
    """One ref, re-read from the page right now. The walk is discarded."""
    ref, node_ref = _ref_of(sess, record, location, tool=tool)
    walk = await _walk(sess, record, pin=node_ref, ref=ref)
    return _pick(walk, ref, record)


async def _act(sess, record, *, tool: str, location: dict | None,
               action: str, value=None, submitting: bool = False,
               writes_value: bool = False, walk: _Walk | None = None) -> dict:
    """ONE DOOR for every Lane C act, and the reason there is only one.

    `act.action_class_for` says a fifth write path cannot be added that
    quietly skips the classifier. This is the fifth path, and it is a single
    function so that the claim is checkable by reading rather than by
    grepping: `click`, `type_text` and `fill_form` all arrive here, and the
    class, the approval, and the TOCTOU check all happen once.

    **What phase 3 changed, and what it deliberately did not.**

    Phase 2 walked the page twice: once to build the descriptor the gate
    judges, and once after the gate so the comparison was against the page as
    it is at the moment of acting. Both walks were right and the second one
    was the point of the check. It also cost sixty-five milliseconds of every
    single act, and it left a window nobody was watching: between the second
    walk arriving in Python and the act message arriving in the browser, the
    page had a round trip to change, and nothing looked.

    So the second walk is now conditional and the check moved INTO the
    browser. The judged read carries the digest the browser took it at; the
    act carries that digest back down; the content script compares it in the
    same synchronous turn as the dispatch, with no await in between. Two
    things follow, and they are the pins this function has to keep:

    - the fast path is STRICTLY STRONGER than phase 2's, because the state is
      checked at the instant of the act rather than a round trip before it;
    - the slow path is IDENTICAL to phase 2's. A browser that will not vouch
      for the state -- a running animation, a page that mutated during the
      walk, an old content script that sends no digest at all -- returns no
      digest, and this function walks twice and compares fingerprints exactly
      as it always did.

    A guard that can only add a refusal cannot weaken the gate. The gate
    itself, `gates.fingerprint`, and `verify_execute` are untouched.
    """
    page = _page(record)
    ref, node_ref = _ref_of(sess, record, location, tool=tool)
    if walk is None or walk.get(ref) is None:
        walk = await _walk(sess, record, pin=node_ref, ref=ref)
    resolved = _pick(walk, ref, record)
    desc = _actlib.target_descriptor(resolved["unit"])
    action_class = _actlib.action_class_for(desc, submitting=submitting)
    summary = _summary(tool, desc, record.handle)
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=page.url, lane=sess.spec.label)
    # THE CHOKE POINT. Read-only grade, credential blindness, origin policy,
    # the 429 backoff, loop detection, the action budget, and the
    # confirmation gate, in that order. Identical call shape to the
    # Playwright tools': the same fields, the same classifier's answer, and
    # the same `writes_value` flag that makes a write into a secret field
    # refuse before anything else happens.
    permit = _policy.approve(_policy.ActionRequest(
        tool=tool, kind="act", session=sess.session_id, page=record.handle,
        url=page.url, target=desc, action_class=action_class,
        args={"action": action, "ref": resolved["ref"]},
        writes_value=writes_value, summary=summary))
    before = page.url
    fresh_desc = desc
    outcome = None
    if walk.digest:
        try:
            outcome = await page.act(action, resolved["node_ref"],
                                     value=value, expect_digest=walk.digest)
        except _extlane.PageMoved:
            outcome = None
    if outcome is None:
        # THE RE-READ AFTER THE GATE, phase 2's path, unchanged. `approve`
        # already ran `verify_execute` against the descriptor above; this
        # second resolve is what makes the comparison meaningful on the
        # confirmation re-run, because the gate captured its fingerprint on
        # the FIRST pass and the element may have moved since. A mismatch is
        # TARGET_CHANGED and comes from the same function every other lane
        # uses.
        fresh = _pick(await _walk(sess, record, pin=node_ref, ref=ref),
                      ref, record)
        fresh_desc = _actlib.target_descriptor(fresh["unit"])
        if _act_fingerprint(desc) != _act_fingerprint(fresh_desc):
            from ..errors import TargetChanged
            raise TargetChanged(
                f"the target changed between the policy check and the "
                f"execution on {record.handle}; nothing was done. Re-read the "
                f"page, and act on the ref the new read returns.")
        outcome = await page.act(action, fresh["node_ref"], value=value)
    record.touch(page.url)
    effect = "navigated" if page.url != before else "same-page"
    invalidated = None
    if effect == "navigated":
        invalidated = sess.invalidate_page(
            record.handle, f"the page navigated from {before}")
    sess.bump("actions", page=record.handle)
    payload = {
        "page": record.handle, "session": sess.session_id,
        "lane": sess.spec.lane,
        "ref": resolved["ref"], "action": action,
        "role": fresh_desc.get("role"), "name": fresh_desc.get("name"),
        "effect": effect, "url": page.url,
        "gate": permit.get("gate"),
        # THE FLAG, ON EVERY ACT. Firefox gives an extension no way to
        # synthesise a trusted event, and the prior-art survey's finding that
        # no major detector gates on the flag alone is a reading of the field
        # rather than a guarantee. Reporting it is what keeps that reading
        # falsifiable by the people using this.
        "is_trusted": outcome.get("isTrusted", False),
        "lane_notes": lane_notes(sess),
    }
    if outcome.get("webdriver") is not None:
        payload["webdriver"] = outcome["webdriver"]
    if invalidated:
        payload["invalidated"] = invalidated
    return payload


def _act_fingerprint(desc: dict) -> dict:
    from ..policy import gates as _gates
    return _gates.fingerprint(desc)


def _summary(tool: str, desc: dict, handle: str) -> str:
    what = desc.get("name") or desc.get("role") or "the element"
    return (f"{tool} on {what!r} ({desc.get('role') or 'element'}) on "
            f"{handle}, in the browser you are signed in to.")


#: What a Lane C tool is asked for and cannot do. A parameter that arrives
#: here and is IGNORED is the silent degrade this whole subsystem argues
#: against: a caller who asked for a right-click and got a left one has a
#: wrong answer with no way to find out. Each entry is the sentence the
#: refusal carries.
UNSUPPORTED_ARGS: dict[str, str] = {
    "button": ("a mouse button other than left. The extension dispatches "
               "element.click(), which is a left activation and takes no "
               "button argument; a right or middle click is real input the "
               "driver lanes can send and this one cannot"),
    "click_count": ("a double or triple click. element.click() fires once, "
                    "and firing it twice is not the event a browser sends "
                    "for a double click"),
    "modifiers": ("modifier keys held during the click. There is no "
                  "keyboard state to hold on this lane"),
    "clear_first": ("clearing the field before typing. The write replaces "
                    "the value outright, so a clear step here would be a "
                    "no-op wearing the name of an operation"),
    "delay_ms": ("a per-keystroke delay. The write sets the value through "
                 "the native property descriptor and fires input and "
                 "change; there are no keystrokes to space out"),
    "rect": "a raw pixel region to capture",
    "pad_px": "padding around a capture target",
    "path": "writing the capture to a file",
    "max_bytes": "a byte cap on the capture",
    "max_pixels": "a pixel cap on the capture",
}

#: The DEFAULT each of these carries at the tool boundary. A value equal to
#: its own default is not a request, and refusing on one would make the
#: ordinary call impossible; a value different from it is what the caller
#: actually asked for.
#:
#: Per argument rather than one shared list of falsy things, and that is a
#: bug this table already caught: `True == 1` in Python, so a shared tuple
#: containing `1` swallowed `clear_first=True` and the refusal never fired.
DEFAULT_ARGS: dict[str, object] = {
    "button": "left", "click_count": 1, "modifiers": None,
    "clear_first": False, "delay_ms": 0,
    "rect": None, "pad_px": 0, "path": None,
    "max_bytes": None, "max_pixels": None,
}


def _asked_for(name: str, value: object) -> bool:
    """Whether the caller SET this, rather than letting its default ride."""
    default = DEFAULT_ARGS.get(name)
    if type(value) is not type(default) and not (
            value is None or default is None):
        return True
    if isinstance(value, bool) or isinstance(default, bool):
        return bool(value) is not bool(default)
    if value in (None, [], ()):
        return default not in (None, [], ())
    return value != default


def _refuse_unsupported(tool: str, asked: dict) -> None:
    """Refuse LOUDLY for anything this lane cannot honour."""
    named = [k for k, v in asked.items()
             if k in UNSUPPORTED_ARGS and _asked_for(k, v)]
    if not named:
        return
    reasons = "; ".join(UNSUPPORTED_ARGS[k] for k in named)
    raise LaneUnsupported(
        f"[lane C(your browser, via the extension)] {tool} was asked for "
        f"{named}, and this lane cannot do that: {reasons}. Nothing was "
        f"done. Drop the argument, or open the session on lane 'A' or 'B', "
        f"where the driver sends real input.")


async def click(sess, record, *, location: dict | None = None,
                button: str = "left", click_count: int = 1,
                modifiers: list | None = None, **_ignored) -> dict:
    _refuse_unsupported("click", {"button": button,
                                  "click_count": click_count,
                                  "modifiers": modifiers})
    return await _act(sess, record, tool="click", location=location,
                      action="click")


async def type_text(sess, record, *, location: dict | None = None,
                    text: str = "", submit: bool = False,
                    clear_first: bool = False, delay_ms: int = 0,
                    **_ignored) -> dict:
    """Write into a field, and optionally send the form.

    `submit=True` is TWO acts and two trips through the choke point, because
    they are two different consequential events: the write is judged as a
    write (credential blindness refuses a password, a card field gates as a
    payment) and the send is judged as a submission (which is where the
    consent ladder's four classes live). Collapsing them into one approval
    would let the class of the cheaper one authorize the dearer one."""
    _refuse_unsupported("type_text", {"clear_first": clear_first,
                                      "delay_ms": delay_ms})
    written = await _act(sess, record, tool="type_text", location=location,
                         action="type", value=text, writes_value=True)
    if not submit:
        return written
    sent = await _act(sess, record, tool="type_text", location=location,
                      action="submit", submitting=True)
    written["submitted"] = sent
    written["effect"] = sent["effect"]
    written["url"] = sent["url"]
    return written


async def fill_form(sess, record, *, fields: list | None = None,
                    submit=None, **_ignored) -> dict:
    """Several fields, each through the same door.

    Gauntlet 2's C1 was exactly this tool taking a card number ungated
    because it asked the credential layer per field and never computed an
    action class. Every field here goes through `_act`, which computes one,
    so a payment-shaped field anywhere in the batch gates the batch on this
    lane exactly as it does on the others: the FIRST field to classify
    refuses, and nothing before it has been written, because the gate fires
    before the write rather than after it.
    """
    entries = list(fields or [])
    if not entries:
        raise BadParams(
            "fill_form needs fields=[{'ref': 'e12', 'value': '...'}, ...].")
    # THE WHOLE BATCH IS CLASSIFIED BEFORE ANYTHING IS WRITTEN. Judging field
    # by field would write the ordinary fields of a payment form and only
    # then refuse at the card number, which is the defect the gauntlet found
    # from the other side: the numbers that had already landed were the harm.
    #
    # ONE WALK FOR THE WHOLE CENSUS. Phase 2 re-read the page once per field
    # here and twice more per field inside `_act`, so a three-field form
    # walked the page nine times for one call. `extract.js` returns the whole
    # page, so the walk that resolves the first field has already resolved
    # the rest; a field it did not reach (past the affordance cap, and not
    # the pinned one) falls back to its own pinned walk rather than being
    # classified from a thinner descriptor.
    #
    for entry in entries:
        if not entry.get("ref"):
            raise BadParams(
                f"lane C fills by ref: every field needs a 'ref' a previous "
                f"read returned, alongside its value. Got {sorted(entry)}. "
                f"The other selector spellings resolve through a live search "
                f"pass that is not built for this lane yet, so they refuse "
                f"here rather than resolving differently from the way they "
                f"resolve everywhere else. Nothing was written.")
    first_ref, first_node = _ref_of(sess, record, {"ref": entries[0]["ref"]},
                                    tool="fill_form")
    census = await _walk(sess, record, pin=first_node, ref=first_ref)
    consequential = []
    for entry in entries:
        ref, node_ref = _ref_of(sess, record, {"ref": entry["ref"]},
                                tool="fill_form")
        found = census.get(ref)
        if found is None:
            found = _pick(await _walk(sess, record, pin=node_ref, ref=ref),
                          ref, record)
            # A separate walk means a different instant, so the census walk
            # can no longer vouch for the page as a whole and its digest is
            # dropped. The acts below then take the two-walk route, which is
            # what phase 2 did for every field of every form.
            census.digest = None
        desc = _actlib.target_descriptor(found["unit"])
        if _actlib.action_class_for(desc) is not None:
            consequential.append(entry["ref"])
    # THE CONSEQUENTIAL FIELDS GO FIRST, so the gate that fires describes the
    # field that made the batch consequential rather than whichever field
    # happened to be first in the caller's list. The order is computed here
    # rather than by marking the caller's own dicts: a tool that edits its
    # arguments is a tool whose caller cannot re-use them.
    ordered = ([e for e in entries if e["ref"] in consequential]
               + [e for e in entries if e["ref"] not in consequential])
    written = []
    for entry in ordered:
        # The census walk is handed to the FIRST act only. Every act after it
        # follows a write, and a write moves the page, so the browser-side
        # guard would reject the census digest anyway; passing it on would be
        # asking a question whose answer is already known.
        result = await _act(sess, record, location={"ref": entry["ref"]},
                            tool="fill_form", action="fill",
                            value=entry.get("value"), writes_value=True,
                            walk=census)
        census = None
        written.append({"ref": result["ref"], "status": "written",
                        "role": result["role"], "name": result["name"]})
    payload = {
        "page": record.handle, "session": sess.session_id,
        "lane": sess.spec.lane, "fields": written,
        "lane_notes": lane_notes(sess),
    }
    if submit:
        ref = submit if isinstance(submit, str) else entries[-1].get("ref")
        payload["submitted"] = await _act(
            sess, record, tool="fill_form", location={"ref": ref},
            action="submit", submitting=True)
    return payload


# ------------------------------------------------------------- screenshots


async def take_screenshot(sess, record, *, target: str = "viewport",
                          image_format: str = "png",
                          quality: int | None = None, **_ignored) -> dict:
    """The viewport, masked, and the payload says both.

    `tabs.captureVisibleTab` is what an extension has. A full-page capture
    would be a scroll-and-stitch, and stitching pixels and calling the result
    a picture of the page is a claim this build does not make, so the request
    for one refuses and names the lanes that can.

    MASKING IS FAIL CLOSED, exactly as it is on the Playwright lane, and it
    had to be built rather than inherited: `captureVisibleTab` takes no mask
    argument, so the mask is CSS the content script applies and removes
    around the capture. A page carrying secret or payment fields whose mask
    did not go on is not captured. A one-time code and a card number are
    rendered in plain text on screen, and a screenshot is the one read on
    this surface that can carry them out of the page whatever the extractor
    refuses to touch.
    """
    page = _page(record)
    if str(image_format).lower() not in ("png", "jpeg", "jpg"):
        raise BadParams(
            f"lane C captures 'png' or 'jpeg'; got {image_format!r}.")
    _refuse_unsupported("take_screenshot", _ignored)
    if target and target != "viewport":
        raise LaneUnsupported(
            f"[lane {sess.spec.label}] "
            f"{lanes.CAPABILITIES['full_page_screenshot']['message']} "
            f"target={target!r} was refused and nothing was captured.")
    _audit.annotate(session=sess.session_id, page=record.handle,
                    url=page.url, lane=sess.spec.label)
    from . import capture as _capture
    masked = 0
    try:
        applied = await page.mask(_capture.MASK_CSS)
        masked = int(applied.get("masked") or 0)
    except Exception as exc:
        raise Conflict(
            f"the secret-field mask could not be applied to {record.handle}, "
            f"so nothing was captured. A screenshot is the one read on this "
            f"surface that can carry a one-time code or a card number out of "
            f"a page in plain sight, and it fails closed rather than "
            f"returning pixels nobody checked. ({exc})") from exc
    try:
        shot = await page.screenshot(
            image_format="jpeg" if str(image_format).lower() in ("jpeg", "jpg")
            else "png", quality=quality)
    finally:
        # The mask comes off whatever happened. Leaving a page with its
        # payment fields painted black would be this tool editing the user's
        # own browser window and walking away.
        try:
            await page.unmask()
        except Exception:
            pass
    sess.bump("reads", page=record.handle)
    return {
        "page": record.handle, "session": sess.session_id,
        "lane": sess.spec.lane, "url": page.url,
        "format": shot.get("format"),
        "scope": "viewport",
        "masked_fields": masked,
        "base64": shot.get("base64"),
        "lane_notes": lane_notes(sess),
    }
