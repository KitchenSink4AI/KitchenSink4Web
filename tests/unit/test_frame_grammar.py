"""The frame grammar, the sticky ids, and the provenance line, without a browser.

Everything here is a decision the build makes BEFORE it touches a page, which
is why it can be tested without one: what counts as an origin, what a location
object may carry, how a ref is minted inside a frame, and what the data
envelope says when one payload carries several documents.
"""

from __future__ import annotations

import pytest

from kitchensink4web import pagedata
from kitchensink4web.anchors import ElementMap
from kitchensink4web.engine import frames
from kitchensink4web.errors import BadParams
from kitchensink4web.ops.act import selector_of


# ---------------------------------------------------------------- grammar


def test_frame_is_a_modifier_and_rides_alongside_a_selector():
    """It NARROWS, so it is not a selector of its own: `{'css': ..., 'frame':
    'if2'}` is one selector in one realm and not two selectors at once."""
    group, value = selector_of({"css": "#pay", "frame": "if2"})
    assert group == "css" and value == "#pay"


def test_frame_alone_is_not_a_location():
    with pytest.raises(BadParams) as exc:
        selector_of({"frame": "if2"})
    assert "exactly one selector" in str(exc.value)


def test_the_selector_list_names_frame_as_a_modifier():
    with pytest.raises(BadParams) as exc:
        selector_of({"nonsense": 1})
    assert "shadow/exact/frame are" in str(exc.value)


# ------------------------------------------------------------- origins


@pytest.mark.parametrize("url,expected", [
    ("https://shop.example/checkout", "https://shop.example"),
    ("http://127.0.0.1:8080/b/x.html", "http://127.0.0.1:8080"),
    # A port is part of an origin, which is what makes a second local port a
    # real cross-origin fixture rather than a pretend one.
    ("http://127.0.0.1:8081/b/x.html", "http://127.0.0.1:8081"),
    # These have no origin of their own: they inherit the embedder's, and
    # saying so is a real answer where an empty string is a missing one.
    ("about:srcdoc", "inherited"),
    ("about:blank", "inherited"),
    ("", "inherited"),
])
def test_origin_of(url, expected):
    assert frames.origin_of(url) == expected


def test_two_ports_on_one_host_are_two_origins():
    assert (frames.origin_of("http://127.0.0.1:8080/a")
            != frames.origin_of("http://127.0.0.1:8081/a"))


# ---------------------------------------------------------- provenance


def _ref(**kw):
    base = dict(fid="if1", frame=None, origin="https://shop.example",
                url="https://shop.example/w", how="src", sandbox=None)
    base.update(kw)
    return frames.FrameRef(**base)


def test_provenance_separates_same_origin_from_first_party():
    """SAME-ORIGIN IS NOT FIRST-PARTY, and this is the sentence that keeps a
    reader from assuming it is. A srcdoc frame runs at the page's own origin
    carrying markup that came from wherever the string came from."""
    plain = frames.provenance(_ref())
    assert "served from https://shop.example" in plain
    inline = frames.provenance(_ref(how="srcdoc"))
    assert "srcdoc" in inline and "whatever wrote the string" in inline
    sandboxed = frames.provenance(_ref(sandbox="allow-scripts"))
    assert 'and the frame is sandboxed (sandbox="allow-scripts")' in sandboxed
    assert frames.provenance(_ref(fid="")) == "the page's own document"


def test_the_envelope_names_every_frame_origin_in_the_payload():
    """One envelope, several documents. A single origin in the label would be
    a claim about only one of them."""
    frame_notes = [
        {"fid": "if1", "provenance": "a document served from https://widget.example"},
        {"fid": "if2", "provenance": "markup written inline by the embedding page (srcdoc)"},
    ]
    wrapped, note = pagedata.wrap("body text", url="https://shop.example",
                                  frames=frame_notes)
    assert note["frames"] == frame_notes
    assert "if1" in note["label"] and "if2" in note["label"]
    assert "Same-origin does not mean the page's author wrote it" in \
        note["label"]
    assert pagedata.unwrap(wrapped) == "body text"


def test_a_frameless_read_carries_no_frame_note():
    """Zero regression in the payload as well as the projection: a page with
    no frames gets the label it got before frames existed."""
    _, note = pagedata.wrap("body text", url="https://shop.example")
    assert "frames" not in note
    assert "embedded frame" not in note["label"]


# ------------------------------------------------------------- ref minting


def _extraction(name: str, url: str = "https://shop.example/w"):
    return {"identity": {"url": url, "page_key": url, "doc_epoch": "e1"},
            "affordances": [{"ref": "e1", "anchor": {"role": "button",
                                                     "name": name,
                                                     "id": "pay"},
                             "state": ""}],
            "regions": [], "headings": [], "forms": [], "tables": []}


def test_a_frame_ref_carries_its_frame_and_a_main_ref_does_not():
    em = ElementMap()
    em.absorb(_extraction("Pay"), "p1", "t1")
    em.absorb(_extraction("Pay"), "p1", "t1", frame="if2")
    main = [r for r, e in em.entries.items() if not e.frame]
    framed = [r for r, e in em.entries.items() if e.frame == "if2"]
    assert main == ["e1"]
    assert framed == ["if2e1"]


def test_two_frames_holding_the_same_widget_do_not_collide():
    """The same widget embedded twice is the ordinary case, not a hostile
    one. A key that ignored the realm would hand both copies one ref and act
    on whichever the lookup reached first."""
    em = ElementMap()
    em.absorb(_extraction("Pay"), "p1", "t1", frame="if1")
    em.absorb(_extraction("Pay"), "p1", "t1", frame="if2")
    assert set(em.entries) == {"if1e1", "if2e1"}
    assert em.entries["if1e1"].frame == "if1"
    assert em.entries["if2e1"].frame == "if2"


def test_absorbing_one_frame_does_not_mark_another_frames_refs_gone():
    """A framed page absorbs once per frame. A sweep that ignored the frame
    would have the second call bury everything the first one just minted."""
    em = ElementMap()
    em.absorb(_extraction("Pay"), "p1", "t1", frame="if1")
    em.absorb(_extraction("Buy"), "p1", "t1", frame="if2")
    assert not em.entries["if1e1"].gone


def test_a_vanished_frame_has_its_refs_marked_gone_with_the_frame_named():
    em = ElementMap()
    em.absorb(_extraction("Pay"), "p1", "t1", frame="if1")
    touched = em.mark_frames_gone("p1", {"if2"}, "the frame is gone")
    assert touched == 1
    entry = em.entries["if1e1"]
    assert entry.gone and "in if1" in entry.gone_as


def test_frames_absorbed_into_one_read_state_share_it():
    """A framed page is ONE read, so a delta taken against it covers the
    frames too rather than only the last one absorbed."""
    em = ElementMap()
    state = em.absorb(_extraction("Pay"), "p1", "t1")
    state = em.absorb(_extraction("Buy"), "p1", "t1", frame="if1", into=state)
    assert set(state.units) == {"e1", "if1e1"}
    assert em.latest["p1"] is state


# ----------------------------------------------------------------- counts


def test_counts_split_every_reason_a_frame_was_not_entered():
    tree = [
        frames.FrameRef(fid="", frame=None, entered=True),
        frames.FrameRef(fid="if1", frame=None, entered=True),
        frames.FrameRef(fid="if2", frame=None, why_not=frames.CROSS_ORIGIN),
        frames.FrameRef(fid="if3", frame=None, why_not=frames.DEPTH_EXCEEDED),
        frames.FrameRef(fid="if4", frame=None,
                        why_not=f"{frames.HIDDEN} (display-none)"),
        frames.FrameRef(fid="if5", frame=None,
                        why_not=frames.ORIGIN_DISAGREEMENT),
    ]
    counts = frames.counts(tree)
    assert counts["total"] == 5
    assert counts["entered"] == 1
    # An origin disagreement is counted WITH cross-origin, because that is
    # what the build does with it: fail closed and say so.
    assert counts["cross_origin"] == 2
    assert counts["depth_capped"] == 1
    assert counts["hidden"] == 1
