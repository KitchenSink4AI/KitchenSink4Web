"""THE FAST PATHS, AND THE PROOF THAT NEITHER OF THEM IS A SHORTCUT.

Phase 3 removed one page walk from every act and skipped the walk entirely on
a read of a page nobody touched. Both are the same class of change and it is
the dangerous one: they make the tool answer without re-reading the page. So
every test here is written as a pair.

**On the acting side** the claim is that the fast path is STRONGER than the
path it replaces. Phase 2 walked the page after the gate and compared
fingerprints, and then sent an act message that the page had a full round trip
to invalidate before it arrived. Phase 3 sends the state the decision was made
on WITH the act, and the browser compares it in the same synchronous turn as
the dispatch. The pins: the guard travels, a page that moved refuses, a
refusal falls back to exactly phase 2's comparison, and the gate fires in
every combination.

**On the reading side** the claim is that a cached answer IS the answer a
fresh walk would have produced. The pins: nothing is held without a digest the
browser vouched for, everything is dropped the moment the digest moves, and an
act or a navigation drops it whether the digest moved or not.

**What is faked and what is not.** The BRIDGE, and only the bridge. The real
`ExtensionPage`, the real `ElementMap.absorb`, the real `target_descriptor`,
the real `action_class_for`, the real `policy.engine.approve`. The live half
of these claims -- that a real Firefox computes a digest that really does move
when the page moves -- is `tests/browser/test_ext_perf_live.py`.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web import anchors, projection
from kitchensink4web.engine import lanes, session as _session
from kitchensink4web.errors import (ConfirmationRequired, CredentialRefused,
                                    TargetChanged)
from kitchensink4web.extension import lane as _extlane
from kitchensink4web.extension.bridge import BridgeError
from kitchensink4web.ops import extops
from kitchensink4web.policy import consent, readonly

from test_ext_gate_parity import EXTRACTION, URL, _copy


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ("KS4WEB_CONSENT", "KS4WEB_PREAUTH", "KS4WEB_EXTENSION",
                 "KS4WEB_ALLOW_ORIGINS", "KS4WEB_DENY_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    before = readonly.grade()
    readonly.apply(False)
    consent.apply("full")
    yield
    readonly.apply(False if before is None else before)
    consent.apply(None)


def run(coro):
    return asyncio.run(coro)


class StampingBridge:
    """A fake bridge that behaves like a browser that CAN vouch for its state.

    Two knobs and nothing else. `digest` is what the content script would
    stamp a walk with, and setting it to None is the "this document is moving"
    case -- a running animation, a mutation during the walk -- which every
    fast path has to degrade to. `refuse_guard` makes the next guarded act
    answer STATE_CHANGED, which is what a real content script does when the
    digest it was handed no longer describes the page.
    """

    def __init__(self, extraction=None, digest="d1"):
        self.extraction = extraction if extraction is not None else EXTRACTION
        self.digest = digest
        self.refuse_guard = 0
        self.calls: list[tuple] = []
        self.acted: list[dict] = []
        self.evaluations: list[dict] = []

    def request(self, method, params=None, timeout=20.0):
        params = params or {}
        self.calls.append((method, params))
        if method == "page.evaluate":
            self.evaluations.append(dict(params))
            if params.get("ifChangedFrom") and self.digest \
                    and params["ifChangedFrom"] == self.digest:
                return {"unchanged": True, "digest": self.digest, "url": URL,
                        "webdriver": False, "readMs": 0}
            return {"data": _copy(self.extraction), "digest": self.digest,
                    "url": URL, "webdriver": False, "readMs": 1.0}
        if method == "page.act":
            if params.get("expectDigest") and self.refuse_guard:
                self.refuse_guard -= 1
                raise BridgeError("STATE_CHANGED: the page moved")
            self.acted.append(dict(params))
            return {"action": params["action"], "ref": params["ref"],
                    "url": URL, "isTrusted": False, "webdriver": False}
        if method == "page.navigate":
            return {"url": params.get("url") or URL, "title": "Checkout",
                    "settled": "complete", "elapsedMs": 12, "status": None}
        if method == "consent.set":
            return {"origins": params.get("origins") or []}
        raise AssertionError(f"the fake bridge was asked for {method!r}")

    def evaluates(self) -> int:
        return sum(1 for m, _ in self.calls if m == "page.evaluate")

    def reset(self) -> None:
        self.calls.clear()
        self.acted.clear()
        self.evaluations.clear()


class _Ctx:
    def __init__(self, bridge):
        self.context = _extlane.ExtensionContext(bridge)


class FakeSession:
    _seq = 0

    def __init__(self, bridge):
        # A SESSION ID PER TEST. The budget ledger is process-wide and the
        # loop detector is a product feature that is right to fire on the
        # same call repeated; a shared id would make one test's clicks look
        # like the next test's loop.
        FakeSession._seq += 1
        self.session_id = f"s-perf{FakeSession._seq}"
        self.spec = lanes.LaneSpec(lane="C", engine="extension",
                                   headless=False)
        self.element_map = anchors.ElementMap()
        self.reads = anchors.ReadStore()
        self.contexts = {"c1": _Ctx(bridge)}

    def bump(self, kind, page=None):
        pass

    def invalidate_page(self, handle, why):
        return {"why": why}


def build(digest="d1", extraction=None):
    bridge = StampingBridge(extraction=extraction, digest=digest)
    page = _extlane.ExtensionPage(bridge, tab_id=7, url=URL, title="Checkout")
    sess = FakeSession(bridge)
    record = _session.PageHandle(handle="p1", page=page, context="c1")
    data = run(projection.extract(page))
    sess.element_map.absorb(data, "p1", sess.reads.mint_token("p1"))
    bridge.reset()
    page.cache_hits = page.cache_misses = 0
    return sess, record, bridge, page


def ref_for(sess, name: str) -> str:
    for ref, entry in sess.element_map.entries.items():
        if entry.anchor.get("name") == name:
            return ref
    raise AssertionError(f"no ref was minted for {name!r}")


# ------------------------------------------------------------- the act, once


def test_an_act_walks_the_page_once_when_the_browser_vouches_for_the_state():
    """The headline. Phase 2 walked twice for every click; this walks once.

    Counted rather than timed, because a walk count is the thing that
    actually changed and a stopwatch on a fake bridge measures nothing."""
    sess, record, bridge, _page = build(digest="d1")
    run(extops.click(sess, record, location={"ref": ref_for(sess, "Help")}))
    assert bridge.evaluates() == 1
    assert len(bridge.acted) == 1


def test_an_act_walks_twice_when_the_browser_will_not_vouch():
    """THE CONTROL ARM, and it is phase 2's path exactly.

    A browser that returns no digest -- a page with a running animation, a
    document that mutated during the walk, an older content script -- gets
    the two-walk fingerprint comparison it always got. The optimisation is
    allowed to be absent; it is not allowed to be assumed."""
    sess, record, bridge, _page = build(digest=None)
    run(extops.click(sess, record, location={"ref": ref_for(sess, "Help")}))
    assert bridge.evaluates() == 2
    assert len(bridge.acted) == 1
    assert "expectDigest" not in bridge.acted[0]


def test_the_guard_travels_with_the_act():
    """The digest the gate judged is the digest the browser is asked to
    match. A guard that was computed and not sent would be a comment."""
    sess, record, bridge, _page = build(digest="d-walk")
    run(extops.click(sess, record, location={"ref": ref_for(sess, "Help")}))
    assert bridge.acted[0]["expectDigest"] == "d-walk"


def test_a_page_that_moved_falls_back_to_the_fingerprint_comparison():
    """A refused guard does not fail the call. It buys the second walk.

    This is the pin that makes the guard safe to add: STATE_CHANGED puts the
    tool back on phase 2's path rather than raising at the caller, so a page
    that legitimately moved between the gate and the act behaves exactly as
    it did before the guard existed."""
    sess, record, bridge, _page = build(digest="d1")
    bridge.refuse_guard = 1
    run(extops.click(sess, record, location={"ref": ref_for(sess, "Help")}))
    assert bridge.evaluates() == 2
    assert len(bridge.acted) == 1
    assert "expectDigest" not in bridge.acted[0]


def test_a_page_that_moved_and_changed_the_target_still_refuses():
    """THE OTHER DIRECTION. The fallback is not a retry that always wins.

    The guard refuses, the second walk comes back describing a DIFFERENT
    element, and `TargetChanged` fires from the same comparison every other
    lane runs. Nothing was done."""
    sess, record, bridge, _page = build(digest="d1")
    bridge.refuse_guard = 1
    # THE HREF, NOT THE NAME. The anchor is role, name and page key, so a
    # renamed element is a ref that does not rebind at all and the refusal
    # would be TargetNotFound -- a different pin, testing a different thing.
    # `href` is in the gate fingerprint and not in the anchor, so this is a
    # link that is still THE SAME LINK to the ref layer and a DIFFERENT
    # target to the gate, which is exactly the case the comparison exists
    # for: the page swapped where the button goes between the decision and
    # the act.
    moved = _copy(EXTRACTION)
    for unit in moved["affordances"]:
        if unit["name"] == "Help":
            unit["href"] = "/somewhere-else-entirely"
    ref = ref_for(sess, "Help")

    calls = {"n": 0}
    real = bridge.request

    def swap(method, params=None, timeout=20.0):
        if method == "page.evaluate":
            calls["n"] += 1
            if calls["n"] >= 2:
                bridge.extraction = moved
        return real(method, params, timeout)

    bridge.request = swap
    with pytest.raises(TargetChanged):
        run(extops.click(sess, record, location={"ref": ref}))
    assert bridge.acted == []


# ---------------------------------------------------- the gate, on both paths


def test_the_card_field_gates_on_the_fast_path():
    """GATE PARITY, RE-VERIFIED ON THE PATH THAT SKIPS A WALK.

    The whole risk of collapsing the double extraction is that the descriptor
    the gate reads comes from somewhere cheaper and thinner. It does not: it
    comes from the same walk, through the same `target_descriptor`, into the
    same `action_class_for`. The verdict on the card field is unchanged."""
    sess, record, bridge, _page = build(digest="d1")
    with pytest.raises(ConfirmationRequired) as caught:
        run(extops.click(sess, record,
                         location={"ref": ref_for(sess, "Card number")}))
    assert "payment-shaped form" in str(caught.value)
    assert bridge.acted == []


def test_the_card_field_gates_the_same_way_with_no_digest():
    """The control arm for the pin above: same verdict, slow path."""
    sess, record, bridge, _page = build(digest=None)
    with pytest.raises(ConfirmationRequired) as caught:
        run(extops.click(sess, record,
                         location={"ref": ref_for(sess, "Card number")}))
    assert "payment-shaped form" in str(caught.value)
    assert bridge.acted == []


def test_writing_a_password_still_refuses_before_the_page_is_touched():
    """Step 2 of the ladder is above the gate and above every fast path."""
    sess, record, bridge, _page = build(digest="d1")
    with pytest.raises(CredentialRefused):
        run(extops.type_text(sess, record,
                             location={"ref": ref_for(sess, "Password")},
                             text="hunter2"))
    assert bridge.acted == []


def test_an_ordinary_link_is_clicked_on_the_fast_path():
    """The control arm that makes every refusal above mean something."""
    sess, record, bridge, _page = build(digest="d1")
    out = run(extops.click(sess, record,
                           location={"ref": ref_for(sess, "Help")}))
    assert out["action"] == "click"
    assert len(bridge.acted) == 1


# ------------------------------------------------------------------ fill_form


def _form_extraction():
    """Three plain fields and a submit button, so the census has work to do
    and nothing in it gates. A payment field here would test the gate, which
    `test_ext_gate_parity.py` already does; what is under test is the number
    of walks."""
    from test_ext_gate_parity import _unit
    return {
        "identity": {"url": URL, "page_key": "/signup", "doc_epoch": "1"},
        "affordances": [
            _unit("f1", "textbox", "Given name", tag="INPUT", type="text",
                  in_form=True, attr_id="a", form_census={"method": "POST"}),
            _unit("f2", "textbox", "Family name", tag="INPUT", type="text",
                  in_form=True, attr_id="b", form_census={"method": "POST"}),
            _unit("f3", "textbox", "Nickname", tag="INPUT", type="text",
                  in_form=True, attr_id="c", form_census={"method": "POST"}),
        ],
        "regions": [], "headings": [], "forms": [], "tables": [],
        "completeness": {"closed_shadow_roots": 0},
        "shape": {"prose_chars": 10},
    }


def test_fill_form_classifies_every_field_from_one_walk():
    """Phase 2 walked the page three times per field: once to classify and
    twice to act. Three fields cost nine walks for one call.

    The census is one walk now, because `extract.js` returns the whole page
    and the walk that resolved the first ref had already resolved the rest.
    Each act after the first still walks, and has to: the write before it
    moved the page."""
    sess, record, bridge, _page = build(digest="d1",
                                        extraction=_form_extraction())
    fields = [{"ref": ref_for(sess, n), "value": "x"}
              for n in ("Given name", "Family name", "Nickname")]
    run(extops.fill_form(sess, record, fields=fields))
    assert len(bridge.acted) == 3
    # One census walk, then one walk for each act after the first. Phase 2's
    # number for the same call was nine.
    assert bridge.evaluates() == 3


def test_fill_form_falls_back_to_a_pinned_walk_for_a_field_the_census_missed():
    """THE CONTROL ARM. A ref past the extractor's affordance cap is not in
    the census walk, and it must get its own pinned walk rather than being
    classified from nothing or skipped."""
    sess, record, bridge, _page = build(digest="d1",
                                        extraction=_form_extraction())
    fields = [{"ref": ref_for(sess, n), "value": "x"}
              for n in ("Given name", "Nickname")]
    thin = _form_extraction()
    thin["affordances"] = [u for u in thin["affordances"]
                           if u["name"] != "Nickname"]
    full = _form_extraction()
    seen = {"n": 0}
    real = bridge.request

    def swap(method, params=None, timeout=20.0):
        if method == "page.evaluate":
            seen["n"] += 1
            # The census walk is thin; the pinned walk that follows is not.
            bridge.extraction = thin if seen["n"] == 1 else full
        return real(method, params, timeout)

    bridge.request = swap
    run(extops.fill_form(sess, record, fields=fields))
    assert len(bridge.acted) == 2
    assert bridge.evaluates() >= 3


# ------------------------------------------------------------- the read cache


def test_a_repeated_read_asks_the_browser_whether_anything_changed():
    """The question rides ON the read rather than in front of it. A separate
    'has anything changed?' round trip would be answering about a document
    the walk after it no longer describes."""
    sess, record, bridge, page = build(digest="d1")
    bridge.reset()
    page.cache_hits = 0
    run(projection.extract(page))
    assert bridge.evaluations[0]["ifChangedFrom"] == "d1"
    assert page.cache_hits == 1


def test_the_cached_answer_equals_the_answer_a_fresh_walk_produces():
    """THE EXTRACTION ITSELF, compared against a page object that has never
    cached anything, so the right-hand side is a genuine full walk rather than
    the same object asked twice.

    The comparison stops at the extraction here, deliberately. The canned
    fixture this file shares is built for the ACTING path and is not complete
    enough for the render ladder, and every field added to satisfy the
    renderer would be a field not being tested. The projection TEXT is pinned
    byte for byte against a real page in `tests/browser/test_ext_perf_live.py`,
    which is the only place the claim can honestly be made.
    """
    sess, record, bridge, page = build(digest="d1")
    cached = run(projection.extract(page))
    assert page.cache_hits >= 1

    fresh_bridge = StampingBridge(digest="d1")
    fresh_page = _extlane.ExtensionPage(fresh_bridge, tab_id=7, url=URL,
                                        title="Checkout")
    fresh = run(projection.extract(fresh_page))
    assert fresh_page.cache_hits == 0
    assert cached == fresh


def test_the_cached_answer_is_a_copy_the_caller_may_chew_on():
    """`absorb` rewrites units in place. A cache that handed out its own
    object would have every ref in it replaced by the first caller and would
    serve session refs to the second one."""
    sess, record, bridge, page = build(digest="d1")
    first = run(projection.extract(page))
    first["affordances"][0]["ref"] = "chewed"
    second = run(projection.extract(page))
    assert second["affordances"][0]["ref"] != "chewed"


def test_nothing_is_held_when_the_browser_will_not_vouch():
    """A null digest is the browser saying it cannot stand behind the state.
    Nothing is cached, and the next read walks."""
    sess, record, bridge, page = build(digest=None)
    run(projection.extract(page))
    bridge.reset()
    run(projection.extract(page))
    assert page.cache_hits == 0
    assert "ifChangedFrom" not in bridge.evaluations[0]


def test_a_moved_digest_drops_every_entry():
    """One generation at a time. An entry taken at a digest the page has left
    describes a document that no longer exists, so they all go together
    rather than aging out one at a time."""
    sess, record, bridge, page = build(digest="d1")
    run(projection.extract(page))
    assert page._cache
    bridge.digest = "d2"
    run(projection.extract(page))
    assert page._cache_digest == "d2"
    assert len(page._cache) == 1


def test_an_act_drops_the_cache():
    """We are about to change the page ourselves. A read racing this act
    must not be served from a generation the act is ending."""
    sess, record, bridge, page = build(digest="d1")
    run(projection.extract(page))
    assert page._cache
    run(extops.click(sess, record, location={"ref": ref_for(sess, "Help")}))
    assert page._cache == {}


def test_a_navigation_drops_the_cache():
    """A new document is a new everything, and a session should not hold
    three hundred kilobytes of a page it has left."""
    sess, record, bridge, page = build(digest="d1")
    run(projection.extract(page))
    assert page._cache
    run(extops.navigate(sess, record, url="https://shop.example.com/other"))
    assert page._cache == {}
    assert page.last_digest is None


def test_two_different_arguments_are_two_different_entries():
    """A pinned walk and a whole-page walk are different questions, and an
    answer to one must never be served for the other."""
    sess, record, bridge, page = build(digest="d1")
    run(projection.extract(page))
    run(projection.extract(page, pin="x1"))
    assert len(page._cache) == 2
    bridge.reset()
    page.cache_hits = 0
    run(projection.extract(page, pin="x1"))
    assert page.cache_hits == 1
    assert bridge.evaluations[0]["arg"]["pin"] == "x1"


def test_a_read_that_came_back_with_an_error_is_not_held():
    """An error is not an answer, and caching one would serve it forever."""
    sess, record, bridge, page = build(digest="d1")
    # The page moved AND the walk failed, which is the only way to reach the
    # error: an unmoved page would be served from the entry `build` left.
    bridge.digest = "d2"
    bridge.extraction = {"error": "SCOPE_NOT_FOUND", "asked_for": "e9"}
    run(page.evaluate(projection.EXTRACT_JS, {"root": None, "pin": None}))
    assert page._cache == {}
