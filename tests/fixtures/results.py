"""Read a tool result the way a real MCP client reads it.

Success responses ship ONE copy of the answer, as text in `content`
(`envelope.ship`, 2026-09-08). A test that reaches for `structured_content`
on a success is reading a field the server deliberately stopped filling, and
it would pass or fail on the transport rather than on the answer. Refusals
still carry both copies, for the reasons stated at `RefusalResult`.

`client_payload` reads whichever copy is present, which is what a client
does, so every assertion built on it is an assertion about what a caller
actually receives.
"""

from __future__ import annotations

import json
from typing import Any


def client_payload(result: Any) -> Any:
    """The object a client parses out of `result`."""
    if isinstance(result, dict):
        return result
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    blocks = getattr(result, "content", None) or []
    text = "".join(getattr(block, "text", "") or "" for block in blocks)
    return json.loads(text)


def content_text(result: Any) -> str:
    """Everything a client would see as text, concatenated."""
    blocks = getattr(result, "content", None) or []
    return "".join(getattr(block, "text", "") or "" for block in blocks)
