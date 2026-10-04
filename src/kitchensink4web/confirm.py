"""The confirmation plumbing: elicitation where the client supports it.

S8 (2026-09-05, Claude Code 2.1.220) settled the mechanism question DESIGN
5.4 left to measurement. MRTR does not exist on the installed client: the
`input_required` result passes through as ordinary content, no protocol
retry occurs, and `requestState` does not survive; the only "retry" observed
was the model paraphrasing tool arguments, which is the echoed-token path
`redeem()` refuses by design. Elicitation IS advertised and round-trips
mechanically: a headless client answers `elicitation/create` instantly with
`cancel`, and an interactive client can put the question to a human.

So the plumbing here is exactly the design's stated order with the dead
branch removed: **elicitation where advertised, fail closed everywhere
else.** `attempt()` takes the `ConfirmationRequired` a gate raised, puts the
gate's own question to the client, and when a human explicitly picks ALLOW
redeems the gate through the same single-use `redeem()` path nothing else
may call. On decline, cancel, an accept without that pick, timeout, a client
with no elicitation, or any transport error, it returns None and the
refusal the gate already produced stands, which is the fail-closed behavior
S8 measured end to end (a headless client auto-cancels in 0.0 s and nothing
executes).

The MRTR-shaped payload stays in the refusal detail as cheap
forward-compatibility a future client may act on; nothing here depends on it.

AN `accept` IS NOT A YES (2026-10-05). The elicitation `action` says
only that the host returned the form; some hosts return it with nobody
choosing anything. Codex and the ChatGPT desktop app in "Full access" answer
`accept` with `content: {}` to any form with no fields
(`can_auto_accept_elicitation`, codex-rs/codex-mcp/src/elicitation.rs), and
the money, credential, deletion and legal prompts WERE that empty form. VS
Code submits a form's preset answers as `accept` when the person types a new
chat message instead of answering (`ChatQuestionCarouselPart.skip()`), and
the lower-risk prompt's only field had a preset. So every question now
carries one REQUIRED choice with NO preset answer, and only that choice set
to the exact yes value redeems a gate; `accept` with an empty form, a
missing choice, the no choice, a near-miss spelling, or a non-string is a
refusal. The schema is written out by hand rather than generated from a
type, because the generated one carried a root `title`, and the ChatGPT app
on Windows parses `requestedSchema` with unknown root keys denied and
cancelled the prompt before anyone saw it (openai/codex #46003).

CALLERS: the server's tool wrapper (one retry of an ordinary tool), and
`run_workflow`'s per-step replay loop, which must confirm per STEP because
retrying a whole workflow would re-execute its completed steps. Never
reachable from a tool argument.
"""

from __future__ import annotations

import asyncio
import time

from .errors import ConfirmationRequired
from .policy import consent, gates

#: Shorter than the gate TTL (180 s) so a redemption can never be minted
#: against a gate that expired while the human was reading the prompt.
ELICIT_TIMEOUT_S = 150.0

#: THE WIRE CONTRACT. The field every question requires, the one value that
#: means yes, and the refusal listed FIRST so a host that ever preselects the
#: first option of a choice lands on no. Plain `enum` strings rather than
#: titled `oneOf` options: the 2025-06-18 schema (what the Codex host
#: negotiates) has only `enum`, and VS Code shows an untitled option's value
#: as its label, so the value is what the person reads.
DECISION_FIELD = "decision"
ALLOW = "Allow"
REFUSE_CHOICES = ("Don't allow",)
#: Offered on Tier 1 prompts only. The money, credential, broadcast,
#: deletion, legal, off-list, and budget prompts never carry it.
REMEMBER_FIELD = "remember_30_minutes"


def question_schema(offer_remember: bool) -> dict:
    """The `requestedSchema` every confirmation sends.

    A "remember this for 30 minutes" answer is what stops one task raising
    the same question five times, and its SCOPE is (origin, action class,
    ttl) rather than a string, a target, or a URL with a query. That is the
    difference between a consent unit and the useless blanket "always
    allow" the author correctly rejected: input strings vary, classes do
    not. It keeps its preset of false, because consent rides on the
    required choice and a submitted preset can only ever say "do not
    remember".

    Root keys are exactly `type`, `properties` and `required`, and each
    field uses only keys the strictest known host parser accepts."""
    properties: dict = {
        DECISION_FIELD: {
            "type": "string",
            "title": "Decision",
            "enum": [*REFUSE_CHOICES, ALLOW],
        },
    }
    if offer_remember:
        properties[REMEMBER_FIELD] = {
            "type": "boolean",
            "title": "Remember 30 Minutes",
            "default": False,
        }
    return {"type": "object", "properties": properties,
            "required": [DECISION_FIELD]}


def read_answer(result) -> str:
    """What a host's elicitation result says, as one of: `allow`,
    `declined`, `cancelled`, or `unanswered` (an `accept` that carries no
    explicit choice). ONLY `allow` lets anything run, and it requires the
    required field to hold the exact yes value as a string."""
    action = getattr(result, "action", None)
    if action == "decline":
        return "declined"
    if action != "accept":
        return "cancelled"
    content = getattr(result, "content", None)
    choice = content.get(DECISION_FIELD) if isinstance(content, dict) else None
    if isinstance(choice, str) and choice == ALLOW:
        return "allow"
    if isinstance(choice, str) and choice in REFUSE_CHOICES:
        return "declined"
    return "unanswered"


def _wants_remember(result) -> bool:
    """Only a JSON `true`: never a string, a number, or a missing field."""
    content = getattr(result, "content", None)
    return isinstance(content, dict) and content.get(REMEMBER_FIELD) is True


async def _ask(ctx, message: str, schema: dict):
    """Send one form-mode `elicitation/create` with this exact schema and
    return the host's raw `ElicitResult`. FastMCP's `ctx.elicit` builds the
    schema from a Python type and validates the reply against it; this
    sends the hand-written schema verbatim and leaves reading the reply to
    `read_answer`, the one place that decides what counts as yes."""
    session = ctx.session
    send = getattr(session, "elicit_form", None) or session.elicit
    return await send(message=message, requestedSchema=schema,
                      related_request_id=ctx.request_id)


def _client_declared_elicitation(ctx) -> bool:
    """Did this client advertise an elicitation channel at `initialize`?

    UNKNOWN IS TREATED AS YES, deliberately and in one direction only. A
    build of the SDK that does not expose the capability check, or a
    transport that has no session behind it, must not turn every gated
    action into an instant unattended refusal on a machine where a human is
    sitting there waiting to answer. False here costs a five-minute wait
    that already existed; a wrong False would cost the human the ability to
    say yes at all."""
    try:
        import mcp.types as _t
        session = ctx.session
        check = getattr(session, "check_client_capability", None)
        if check is None:
            return True
        return bool(check(_t.ClientCapabilities(
            elicitation=_t.ElicitationCapability())))
    except Exception:                                    # noqa: BLE001
        return True


async def attempt(exc: ConfirmationRequired) -> gates.Gate | None:
    """Put a raised gate's question to the client; a redeemed Gate when a
    human explicitly picked ALLOW, None on everything else. None means the
    caller returns the original refusal: fail closed is the default, not a
    branch.

    This is also where the UNATTENDED signal is measured, because this is
    the only place in the build that watches the confirmation channel
    behave. Detection, never assumption: a client that raises on `elicit`
    advertises no channel, and S8 measured a headless client auto-cancelling
    in 0.0 s. The flag NEVER widens consent; it only lets the next refusal
    say the honest thing instead of waiting 150 seconds to say it."""
    detail = getattr(exc, "detail", None) or {}
    token = detail.get("requestState")
    if not token:
        # An unattended refusal carries no elicitation payload on purpose:
        # there is nothing to ask and nowhere to ask it.
        return None
    try:
        requests = detail.get("inputRequests") or [{}]
        message = (requests[0].get("params") or {}).get("message") \
            or "KS4Web asks: allow this gated action?"
    except (AttributeError, IndexError, TypeError):
        message = "KS4Web asks: allow this gated action?"

    try:
        from fastmcp.server.dependencies import get_context
        ctx = get_context()
    except Exception:
        return None                     # no live request context: fail closed

    # ASK THE CLIENT WHAT IT SAID IT COULD DO, BEFORE ASKING IT ANYTHING.
    #
    # The detection above is real and it is why a headless client that
    # auto-cancels is caught in 0.0 s: a client whose transport RAISES on
    # `elicit` advertises no channel. What it does not cover is a client
    # whose transport accepts the request and then nobody answers. The
    # integration's own harness declared no `elicitation` capability, its
    # transport took the request anyway, and the call blocked for the full
    # 150-second cap before failing closed. With UNATTENDED_AFTER = 2 that
    # is two full waits, five minutes, before the third refusal becomes
    # instant.
    #
    # The client's capabilities are known at `initialize` and the SDK
    # exposes them, so this is still DETECTION and never assumption: it
    # reads what the client declared about itself rather than guessing from
    # how it behaved. Nothing about the fail-closed default moves, and
    # nothing in the ladder moves: this takes the SAME `no_channel` branch
    # the transport error takes, five minutes earlier. (Verify round V-20.)
    if not _client_declared_elicitation(ctx):
        consent.note_confirmation("no_channel", 0.0)
        return None

    # A GATE THAT IS ALREADY GONE IS NEVER PUT TO A HUMAN. An expired,
    # spent, or unknown token cannot be redeemed by any answer, so asking
    # would only collect a yes that does nothing and tell the person their
    # answer mattered.
    pending = gates.ENGINE.peek_pending(token)
    if pending is None:
        return None
    action_class = pending.action_class
    offer_remember = consent.grantable(action_class)
    schema = question_schema(offer_remember)
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            _ask(ctx, f"{message} (choose {ALLOW} to let it run; any other "
                      f"answer refuses it; nothing runs until you answer)",
                 schema),
            timeout=ELICIT_TIMEOUT_S)
    except asyncio.TimeoutError:
        consent.note_confirmation("timeout", time.monotonic() - started)
        return None
    except Exception:
        # No elicitation capability, or a transport error. Either way no
        # human answer arrived, no answer means no action, and the channel
        # has told us something about whether one is reachable at all.
        consent.note_confirmation("no_channel", time.monotonic() - started)
        return None
    elapsed = time.monotonic() - started
    verdict = read_answer(result)
    if verdict != "allow":
        # `unanswered` is an accept with no explicit choice: a host filling
        # in the form itself, or presets submitted when the person typed
        # something else. Returned instantly it is the same evidence of an
        # unattended client that an instant cancel is.
        consent.note_confirmation(verdict, elapsed)
        return None
    consent.note_confirmation("accepted", elapsed)
    try:
        grant = gates.ENGINE.redeem(token, {"allow": True})
    except Exception:
        # Expired or already-redeemed gate: the refusal stands.
        return None
    if offer_remember and _wants_remember(result):
        recorded = consent.add_grant(action_class, _origin_of(pending))
        if recorded:
            from .policy import audit
            audit.LOG.record("consent_grant", "created", args=recorded)
    return grant


def _origin_of(pending) -> str | None:
    """The origin a grant is scoped to, taken from the gate's own record and
    never from anything a caller supplied."""
    if pending is None:
        return None
    return getattr(pending, "origin", None)
