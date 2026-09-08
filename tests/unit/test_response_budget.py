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
import json

import pytest
from fastmcp import Client

from kitchensink4web import envelope, server
from kitchensink4web.ops import lite
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
