"""THE FIFTH PATH MEETS THE CHOKE POINT.

`act.action_class_for` says four write paths compute their class through it
and that "a fifth path cannot be added that quietly skips this."
`tests/browser/test_gauntlet2_fixes.py::test_gate_parity_across_every_write_
path` is the live pin for the four. Lane C is the fifth, and this is its pin,
run without a browser so it is in the fast suite where a regression is seen
the same day.

**What is faked and what is not.** The BRIDGE is faked: it returns a canned
extraction instead of running the walk in a real page. Everything above it is
the real code -- the real `ExtensionPage`, the real `ElementMap.absorb`, the
real `act.target_descriptor`, the real `act.action_class_for`, the real
`policy.engine.approve` with its real ladder. So what these tests prove is
that Lane C's plumbing carries a descriptor to the gate intact and that the
gate fires on it. What they cannot prove is that the extractor produces the
same descriptor as the other lanes, because no extractor runs here; that is
`tests/browser/test_ext_lane_live.py`'s job, and the two are complementary
rather than redundant.

**Both directions, everywhere.** Every refusal pin has a control arm in the
same file: an ordinary button that must NOT gate, a GET search that must stay
in grade. A gate that fires on everything is the same failure as a gate that
fires on nothing, seen from the other side.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from kitchensink4web import anchors
from kitchensink4web.engine import lanes, session as _session
from kitchensink4web.errors import (ConfirmationRequired, CredentialRefused,
                                    ReadOnlyMode)
from kitchensink4web.extension import lane as _extlane
from kitchensink4web.ops import extops
from kitchensink4web.policy import audit, consent, gates, readonly

_ENVS = ("KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_SENSITIVE_ORIGINS",
         "KS4WEB_ALLOW_ORIGINS", "KS4WEB_DENY_ORIGINS", "KS4WEB_EXTENSION")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    # `apply(False)` is ACTING ALLOWED: the grades are 'browse' and
    # 'strict', the SHIPPED DEFAULT is 'browse' (read-only), and a bare
    # `apply(None)` re-resolves that default rather than clearing it.
    # `consent.apply('full')` is the widest consent scope, which is the
    # honest place to start a gate test: a class that still fires under
    # `full` fires everywhere.
    #
    # The grade is restored to what this process was ALREADY at, not to a
    # value this file picked: conftest's `_no_grade_leak` fails any test
    # that moves it, and it is right to.
    before = readonly.grade()
    readonly.apply(False)
    consent.apply("full")
    yield
    for name in _ENVS:
        os.environ.pop(name, None)
    readonly.apply(False if before is None else before)
    consent.apply(None)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------- the fixture

URL = "https://shop.example.com/checkout"


def _unit(node_ref, role, name, **extra):
    """One extractor unit, in the shape `extract.js` emits.

    The field names are the ones `act.target_descriptor` reads, and they are
    written out here rather than generated so that a reader can see exactly
    which fact makes each verdict come out the way it does."""
    unit = {
        "ref": node_ref, "role": role, "name": name,
        "anchor": {"role": role, "name": name, "page_key": "/checkout"},
        "state": "",
    }
    unit.update(extra)
    return unit


#: A checkout page: a card field, an ordinary text field, the form's submit
#: button, and a plain link that must never gate. One fixture, several
#: verdicts, which is what makes the control arms meaningful.
EXTRACTION = {
    "identity": {"url": URL, "page_key": "/checkout", "doc_epoch": "1"},
    "affordances": [
        _unit("x1", "textbox", "Card number", tag="INPUT", type="text",
              autocomplete="cc-number", payment=True, in_form=True,
              attr_id="cc", form_payment=True,
              form_census={"method": "POST"}),
        _unit("x2", "textbox", "Full name", tag="INPUT", type="text",
              autocomplete="name", in_form=True, attr_id="who",
              form_census={"method": "POST"}),
        _unit("x3", "button", "Pay now", tag="BUTTON", type="submit",
              in_form=True, form_payment=True,
              form_census={"method": "POST"}),
        _unit("x4", "link", "Help", tag="A", href="/help"),
        _unit("x5", "textbox", "Password", tag="INPUT", type="password",
              autocomplete="current-password", secret=True, in_form=True,
              attr_id="pw", form_census={"method": "POST"}),
    ],
    "regions": [], "headings": [], "forms": [], "tables": [],
    "completeness": {"closed_shadow_roots": 0},
    "shape": {"prose_chars": 10},
}


class FakeBridge:
    """A bridge that answers with the canned extraction.

    It implements exactly the surface `ExtensionPage` uses, so the page
    object under test is the real one: the script-name mapping, the identity
    absorption, and the `to_thread` hop all run."""

    def __init__(self, extraction=None):
        self.extraction = extraction if extraction is not None else EXTRACTION
        self.calls: list[tuple] = []
        self.acted: list[dict] = []

    def request(self, method, params=None, timeout=20.0):
        params = params or {}
        self.calls.append((method, params))
        if method == "page.evaluate":
            assert params["script"] == "extract", params["script"]
            return {"data": _copy(self.extraction), "url": URL,
                    "webdriver": False, "readMs": 1.0}
        if method == "page.act":
            self.acted.append(dict(params))
            return {"action": params["action"], "ref": params["ref"],
                    "url": URL, "isTrusted": False, "webdriver": False}
        if method == "page.navigate":
            return {"url": params.get("url") or URL, "title": "Checkout",
                    "settled": "complete", "elapsedMs": 12, "status": None}
        if method == "consent.set":
            return {"origins": params.get("origins") or []}
        raise AssertionError(f"the fake bridge was asked for {method!r}")


def _copy(value):
    """A DEEP copy, because `absorb` rewrites units in place and a second
    read has to see the extractor's own ids again rather than the session
    refs the first read left behind."""
    import copy
    return copy.deepcopy(value)


class FakeSession:
    def __init__(self, bridge):
        self.session_id = "s1"
        self.spec = lanes.LaneSpec(lane="C", engine="extension",
                                   headless=False)
        self.element_map = anchors.ElementMap()
        self.reads = anchors.ReadStore()
        self.bumped: list[str] = []
        self.contexts = {"c1": _Ctx(bridge)}

    def bump(self, kind, page=None):
        self.bumped.append(kind)

    def invalidate_page(self, handle, why):
        return {"why": why}


class _Ctx:
    def __init__(self, bridge):
        self.context = _extlane.ExtensionContext(bridge)


@pytest.fixture
def lane():
    """A Lane C session, a page handle, and refs already minted.

    The refs are minted through `extract` + `ElementMap.absorb` rather than
    through `get_page_view`, and the difference is deliberate: rendering a
    canned extraction would mean maintaining a fixture complete enough for
    the whole render ladder, and every field added to satisfy the RENDERER
    is a field that is not being tested here. What the acting tests need is
    a session holding refs a caller could really be holding, which is
    exactly what absorb produces. The projection's own shape is proven
    against a real page in `tests/browser/test_ext_lane_live.py`.
    """
    bridge = FakeBridge()
    page = _extlane.ExtensionPage(bridge, tab_id=7, url=URL, title="Checkout")
    sess = FakeSession(bridge)
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    from kitchensink4web import projection
    data = run(projection.extract(page))
    sess.element_map.absorb(data, "p1", sess.reads.mint_token("p1"))
    return sess, record, bridge


def ref_for(sess, name: str) -> str:
    """The session ref for a unit, by its accessible name."""
    for ref, entry in sess.element_map.entries.items():
        if entry.anchor.get("name") == name:
            return ref
    raise AssertionError(f"no ref was minted for {name!r}")


def verdict(call):
    """Which class fired, or 'ungated'. Same shape the live gauntlet pin uses,
    so the two tables can be read side by side."""
    try:
        run(call())
    except ConfirmationRequired as exc:
        text = str(exc)
        for phrase, cls in (
                ("payment-shaped form", "payment_form"),
                ("password or a one-time code", "credential_submit"),
                ("reaches other people", "broadcast_submit"),
                ("deletes, cancels", "destructive_submit"),
                ("agreeing to terms", "legal_assent")):
            if phrase in text:
                return cls
        if "submitting a form" in text:
            return "form_submit"
        return "gated"
    except CredentialRefused:
        return "credential_refused"
    return "ungated"


# ------------------------------------------------- the parity pin, five paths


def test_the_card_field_gates_the_same_class_on_every_lane_c_door(lane):
    """ONE fixture, ONE field, THREE Lane C doors, ONE verdict.

    The live gauntlet test proves this for click, type_text, fill_form and
    press_keys on the Playwright lanes. Lane C has three of those doors and
    they all arrive at `extops._act`, so the pin here is that no door found
    its way around it."""
    sess, record, _bridge = lane
    card = ref_for(sess, "Card number")
    pay = ref_for(sess, "Pay now")
    verdicts = {
        "click": verdict(lambda: extops.click(
            sess, record, location={"ref": pay})),
        "type_text": verdict(lambda: extops.type_text(
            sess, record, location={"ref": card}, text="4111111111111111")),
        "fill_form": verdict(lambda: extops.fill_form(
            sess, record, fields=[{"ref": card, "value": "4111111111111111"}])),
    }
    assert set(verdicts.values()) == {"payment_form"}, verdicts


def test_the_card_number_never_lands_when_the_gate_refuses(lane):
    """The gate fires BEFORE the write. Gating the submit that follows an
    ungated fill gates the wrong event: the card number is the thing being
    written, and once it is in the field it has been written."""
    sess, record, bridge = lane
    card = ref_for(sess, "Card number")
    who = ref_for(sess, "Full name")
    with pytest.raises(ConfirmationRequired):
        run(extops.fill_form(sess, record, fields=[
            {"ref": card, "value": "4111111111111111"},
            {"ref": who, "value": "buyer"}]))
    # NEITHER field, not just the payment one: a payment-shaped field
    # anywhere in a batch gates the batch, and nothing reached the page.
    assert bridge.acted == []


def test_an_ordinary_link_does_not_gate(lane):
    """THE CONTROL ARM. A gate that fires on everything is the same failure
    as a gate that fires on nothing, and without this line the three pins
    above would pass on a build that refused every click."""
    sess, record, bridge = lane
    assert verdict(lambda: extops.click(
        sess, record, location={"ref": ref_for(sess, "Help")})) == "ungated"
    assert bridge.acted and bridge.acted[-1]["action"] == "click"


def test_writing_a_password_refuses_before_anything_else_happens(lane):
    """CREDENTIAL BLINDNESS, on the fifth path. It is step 2 of the choke
    point, above the origin policy and above the gate, and it refuses the
    WRITE rather than gating it: there is no confirmation that makes this
    server type a password."""
    sess, record, bridge = lane
    assert verdict(lambda: extops.type_text(
        sess, record, location={"ref": ref_for(sess, "Password")},
        text="hunter2")) == "credential_refused"
    assert bridge.acted == []


def test_read_only_refuses_every_lane_c_act(lane):
    """DEFENCE IN DEPTH, path five. The mutating tools are ABSENT under
    read-only, so reaching this branch means something slipped past
    registration; the choke point refuses anyway and the claim stays true."""
    sess, record, bridge = lane
    readonly.apply("browse")
    try:
        with pytest.raises(ReadOnlyMode):
            run(extops.click(sess, record,
                             location={"ref": ref_for(sess, "Help")}))
    finally:
        readonly.apply(False)
    assert bridge.acted == []


def test_a_read_still_works_under_read_only(lane):
    """The other direction of the pin above. Read-only removes the acting,
    never the reading, and a Lane C that refused reads there would be a lane
    nobody could use in the mode most people run.

    Asked at the resolve layer rather than through the whole render, for the
    reason the fixture gives: what is under test is the policy, and the
    resolve is the first thing a read does that the policy could refuse."""
    sess, record, _bridge = lane
    readonly.apply("browse")
    try:
        resolved = run(extops._resolve(
            sess, record, {"ref": ref_for(sess, "Help")}, tool="read"))
    finally:
        readonly.apply(False)
    assert resolved["ref"]


def test_a_denied_origin_refuses_the_navigation(lane, monkeypatch):
    """The origin policy is step 3 and it is deny-first. Lane C reaches it
    through the same `ActionRequest`, so an operator's deny list covers the
    browser they are signed in to exactly as it covers the others."""
    from kitchensink4web.errors import NavigationBlocked
    monkeypatch.setenv("KS4WEB_DENY_ORIGINS", "blocked.example.com")
    with pytest.raises(NavigationBlocked):
        run(extops.navigate(lane[0], lane[1],
                            url="https://blocked.example.com/x"))


def test_an_allowed_origin_navigates(lane, monkeypatch):
    """Control arm for the deny list."""
    monkeypatch.setenv("KS4WEB_DENY_ORIGINS", "blocked.example.com")
    result = run(extops.navigate(lane[0], lane[1],
                                 url="https://shop.example.com/cart"))
    assert result["url"]


# ------------------------------------------------------ the audit and the lane


def test_every_act_reports_that_its_event_was_not_trusted(lane):
    """Firefox gives an extension no way to synthesise a trusted event, and
    the prior-art survey's finding that no major detector gates on the flag
    alone is a reading of the field rather than a guarantee. Reporting it on
    every act is what keeps that reading falsifiable."""
    sess, record, _bridge = lane
    result = run(extops.click(sess, record,
                              location={"ref": ref_for(sess, "Help")}))
    assert result["is_trusted"] is False


def test_every_read_reports_navigator_webdriver(lane):
    """Phase 1's rule, kept in production reads. The claim the architecture
    rests on stays checkable rather than being argued once in a design
    document. The page object records it off every command it makes."""
    _sess, record, _bridge = lane
    assert record.page.webdriver is False


def test_the_lane_notes_name_what_this_lane_cannot_do(lane):
    """Every payload carries the absences. A caller comparing a Lane C
    screenshot against a Lane A one has to be able to see that one of them is
    a viewport crop without going and reading a capability table."""
    sess, _record, _bridge = lane
    notes = extops.lane_notes(sess)
    assert set(notes) >= {"closed_shadow_count", "navigation_status",
                          "full_page_screenshot", "trusted_events", "frames"}


def test_the_navigation_status_is_an_absence_and_not_a_two_hundred(lane):
    """The most expensive single wrong value the payload could carry: every
    wall verdict downstream reads the status."""
    result = run(extops.navigate(lane[0], lane[1],
                                 url="https://shop.example.com/cart"))
    assert result["status"] is None


def test_the_browser_side_consent_list_widens_only_after_the_ladder_passed(
        lane, monkeypatch):
    """The extension's own origin list is a RECORD OF DECISIONS, not a second
    policy. An origin the ladder refused must never reach it."""
    from kitchensink4web.errors import NavigationBlocked
    sess, record, _bridge = lane
    ctx = sess.contexts["c1"].context
    monkeypatch.setenv("KS4WEB_DENY_ORIGINS", "blocked.example.com")
    with pytest.raises(NavigationBlocked):
        run(extops.navigate(sess, record, url="https://blocked.example.com/x"))
    assert "https://blocked.example.com" not in ctx.consented
    run(extops.navigate(sess, record, url="https://ok.example.com/x"))
    assert "https://ok.example.com" in ctx.consented


def test_a_full_page_screenshot_refuses_rather_than_cropping(lane):
    """A viewport crop returned under the name `full` would be the silent
    degrade this whole subsystem argues against."""
    from kitchensink4web.errors import LaneUnsupported
    sess, record, _bridge = lane
    with pytest.raises(LaneUnsupported) as caught:
        run(extops.take_screenshot(sess, record, target="full"))
    assert "scroll-and-stitch" in str(caught.value)


def test_the_evaluate_seam_refuses_source_it_was_not_shipped(lane):
    """A wire that could carry code, with a native messaging host on the
    other end of it, is a shape this build will not ship. The refusal names
    the five scripts the extension has."""
    from kitchensink4web.errors import LaneUnsupported
    _sess, record, _bridge = lane
    with pytest.raises(LaneUnsupported) as caught:
        run(record.page.evaluate("() => document.cookie"))
    assert "unsafe-eval" in str(caught.value)


def test_the_five_shipped_scripts_are_accepted(lane):
    """The other direction. A seam that refused everything would pass the
    test above and serve nobody."""
    from kitchensink4web import projection
    for source, name in ((projection.EXTRACT_JS, "extract"),
                         (projection.FIND_JS, "find"),
                         (projection.TEXT_JS, "text"),
                         (projection.ARTICLE_JS, "article"),
                         (projection.SCHEMA_JS, "schema")):
        assert _extlane.script_name(source) == name


def test_the_detail_scale_is_the_same_on_both_lanes():
    """`detail='full'` has to mean the same multiplier here as it does in
    `lite.get_page_view`, or one lane charges a different budget for the same
    word."""
    from kitchensink4web.ops import lite
    assert extops.DETAIL_SCALE == lite._DETAIL_SCALE


def test_the_audit_records_the_lane(lane):
    """A trail that could not distinguish an action taken in the user's own
    browser from one taken in a throwaway profile would be missing the fact
    that matters most about it."""
    sess, record, _bridge = lane

    async def click_and_read():
        # THE READ HAS TO HAPPEN IN THE SAME CONTEXT AS THE WRITE.
        # `annotate` is context-local so concurrent calls cannot cross, and
        # `asyncio.run` starts a fresh context, so an assertion outside the
        # coroutine would read an empty buffer and pass for the wrong
        # reason on a build that annotated nothing at all.
        await extops.click(sess, record,
                           location={"ref": ref_for(sess, "Help")})
        return audit.take_annotation("lane")

    assert run(click_and_read()) == sess.spec.label
    assert "your browser" in sess.spec.label
