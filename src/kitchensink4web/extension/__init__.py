"""Lane C plumbing: the browser extension bridge.

Phase 1 of the extension build (spec section 11). Four pieces, each with one
job:

* ``framing`` -- the native messaging wire format, 4-byte length + UTF-8 JSON.
* ``protocol`` -- what a well-formed command and response look like, and how
  a chunked response is put back together.
* ``relay`` -- the process Firefox launches. It owns stdin/stdout and nothing
  else, and forwards to the already-running server over loopback.
* ``bridge`` -- the server side of that loopback hop, and the only object the
  rest of KS4Web ever talks to.

The relay imports NOTHING outside the standard library, deliberately. Firefox
launches it in an environment we do not control and cannot inspect, so a
missing third-party import there would surface as a native messaging
disconnect with no diagnosis attached.
"""

from __future__ import annotations

__all__ = ["framing", "protocol", "relay", "bridge", "register"]
