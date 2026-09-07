"""The `accessibility` pack: a WCAG audit that never claims more than it ran.

**The engine is axe-core, and it is a DEPENDENCY rather than a vendored
file** (author ruling 2026-09-07). The reason to use it rather than write
one is authority: the value of an accessibility finding is that it speaks
the vocabulary the field already uses, so a rule id and a success-criterion
mapping land in somebody's ticket, CI, and conformance report unchanged. A
home-grown engine can be correct and still be useless as evidence. Two
supporting facts, both checked: Playwright deleted its own accessibility API
in November 2025 and its deprecation notice named axe as the replacement,
and Lighthouse's accessibility category is axe-core underneath.

It arrives through `pip install kitchensink4web[accessibility]`, from its own
publisher, under its own name, with its own license files. This project
redistributes none of it. The dependency ledger carries the row, the license
finding, and the version-currency check.

**The server drives the frames; the engine does not.** axe skips
cross-origin iframes by default and its result still looks complete: no
flag, no count, no note. That is a silent omission aimed straight at the
honesty contract, so the engine runs per entered frame with its own iframe
traversal switched OFF, and `engine/frames.py` decides which frames are
entered. It is the only arrangement in which `frames_not_entered` can be
truthful, because the server is the thing that knows what it declined.

**Four honesty rules, none of them negotiable**, because an accessibility
report that overstates its coverage produces a false conformance claim a
real person then relies on:

1. `incomplete` becomes `needs_review` and is never folded into violations
   or passes, never counted in a denominator, and never dropped silently at
   any rung. It is what the engine RAN and could not decide.
2. There is no score. A 0-to-100 number has no defensible arithmetic:
   every published one is somebody's weighting, and weighting
   `needs_review` at all, including at zero, is a claim.
3. The viewport is stated, because it is a real audit input rather than
   decoration. axe puts out-of-viewport elements into `incomplete` for the
   contrast rules, so the same page audited at two window sizes produces
   different counts and a result that does not name the window is not
   reproducible.
4. The payload says the audit ran inside the page's own JavaScript. A page
   that wants to influence the result can. Claiming otherwise would be a
   guarantee this design cannot back, since the engine runs in the main
   world beside the page's own script.

The tool is `get_accessibility`, not `audit_accessibility`: `get_audit`
already exists in this server and renders the action log, and two unrelated
concepts sharing a word in one `tools/list` costs whoever reads it next.

Env vars this module adds: KS4WEB_A11Y_TIMEOUT_MS (hard wall clock per
engine run, default 30000).
"""

from __future__ import annotations

import asyncio
import os
import time

import json as _json

from .. import pagedata as _pagedata
from ..engine import frames as _frames
from ..errors import (BadParams, RangeOutOfBounds, TargetNotFound, Timeout,
                      ValidationFailed)
from ..projection import instrument, meter
from . import common
from . import lite as _lite

ENV_TIMEOUT = "KS4WEB_A11Y_TIMEOUT_MS"

EXTRA = "kitchensink4web[accessibility]"

IMPACTS = ("critical", "serious", "moderate", "minor")
INCLUDES = ("violations", "violations+review", "all")

#: How much of any page-derived string may ride into the payload. The audit
#: log's own clip, reused rather than re-chosen: a 40,000-character element
#: is a page, not a snippet.
SNIPPET_CLIP = 200

#: Deque's own published figure for how much of WCAG automated testing with
#: axe finds. Attributed rather than stated as a general fact, and never
#: decomposed: there is no published per-success-criterion breakdown behind
#: it, so the payload may cite it and must not extrapolate from it.
COVERAGE_CAVEAT = (
    "Deque publishes that automated testing with axe finds about 57% of "
    "WCAG issues. A clean automated result is not a conformance claim. "
    "Keyboard operation, focus order, whether alternative text is "
    "MEANINGFUL, and error identification all need a human.")

NOT_CHECKED = (
    "whether alternative text describes the image",
    "whether the focus order is logical",
    "whether the page is operable by keyboard alone",
    "whether an error message identifies the error",
    "whether a heading describes the section under it",
    "whether a link's text makes sense out of context",
)

ADVERSARIAL = (
    "This audit runs inside the page's own JavaScript context. A page that "
    "wants to influence the result can. Treat the output as a report about "
    "a cooperative page, not as a verified measurement of a hostile one.")


def _timeout_s() -> float:
    try:
        return max(1.0, int(os.environ.get(ENV_TIMEOUT, "30000")) / 1000)
    except ValueError:
        return 30.0


def _engine_source() -> str:
    """The engine's own source text, from the installed package.

    Never fetched at run time and never vendored into this repo: a strict
    Content-Security-Policy would block a network-loaded script, the server
    must work offline, and a runtime-fetched auditor is a supply-chain
    injection channel into every page a user audits."""
    try:
        from axe_playwright_python.base import AXE_SCRIPT
    except ImportError as exc:
        raise ValidationFailed(
            f"the accessibility engine is not installed in this "
            f"environment, so no audit was run and nothing is reported. "
            f"It is an optional dependency: pip install {EXTRA}. Nothing "
            f"here falls back to a different engine, because a result "
            f"labeled with an engine that did not produce it is worse than "
            f"no result.") from exc
    return AXE_SCRIPT


#: Map every axe target selector on this page back to a ref, in ONE pass.
#:
#: Spliced with the instrument prelude, which the ENGINE deliberately is not
#: (P17-18): handing third-party code the per-process secret would defeat
#: the reason the channel bakes it into script sources. The mapping happens
#: here, on this server's own script, after the run.
_REF_JS = instrument(r"""
(sels) => {
// @@KS4WEB_INSTRUMENT@@
  const out = {};
  for (const sel of sels) {
    let el = null;
    try { el = document.querySelector(sel); } catch (e) { el = null; }
    if (!el) { out[sel] = null; continue; }
    let node = null;
    try { node = KS.refof.get(el); } catch (e) { node = null; }
    out[sel] = node || null;
  }
  return out;
}
""")

_VERSION_JS = "() => (window.axe && window.axe.version) || null"

_RUN_JS = r"""
(opts) => axe.run(document, opts).then(r => ({
  violations: r.violations,
  incomplete: r.incomplete,
  passes: r.passes.length,
  inapplicable: r.inapplicable.length,
  engine: r.testEngine,
  environment: r.testEnvironment
}))
"""

_TAGS_JS = """
() => {
  const seen = new Set();
  for (const rule of axe.getRules()) {
    for (const tag of (rule.tags || [])) seen.add(tag);
  }
  return Array.from(seen).sort();
}
"""


def _clip(value, limit: int = SNIPPET_CLIP) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "..."


async def _run_in(frame_obj, source: str, options: dict) -> dict:
    """Inject and run, in one realm. The injection route is
    `page.evaluate(<source string>)`, which was MEASURED against a page
    served with `Content-Security-Policy: script-src 'self'` and no
    `unsafe-eval` before any of this was written: it runs on both Chromium
    and Firefox. `add_script_tag` is the route that does NOT work there,
    because it inserts a real `<script>` element the page's own CSP governs,
    so it is never used. No context in this build sets `bypass_csp`, and
    none needs to."""
    await frame_obj.evaluate(source)
    version = await frame_obj.evaluate(_VERSION_JS)
    result = await frame_obj.evaluate(_RUN_JS, options)
    result["engine_version"] = version
    return result


def _fold(results: list[tuple[str, dict]]) -> dict:
    """Stitch per-frame results into one set of counts that ADD.

    A rule violated in two frames is one rule with the nodes of both, which
    is what an aggregate read is for; every node keeps the frame it came
    from so a drilldown can still say where."""
    rules: dict[str, dict] = {}
    review: dict[str, dict] = {}
    passes = 0
    inapplicable = 0
    for fid, res in results:
        passes += res.get("passes", 0)
        inapplicable += res.get("inapplicable", 0)
        for bucket, target in ((res.get("violations") or [], rules),
                               (res.get("incomplete") or [], review)):
            for entry in bucket:
                row = target.setdefault(entry["id"], {
                    "rule": entry["id"],
                    "impact": entry.get("impact"),
                    "wcag": [t for t in (entry.get("tags") or [])
                             if t.startswith("wcag") or t.startswith("best")],
                    "help": entry.get("help") or "",
                    "help_url": entry.get("helpUrl") or "",
                    "nodes": [],
                })
                for node in (entry.get("nodes") or []):
                    reasons = []
                    for key in ("any", "all", "none"):
                        for check in (node.get(key) or []):
                            message = check.get("message")
                            if message:
                                reasons.append(message)
                    row["nodes"].append({
                        "frame": fid or None,
                        "target": _clip("; ".join(
                            str(t) for t in (node.get("target") or []))),
                        "html": _clip(node.get("html")),
                        "impact": node.get("impact"),
                        "why": _clip(reasons[0] if reasons else
                                     node.get("failureSummary"), 240),
                    })
    return {"violations": rules, "needs_review": review,
            "passes": passes, "inapplicable": inapplicable}


def _impact_counts(rules: dict) -> dict:
    out = {k: 0 for k in IMPACTS}
    for row in rules.values():
        key = row.get("impact")
        if key in out:
            out[key] += 1
    return out


_IMPACT_ORDER = {name: i for i, name in enumerate(IMPACTS)}


def _sorted_rules(rules: dict) -> list:
    return sorted(rules.values(),
                  key=lambda r: (_IMPACT_ORDER.get(r.get("impact"), 9),
                                 -len(r["nodes"]), r["rule"]))


def _rule_line(row: dict, examples: int, refs: dict) -> dict:
    line = {"rule": row["rule"], "impact": row.get("impact"),
            "wcag": row["wcag"][:6], "help": row["help"],
            "help_url": row["help_url"], "count": len(row["nodes"])}
    if examples:
        shown = row["nodes"][:examples]
        line["examples"] = [
            {**{k: v for k, v in node.items() if k != "why"},
             "ref": refs.get(node["target"])}
            for node in shown]
        if len(row["nodes"]) > len(shown):
            line["more"] = (
                f"{len(shown)} of {len(row['nodes'])} shown; "
                f"get_accessibility(rule='{row['rule']}') returns every node")
    return line


def _review_line(row: dict) -> dict:
    reasons = [node["why"] for node in row["nodes"] if node.get("why")]
    return {
        "rule": row["rule"], "count": len(row["nodes"]),
        "why": (reasons[0] if reasons else
                "the engine ran this check and could not decide it"),
        "note": ("this is neither a pass nor a failure. It is a check that "
                 "ran and could not be decided, and it is counted "
                 "separately everywhere in this payload."),
    }


def _coverage(environment: dict, folded: dict, ladder: list) -> dict:
    """What this audit did NOT check, stated in the payload rather than in
    documentation nobody reads."""
    contrast_unresolved = sum(
        len(row["nodes"]) for key, row in folded["needs_review"].items()
        if "contrast" in key)
    return {
        "method": "automated",
        "caveat": COVERAGE_CAVEAT,
        "not_checked": list(NOT_CHECKED),
        "contrast_unresolved": contrast_unresolved,
        "viewport": {"width": environment.get("windowWidth"),
                     "height": environment.get("windowHeight")},
        "viewport_note": (
            "stated because it is an audit INPUT rather than decoration: "
            "the engine cannot determine contrast for an element outside "
            "the viewport, so it reports those as needs_review, and the "
            "same page at another window size returns different counts. A "
            "result without its viewport is not reproducible. "
            "manage_session(action='open', viewport='1920x1080') sets it."),
        "frames_not_entered": len(_frames.untouched(ladder)),
        "adversarial": ADVERSARIAL,
    }


async def get_accessibility(
    page: str,
    tags: list | None = None,
    rule: str | None = None,
    impact: str | None = None,
    include: str = "violations",
    start_index: int = 0,
    budget_tokens: int = 3000,
    frames: bool = True,
) -> dict:
    """Audit a page against the WCAG rules with axe-core, the engine whose
    rule identifiers and success-criterion mappings the accessibility field
    already writes its tickets and CI against. The default read aggregates
    BY RULE with counts and up to three example nodes each, so a page with
    five hundred problems does not return five hundred entries; rule='...'
    then returns every node for one rule, paginated, each carrying a ref
    where the element is in the anchor registry. Checks the engine ran and
    could not decide come back as needs_review, never as passes and never
    as failures, and no percentage anywhere is computed from a denominator
    containing them. There is no score: every 0-to-100 accessibility number
    is somebody's weighting rather than a measurement. The result states
    the engine and version, the viewport it was measured at (out-of-view
    elements cannot be contrast-checked, so the window size changes the
    answer), which frames were audited and which were not, and that
    automated testing finds a minority of accessibility problems.
    """
    include = common.enum_arg(include, INCLUDES, default="violations",
                              tool="get_accessibility", name="include")
    if impact is not None and impact not in IMPACTS:
        raise BadParams(
            f"unknown impact {impact!r}: the engine's impact levels are "
            f"{list(IMPACTS)}. Omit it for every level.")
    if start_index and not rule:
        raise BadParams(
            "start_index pages through the nodes of ONE rule, so it needs "
            "rule='...' beside it. The aggregate read has one line per "
            "rule and nothing to page through.")
    if tags is not None and not isinstance(tags, list):
        raise BadParams(
            "tags takes a list of axe tag strings, for example "
            "['wcag2a', 'wcag2aa']. Omit it for the engine's default set.")

    source = _engine_source()
    sess, record = common.locate(page)
    # The audit is a READ and takes the read path: an origin nothing ruled
    # on, a browser error page, and a recorded wall are all refused before
    # any page content is audited or returned.
    await _lite._read_gate(sess, record, tool="get_accessibility")
    sess.counters["reads"] += 1

    options: dict = {"iframes": False,
                     "resultTypes": ["violations", "incomplete"]}
    if tags:
        options["runOnly"] = {"type": "tag",
                              "values": [str(t) for t in tags[:20]]}

    ladder = await _frames.ladder(record) if frames else [
        _frames.FrameRef(fid="", frame=record.page.main_frame, depth=0,
                         url=record.page.url, same_origin=True,
                         entered=True, how="document")]
    entered = _frames.entered(ladder)
    started = time.monotonic()
    results: list[tuple[str, dict]] = []
    environment: dict = {}
    engine_version = None
    try:
        async def sweep():
            for ref in entered:
                realm = record.page if ref.is_main else ref.frame
                got = await _run_in(realm, source, options)
                results.append((ref.fid, got))
                if not environment:
                    environment.update(got.get("environment") or {})
                return_version = got.get("engine_version")
                if return_version:
                    nonlocal engine_version
                    engine_version = return_version
        await asyncio.wait_for(sweep(), _timeout_s())
    except (asyncio.TimeoutError, TimeoutError) as exc:
        # A PARTIAL AUDIT IS A DANGEROUS ARTIFACT. An audit that stopped at
        # 60% and reported nine violations reads exactly like a clean audit
        # that found nine, so nothing partial is returned.
        raise Timeout(
            f"the accessibility engine did not finish inside the "
            f"{_timeout_s():.0f}-second cap on this page, so NOTHING is "
            f"returned rather than a partial audit that would read like a "
            f"complete one. The usual cause is the engine waiting on the "
            f"page's own stylesheets, which it loads to compute contrast. "
            f"Narrow the run with tags=['wcag2a'], or raise "
            f"{ENV_TIMEOUT}.") from exc
    except Exception as exc:
        detail = str(exc).splitlines()[0][:200]
        if "axe is not defined" in detail or "evaluat" in detail.lower():
            raise ValidationFailed(
                f"the accessibility engine could not run in this page: "
                f"{detail}. Nothing is returned rather than an empty audit "
                f"that would read like a clean page.") from exc
        raise

    folded = _fold(results)
    if impact:
        folded["violations"] = {k: v for k, v in folded["violations"].items()
                                if v.get("impact") == impact}
    elapsed = round((time.monotonic() - started) * 1000)

    if tags and not folded["violations"] and not folded["needs_review"] \
            and not folded["passes"]:
        # An unknown tag makes axe run nothing at all, which is
        # indistinguishable from a clean page. Name the valid set instead.
        known = await record.page.evaluate(_TAGS_JS)
        unknown = [t for t in tags if t not in known]
        if unknown:
            raise BadParams(
                f"no rule in this engine carries the tag(s) {unknown}, so "
                f"the run selected nothing and the empty result would have "
                f"read like a clean page. This engine's tags are {known}.")

    # ---------------------------------------------------------- assemble

    rules = folded["violations"]
    review = folded["needs_review"]
    ordered = _sorted_rules(rules)
    coverage = _coverage(environment, folded, ladder)
    scope = {
        "engine": f"axe-core {engine_version or 'version unreported'}",
        "engine_source": ("an optional pip dependency of this server, not "
                          "vendored into it"),
        "tags": (list(tags) if tags else "the engine's default rule set"),
        "frames_audited": [{"frame": r.fid or "(main document)",
                            "url": r.url} for r in entered],
        "frames_not_entered": [
            {"frame": r.fid, "why": r.why_not or "not entered",
             "origin": r.origin} for r in _frames.untouched(ladder)],
    }
    if scope["frames_not_entered"]:
        # The verified silent-omission hazard, made loud. The engine skips
        # cross-origin frames and its result still looks complete; the count
        # of what nobody looked at is the only honest answer.
        scope["frames_note"] = (
            f"{len(scope['frames_not_entered'])} frame(s) on this page were "
            f"NOT audited, so any accessibility problem inside them is "
            f"absent from these counts rather than absent from the page.")
    totals = {
        "rules_violated": len(rules),
        "nodes_affected": sum(len(r["nodes"]) for r in rules.values()),
        "by_impact": _impact_counts(rules),
        "needs_review_rules": len(review),
        "needs_review_nodes": sum(len(r["nodes"]) for r in review.values()),
        "passed_rules": folded["passes"],
        "inapplicable_rules": folded["inapplicable"],
        "note": ("needs_review is counted on its own and appears in no "
                 "denominator anywhere in this payload. It is what the "
                 "engine ran and could not decide: neither a pass nor a "
                 "failure. There is deliberately no score."),
    }

    # ------------------------------------------------- the drilldown read
    if rule is not None:
        row = rules.get(rule) or review.get(rule)
        if row is None:
            fired = sorted(set(rules) | set(review))
            listed = (str(fired) if fired else
                      "(none: nothing the selected tags cover was violated "
                      "or left undecided here)")
            raise TargetNotFound(
                f"no rule named {rule!r} fired on this page. The rules that "
                f"did are {listed}. Rule ids come from the aggregate read, "
                f"so a second aggregate call is not needed to find one.")
        nodes = row["nodes"]
        if start_index and start_index >= len(nodes):
            raise RangeOutOfBounds(
                f"rule {rule!r} affects {len(nodes)} node(s), so "
                f"start_index runs from 0 to {max(0, len(nodes) - 1)}; "
                f"{start_index} is past the end.")
        chunk, total, nxt = common.page_slice(nodes, start_index, 50)
        refs = await _resolve_refs(sess, record, chunk)
        body = {
            "rule": row["rule"], "impact": row.get("impact"),
            "wcag": row["wcag"][:6], "help": row["help"],
            "help_url": row["help_url"],
            "kind": ("violation" if rule in rules else "needs_review"),
            "nodes": [{**node, "ref": refs.get(node["target"])}
                      for node in chunk],
            "shown": len(chunk), "total": total,
            "start_index": start_index,
            "next_start_index": nxt,
        }
        if rule in review:
            body["note"] = (
                "this rule is in needs_review: the engine ran it and could "
                "not decide it. Nothing here is a failure and nothing here "
                "is a pass.")
        payload = {"page": record.handle, "session": sess.session_id,
                   "url": record.page.url, "scope": scope, "totals": totals,
                   "coverage": coverage, "elapsed_ms": elapsed, **body}
        return _enveloped(payload, record, budget_tokens)

    # -------------------------------------------------- the aggregate read
    refs = await _resolve_refs(
        sess, record, [node for row in ordered for node in row["nodes"][:3]])

    def build(rung: int) -> dict:
        examples = {0: 3, 1: 1}.get(rung, 0)
        shown = ordered
        dropped: list[str] = []
        if rung >= 4:
            shown = [r for r in ordered
                     if r.get("impact") in ("critical", "serious")]
            dropped = [r["rule"] for r in ordered if r not in shown]
        out = {
            "page": record.handle, "session": sess.session_id,
            "url": record.page.url,
            "scope": scope, "totals": totals,
            "violations": [_rule_line(row, examples, refs) for row in shown],
            "coverage": coverage,
            "elapsed_ms": elapsed,
        }
        if include in ("violations+review", "all") or review:
            if rung >= 3:
                # needs_review COLLAPSES to a summary line. It is never
                # dropped: a read that stops reporting what the engine could
                # not decide is a read that started overstating itself.
                out["needs_review_summary"] = {
                    "rules": len(review),
                    "nodes": totals["needs_review_nodes"],
                    "rule_ids": sorted(review)[:20],
                    "how": ("get_accessibility(rule='<id>') returns the "
                            "nodes and the engine's own reason for each"),
                }
            else:
                out["needs_review"] = [_review_line(row)
                                       for row in review.values()]
        if include == "all":
            out["passes_note"] = (
                f"{folded['passes']} rule(s) passed and "
                f"{folded['inapplicable']} did not apply to this page. "
                f"They are counted rather than listed: a list of rules "
                f"nothing violated is the least useful thing this payload "
                f"could spend a budget on.")
        if dropped:
            out["dropped_by_rung"] = {
                "rules": dropped[:40],
                "why": ("the budget forced this read to its lowest rung, so "
                        "only critical and serious rules are detailed. The "
                        "totals above still count every rule; "
                        "budget_tokens raises the ceiling"),
            }
        return out

    chosen, rung = None, 0
    for rung in range(5):
        chosen = build(rung)
        if meter.ntok(_json.dumps(chosen, ensure_ascii=False)) \
                <= max(500, int(budget_tokens)):
            break
    used = meter.ntok(_json.dumps(chosen, ensure_ascii=False))
    chosen["budget"] = {
        "used": used, "budget": int(budget_tokens), "rung": f"{rung} of 4",
        "estimator": meter.ENCODING_NAME,
        "note": ("an estimate from the same encoder the page reads use, not "
                 "a billing meter"),
    }
    chosen["completeness"] = {
        "rules_printed": len(chosen["violations"]),
        "rules_total": len(rules),
        "example_nodes_per_rule": {0: 3, 1: 1}.get(rung, 0),
        "needs_review": ("collapsed to a summary" if rung >= 3
                         else "listed per rule"),
        "frames_not_entered": len(scope["frames_not_entered"]),
        "how_to_get_the_rest": ("get_accessibility(rule='<id>') returns "
                                "every node for one rule, paginated"),
    }
    return _enveloped(chosen, record, budget_tokens)


async def _resolve_refs(sess, record, nodes: list) -> dict:
    """Map each node's target selector to a ref where the element is in the
    anchor registry, and to nothing where it is not.

    A ref is never fabricated. An element the last read did not mint a ref
    for comes back with `ref: null`, which is the honest answer: the
    registry is what makes a ref actionable, and a selector dressed up as a
    ref would resolve to nothing at the moment somebody used it."""
    targets = [node["target"] for node in nodes
               if node.get("target") and not node.get("frame")]
    if not targets:
        return {}
    try:
        found = await record.page.evaluate(_REF_JS, targets[:100])
    except Exception:
        return {}
    live = _anchor_lookup(sess, record)
    return {sel: live.get(node_ref) for sel, node_ref in (found or {}).items()
            if node_ref and live.get(node_ref)}


def _anchor_lookup(sess, record) -> dict:
    """node_ref -> ref, from the session's own map."""
    try:
        table = sess.element_map.node_refs.get(record.handle) or {}
    except Exception:
        return {}
    return {node_ref: ref for ref, node_ref in table.items()}


def _enveloped(payload: dict, record, budget_tokens: int) -> dict:
    """Every page-derived string in one labeled envelope.

    Two provenances are mixed in an audit result and they are not the same
    thing. Rule ids, impacts, help text and WCAG mappings come from the
    engine's own static catalogue and are the server's voice. Target
    selectors, HTML snippets and per-node reasons are derived from the
    page's markup and class names, and a failure summary in particular
    LOOKS like engine prose while carrying page bytes inside it."""
    strings: list[str] = []
    for row in payload.get("violations", []):
        for node in row.get("examples", []) or []:
            strings.append(f'{node.get("target")} :: {node.get("html")}')
    for node in payload.get("nodes", []) or []:
        strings.append(f'{node.get("target")} :: {node.get("html")} :: '
                       f'{node.get("why")}')
    for row in payload.get("needs_review", []) or []:
        strings.append(f'{row.get("rule")}: {row.get("why")}')
    if not strings:
        return payload
    wrapped, note = _pagedata.wrap("\n".join(strings), url=record.page.url)
    payload["page_derived"] = wrapped
    note["label"] = (
        "The block below repeats the page-derived parts of this audit: "
        "element markup, CSS selectors built from the page's own class "
        "names and ids, and per-node reasons the engine interpolated page "
        "content into. " + note["label"])
    payload["page_data"] = note
    return payload


#: The pack roster.
TOOLS = (get_accessibility,)
