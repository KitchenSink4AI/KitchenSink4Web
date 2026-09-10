"""The mail composer, and the class of page it stands for: a form with no
`<form>`.

FOUND 2026-09-10, in the author-present acceptance test against a real
signed-in outlook.live.com mailbox with a compose window open. `get_page_view`
never listed the composer's To well, subject box, message body, or Send
button, at 3,000 / 6,000 / 12,000 tokens, at `detail=full`, or under a scoped
region read. A screenshot of the same session shows all four rendered. The
read's own completeness block reported "unlisted affordances: 20 in 1
class(es) [other controls=20]" and those twenty stayed unlisted at every
budget, so it was never the ladder.

It was the CLASSIFIER. All twenty controls were walked, none was hidden, none
hit the return cap, and every one of them landed in `other` -- the class with
the smallest quota on the ladder -- because all three routes out of it ask for
markup a modern web application does not write:

  - `form_control` wanted a `<form>` ancestor. The read's own page-shape
    block said "forms (page has none)"; the composer posts over `fetch`.
  - `primary` wanted the button to sit in a `main`, `dialog`, `form` or
    `search` region. The composer is a bare `<div>` outside every landmark,
    which the read also said in its own words: "1 region(s) own nothing at
    all and were not listed".
  - So `other`, where a Send button competes with the inbox for 24 slots and
    loses on rank, because a message row is a bigger named in-viewport box
    than a Send button is.

The severity is lane C's. There the acting tools take ONLY refs a read
minted, so a control no read lists is a control no agent can reach: not an
expensive second call, total acting blindness on the one control that sends
the mail.

THE FIX is `panel` segmentation in `extract.js`: two or more fields sharing a
tight container are a form whatever the tag says, so the container becomes a
region and the two existing class rules fire on it unchanged. Three variants
below are pinned because the fix must not be a special case for the overlay:
the composer is the same form-less field cluster whether it is painted over
the whole viewport, docked in the corner, or built as a web component, and
only the first one produces a viewport lid. The shadow variant is here because
`querySelectorAll` stops dead at every shadow boundary, so a field-group pass
that ran only over the light tree would have been silently better at mail
clients that ship plain divs than at ones that ship components.

Measured on this fixture with the fix reverted, at budgets 3,000 / 5,000 /
12,000, all at degradation rung 1: "To", "Add a subject" and "Send" absent
from every read, "unlisted affordances: 67 in 1 class(es) [other
controls=67]", and the compose surface present in no region of the page-shape
block. The message body survived on box area alone.
"""

from __future__ import annotations

import asyncio

import pytest

from kitchensink4web import pagedata
from kitchensink4web.engine.session import MANAGER
from kitchensink4web.ops import lite
from kitchensink4web.policy import audit, budgets, readonly

pytestmark = pytest.mark.browser

#: The four controls the acceptance test named, by accessible name. A read
#: that carries these carries the composer.
COMPOSER = ("To", "Add a subject", "Message body", "Send")


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "LOG", audit.AuditLog())
    monkeypatch.setattr(budgets, "BOOK", budgets.BudgetBook())
    monkeypatch.setattr(audit, "STATE_DIR", tmp_path)
    readonly.apply(False)
    yield
    readonly.apply(False)


def run(coro):
    async def main():
        try:
            return await coro
        finally:
            await MANAGER.close_all()

    return asyncio.run(main())


def _block(projection: str, header: str) -> str:
    assert header in projection, f"the read carried no {header} block"
    return projection.split(header)[1].split("\n## ")[0]


async def _read(html, budget_tokens=5000):
    session = await MANAGER.open(lane="A", engine="chromium", headless=True)
    record = session.page(session.focused)
    await record.page.set_content(html)
    view = await lite.get_page_view(page=session.focused,
                                    budget_tokens=budget_tokens)
    return session, view


def _refs_for(affordances: str, names) -> dict[str, str]:
    """The ref each named control minted, or nothing under its name."""
    out: dict[str, str] = {}
    for line in affordances.splitlines():
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) < 3:
            continue
        for name in names:
            if parts[2] == f'"{name}"':
                out[name] = parts[0]
    return out


@pytest.mark.parametrize(
    "page_name", ["compose_overlay", "compose_docked", "compose_shadow"])
def test_a_form_less_composer_mints_refs_for_every_control_that_sends_mail(
        page_name):
    """The bug, stated as the property that was violated.

    A standard-budget read, no `detail=full`, no scoping, no second call:
    every one of the four controls is listed AND the ref it printed resolves
    to a live affordance, which is what makes it actable on a lane that
    accepts nothing else."""
    from tests.fixtures import pages

    async def go():
        session, view = await _read(getattr(pages, page_name.upper()))
        affordances = _block(view["projection"], "## 3 AFFORDANCES")
        refs = _refs_for(affordances, COMPOSER)
        missing = [n for n in COMPOSER if n not in refs]
        assert not missing, (
            f"{page_name}: the read did not list {missing}. On lane C that "
            f"is a control no agent can reach at any budget.\n"
            f"{affordances}")
        for name, ref in refs.items():
            entry = session.element_map.entries.get(ref)
            assert entry is not None and entry.kind == "affordance", (
                f'"{name}" printed {ref}, which is not an actable ref')

    run(go())


@pytest.mark.parametrize(
    "page_name", ["compose_overlay", "compose_docked", "compose_shadow"])
def test_the_composer_is_a_named_region_rather_than_a_surface_in_no_block(
        page_name):
    """The honesty half.

    Before the fix the compose surface appeared in NO block of the read: not
    in page shape, not in the forms inventory, and its controls carried no
    region. An agent reading that page had no way to learn a composer was
    open, which is the completeness failure underneath the ranking one."""
    from tests.fixtures import pages

    async def go():
        _, view = await _read(getattr(pages, page_name.upper()))
        shape = _block(view["projection"], "## 2 PAGE SHAPE")
        assert "| panel |" in shape, (
            f"{page_name}: the composer is in no listed region\n{shape}")
        assert "Compose" in shape, (
            f"{page_name}: the panel region carried no usable label\n{shape}")

    run(go())


@pytest.mark.parametrize(
    "page_name", ["compose_overlay", "compose_docked", "compose_shadow"])
def test_the_composers_fields_are_form_controls_without_a_form_element(
        page_name):
    """The class, named, because the quota is the thing that failed.

    `form_control` carries the largest quota on the ladder and the promise
    that it is complete or honestly incomplete, never sampled. The three
    fields belong there: a subject `<input>`, a contenteditable recipient
    well and a contenteditable body are the fields of a form the page simply
    never wrote a `<form>` tag for. Asserted through the projection's own
    class accounting rather than through the printed lines, so the pin fails
    if the classification regresses even while the ranker happens to keep
    printing them."""
    from kitchensink4web.projection import extract as extract_js
    from tests.fixtures import pages

    async def go():
        session = await MANAGER.open(lane="A", engine="chromium",
                                     headless=True)
        record = session.page(session.focused)
        await record.page.set_content(getattr(pages, page_name.upper()))
        data = await extract_js(record.page)
        assert not data["forms"], (
            "the fixture grew a <form> element and stopped testing the case "
            "it exists for")
        if page_name == "compose_shadow":
            # The variant is only worth its runtime if the composer really is
            # behind a shadow boundary. A fixture whose script silently failed
            # would pass every assertion below as an ordinary light-tree page.
            assert data["completeness"]["shadow_roots_traversed"] >= 1, (
                "the shadow fixture built no shadow root, so this parameter "
                "is testing the light-tree case twice")
        by_name = {a["name"]: a for a in data["affordances"]}
        for field in ("To", "Add a subject", "Message body"):
            assert by_name[field]["cls"] == "form_control", (
                f'"{field}" came back as {by_name[field]["cls"]}')
            assert by_name[field]["region"], (
                f'"{field}" belongs to no region')
        for command in ("Send", "Discard"):
            assert by_name[command]["cls"] == "primary", (
                f'"{command}" came back as {by_name[command]["cls"]}')

    run(go())


def test_the_overlay_variant_still_reports_the_lid_it_used_to_report():
    """The line that must NOT move.

    The composer painted over the whole viewport IS a viewport lid, and H-09
    exists because a read that stays silent about one tells an agent every
    control is visible while a human sees a white box. Surfacing the panel's
    own controls does not make the page underneath readable, and the split
    the completeness block prints -- what a click would refuse, what it would
    run -- is the same measurement it always was."""
    from tests.fixtures import pages

    async def go():
        _, view = await _read(pages.COMPOSE_OVERLAY)
        completeness = _block(view["projection"], "## 4 COMPLETENESS")
        assert "an opaque panel covers the viewport" in completeness
        assert "behind_it=" in completeness and "actable=" in completeness

    run(go())


def test_the_docked_variant_reports_no_lid_because_it_covers_nothing():
    """The other side of the same line: a corner-docked composer hides
    nothing, so a read that announced a lid there would be inventing one."""
    from tests.fixtures import pages

    async def go():
        _, view = await _read(pages.COMPOSE_DOCKED)
        completeness = _block(view["projection"], "## 4 COMPLETENESS")
        assert "an opaque panel covers the viewport" not in completeness

    run(go())


@pytest.mark.parametrize("budget", [3000, 5000, 12000])
def test_the_composer_survives_every_budget_the_acceptance_test_tried(budget):
    """The field measurement, as a pin.

    The acceptance test's evidence that this was classification rather than
    the ladder was that the same twenty controls stayed unlisted from 3,000
    tokens to 12,000. The inverse is the property now: the composer is there
    at the smallest budget a caller can reasonably pass and it is still there
    when the budget stops binding."""
    from tests.fixtures import pages

    async def go():
        _, view = await _read(pages.COMPOSE_OVERLAY, budget_tokens=budget)
        affordances = _block(view["projection"], "## 3 AFFORDANCES")
        refs = _refs_for(affordances, COMPOSER)
        assert set(refs) == set(COMPOSER), (
            f'at {budget} tokens the read lost '
            f'{sorted(set(COMPOSER) - set(refs))}')

    run(go())


def test_a_lone_loose_field_does_not_become_a_form_of_its_own():
    """THE BOUND, pinned so the widening cannot creep.

    The `form_control` quota's promise -- complete whenever the form fits,
    never sampled -- was written against exactly the failure this fix is one
    edit away from causing: every loose input on an app shell claiming it.
    Two fields make a form; one does not. `appshell` carries a navigation bar
    and sixty links and no field at all, so it must gain no panel."""
    from tests.fixtures import pages

    async def go():
        _, view = await _read(pages.APPSHELL)
        assert "| panel |" not in view["projection"], (
            "a page with no fields grew a panel region")

    run(go())


def test_a_toolbar_of_filters_is_not_a_form_however_many_controls_it_has():
    """THE BOUND THAT THE FIRST VERSION OF THIS FIX BROKE, kept here in the
    file that broke it.

    The first seed rule counted any field at all, and
    `corpus/b/loose_controls.html` -- an application-shell toolbar with a
    search box, four filter checkboxes, two selects, a radio group, a date
    and a range -- became a panel, so all nineteen loose controls claimed the
    form-control quota. Phase 2's own pin caught it
    (`test_phase2_reads.py::test_loose_controls_compete_rather_than_claiming
    _the_form_exemption`), which is that pin doing exactly its job.

    The line is what a human DOES with the controls: a composer is a surface
    you type into, a toolbar is a bar you set. So only free-text fields seed a
    group, and one search box in a toolbar is one seed rather than two. This
    is the same page rebuilt as a fixture rather than a corpus file, so the
    bound holds in a fresh clone where `corpus/` is absent."""
    async def go():
        _, view = await _read(_TOOLBAR_SHELL)
        assert "| panel |" not in view["projection"], (
            "a filter toolbar was segmented as a form, so nineteen loose "
            f'controls just claimed the form-control quota\n'
            f'{_block(view["projection"], "## 2 PAGE SHAPE")}')
        # And the toolbar's own controls are still THERE, which is the other
        # half: not claiming the exemption is not the same as being dropped.
        assert '"Search records"' in view["projection"]

    run(go())


#: The `loose_controls` shape, inlined so the bound is pinned without the
#: local-only corpus tree.
_TOOLBAR_SHELL = """<!doctype html><html lang="en"><head>
<title>An app shell whose controls live outside any form</title></head><body>
<header><nav aria-label="Primary"><a href="/a">Dashboard</a>
<a href="/b">Records</a></nav></header>
<div role="toolbar" aria-label="Record tools">
  <label for="q">Search records</label>
  <input id="q" type="search" aria-label="Search records">
  <button>Search</button>
  <label><input type="checkbox" checked> Open</label>
  <label><input type="checkbox"> Closed</label>
  <label><input type="checkbox"> Assigned to me</label>
  <label><input type="checkbox"> Flagged</label>
  <label for="sort">Sort by</label>
  <select id="sort"><option>Newest</option><option>Oldest</option></select>
  <label for="pp">Per page</label>
  <select id="pp"><option>25</option><option>50</option></select>
  <label><input type="radio" name="view" checked> List</label>
  <label><input type="radio" name="view"> Board</label>
  <label><input type="radio" name="view"> Calendar</label>
  <button>Assign selected</button><button>Export selected</button>
  <button>Archive selected</button><button>Delete selected</button>
  <label for="since">Updated since</label>
  <input id="since" type="date" value="2026-01-01">
  <label for="conf">Minimum confidence</label>
  <input id="conf" type="range" min="0" max="100" value="60">
</div>
<main><h1>Records</h1></main></body></html>"""


def test_a_real_form_is_untouched_by_the_panel_rule():
    """The other bound. `formpage` has a `<form>`, so its fields were always
    form controls and its panel count must be zero: a page that declares its
    structure classifies exactly as it did before this fix existed."""
    from tests.fixtures import pages

    async def go():
        _, view = await _read(pages.FORMPAGE)
        assert "| panel |" not in view["projection"], (
            "a real <form> was also segmented as a panel, so the page is "
            "described twice")
        assert "Place order" in view["projection"]

    run(go())


def test_the_composers_controls_are_reachable_by_name_as_well():
    """The neighbouring route, checked rather than assumed.

    `find_elements` is the documented cheap follow-up for anything a read
    left out, and it runs its own search rather than reading the affordance
    list, so the two can disagree. On the page that broke, they must both
    reach the Send button."""
    from tests.fixtures import pages

    async def go():
        session, _ = await _read(pages.COMPOSE_OVERLAY)
        found = await lite.find_elements(page=session.focused, query="Send")
        assert found["matched"] >= 1, "find_elements could not reach Send"
        ref = pagedata.unwrap(found["results"]).splitlines()[1].split(" | ")[0]
        assert session.element_map.entries[ref].kind == "affordance"

    run(go())
