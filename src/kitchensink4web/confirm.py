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
gate's own question to the client, and on an explicit ACCEPT redeems the
gate through the same single-use `redeem()` path nothing else may call. On
decline, cancel, timeout, a client with no elicitation, or any transport
error, it returns None and the refusal the gate already produced stands,
which is the fail-closed behavior S8 measured end to end (a headless client
auto-cancels in 0.0 s and nothing executes).

The MRTR-shaped payload stays in the refusal detail as cheap
forward-compatibility a future client may act on; nothing here depends on it.

CALLERS: the server's tool wrapper (one retry of an ordinary tool), and
`run_workflow`'s per-step replay loop, which must confirm per STEP because
retrying a whole workflow would re-execute its completed steps. Never
reachable from a tool argument.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .errors import ConfirmationRequired
from .policy import consent, gates

#: Shorter than the gate TTL (180 s) so a redemption can never be minted
#: against a gate that expired while the human was reading the prompt.
ELICIT_TIMEOUT_S = 150.0


@dataclass
class _Remembered:
    """The schema for a grantable prompt: one boolean beside the accept.

    A "remember this for 30 minutes" answer is what stops one task raising
    the same question five times, and its SCOPE is (origin, action class,
    ttl) rather than a string, a target, or a URL with a query. That is the
    difference between a consent unit and the useless blanket "always
    allow" the author correctly rejected: input strings vary, classes do
    not.

    Offered only on Tier 1 prompts. The money, credential, broadcast,
    deletion, legal, off-list, and budget prompts keep the bare
    accept/decline they ship with, so nothing about those renders
    differently on any client."""

    remember_30_minutes: bool = False


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
    """Put a raised gate's question to the client; a redeemed Gate on an
    explicit human ACCEPT, None on everything else. None means the caller
    returns the original refusal: fail closed is the default, not a branch.

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
        from fastmcp.server.context import AcceptedElicitation
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

    pending = gates.ENGINE.peek_pending(token)
    action_class = pending.action_class if pending is not None else None
    offer_remember = consent.grantable(action_class)
    schema = _Remembered if offer_remember else None
    started = time.monotonic()
    try:
        answer = await asyncio.wait_for(
            ctx.elicit(f"{message} (accept to allow; decline or cancel to "
                       f"refuse; nothing runs until you answer)",
                       response_type=schema),
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
    if not isinstance(answer, AcceptedElicitation):
        consent.note_confirmation("cancelled", elapsed)
        return None
    consent.note_confirmation("accepted", elapsed)
    try:
        grant = gates.ENGINE.redeem(token, {"allow": True})
    except Exception:
        # Expired or already-redeemed gate: the refusal stands.
        return None
    if offer_remember and _wants_remember(answer):
        recorded = consent.add_grant(action_class, _origin_of(pending))
        if recorded:
            from .policy import audit
            audit.LOG.record("consent_grant", "created", args=recorded)
    return grant


def _wants_remember(answer) -> bool:
    data = getattr(answer, "data", None)
    return bool(getattr(data, "remember_30_minutes", False))


def _origin_of(pending) -> str | None:
    """The origin a grant is scoped to, taken from the gate's own record and
    never from anything a caller supplied."""
    if pending is None:
        return None
    return getattr(pending, "origin", None)
