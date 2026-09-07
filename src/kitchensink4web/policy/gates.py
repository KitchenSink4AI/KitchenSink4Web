"""Confirmation gates that re-validate their target at execution time.

DESIGN 5.4. Everyone gates; the TOCTOU research shows naive gates are
defeatable. The attack: a page times its own DOM so the benign "Continue"
the agent reasoned about is swapped for a destructive control between the
confirmation and the click.

**The TOCTOU rule, binding on every gate in the system:** the gate captures
an identity fingerprint at ASK time and RE-COMPUTES it at EXECUTE time. Any
mismatch aborts with `TARGET_CHANGED`, printing what changed. This applies
to coordinate actions too, where the fingerprint is the element currently
under the point.

**The rebind interlock (DESIGN 3.5, E6):** a target that REBOUND between a
gate's ASK and its EXECUTE aborts with `TARGET_CHANGED` even when the rebind
was legitimate on its own terms. Rebinding never launders a stale
confirmation; the human confirmed a specific element, not a role and a name.

**The mechanism is a retry pattern, not a callback.** Sampling is deprecated
(SEP-2577) and the platform's replacement for server-initiated requests is
MRTR: the server returns `input_required` carrying `requestState`, the
server's own correlation token, and the client retries with the human's
answer attached. The token is how an arriving retry is matched back to the
pending gate, its captured fingerprint, and its TOCTOU re-validation, so it
is stored with the gate record rather than treated as protocol noise.

**Fail-closed is structural here, not a branch.** A gated action executes
only after `redeem()` returns a grant, `redeem()` is called only by the
server's confirmation plumbing (never from any tool argument: a test greps
the ops tree for exactly that), and a client that advertises neither MRTR
nor elicitation simply never produces a redemption. No answer, no
execution, and the refusal the caller holds says so.

**What no gate may ever do:** alter policy state. There is no gate class
that unlocks read-only mode, loads a pack, widens an origin list, or
disables any part of this layer; the classes below are the closed set, and
a test asserts none of them names policy. That absence is the mechanical
half of the read-only invariant (the registration half is the other).
"""

from __future__ import annotations

import contextvars
import secrets as _secrets
import time
from dataclasses import dataclass, field

from ..errors import ConfirmationRequired, TargetChanged, ValidationFailed

#: The gated action classes (DESIGN 5.4), CLOSED. Adding one is a design
#: change, not a convenience. None of them touches policy state, and
#: test_gates.py asserts that property over this table.
GATED_CLASSES: dict[str, str] = {
    "form_submit": "submitting a form",
    # The parenthetical named the ONE signal detection used, and stopped being
    # true when detection went multi-signal (re-attack R3, 2026-09-06): a
    # field named `cardnumber` with no autocomplete token anywhere now gates,
    # and telling the human "autocomplete detected" about it would be a
    # sentence the server cannot back.
    # The parenthetical went the same way for the same reason, one wave
    # later (fix wave 2026-09-08, V-19). Payment is no longer a field-only
    # property: a submitter reading "Pay now" on a form with no card input
    # anywhere -- a stored-card confirm, a one-click buy, a donation
    # confirm -- now classifies here, and telling the human "a card number
    # field was detected in it" about that form is a sentence the server
    # cannot back. The false clause is REMOVED rather than replaced;
    # FLAGGED for the author, because the evidence-naming half of this
    # sentence was doing real work and the replacement is copy, not
    # machinery. The facts it has to convey ride with the build report.
    "payment_form": "acting on a payment-shaped form",
    "file_upload": "uploading a file from disk",
    "download_to_disk": "saving a download to disk",
    "storage_clear": "clearing cookies or site storage",
    # Loading a saved login is consequential in the OTHER direction, and the
    # ship-route test (2026-09-06) caught it borrowing storage_clear's
    # words: the human was asked to allow "clearing cookies or site
    # storage" for an operation that clears nothing. Someone reading
    # carefully declines a load because it looks like a wipe.
    "storage_load": "loading a saved signed-in session into this browser",
    # Answering a native dialog with OK. Dismissal is not here on purpose: it
    # is the posture the server already has with nothing armed, so asking a
    # human to allow the status quo is a prompt that teaches people to click
    # through prompts. Accepting is the branch that commits whatever the page
    # does next, and `dialogs.gate_reason_for_accept` decides per dialog,
    # gating on doubt and supplying the sentence the human reads.
    "dialog_accept": "answering a native browser dialog with OK",
    "evaluate_script": "evaluating script in the page",
    # Joined 2026-09-06 by author ruling (gauntlet 3, F6): the clipboard can
    # hold whatever the human last copied, from any application — a
    # password-manager copy, a 2FA code, a private address — and the tool
    # grants itself the browser permission, so this gate is the only human
    # in the loop outside read-only mode. Write stays ungated: it
    # overwrites, it does not exfiltrate.
    "clipboard_read": "reading whatever was last copied to the clipboard",
    "navigation_offlist": "navigating to an origin outside the allowlist",
    "action_offlist": "acting inside an origin outside the allowlist",
    "budget_reset": "resetting the session's action budgets",
    # ------------------------------------------------------------------
    # THE CONSENT LADDER'S SEVEN (2026-09-07). `form_submit` covered a
    # library catalog query and a "Delete account" button with one class,
    # one prompt, and one sentence, so the gate could not name its own harm
    # and fired on research the granted mode already implied consent for.
    # The four submission classes below are what it splits into; the last
    # three are the classes the old table had no member for at all.
    #
    # EACH ONE NEEDS ITS OWN SENTENCE, and the `storage_load` incident four
    # entries up is the standing reminder why: a borrowed sentence asked a
    # human to allow "clearing cookies or site storage" for an operation
    # that clears nothing, and someone reading carefully declines the wrong
    # thing. The sentences below are COPY PLACEHOLDERS pending the author's
    # own words (build report FACTS TO CONVEY 1-7); each states the FACT
    # the final wording must convey and nothing beyond it.
    # ------------------------------------------------------------------
    # Credential blindness refuses the tool WRITING a password. Nothing
    # refused it PRESSING the button that sends one a human typed, so an
    # authentication attempt could happen that the human never authorized.
    "credential_submit": "submitting a form that carries a password or a "
                         "one-time code",
    # The human's name attached to words they did not write, irreversibly,
    # in public or in somebody's inbox.
    "broadcast_submit": "sending a submission that reaches other people",
    "destructive_submit": "submitting something that deletes, cancels, "
                          "revokes, or deactivates",
    "legal_assent": "agreeing to terms, a contract, a waiver, or a consent",
    # The PAGE declared this, and the server relays the claim rather than
    # judging the content. There is no topic classifier in this build.
    "age_gate_detected": "acting on a page that declares itself adult-only",
    "sensitive_origin": "acting on an origin you listed as one to always "
                        "ask about",
    # Feature #12. It authorizes ONE data flow to ONE origin, names no
    # policy, unlocks no mode, widens no origin list, and loads no pack, so
    # it satisfies the closed-set invariant the table is held to.
    "credential_injection": "attaching a stored credential to requests sent "
                            "to one origin",
}

#: A pending gate lives this long. A confirmation arriving later than this
#: refers to a page state nobody can vouch for, so it expires rather than
#: executing stale intent.
GATE_TTL_S = 180.0

#: The fingerprint fields TOCTOU compares. `label` is the visible text the
#: human actually read, which is the whole point of the check; `href` covers
#: links and `action` covers forms.
FINGERPRINT_FIELDS = ("role", "name", "label", "page_key", "landmark",
                     "landmark_label", "href", "action", "secret", "payment")


def fingerprint(source: dict) -> dict:
    """Normalize a target descriptor (an anchor, a form line, a resolved
    unit) into the comparable fingerprint."""
    return {k: source.get(k) for k in FINGERPRINT_FIELDS
            if source.get(k) not in (None, "")}


@dataclass
class Gate:
    token: str
    action_class: str
    tool: str
    session: str
    page: str | None
    target: dict
    summary: str
    #: The page origin this gate was raised on, carried so an in-session
    #: "remember this" answer can be scoped to (origin, class) without any
    #: caller supplying either. Never a URL with a query: a grant scoped to
    #: a query string would be the string-matching blanket approval the
    #: consent ladder exists to replace.
    origin: str | None = None
    created: float = field(default_factory=time.monotonic)
    redeemed: bool = False


#: The confirmation plumbing's hand-off slot (S8 wiring). When the server's
#: elicitation plumbing obtains a human ACCEPT, it redeems the gate and
#: deposits the resulting Gate here, then re-runs the refused call once in
#: the same context. `ask()` consumes a matching deposit instead of raising,
#: which is what lets the second pass proceed WITHOUT any tool argument ever
#: carrying a token: the slot is context-local, single-use, and reachable
#: only from server-side code. A model echoing a requestState still reaches
#: `redeem()` never, exactly as before.
_deposited: contextvars.ContextVar[Gate | None] = contextvars.ContextVar(
    "ks4web_gate_grant", default=None)


def deposit_grant(gate: Gate) -> None:
    """Place a redeemed gate for the confirmation re-run. CALLERS: the
    server's elicitation plumbing only, never anything reachable from a tool
    argument."""
    _deposited.set(gate)


def clear_grant() -> None:
    _deposited.set(None)


def peek_grant(action_class: str | None) -> Gate | None:
    """The deposited grant, if one exists for this action class, without
    consuming it. The choke point uses this to skip re-charging a budget the
    ask pass already charged for the same action."""
    gate = _deposited.get()
    if gate is not None and action_class and gate.action_class == action_class:
        return gate
    return None


class GateEngine:
    """Pending gates, keyed by their requestState correlation token."""

    def __init__(self) -> None:
        self._pending: dict[str, Gate] = {}

    # ----------------------------------------------------------------- ask

    def ask(self, action_class: str, *, tool: str, session: str,
            page: str | None, target: dict | None, summary: str,
            live_only: bool = False, unattended: bool = False,
            origin: str | None = None) -> Gate:
        """Record the gate and refuse with the confirmation payload.

        Raises on the first pass. On a confirmation re-run (the elicitation
        plumbing redeemed the gate and deposited it), a deposit matching this
        action class is CONSUMED and returned instead, and the caller runs
        the TOCTOU re-validation (`verify_execute`) before acting. The
        captured fingerprint is what EXECUTE will be held to.

        `live_only` marks a Tier 2 class, where the refusal must say that no
        configuration makes this proceed without a human. `unattended` says
        this process has EVIDENCE that no human is answering (a client with
        no confirmation channel, or repeated instant cancels), in which case
        the refusal is raised immediately rather than after a round trip
        nobody will answer.

        **The refusal is a refusal and never a queue** (author ruling,
        2026-09-07). A pending decision approved forty minutes later cannot
        execute the original target, because `GATE_TTL_S` is 180 seconds and
        the TOCTOU fingerprint expires with it. Extending the TTL to make
        deferred execution work would open precisely the hole this whole
        system exists to close, so the honest answer is to refuse now."""
        granted = peek_grant(action_class)
        if granted is not None:
            clear_grant()          # single-use, like the redemption it holds
            return granted
        if action_class not in GATED_CLASSES:
            raise ValidationFailed(
                f"unknown gated action class {action_class!r}; the closed "
                f"set is {sorted(GATED_CLASSES)}. A class is added in the "
                f"design, not at a call site.")
        if unattended:
            raise self._unattended_refusal(action_class, summary, live_only)
        self._sweep()
        token = _secrets.token_urlsafe(18)
        gate = Gate(token=token, action_class=action_class, tool=tool,
                    session=session, page=page,
                    target=fingerprint(target or {}), summary=summary,
                    origin=origin)
        self._pending[token] = gate
        exc = ConfirmationRequired(
            f"{GATED_CLASSES[action_class]} needs a human confirmation "
            f"before it runs. {summary} Nothing has been done. If your "
            f"client supports interactive requests the confirmation prompt "
            f"is attached; where it supports neither MRTR nor elicitation "
            f"this action FAILS CLOSED and cannot be performed from this "
            f"client. As of 2026-09 that is the claude.ai web client, "
            f"which receives the prompt and does not display it; Claude "
            f"Desktop and Claude Code both display it and this action "
            f"completes there. The target is re-validated at execution "
            f"time, so a "
            f"page that swaps the element after this confirmation gets "
            f"TARGET_CHANGED, not the click.")
        exc.detail = {
            "resultType": "input_required",
            "requestState": token,
            "expires_in_s": int(GATE_TTL_S),
            "inputRequests": [{
                "method": "elicitation/create",
                "params": {
                    "message": (f"KS4Web asks: allow "
                                f"{GATED_CLASSES[action_class]}? {summary}"),
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"allow": {"type": "boolean"}},
                        "required": ["allow"],
                    },
                },
            }],
        }
        raise exc

    #: COPY PLACEHOLDER (build report FACTS TO CONVEY 8-9): the
    #: unattended-session refusal. The facts it must carry: nothing was
    #: done; no human answered and this process has evidence that none can;
    #: the work is NOT queued, because a decision made later cannot execute
    #: the target this one named; and either the pre-authorization route
    #: (Tier 1) or the statement that no setting makes this proceed
    #: unattended (Tier 2).
    def _unattended_refusal(self, action_class: str, summary: str,
                            live_only: bool) -> ConfirmationRequired:
        route = (
            "No setting makes this proceed without a human. Paying, "
            "submitting a credential, sending something that reaches other "
            "people, deleting, accepting terms, acting off an allowlist, "
            "and resetting the budgets are irreducible by design."
            if live_only else
            "A human can pre-authorize this class for a named origin at the "
            "settings surface with KS4WEB_PREAUTH, which is a launch-time "
            "choice no tool call can make.")
        return ConfirmationRequired(
            f"{GATED_CLASSES[action_class]} needs a human confirmation and "
            f"no human is answering in this session. {summary} Nothing has "
            f"been done and nothing was queued: a confirmation gate expires "
            f"in {int(GATE_TTL_S)}s together with the fingerprint of the "
            f"element it named, so a decision made later could not execute "
            f"this action anyway, and a queue that pretended otherwise "
            f"would be the stale-intent hole this system exists to close. "
            f"{route}")

    # -------------------------------------------------------------- redeem

    def redeem(self, request_state: str, answer: dict) -> Gate:
        """Match a confirmation answer back to its pending gate.

        CALLERS: the server's MRTR/elicitation plumbing ONLY. This function
        must never be reachable from a tool argument, because a token the
        model can echo back itself is not a confirmation. Single-use: a
        redeemed gate is gone whether or not the execution then succeeds."""
        gate = self._pending.pop(request_state, None)
        if gate is None:
            raise ValidationFailed(
                "no pending confirmation matches this requestState; it may "
                "have expired, been redeemed already, or never existed. "
                "Gates are single-use: re-request the action to get a fresh "
                "one.")
        if time.monotonic() - gate.created > GATE_TTL_S:
            raise ValidationFailed(
                f"the confirmation for {gate.tool} expired after "
                f"{int(GATE_TTL_S)}s and was not executed. The page may have "
                f"changed since the human read the prompt; re-request the "
                f"action.")
        if not (isinstance(answer, dict) and answer.get("allow") is True):
            raise ValidationFailed(
                f"the human declined {GATED_CLASSES[gate.action_class]} "
                f"({gate.tool}); nothing was done and the gate is closed.")
        gate.redeemed = True
        return gate

    # ------------------------------------------------------------- execute

    def verify_execute(self, gate: Gate, current_target: dict | None,
                       resolution_outcome: str = "ok") -> dict:
        """The TOCTOU re-validation, run immediately before the action.

        `current_target` is the target's fingerprint AS RESOLVED RIGHT NOW,
        from a fresh read, and `resolution_outcome` is the rebind ladder's
        verdict for it. Returns the grant record for the audit trail."""
        if not gate.redeemed:
            raise ValidationFailed(
                f"gate {gate.token[:8]}… was never redeemed; a gated action "
                f"executes only after a human answered. Nothing was done.")
        if resolution_outcome == "rebound":
            raise TargetChanged(
                f"the confirmed target was REBOUND between the confirmation "
                f"and the execution ({gate.summary}). A rebind may be "
                f"legitimate on its own terms and it still never launders a "
                f"stale confirmation: the human confirmed a specific "
                f"element. Nothing was done; re-read, re-confirm, retry.")
        now = fingerprint(current_target or {})
        differing = [
            f for f in FINGERPRINT_FIELDS
            if gate.target.get(f) != now.get(f)
            and (f in gate.target or f in now)
        ]
        if differing:
            was = {f: gate.target.get(f) for f in differing}
            is_now = {f: now.get(f) for f in differing}
            raise TargetChanged(
                f"the target changed between the confirmation and the "
                f"execution; nothing was done. Fields that differ: "
                f"{differing}. Confirmed: {was}. Found at execution: "
                f"{is_now}. Re-read the page, re-confirm, and retry.")
        return {"gate": gate.token, "action_class": gate.action_class,
                "confirmed_target": gate.target}

    # ------------------------------------------------------------ plumbing

    def peek_pending(self, request_state: str) -> Gate | None:
        """The pending gate for a correlation token, WITHOUT redeeming it.

        The confirmation plumbing needs two facts before it can word the
        prompt: which class is being asked about (Tier 2 gets no "remember
        this" answer) and which origin a grant would be scoped to. Reading
        them here keeps both off the tool boundary; `redeem` is still the
        only door that consumes anything."""
        return self._pending.get(request_state)

    def pending(self) -> list[dict]:
        self._sweep()
        return [{"requestState": g.token, "action_class": g.action_class,
                 "tool": g.tool, "session": g.session,
                 "age_s": round(time.monotonic() - g.created, 1)}
                for g in self._pending.values()]

    def _sweep(self) -> None:
        now = time.monotonic()
        for token in [t for t, g in self._pending.items()
                      if now - g.created > GATE_TTL_S]:
            self._pending.pop(token, None)


def verify_cleared(action_class: str, current_target: dict | None, *,
                   resolution_outcome: str = "ok",
                   summary: str = "") -> dict:
    """The verification a CONSENT-CLEARED action still runs, and an honest
    account of which half of it survives.

    A clearance skips the ASK. The ask is also what produced the SECOND
    read: a gated action refuses, the server re-runs the tool body, the
    target is resolved again, and `verify_execute` compares the fingerprint
    captured at ask time against the fresh one. A cleared action has one
    pass, so there is no earlier fingerprint to compare against and this
    function does not pretend to make one.

    What DOES survive, and it is the half that catches the live attack: the
    REBIND INTERLOCK. `resolution_outcome` is the rebind ladder's verdict for
    this target on this pass, and a target that rebound aborts here exactly
    as it aborts behind a redeemed gate. A rebind may be legitimate on its
    own terms and it still never launders a consent scope: the human granted
    a class, not a moved element.

    The fingerprint is captured into the returned record so the audit says
    WHAT was cleared, which is what makes a cleared action reviewable after
    the fact."""
    if resolution_outcome == "rebound":
        raise TargetChanged(
            f"the target REBOUND while this action was being authorized "
            f"({summary or action_class}). A rebind may be legitimate on its "
            f"own terms and it still never launders a standing consent: the "
            f"scope covers a class of action, not an element that moved "
            f"underneath one. Nothing was done; re-read the page and retry.")
    return {"gate": None, "action_class": action_class,
            "confirmed_target": fingerprint(current_target or {})}


#: The process engine. The choke point asks it; the confirmation plumbing
#: redeems it; nothing else holds a reference.
ENGINE = GateEngine()
