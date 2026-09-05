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

from .errors import ConfirmationRequired
from .policy import gates

#: Shorter than the gate TTL (180 s) so a redemption can never be minted
#: against a gate that expired while the human was reading the prompt.
ELICIT_TIMEOUT_S = 150.0


async def attempt(exc: ConfirmationRequired) -> gates.Gate | None:
    """Put a raised gate's question to the client; a redeemed Gate on an
    explicit human ACCEPT, None on everything else. None means the caller
    returns the original refusal: fail closed is the default, not a branch."""
    detail = getattr(exc, "detail", None) or {}
    token = detail.get("requestState")
    if not token:
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
    try:
        answer = await asyncio.wait_for(
            ctx.elicit(f"{message} (accept to allow; decline or cancel to "
                       f"refuse; nothing runs until you answer)",
                       response_type=None),
            timeout=ELICIT_TIMEOUT_S)
    except Exception:
        # No elicitation capability, a transport error, or a timeout. All of
        # them mean no human answer arrived, and no answer means no action.
        return None
    if not isinstance(answer, AcceptedElicitation):
        return None
    try:
        return gates.ENGINE.redeem(token, {"allow": True})
    except Exception:
        # Expired or already-redeemed gate: the refusal stands.
        return None
