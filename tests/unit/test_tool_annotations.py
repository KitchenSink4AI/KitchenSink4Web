"""Guard: every tool ships a title, and every tool that can change
something declares whether the change may be destructive.

The Anthropic Connectors Directory requires `title` and the applicable
hints on every tool, and a client shows the title to a human instead of
the raw tool name, so a missing or wrong one is a product defect rather
than a documentation nit. Three things are checked here.

FIRST, coverage and shape on the wire: every registered tool carries a
non-empty title, titles are unique within this server, none exceeds 40
characters, and none carries product or marketing language.

SECOND, the classification itself. The non-destructive allowlist below is
hand-audited and lives in the TEST on purpose. `policy/tool_annotations.py`
is where the server reads its classification from; if both sides shared
one list the test would only prove the file equals itself. A new tool
consequently fails twice until somebody classifies it deliberately, once
at registration, where `annotations()` raises on an unclassified mutating
name, and once here.

THIRD, the published tables. `docs/TOOL_TITLES.md` and
`docs/TOOL_ANNOTATIONS.md` are what a reviewer reads and what a maintainer
disputes a row in. They are generated from the module, so they are checked
against it here; a table that drifts from the wire is worse than no table.
"""

from __future__ import annotations

import re
from pathlib import Path

import asyncio

import pytest

from kitchensink4web import packs, server
from kitchensink4web.policy import readonly
from kitchensink4web.policy import tool_annotations as ann

DOCS = Path(__file__).resolve().parents[2] / "docs"

#: Words a tool title must not carry. The checklist rejects tool metadata
#: that promotes a product, and a title is the most visible metadata there
#: is.
MARKETING = {
    "best", "powerful", "easy", "easiest", "fast", "fastest", "pro",
    "premium", "ultimate", "smart", "magic", "magical", "free", "awesome",
    "amazing", "seamless", "effortless", "revolutionary", "unlimited",
    "kitchensink4ai", "kitchensink4word", "kitchensink4xl",
    "kitchensink4ppt", "kitchensink4web",
}


def _wire(tool) -> dict:
    return tool.to_mcp_tool().model_dump(exclude_none=True)


#: Every pack this server can launch with. The surface is enumerated from a
#: full-pack launch rather than the default one, because an annotation that
#: is only correct in lite mode is not correct.
ALL_PACKS = sorted(packs.PACK_SUMMARIES)


@pytest.fixture()
def registered():
    """tool name -> tool object, with every pack on and acting unlocked.

    FUNCTION-scoped, and it restores the exact grade it found. The read-only
    grade is process-global, so a module-scoped version of this fixture
    outlives the conftest's per-test `_no_grade_leak` check and leaves the
    grade wrong for every test the shuffle runs afterwards. Re-launching per
    test costs milliseconds; getting this wrong costs the rest of the suite.
    """
    before = readonly.grade()
    state = server.configure(cli_packs=ALL_PACKS, read_only=False)
    assert state["read_only"] is None
    tools = asyncio.run(server.mcp._list_tools())
    yield {t.name: t for t in tools}
    server.configure(read_only=before if before is not None else False)


def test_every_registered_tool_carries_a_non_empty_title(registered):
    missing = [name for name, tool in sorted(registered.items())
               if not _wire(tool).get("title")]
    assert not missing, (
        f"these tools reach tools/list with no title: {missing}")


def test_titles_are_unique_within_this_server(registered):
    seen: dict = {}
    clashes = []
    for name, tool in sorted(registered.items()):
        title = _wire(tool)["title"]
        if title in seen:
            clashes.append(f"{title!r}: {seen[title]} and {name}")
        seen[title] = name
    assert not clashes, (
        "two tools would show the same name in a client: " + "; ".join(clashes))


def test_no_title_is_longer_than_forty_characters(registered):
    long = {name: _wire(tool)["title"]
            for name, tool in registered.items()
            if len(_wire(tool)["title"]) > 40}
    assert not long, f"titles over 40 characters: {long}"


def test_no_title_carries_marketing_language(registered):
    offenders = {}
    for name, tool in registered.items():
        words = set(re.findall(r"[a-z0-9]+", _wire(tool)["title"].lower()))
        hit = words & MARKETING
        if hit:
            offenders[name] = sorted(hit)
    assert not offenders, (
        f"a tool title is not a place to sell anything: {offenders}")


def test_the_title_table_covers_the_registered_surface_exactly(registered):
    registered = set(registered)
    assert registered - set(ann.TITLES) == set(), (
        "tools with no title (add them to tool_annotations.py): "
        f"{sorted(registered - set(ann.TITLES))}")
    assert set(ann.TITLES) - registered == set(), (
        "tool_annotations.py titles tools that no longer exist: "
        f"{sorted(set(ann.TITLES) - registered)}")


def test_an_untitled_name_raises_rather_than_getting_a_generated_title():
    with pytest.raises(RuntimeError):
        ann.title("a_tool_that_does_not_exist")


def test_the_wire_title_is_the_one_the_module_declares(registered):
    for name, tool in sorted(registered.items()):
        assert _wire(tool)["title"] == ann.TITLES[name], name


def _doc_rows(filename: str) -> list:
    text = (DOCS / filename).read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append([c.strip("`") for c in cells])
    return rows


def test_the_published_title_table_matches_the_module():
    rows = _doc_rows("TOOL_TITLES.md")
    published = {name: title for name, title, *_ in rows}
    assert published == ann.TITLES, (
        "docs/TOOL_TITLES.md has drifted from tool_annotations.py. "
        "Regenerate it rather than editing either side by hand.")


# --------------------------------------------- destructiveHint and friends

#: HAND-AUDITED. Every name here was classified by reading the tool's
#: implementation, against the rule stated in docs/TOOL_ANNOTATIONS.md: a
#: tool is non-destructive only when every path either ADDS without
#: replacing, or changes no user data at all.
NON_DESTRUCTIVE_TOOLS = {
    "emulate", "read_image_text", "scroll", "set_routing"
}


def test_every_mutating_tool_carries_a_destructive_hint(registered):
    missing = []
    for name, tool in sorted(registered.items()):
        annotations = getattr(tool, "annotations", None)
        if annotations is None:
            missing.append(name)
            continue
        if (annotations.readOnlyHint is False
                and annotations.destructiveHint is None):
            missing.append(name)
    assert not missing, (
        f"these tools can change something and say nothing about whether "
        f"the change is destructive: {missing}")


def test_no_read_only_tool_claims_a_destructive_hint(registered):
    """The field is meaningful only when readOnlyHint is false. A value on
    a read-only tool is noise a reviewer has to interpret."""
    noisy = [name for name, tool in registered.items()
             if tool.annotations.readOnlyHint is True
             and tool.annotations.destructiveHint is not None]
    assert not noisy, noisy


def test_the_destructive_classification_covers_the_surface(registered):
    mutating = {name for name, tool in registered.items()
                if tool.annotations.readOnlyHint is False}
    classified = ann.DESTRUCTIVE | ann.NON_DESTRUCTIVE
    assert mutating - classified == set(), (
        "unclassified tools (add them to tool_annotations.py): "
        f"{sorted(mutating - classified)}")
    assert classified - mutating == set(), (
        "tool_annotations.py classifies tools that are read-only or gone: "
        f"{sorted(classified - mutating)}")
    assert not (ann.DESTRUCTIVE & ann.NON_DESTRUCTIVE)


def test_the_non_destructive_set_matches_the_hand_audited_allowlist(registered):
    on_the_wire = {
        name for name, tool in registered.items()
        if tool.annotations.destructiveHint is False
    }
    assert on_the_wire == NON_DESTRUCTIVE_TOOLS, (
        "the non-destructive set changed. Added: "
        f"{sorted(on_the_wire - NON_DESTRUCTIVE_TOOLS)}; removed: "
        f"{sorted(NON_DESTRUCTIVE_TOOLS - on_the_wire)}. Classify the tool "
        "by reading its implementation against the rule in "
        "docs/TOOL_ANNOTATIONS.md, then update BOTH this allowlist and "
        "tool_annotations.py.")


def test_an_unclassified_mutating_tool_raises_at_registration():
    try:
        ann.annotations("a_tool_that_does_not_exist", read_only=False)
    except RuntimeError:
        return
    raise AssertionError(
        "an unclassified mutating tool must refuse to register rather than "
        "defaulting: defaulting to false is a false safety claim and "
        "defaulting to true is a lie about a read.")


def test_open_world_hint_is_declared_on_every_tool(registered):
    missing = [name for name, tool in registered.items()
               if tool.annotations.openWorldHint is None]
    assert not missing, missing


def test_only_the_local_tools_are_closed_world(registered):
    closed = {name for name, tool in registered.items()
              if tool.annotations.openWorldHint is False}
    assert closed == ann.CLOSED_WORLD, (
        "a tool that reaches a remote site must say so: added "
        f"{sorted(closed - ann.CLOSED_WORLD)}, removed "
        f"{sorted(ann.CLOSED_WORLD - closed)}")


def test_idempotent_hint_is_true_or_absent_never_false(registered):
    for name, tool in registered.items():
        hint = tool.annotations.idempotentHint
        assert hint in (True, None), (name, hint)
        assert (hint is True) == (name in ann.IDEMPOTENT), name


def test_the_published_annotation_tables_match_the_module():
    text = (DOCS / "TOOL_ANNOTATIONS.md").read_text(encoding="utf-8")
    destructive, non_destructive = set(), set()
    bucket = None
    for line in text.splitlines():
        if line.startswith("## Tools that may perform destructive"):
            bucket = destructive
        elif line.startswith("## Tools that may not"):
            bucket = non_destructive
        elif line.startswith("## "):
            bucket = None
        elif bucket is not None and line.startswith("| `"):
            bucket.add(line.strip("|").split("|")[0].strip().strip("`"))
    assert destructive == ann.DESTRUCTIVE, (
        "docs/TOOL_ANNOTATIONS.md destructive table has drifted: added "
        f"{sorted(destructive - ann.DESTRUCTIVE)}, removed "
        f"{sorted(ann.DESTRUCTIVE - destructive)}")
    assert non_destructive == ann.NON_DESTRUCTIVE, (
        "docs/TOOL_ANNOTATIONS.md non-destructive table has drifted: added "
        f"{sorted(non_destructive - ann.NON_DESTRUCTIVE)}, removed "
        f"{sorted(ann.NON_DESTRUCTIVE - non_destructive)}")


def test_every_destructive_row_states_a_reason():
    text = (DOCS / "TOOL_ANNOTATIONS.md").read_text(encoding="utf-8")
    thin = []
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 2 and len(cells[1]) < 20:
            thin.append(cells[0])
    assert not thin, (
        f"a reviewer cannot dispute a row with no reason on it: {thin}")
