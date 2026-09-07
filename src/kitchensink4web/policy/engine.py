"""The policy choke point: one gate every acting call goes through.

Built BEFORE the action tools, deliberately (PLAN Phase 3): if the action
tools existed first, some of them would be written outside the policy path,
and the incumbent's own history proves per-tool discipline fails the moment
someone adds a feature. Phase 4's tools do not implement policy; they
DESCRIBE the action and call `approve()`.

The order of checks is part of the contract, cheapest and most protective
first, and no budget is charged for an action that something above it
already refused:

    1. read-only grade limits    (defense in depth; the tools are absent
                                  under read-only, and the choke point
                                  refuses anyway if one is ever reached)
    2. credential blindness      (a write into a secret field refuses
                                  before anything else happens)
    3. origin policy             (deny first; off-list becomes a gate class)
    4. per-domain rate limiting  (a site that said 429 stays said)
    5. loop detection            (before the charge: a loop should trip as
                                  a loop, not exhaust a budget first)
    6. budget charge             (finite always)
    7. confirmation gate         (last, so the human is only asked about an
                                  action every other check already passed)

**What this module can never do:** change policy. There is no approve()
path, no gate class, and no argument that alters read-only mode, the pack
selection, the origin lists, or the budgets' limits. The read-only invariant
test enforces that mechanically across the whole tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..errors import ReadOnlyMode
from . import audit, budgets, consent, credentials, gates, origins, readonly

ENV_HIDDEN = "KS4WEB_HIDDEN_CONTENT"


def hidden_content_allowed() -> bool:
    """P1's include_hidden switch. Default ON: hidden content is reachable
    through the LABELED route (`get_text(include_hidden=True)` returns it in
    a separately labeled section, never mixed into the main text). Setting
    KS4WEB_HIDDEN_CONTENT=off at launch removes even that route."""
    value = os.environ.get(ENV_HIDDEN, "labeled").strip().lower()
    return value not in ("0", "false", "off", "no")


@dataclass
class ActionRequest:
    """What a tool is about to do, described for policy rather than done."""

    tool: str
    kind: str                       # "navigate" | "act" | "download"
    session: str
    page: str | None = None
    url: str | None = None          # the destination or the current page
    target: dict | None = None      # anchor / field descriptor
    action_class: str | None = None  # a GATED_CLASSES member, if any
    args: dict | None = None        # for the loop-detection signature
    writes_value: bool = False      # typing / filling into `target`
    gate_grant: dict | None = None  # a redeemed gate, from the MRTR plumbing
    resolution: str = "ok"          # the rebind ladder's outcome for target
    summary: str = ""               # one human line for the gate prompt
    extra_charges: tuple = field(default_factory=tuple)
    #: The filesystem path this action reads from or writes to, where it has
    #: one. The consent ladder needs it: a download INTO a configured
    #: sandbox root is in-grade and a download anywhere else is not, and the
    #: difference is a path, not a class.
    dest_path: str | None = None


_KIND_CHARGE = {"navigate": "navigations", "act": "actions",
                "download": "downloads"}


def approve(request: ActionRequest) -> dict:
    """Run the whole policy ladder for one action. Raises a typed refusal at
    the first failed check; returns the permit record for the audit trail."""
    grade = readonly.grade()

    # 1. Read-only. Mutating tools are ABSENT under read-only (DESIGN 5.2),
    #    so this branch firing means something slipped past registration;
    #    refusing here keeps the claim true even then. Navigation is the
    #    permitted-but-graded case.
    if grade is not None and request.kind in ("act", "download"):
        raise ReadOnlyMode(
            f"this server is read-only (grade {grade!r}) and {request.tool} "
            f"describes a mutating action. No tool in this mode can click, "
            f"type, submit, upload, download, evaluate script, or write "
            f"storage. Restart without --read-only to act.")

    # 2. Credential blindness.
    if request.writes_value and request.target is not None:
        credentials.refuse_secret_write(request.target, request.tool)

    # 3. Origin policy, deny first. An off-list origin is not a refusal, it
    #    is a gate class (refused outright only under strict, inside
    #    check_navigation).
    verdict = "allowed"
    domain = None
    if request.url:
        verdict = origins.check_navigation(request.url, grade)
        domain = urlparse(request.url).hostname
        if verdict == "off-list" and not request.action_class:
            request.action_class = ("navigation_offlist"
                                    if request.kind == "navigate"
                                    else "action_offlist")

    # 4. A domain that answered 429 stays answered until its window passes.
    if domain:
        budgets.BOOK.check_domain(domain)

    # 3b. THE TWO ESCALATIONS THAT HAVE NO CLASS OF THEIR OWN (consent
    #     ladder). An ordinary click on a page the PAGE declared adult-only,
    #     and an ordinary click on an origin the HUMAN listed as one to
    #     always ask about, both carry no action class today and therefore
    #     no gate. Neither is a content judgment: one relays the page's own
    #     declaration and the other reads a list the human wrote.
    age_declared = bool((request.target or {}).get("page_age_declared"))
    if request.kind in ("act", "download") and not request.action_class:
        if consent.is_sensitive_origin(request.url):
            request.action_class = "sensitive_origin"
        elif age_declared:
            request.action_class = "age_gate_detected"

    # A confirmed re-run (S8 wiring): the elicitation plumbing redeemed the
    # gate the FIRST pass asked for and deposited it, and this pass is the
    # same action moments later. The first pass already noted the call and
    # charged the budget, so repeating either would bill one action twice
    # and walk the loop detector at double speed for gated actions.
    confirmed_rerun = (request.action_class is not None
                       and request.gate_grant is None
                       and gates.peek_grant(request.action_class) is not None)

    # 5. Loop detection, before the charge.
    if not confirmed_rerun:
        budgets.BOOK.note_call(
            request.session, request.tool,
            budgets.fingerprint(gates.fingerprint(request.target or {}))
            if request.target else None,
            budgets.fingerprint(request.args) if request.args else None)

    # 6. The budget charge.
    if not confirmed_rerun:
        charge_kind = _KIND_CHARGE.get(request.kind)
        if charge_kind:
            budgets.BOOK.charge(request.session, charge_kind,
                                origin=domain if request.kind == "navigate"
                                else None)
        for extra in request.extra_charges:
            budgets.BOOK.charge(request.session, extra)

    # 7. The confirmation gate, last. With no redeemed grant this RAISES
    #    (CONFIRMATION_REQUIRED, failing closed on clients with no
    #    confirmation channel), unless the elicitation plumbing deposited a
    #    redeemed gate for this class, which ask() consumes and returns. With
    #    a grant either way, the TOCTOU re-validation and the rebind
    #    interlock run HERE, immediately before the caller acts.
    gate_record = None
    if request.action_class:
        gate_record = confirm(
            request.action_class, tool=request.tool, session=request.session,
            page=request.page, target=request.target,
            summary=request.summary or f"{request.tool} on "
                                       f"{request.url or request.page}",
            url=request.url, kind=request.kind,
            dest_path=request.dest_path, origin_verdict=verdict,
            age_declared=age_declared, resolution=request.resolution,
            gate_grant=request.gate_grant)

    return {"allowed": True, "origin_verdict": verdict,
            "read_only": grade, "gate": gate_record}


def confirm(action_class: str, *, tool: str, session: str | None,
            page: str | None, target: dict | None, summary: str,
            url: str | None = None, kind: str = "act",
            dest_path: str | None = None, origin_verdict: str = "allowed",
            age_declared: bool = False, resolution: str = "ok",
            gate_grant=None) -> dict:
    """STEP 7, AND THE ONE PLACE A GATED CLASS MEETS THE CONSENT LADDER.

    Factored out of `approve()` on 2026-09-07 because it turned out not to be
    the only caller. Eleven sites in `ops/` reach a gate WITHOUT going through
    `approve()` and every one of them is legitimate on its own terms: the
    off-list landing gate fires after a navigation the ladder already ruled
    on; `type_text` and `fill_form` re-ask when a focus handler changes what a
    field IS; `manage_session(open, auth_state=)` asks BEFORE opening so a
    fail-closed answer does not strand a half-built session; the storage doors
    gate a call that charges no action budget.

    They were all calling `gates.ENGINE.ask()` directly, which meant they
    never saw the consent scope. `storage_clear` under `full` still asked and
    `KS4WEB_PREAUTH=storage_load@github.com` cleared `load_auth_state` while
    leaving `manage_session(open, auth_state=...)` asking, which is the same
    operation spelled differently. A ladder with eleven doors around it is not
    a ladder, so there is one door now and this is it.

    THE ORDER IS THE CONTRACT:

    1. a redeemed grant handed in by the confirmation plumbing executes,
       after the TOCTOU re-validation, labelled `human`;
    2. otherwise the ladder decides, and a clearance skips the ASK while the
       rebind interlock still runs;
    3. otherwise the gate asks, and an unattended session gets an honest
       refusal now rather than a 150-second wait for an answer nobody will
       give.

    THE AUDIT NEVER RECORDS `human` FOR A GRADE- OR PREAUTH-CLEARED ACTION.
    A trail that did would be a false record, and the audit's own framing as
    an operational log for the user cannot survive one."""
    decision = consent.decide(
        action_class, url=url, desc=target, dest_path=dest_path,
        origin_verdict=origin_verdict, kind=kind, age_declared=age_declared)
    if gate_grant is not None:
        record = gates.ENGINE.verify_execute(
            gate_grant if isinstance(gate_grant, gates.Gate)
            else _grant_error(), target, resolution_outcome=resolution)
        record["cleared_by"] = "human"
    elif decision.clears:
        record = gates.verify_cleared(
            decision.action_class, target, resolution_outcome=resolution,
            summary=summary)
        record["cleared_by"] = decision.cleared_by
        record["cleared_because"] = decision.reason
    else:
        granted = gates.ENGINE.ask(
            action_class, tool=tool, session=session or "", page=page,
            target=target, summary=summary,
            live_only=decision.outcome == consent.ASK_LIVE_ONLY,
            unattended=consent.unattended(),
            origin=consent.origin_of(url))
        record = gates.ENGINE.verify_execute(
            granted, target, resolution_outcome=resolution)
        record["cleared_by"] = "human"
    audit.annotate(gate=record)
    return record


def _grant_error():
    from ..errors import ValidationFailed
    raise ValidationFailed(
        "gate_grant must be the Gate record returned by the confirmation "
        "plumbing's redeem(); it is never constructed from tool arguments, "
        "because a token the model can echo back is not a confirmation.")


def reset_budgets(session: str, gate_grant) -> dict:
    """The budget reset route. Only reachable through a redeemed gate of
    class `budget_reset`; anything else refuses."""
    if not isinstance(gate_grant, gates.Gate) \
            or gate_grant.action_class != "budget_reset":
        from ..errors import ValidationFailed
        raise ValidationFailed(
            "a budget reset executes only behind a redeemed 'budget_reset' "
            "confirmation gate, so a human answers it. Nothing was reset. "
            + budgets.RESET_ROUTE)
    grant = gates.ENGINE.verify_execute(gate_grant, gate_grant.target)
    return budgets.BOOK.reset(session, grant["gate"])
