"""The frame ladder: which frames this build enters, and why not the rest.

The second traversal. The first one (open shadow roots, 2026-09-06) worked
because every open root lives in the SAME execution context as its document,
so one `page.evaluate` reaches all of them. A frame does not: it has its own
`window`, its own realm, its own ref registry. That is why the shadow build
removed the `frame` modifier rather than faking it, and it is what this module
supplies.

**The seam is smaller than it looks.** Every in-page pass in this build takes
"a page-like object with an `evaluate` method" (`projection/__init__` says so
in its own docstring), and a Playwright `Frame` is exactly that. So
`extract.js`, `find.js`, `text.js` and the acting resolver run inside a frame
unchanged. What this module owns is the part that is NOT in-page: enumerating
the frame tree, deciding which frames may be entered, and giving each one a
stable id so a ref can say which realm it came from.

SAME-ORIGIN ONLY, and the reason is the security posture rather than the cost.
The driver can evaluate in a cross-origin frame; Playwright does it routinely.
This build will not, because a cross-origin document is content the embedding
page's own origin cannot read, and a tool that reads it anyway hands the model
data the page it is browsing could not obtain for itself. So a cross-origin
frame is COUNTED and REPORTED and never touched, which is the same
honest-absence shape closed shadow roots already have: "no one looked" and "no
one may look" are different facts and the read states which one applies.

Three classification rules, in the order they bind:

1. **The parent document's own script access is the authority.** Not the URL.
   `<iframe src="/same/path" sandbox>` without `allow-same-origin` runs in an
   opaque origin and `contentDocument` throws, so it is cross-origin whatever
   its src says. `srcdoc` and `about:blank` inherit the parent's origin and
   are enterable. The test is the one the browser enforces.
2. **A disagreement between the two fails closed.** When the URL says one
   origin and script access says another, the frame is treated as unreachable
   and the disagreement is reported. Only `document.domain` relaxation
   produces that legitimately, and it is deprecated; the other way to produce
   it is a bug in this classifier, which should be loud.
3. **Same-origin is not the same as first-party.** A frame can be same-origin
   and still carry markup from somewhere else: `srcdoc` written from a fetched
   string, a sandboxed frame with `allow-same-origin`, a document served from
   an upload path. So every frame carries a PROVENANCE label that travels with
   its text into the data envelope, and the label names how the content got
   there rather than only which origin serves it.

The depth cap is the frame answer to the 28-deep renderer crash the shadow
build classified. Deeply nested frames are a page a hostile site can serve
deliberately, each level costs a real execution context, and Chromium's own
nesting limit is not a number this build should discover by crashing into it.
Frames past the cap are counted, named, and not entered, and a caller who
addresses one by ref gets a typed refusal that names the cap rather than a
mysterious miss.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ..projection import instrument

#: How deep the traversal goes, counting the main document as depth 0. Five is
#: past anything a real site does with same-origin frames (a payment field
#: inside a widget inside a shell is three) and well short of the depth where
#: a renderer starts paying for the nesting itself.
DEPTH_CAP = max(1, int(os.environ.get("KS4WEB_FRAME_DEPTH_CAP", "5")))

#: How many frames one read may enter. Ad-heavy pages carry dozens of frames,
#: nearly all of them cross-origin and therefore free, but a page can also
#: mint fifty same-origin frames and each one is a full extraction. The cap is
#: on what is ENTERED; every frame is still counted and reported.
COUNT_CAP = max(1, int(os.environ.get("KS4WEB_FRAME_COUNT_CAP", "24")))

#: The reasons a frame was not entered, in the words the completeness block
#: prints. Every frame this build skips carries exactly one of these.
CROSS_ORIGIN = "cross-origin"
DEPTH_EXCEEDED = "past the frame depth cap"
COUNT_EXCEEDED = "past the frame count cap"
DETACHED = "detached before it could be read"
HIDDEN = "the frame element is hidden"
ORIGIN_DISAGREEMENT = "origin disagreement, treated as cross-origin"
UNREADABLE = "the frame could not be reached by the driver"


@dataclass
class FrameRef:
    """One frame in the tree, classified, with the id its refs carry.

    `fid` is the empty string for the main document, so a page with no frames
    mints exactly the refs it minted before this build and its projection is
    byte-identical. Frame refs are `if1`, `if2`, ... numbered flat across the
    whole tree in discovery order, which is what makes `if2e5` readable as
    "the fifth element of frame two" without a nesting path to parse."""

    fid: str
    frame: Any                       # a Playwright Frame: the page-like object
    parent_id: str | None = None
    depth: int = 0
    url: str = ""
    origin: str = ""
    same_origin: bool = False
    entered: bool = False
    why_not: str | None = None
    #: How the content got into the frame, and what that says about who wrote
    #: it. This is the provenance the data envelope names.
    how: str = "src"
    sandbox: str | None = None
    title: str = ""
    src: str = ""
    #: The parent-side facts about the iframe ELEMENT: its own hidden reason,
    #: and the ref the parent document minted for it. An element inside a
    #: frame whose iframe element is hidden in the parent is hidden, and this
    #: is the field that carries the parent's half of that verdict.
    hidden: str | None = None
    node_ref: str | None = None
    #: The iframe element's viewport-relative box in the PARENT, which is the
    #: offset a screenshot clip taken inside this frame has to be shifted by.
    box: dict | None = None
    #: The CUMULATIVE shift from this frame's viewport to the page's, summed
    #: down the chain. A rectangle a frame reports at (10, 20) is at
    #: (10 + offset.x, 20 + offset.y) in the screenshot the page takes, which
    #: is what lets the pixel arbiter rule on an element inside a frame
    #: instead of abstaining and refusing on the box math alone.
    offset: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    #: The chain of iframe elements from the main document down to this frame,
    #: as (fid, node_ref) pairs. The occlusion composition walks it.
    chain: list = field(default_factory=list)
    #: The FrameRef this one is embedded in, and the page-like object that
    #: realm evaluates in. The occlusion composition needs both: an element
    #: inside a frame is only visible if the `<iframe>` element is visible
    #: WHERE IT SITS, and that is a question only the parent can answer.
    parent: object = None

    @property
    def is_main(self) -> bool:
        return self.fid == ""

    def to_dict(self) -> dict:
        """The reporting shape. The projection package never sees a Frame
        object, only this, which is what keeps it free of the driver."""
        return {"fid": self.fid, "entered": self.entered,
                "why_not": self.why_not, "label": self.label(),
                "origin": self.origin, "url": self.url, "how": self.how,
                "sandbox": self.sandbox, "depth": self.depth,
                "title": self.title, "provenance": provenance(self)}

    def label(self) -> str:
        """One line naming this frame, its origin, and its provenance."""
        bits = [self.fid or "main", self.origin or self.url or "(no url)"]
        if self.how != "src":
            bits.append(self.how)
        if self.sandbox is not None:
            bits.append(f"sandbox=\"{self.sandbox}\"" if self.sandbox
                        else "sandbox (no tokens)")
        if self.title:
            bits.append(f'"{self.title}"')
        return " | ".join(bits)


def origin_of(url: str) -> str:
    """The origin of a URL, or a name for the schemes that have none.

    `about:srcdoc` and `about:blank` have no origin of their own: they inherit
    the embedder's. Returning the literal here rather than an empty string
    keeps the disagreement check in `_classify` honest, because "inherited" is
    a real answer and "" is a missing one."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    if parts.scheme in ("about", "javascript", "blob", "data", ""):
        return "inherited"
    if not parts.netloc:
        return "inherited"
    return f"{parts.scheme}://{parts.netloc}"


#: Parent-side facts about one iframe element. This runs in the PARENT frame's
#: context with the iframe element as its argument, which is the only place
#: the two questions that matter can both be asked: whether the parent can
#: script into the frame, and whether the frame's own box is visible where it
#: sits. Both are the parent's to answer.
_FRAME_FACTS_JS = instrument(r"""
(el) => {
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_VISIBILITY@@
  if (!el || !el.tagName) return { gone: true };
  // THE AUTHORITATIVE TEST. Not the URL: a sandboxed frame without
  // allow-same-origin runs in an opaque origin and this throws, whatever its
  // src says, and a srcdoc frame inherits the parent's origin and this
  // succeeds, though its URL is `about:srcdoc` and names no origin at all.
  let same = false;
  try {
    same = !!(el.contentDocument && el.contentDocument.documentElement);
  } catch (e) { same = false; }
  const sandbox = el.hasAttribute('sandbox')
    ? (el.getAttribute('sandbox') || '') : null;
  const src = el.getAttribute('src') || '';
  const how = el.hasAttribute('srcdoc') ? 'srcdoc'
    : (!src || src === 'about:blank') ? 'about:blank'
    : (/^javascript:/i.test(src) ? 'javascript:' : 'src');
  // The parent's half of the visibility verdict. An element inside a frame
  // whose own <iframe> box is display:none, zero-opacity, or occluded is an
  // element a human cannot see, and nothing inside the frame can know that.
  const hidden = ksHiddenAnywhere(el);
  // THE FRAME'S IDENTITY, in the channel's own frame map rather than in the
  // shared `refof`. Every other pass writes `refof` in its own namespace, so
  // an `<iframe>` that some later pass classified would lose the id this one
  // keyed on and come back as a NEW frame with a new id, taking every ref
  // minted inside it out of reach. The id is also registered in the ref map
  // so the element can be reached again for a box re-check.
  let ref = KS.frameid.get(el);
  if (!ref) {
    ref = 'x' + (KS.frameseq = (KS.frameseq || 0) + 1);
    KS.frameid.set(el, ref);
  }
  KS.refs.set(ref, el);
  const box = el.getBoundingClientRect();
  const st = ksCS(el);
  return {
    gone: false, same_origin: same, sandbox: sandbox, src: src.slice(0, 300),
    how: how, title: (el.getAttribute('title') || '').slice(0, 80),
    hidden: hidden, node_ref: ref,
    // Viewport-relative, which is what a screenshot clip is measured in.
    box: { x: box.left, y: box.top, w: box.width, h: box.height },
    border: { left: parseFloat(st.borderLeftWidth) || 0,
              top: parseFloat(st.borderTopWidth) || 0 }
  };
}
""")


async def ladder(record, *, depth_cap: int | None = None,
                 count_cap: int | None = None) -> list[FrameRef]:
    """Enumerate this page's frame tree and classify every frame in it.

    Returns the main frame first, then every child in breadth-first discovery
    order. `entered` says whether this build will run anything inside it, and
    `why_not` names the reason where it will not, in the words the read
    prints. Nothing here evaluates anything in a frame it will not enter: the
    classification runs entirely in the PARENT, which is the only realm whose
    access rights this build is willing to borrow.

    A page with no frames costs one attribute read and returns one record, so
    the common page pays nothing for this."""
    depth_cap = DEPTH_CAP if depth_cap is None else depth_cap
    count_cap = COUNT_CAP if count_cap is None else count_cap
    page = record.page
    main = page.main_frame
    top_origin = origin_of(page.url)
    out = [FrameRef(fid="", frame=main, depth=0, url=page.url,
                    origin=top_origin, same_origin=True, entered=True,
                    how="document")]
    by_frame = {main: out[0]}
    try:
        children = list(main.child_frames)
    except Exception:
        return out
    if not children:
        return out

    seq = 0
    entered = 0
    queue = [(child, out[0]) for child in children]
    while queue:
        frame, parent = queue.pop(0)
        seq += 1
        url = ""
        try:
            url = frame.url or ""
        except Exception:
            url = ""
        ref = FrameRef(fid="", frame=frame, parent_id=parent.fid,
                       depth=parent.depth + 1, url=url,
                       origin=origin_of(url), chain=list(parent.chain))
        await _classify(record, parent, ref, top_origin)
        # THE ID IS MINTED AFTER CLASSIFICATION, because the identity it is
        # keyed on comes from the parent: the ref the parent minted for the
        # `<iframe>` element. Position in the tree is not an identity, and a
        # ref that quietly renumbered when a sibling frame was removed would
        # be a stale ref wearing a live one's clothes.
        key = (f"{parent.fid}/{ref.node_ref}" if ref.node_ref
               else f"{parent.fid}#{seq}")
        ref.fid = record.frame_id(key)
        ref.parent = parent
        out.append(ref)
        by_frame[frame] = ref
        if ref.same_origin and ref.why_not is None:
            if ref.depth > depth_cap:
                ref.why_not = DEPTH_EXCEEDED
            elif entered >= count_cap:
                ref.why_not = COUNT_EXCEEDED
            else:
                ref.entered = True
                entered += 1
        # A frame that is not entered still has its CHILDREN enumerated where
        # the driver can see them, because the completeness block reports
        # every frame on the page and not only the reachable half. Children of
        # a cross-origin frame inherit the reason: this build has no access to
        # the parent, so it has none to the child either.
        try:
            kids = list(frame.child_frames)
        except Exception:
            kids = []
        for kid in kids:
            queue.append((kid, ref))
    return out


async def _classify(record, parent: FrameRef, ref: FrameRef,
                    top_origin: str) -> None:
    """Fill in one frame's parent-side facts, or say why they are missing."""
    if not parent.entered and parent.why_not:
        # No access to the parent means no access to the element that holds
        # this frame, so the reason travels down rather than being guessed at.
        ref.why_not = parent.why_not
        ref.same_origin = False
        return
    element = None
    try:
        element = await ref.frame.frame_element()
    except Exception:
        ref.why_not = DETACHED
        return
    try:
        facts = await parent.frame.evaluate(_FRAME_FACTS_JS, element)
    except Exception:
        ref.why_not = UNREADABLE
        return
    finally:
        try:
            await element.dispose()
        except Exception:
            pass
    if not facts or facts.get("gone"):
        ref.why_not = DETACHED
        return
    if facts.get("error") == "INSTRUMENT_MISSING":
        ref.why_not = UNREADABLE
        return
    ref.same_origin = bool(facts["same_origin"])
    ref.sandbox = facts["sandbox"]
    ref.how = facts["how"]
    ref.title = facts["title"]
    ref.src = facts["src"]
    ref.hidden = facts["hidden"]
    ref.node_ref = facts["node_ref"]
    ref.box = facts.get("box")
    box = facts.get("box") or {"x": 0.0, "y": 0.0}
    # The iframe's CONTENT box starts inside its border, and the frame's own
    # viewport origin is that inner corner, not the element's outer one. The
    # border width is the difference and it is routinely 2px, which is enough
    # to clip the wrong rectangle on a small control.
    ref.offset = {"x": parent.offset["x"] + box.get("x", 0.0)
                  + (facts.get("border") or {}).get("left", 0.0),
                  "y": parent.offset["y"] + box.get("y", 0.0)
                  + (facts.get("border") or {}).get("top", 0.0)}
    ref.chain = list(parent.chain) + [(parent.fid, facts["node_ref"])]
    if ref.how in ("srcdoc", "about:blank") and ref.origin == "inherited":
        ref.origin = parent.origin
    if not ref.same_origin:
        ref.why_not = CROSS_ORIGIN
        return
    # A HIDDEN FRAME IS NOT ENTERED, and this is the shadow build's rule one
    # boundary along: its walk returns on a hidden host BEFORE descending, so
    # a hidden component's payload lands in the hidden ledger instead of the
    # projection. An `<iframe>` under `display:none` is the same channel with
    # a whole document behind it, and a read that walked into it would deliver
    # text no human on that page can see, labelled as page content.
    if ref.hidden:
        ref.why_not = f"{HIDDEN} ({ref.hidden})"
        return
    # Rule 2: script access and the URL must agree. They do on every ordinary
    # page; `document.domain` relaxation is the one legitimate way to make
    # them differ and it is deprecated in every engine this build runs on.
    if (ref.origin not in ("", "inherited") and top_origin not in ("", "inherited")
            and ref.origin != parent.origin and ref.origin != top_origin):
        ref.same_origin = False
        ref.why_not = ORIGIN_DISAGREEMENT


def provenance(ref: FrameRef) -> str:
    """What this frame's content IS, in one clause, for the data envelope.

    Same-origin does not mean first-party. This is the sentence that keeps a
    reader from assuming it does."""
    if ref.is_main:
        return "the page's own document"
    if ref.how == "srcdoc":
        base = ("markup written inline by the embedding page (srcdoc), which "
                "runs at the page's own origin whatever wrote the string")
    elif ref.how == "about:blank":
        base = ("an empty frame filled in by script, which runs at the "
                "embedding page's origin")
    elif ref.how == "javascript:":
        base = ("a frame whose content came from a javascript: URL, which "
                "runs at the embedding page's origin")
    else:
        base = f"a document served from {ref.origin}"
    if ref.sandbox is not None:
        base += (f'; the frame is sandboxed (sandbox="{ref.sandbox}")'
                 if ref.sandbox else "; the frame is sandboxed")
    return base


def path(ref: FrameRef) -> list:
    """This frame's ancestors, outermost first, then the frame itself.

    An element inside a frame inside a frame is visible only if every
    `<iframe>` element on the way down is visible where it sits, so the
    visibility check walks this list rather than looking at one hop."""
    chain: list = []
    node = ref
    while node is not None and not node.is_main:
        chain.insert(0, node)
        node = node.parent
    return chain


def entered(refs: list[FrameRef]) -> list[FrameRef]:
    return [r for r in refs if r.entered]


def untouched(refs: list[FrameRef]) -> list[FrameRef]:
    return [r for r in refs if not r.entered]


def find(refs: list[FrameRef], fid: str) -> FrameRef | None:
    for ref in refs:
        if ref.fid == fid:
            return ref
    return None


def counts(refs: list[FrameRef]) -> dict:
    """The completeness numbers, computed once so every surface agrees."""
    children = [r for r in refs if not r.is_main]
    return {
        "total": len(children),
        "entered": len([r for r in children if r.entered]),
        "cross_origin": len([r for r in children
                             if r.why_not in (CROSS_ORIGIN,
                                              ORIGIN_DISAGREEMENT)]),
        "depth_capped": len([r for r in children
                             if r.why_not == DEPTH_EXCEEDED]),
        "count_capped": len([r for r in children
                             if r.why_not == COUNT_EXCEEDED]),
        "hidden": len([r for r in children
                       if (r.why_not or "").startswith(HIDDEN)]),
        "unreachable": len([r for r in children
                            if r.why_not in (DETACHED, UNREADABLE)]),
        "depth_cap": DEPTH_CAP,
        "count_cap": COUNT_CAP,
    }
