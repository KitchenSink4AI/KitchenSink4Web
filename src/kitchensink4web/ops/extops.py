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


async def _resolve(sess, record, location: dict | None, *, tool: str) -> dict:
    """A ref, re-read from the page RIGHT NOW.

    Every act on this lane resolves this way, and it is a fresh extraction on
    purpose: the descriptor the gate fingerprints and the descriptor the
    classifier reads have to describe the element as it is at this instant,
    not as it was when the caller read the page. The extraction is pinned to
    the ref so an element past the extractor's 300-affordance cap is still
    in the candidate list.
    """
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
    page = _page(record)
    token = sess.reads.mint_token(record.handle)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    data = await _projection.extract(page, pin=node_ref)
    if data.get("error"):
        raise TargetNotFound(
            f"{ref!r} is not on {record.handle} any more "
            f"({data.get('error')}). Refs are invalidated by a navigation and "
            f"by a page close; re-read the page.")
    sess.element_map.absorb(data, record.handle, token, ts=ts)
    # AFFORDANCES FIRST, and `forms[].fields` is deliberately not searched:
    # a text input is an affordance in its own right and carries the whole
    # descriptor the classifier reads (secret, payment, the form census, the
    # activation delegate), while the copy nested inside a form carries a
    # short summary and an unabsorbed ref. Searching the summary would find
    # the element and hand the gate a thinner descriptor than the one every
    # other lane classifies.
    for kind in ("affordances", "forms"):
        for unit in data.get(kind) or []:
            if unit.get("ref") == ref:
                return {"unit": unit, "ref": ref,
                        "node_ref": unit.get("node_ref"),
                        "kind": kind}
    raise TargetNotFound(
        f"{ref!r} was minted on {record.handle} and the element it names is "
        f"not in a fresh read of the page. It may have been removed, or the "
        f"page may have replaced it with a different element carrying the "
        f"same words; either way nothing was done.")


async def _act(sess, record, *, tool: str, location: dict | None,
               action: str, value=None, submitting: bool = False,
               writes_value: bool = False) -> dict:
    """ONE DOOR for every Lane C act, and the reason there is only one.

    `act.action_class_for` says a fifth write path cannot be added that
    quietly skips the classifier. This is the fifth path, and it is a single
    function so that the claim is checkable by reading rather than by
    grepping: `click`, `type_text` and `fill_form` all arrive here, and the
    class, the approval, and the TOCTOU re-read all happen once.
    """
    page = _page(record)
    resolved = await _resolve(sess, record, location, tool=tool)
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
    # THE RE-READ AFTER THE GATE. `approve` already ran `verify_execute`
    # against the descriptor above; this second resolve is what makes the
    # comparison meaningful on the confirmation re-run, because the gate
    # captured its fingerprint on the FIRST pass and the element may have
    # moved since. A mismatch is TARGET_CHANGED and comes from the same
    # function every other lane uses.
    fresh = await _resolve(sess, record, location, tool=tool)
    fresh_desc = _actlib.target_descriptor(fresh["unit"])
    if _act_fingerprint(desc) != _act_fingerprint(fresh_desc):
        from ..errors import TargetChanged
        raise TargetChanged(
            f"the target changed between the policy check and the "
            f"execution on {record.handle}; nothing was done. Re-read the "
            f"page, and act on the ref the new read returns.")
    before = page.url
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


async def click(sess, record, *, location: dict | None = None,
                **_ignored) -> dict:
    return await _act(sess, record, tool="click", location=location,
                      action="click")


async def type_text(sess, record, *, location: dict | None = None,
                    text: str = "", submit: bool = False, **_ignored) -> dict:
    """Write into a field, and optionally send the form.

    `submit=True` is TWO acts and two trips through the choke point, because
    they are two different consequential events: the write is judged as a
    write (credential blindness refuses a password, a card field gates as a
    payment) and the send is judged as a submission (which is where the
    consent ladder's four classes live). Collapsing them into one approval
    would let the class of the cheaper one authorize the dearer one."""
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
    for entry in entries:
        resolved = await _resolve(sess, record,
                                  {"ref": entry.get("ref")}, tool="fill_form")
        desc = _actlib.target_descriptor(resolved["unit"])
        if _actlib.action_class_for(desc) is not None:
            # Route THIS field through the door first, so the gate that fires
            # is the one that describes the consequential field rather than
            # whichever field happened to be first in the list.
            await _act(sess, record, tool="fill_form",
                       location={"ref": entry.get("ref")}, action="fill",
                       value=entry.get("value"), writes_value=True)
            entry["_done"] = True
    written = []
    for entry in entries:
        if entry.pop("_done", False):
            written.append({"ref": entry.get("ref"), "status": "written"})
            continue
        result = await _act(sess, record, location={"ref": entry.get("ref")},
                            tool="fill_form", action="fill",
                            value=entry.get("value"), writes_value=True)
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
