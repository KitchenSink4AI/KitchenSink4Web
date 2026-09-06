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
    "payment_form": "acting on a payment-shaped form (a card number, expiry, "
                    "or security-code field was detected in it)",
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
    "navigation_offlist": "navigating to an origin outside the allowlist",
    "action_offlist": "acting inside an origin outside the allowlist",
    "budget_reset": "resetting the session's action budgets",
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
            page: str | None, target: dict | None, summary: str) -> Gate:
        """Record the gate and refuse with the confirmation payload.

        Raises on the first pass. On a confirmation re-run (the elicitation
        plumbing redeemed the gate and deposited it), a deposit matching this
        action class is CONSUMED and returned instead, and the caller runs
        the TOCTOU re-validation (`verify_execute`) before acting. The
        captured fingerprint is what EXECUTE will be held to."""
        granted = peek_grant(action_class)
        if granted is not None:
            clear_grant()          # single-use, like the redemption it holds
            return granted
        if action_class not in GATED_CLASSES:
            raise ValidationFailed(
                f"unknown gated action class {action_class!r}; the closed "
                f"set is {sorted(GATED_CLASSES)}. A class is added in the "
                f"design, not at a call site.")
        self._sweep()
        token = _secrets.token_urlsafe(18)
        gate = Gate(token=token, action_class=action_class, tool=tool,
                    session=session, page=page,
                    target=fingerprint(target or {}), summary=summary)
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


#: The process engine. The choke point asks it; the confirmation plumbing
#: redeems it; nothing else holds a reference.
ENGINE = GateEngine()
