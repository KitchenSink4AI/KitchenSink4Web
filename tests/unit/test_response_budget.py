"""What a response costs, and what it still says after it got cheaper.

The ship-polish wave (fat audit D1-D5) made responses smaller. Every pin
here is one of two kinds and says which it is:

  BUDGET       the response got cheaper, measured against the shape it
               replaced rather than against a number someone chose
  COMPLETENESS the answer is still all there, proved by rebuilding the old
               shape out of the new one and comparing, not by asserting
               that some string survived

A budget pin on its own is how a trim quietly deletes an answer, so no
trim in this file has one without the other.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import pathlib

import pytest
from fastmcp import Client

from kitchensink4web import envelope, server
from kitchensink4web.engine import lanedb, lanes
from kitchensink4web.ops import lite
from kitchensink4web.projection import project, render
from tests.fixtures.results import client_payload, content_text


def _call(name: str, args: dict):
    """Through a real client, the way test_registration does it: a refusal
    is a result here, not an exception."""
    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool(name, args, raise_on_error=False)

    return asyncio.run(run())


def _tools():
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


# ------------------------------------------------------------------- D1


def test_a_success_ships_exactly_one_copy_of_its_answer(launch):
    """BUDGET. The answer used to leave as `structuredContent` AND as a
    text serialization of the same object, byte for byte identical."""
    launch()
    result = _call("get_workflows", {"topic": "read-only"})
    assert result.structured_content is None, (
        "a success carries no structured copy: the client reads content")
    assert len(result.content) == 1


def test_the_text_a_client_reads_is_the_whole_payload(launch):
    """COMPLETENESS. The one copy that ships parses back to exactly the
    object the op built, so nothing was traded away for the saving."""
    launch()
    result = _call("get_workflows", {"topic": "budgeting"})
    rebuilt = json.loads(content_text(result))
    direct = asyncio.run(lite.get_workflows(topic="budgeting"))
    assert rebuilt == envelope.success(direct)


def test_no_tool_promises_a_structured_copy_it_no_longer_sends(launch):
    """Both directions. `outputSchema` in tools/list tells a client to
    expect `structuredContent`; this server stopped sending one on the
    success path, so advertising it would be a false promise. It also
    validated nothing: it was {"type":"object","additionalProperties":true}
    on all fifty-two tools."""
    launch(cli_packs=["extract", "capture", "network", "storage", "files",
                      "diagnostics", "workflows"], read_only=False)
    tools = _tools()
    assert len(tools) > 40, "the full surface should be up for this check"
    offenders = [n for n, t in tools.items() if t.output_schema is not None]
    assert offenders == []


def test_a_refusal_keeps_its_structured_copy_and_loses_the_indent(launch):
    """Both directions, and the reasons differ from the success path:
    isError forces this shape anyway, a refusal is sixty tokens, and
    RefusalResult's own mapping protocol reads structured_content back
    in-process. What a refusal does NOT need is pretty-printing."""
    launch()
    result = _call("get_workflows", {"topic": "no-such-topic"})
    assert result.is_error is True
    assert result.structured_content is not None, (
        "ops and the test harness index a refusal like the dict it is")
    text = content_text(result)
    assert "\n" not in text, "a refusal ships compact, like every success"
    assert json.loads(text) == result.structured_content


def test_the_refusal_still_names_every_topic_and_a_recovery(launch):
    """COMPLETENESS for the pin above: compact is a whitespace change and
    nothing else."""
    launch()
    payload = client_payload(_call("get_workflows", {"topic": "nope"}))
    assert payload["error"]["code"] == "BAD_PARAMS"
    assert "reading" in payload["error"]["message"]
    assert payload["error"]["hint"]


# ------------------------------------------------------------------- D2


def _all_topics(launch_fixture):
    launch_fixture()
    return client_payload(_call("get_workflows", {"topic": "all"}))["workflows"]


def test_a_bare_call_returns_the_menu_not_the_manual(launch):
    """BUDGET. A bare call is a caller orienting, and orientation does not
    need every recipe for every pack, including the packs this launch did
    not load."""
    launch()
    menu = content_text(_call("get_workflows", {}))
    everything = content_text(_call("get_workflows", {"topic": "all"}))
    assert len(menu) * 4 < len(everything), (
        f"the menu is {len(menu)} chars against {len(everything)} for the "
        f"full dump; it is supposed to be a fraction of it")


def test_every_topic_is_still_reachable_by_name_and_unchanged(launch):
    """COMPLETENESS, and it is the pin that matters for D2: no topic text
    was rewritten or dropped, it was re-homed behind its own name. Each
    topic is fetched individually and compared against the entry in the
    full dump."""
    everything = _all_topics(launch)
    assert len(everything) >= 14
    for name, body in everything.items():
        one = client_payload(_call("get_workflows", {"topic": name}))
        assert one["topic"] == name
        assert one["workflow"] == body, f"topic {name} changed on the way out"


def test_the_menu_names_every_topic_and_only_real_topics(launch):
    """Both directions. A topic with no gloss would ship a menu with a hole
    in it; a gloss with no topic would advertise a name that refuses."""
    everything = _all_topics(launch)
    menu = client_payload(_call("get_workflows", {}))["topics"]
    assert set(menu) == set(everything)
    for name, gloss in menu.items():
        assert gloss and isinstance(gloss, str), name


def test_the_menu_says_how_to_spend_it(launch):
    """A menu that does not say the names are arguments is a list of words.
    Both routes it names are asserted to work, so the sentence cannot go
    stale against the code."""
    launch()
    payload = client_payload(_call("get_workflows", {}))
    assert "topic=" in payload["how"]
    assert "'all'" in payload["how"] or '"all"' in payload["how"]
    for name in payload["topics"]:
        assert _call("get_workflows", {"topic": name}).is_error is False


def test_all_is_reserved_and_no_real_topic_can_take_it(launch):
    """`all` has to mean the dump, so a topic of that name would shadow it
    silently. Held here rather than in a comment."""
    everything = _all_topics(launch)
    assert lite._ALL_TOPICS not in everything


@pytest.mark.parametrize("spelling", ["ALL", " all ", "All"])
def test_the_dump_answers_to_the_same_spellings_a_topic_does(launch,
                                                             spelling):
    """`topic` is stripped and lowercased for every other name; `all` is
    not a special case that forgot."""
    launch()
    result = _call("get_workflows", {"topic": spelling})
    assert result.is_error is False
    assert "workflows" in client_payload(result)


# ------------------------------------------------------------------- D3


def _sessions_topic(launch_fixture):
    launch_fixture()
    return client_payload(
        _call("get_workflows", {"topic": "sessions"}))["workflow"]


def test_the_status_teaching_moved_verbatim_and_not_a_word_changed(launch):
    """COMPLETENESS, and the one that matters for D3: status was 52% text
    that said the same words on every call whatever the state was, and the
    fat audit's instruction was to RELOCATE it, not to rewrite it. Every
    paragraph is compared against the constant status itself still uses, so
    a future edit that reworded one copy fails here rather than shipping
    two accounts of the same rule."""
    topic = _sessions_topic(launch)
    assert topic["shared_state"] == (
        f"{lite.SHARED_STATE_RULE} {lite.SHARED_STATE_DETAIL}")
    assert topic["idle_bounds"] == lite.IDLE_ADVISORY_NOTE
    assert topic["lane_database"] == lanedb.DISCLOSURE
    assert topic["browser_recommendation"]["note"]
    assert topic["browser_recommendation"]["default"]["why"]
    assert topic["browser_recommendation"]["research"]["why"]


def test_the_lane_database_disclosure_has_exactly_one_copy(launch):
    """Both directions. A privacy promise printed from two places is a
    privacy promise that can disagree with itself. The status block stopped
    repeating it; the action a caller reaches for when the question IS the
    database still carries it, and it comes from the same constant."""
    launch()
    assert lanedb.status(explain=True)["never_stores"] == (
        lanedb.DISCLOSURE["never_stores"])
    assert "never_stores" not in lanedb.status(explain=False)
    lanes_action = client_payload(
        _call("manage_session", {"action": "lanes"}))
    assert lanes_action["lane_database"]["never_stores"] == (
        lanedb.DISCLOSURE["never_stores"])


def test_the_recommendation_keeps_its_lanes_when_it_drops_its_reasons(
        launch):
    """COMPLETENESS. `explain=False` is allowed to drop sentences and is
    not allowed to drop an answer."""
    launch()
    full = lanes.recommended_lane()
    brief = lanes.recommended_lane(explain=False)
    assert brief["default"]["lane"] == full["default"]["lane"]
    assert brief["research"]["lane"] == full["research"]["lane"]
    assert brief["installed"] == full["installed"]
    assert "why" not in brief["default"]
    assert "note" not in brief


def test_status_names_where_the_teaching_went(launch):
    """A block that stops explaining itself and does not say where the
    explanation is has not been trimmed, it has been deleted. The pointer
    is asserted to be a call that actually answers."""
    launch()
    status = client_payload(_call("manage_session", {"action": "status"}))
    assert status["explained_by"] == "get_workflows(topic='sessions')"
    assert _call("get_workflows", {"topic": "sessions"}).is_error is False


def test_status_keeps_the_state_and_the_claims(launch):
    """Both directions for the whole of D3: what left status was text that
    never varied, and every one of these varies or is a claim the server
    makes about itself."""
    launch()
    status = client_payload(_call("manage_session", {"action": "status"}))
    assert status["idle_advisory"]["automatic_action"] == "none"
    assert "quiet_after_s" in status["idle_advisory"]
    assert "read_only" in status
    assert "optional_features" in status
    assert status["lane_database"]["learning"]
    assert "installed" in status["browsers"]


def test_a_reap_that_did_nothing_says_nothing(launch):
    """A startup fact restated forever is not a status. The census keys
    (`journals`, `skipped_live_owner`) are deliberately not triggers: a
    machine running a second KS4Web has them non-zero on every healthy
    launch, which would make the condition always true."""
    assert lite._reap_did_something({}) is False
    assert lite._reap_did_something(
        {"journals": 3, "skipped_live_owner": 2, "killed": [],
         "declined": [], "profiles_removed": []}) is False
    assert lite._reap_did_something(
        {"journals": 1, "killed": [4321]}) is True
    assert lite._reap_did_something({"declined": [{"pid": 1}]}) is True
    assert lite._reap_did_something({"profiles_removed": ["x"]}) is True
    assert lite._reap_did_something({"audits_removed": 2}) is True


# ------------------------------------------------------------------- D4

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
FIXTURES = ("article", "appshell", "formpage", "names", "hidden")
META = {"status": 200, "load_state": "load", "lane": "A(chromium)",
        "page": "p1", "read_token": "rt1", "ts": "2026-09-05T00:00:00"}


def _projection(name: str, budget: int = 5000):
    data = json.loads((DATA / f"extract_{name}.json").read_text(
        encoding="utf-8"))
    return project(data, META, budget=budget)


def _section(text: str, title: str) -> str:
    """One `## N TITLE` section of a projection, header included."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("## ") and title in ln)
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


@pytest.mark.parametrize("name", FIXTURES)
@pytest.mark.parametrize("title", ["PAGE SHAPE", "COMPLETENESS",
                                   "NEXT CALLS"])
def test_a_section_header_is_a_label_and_not_a_tutorial(name, title):
    """BUDGET. These three headers carried an explanation that did not vary
    from page to page and was reprinted on every read forever."""
    text = _projection(name).text
    header = next((ln for ln in text.splitlines()
                   if ln.startswith("## ") and title in ln), None)
    if header is None:
        pytest.skip(f"{name} has no {title} section")
    assert header.rstrip().endswith(title), (
        f"the {title} header is explaining itself again: {header!r}")


@pytest.mark.parametrize("name", FIXTURES)
def test_the_completeness_claims_are_untouched_by_the_header_trim(name):
    """COMPLETENESS, both directions, and it is the pin the brief asks for
    by name. What the ledger CLAIMS is the product; only the header above
    it was allowed to change. Rebuilt by stripping the header line and
    comparing the rest against a rendering under the header this section
    used to carry."""
    text = _projection(name).text
    body = _section(text, "COMPLETENESS").splitlines()[1:]
    assert body, "the completeness ledger rendered nothing at all"
    joined = "\n".join(body)
    # The ledger still states each class of thing it did not see, and still
    # ends with the meter's own measured bill.
    assert "budget:" in joined
    assert any("hidden" in ln or "omitted" in ln or "not " in ln
               for ln in body), joined


def test_the_header_teaching_is_reachable_and_verbatim(launch):
    """COMPLETENESS. Nothing was deleted: each sentence moved into the
    workflow topic that already owned the subject, and the topic quotes the
    SAME constant the header used to interpolate, so the two cannot
    drift."""
    launch()
    budgeting = client_payload(
        _call("get_workflows", {"topic": "budgeting"}))["workflow"]
    reading = client_payload(
        _call("get_workflows", {"topic": "reading"}))["workflow"]
    assert any(render.HEADER_TEACHING["page_shape"] in line
               for line in budgeting)
    assert any(render.HEADER_TEACHING["completeness"] in line
               for line in reading)
    assert any(render.HEADER_TEACHING["next_calls"] in line
               for line in reading)


@pytest.mark.parametrize("name", FIXTURES)
def test_the_trim_never_costs_the_reader_content(name):
    """Both directions. A header trim frees tokens under a ceiling that did
    not move, so a read either spends them on content or hands them back.
    What it must never do is print LESS than it did before."""
    result = _projection(name)
    assert result.tokens <= 5000
    for title in ("IDENTITY", "COMPLETENESS"):
        assert f" {title}" in result.text


# ------------------------------------------------------------------- D5


def test_get_text_defaults_to_a_size_the_caller_did_not_have_to_pick():
    """BUDGET. 20,000 characters measured 6,598 tokens on the corpus GDP
    article, which is 1.3x the ENTIRE default page-view budget in a call
    nobody sized. Every other read here is token-budgeted and conservative
    with it."""
    default = inspect.signature(lite.get_text).parameters["max_chars"].default
    assert default == 8000
    view = inspect.signature(lite.get_page_view).parameters
    assert default < view["budget_tokens"].default * 3, (
        "the get_text default should not be able to outweigh a whole page "
        "view again; a page view's budget is in TOKENS and this is in "
        "characters, and this corpus runs about 3 characters per token")


def test_the_continue_story_still_names_the_number_it_will_return():
    """COMPLETENESS. The honest pagination line interpolates max_chars, so
    changing the default cannot leave it advertising the old size."""
    source = inspect.getsource(lite.get_text)
    assert "start_index={got[\"next_start_index\"]}" in source
    assert "{max_chars:,} characters" in source
    assert "20,000 characters" not in source, (
        "the continue line hard-codes a size again")
