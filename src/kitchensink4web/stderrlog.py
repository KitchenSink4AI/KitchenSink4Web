"""Log lines never make the server wait on stderr.

THE FAILURE. The stdio binding lets a client "capture, forward, or ignore"
a server's stderr. A client that pipes it and never reads it leaves a pipe
that holds 4096 bytes on Windows (measured), and startup already writes
about 2.6 KB of it (the banner). Any log write after the pipe is full blocks
the thread that made it, and in a stdio server that is the one event loop:
nothing is answered again, `initialize` included. The trigger first
reported was a dual-era client's `server/discover` probe sent before
`initialize`. The mcp SDK answers it correctly (JSON-RPC -32602, which the
2026-07-28 stdio binding treats as "legacy server, fall back"), and then
logs the whole pydantic error, about 8 KB for one probe, on the root logger.
Measured on Web 1.0.3 on 2026-10-05: with stderr drained the exchange
worked; with stderr unread the server went silent after the first probe,
before or after `initialize`.

Shortening the line only moves the wall. KitchenSink4XL first clipped
every record to one short line and the server still went silent after
about 36 bad requests, once the short lines had filled the pipe. So:

1. Every record on the root logger (where the SDK logs) and on fastmcp's own
   logger (which does not propagate) goes to ONE handler that only puts a
   line on a bounded queue. A daemon thread writes the queue to stderr. The
   server's loop never touches stderr: when the queue is full the line is
   dropped and counted, and the writer says how many were dropped the next
   time stderr takes a write.
2. Each record is one line with no traceback, clipped to MAX_LINE bytes,
   and the SDK's validation dump collapses to its first line plus the
   method the client sent, so a reading client's log stays useful.
3. Python warnings are routed through logging, so they take the same path.

What this does not cover: the startup lines written before the server
serves (the "KS4Web: N tools" line and FastMCP's banner, about 2.6 KB),
which fit in an empty pipe, and anything a child process writes to the
inherited stderr itself.
"""

from __future__ import annotations

import logging
import queue
import re
import sys
import threading
import time

#: The two warnings the mcp SDK emits for an unparseable message, verbatim
#: (`mcp/shared/session.py`, `_receive_loop`).
PREFIXES = ("Failed to validate request: ",
            "Failed to validate notification: ")

#: The most one log record may put on stderr, newline included.
MAX_LINE = 240

#: How many lines may wait for stderr before new ones are dropped.
QUEUE_LINES = 256

_METHOD = re.compile(r"input_value='([^']{1,80})'")


def _clip(text: str, limit: int) -> str:
    """At most `limit` UTF-8 bytes, cut on a character boundary."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit - 3].decode("utf-8", "ignore") + "..."


class SdkValidationDump(logging.Filter):
    """Collapse the SDK's validation warning to one line naming the method;
    every other record passes untouched."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:                                # noqa: BLE001
            return True
        for prefix in PREFIXES:
            if text.startswith(prefix):
                break
        else:
            return True
        body = text[len(prefix):]
        line = prefix + body.split("\n", 1)[0].strip()
        found = _METHOD.search(body)
        if found:
            line += f" (method {found.group(1)!r})"
        record.msg = line
        record.args = ()
        return True


class OneLine(logging.Formatter):
    """`LEVEL:logger:message`, newlines folded, no traceback, clipped."""

    def __init__(self) -> None:
        super().__init__("%(levelname)s:%(name)s:%(message)s")

    def format(self, record: logging.LogRecord) -> str:
        # `formatMessage` rather than `format`: the base class appends
        # `exc_text` and `stack_info`, which are tracebacks.
        try:
            record.message = record.getMessage()
            text = self.formatMessage(record)
        except Exception:                                # noqa: BLE001
            text = f"{record.levelname}:{record.name}:(unformattable record)"
        text = " | ".join(part.strip() for part in text.splitlines()
                          if part.strip())
        return _clip(text, MAX_LINE - 1)


class NonBlockingStderr:
    """A logging handler whose `emit` only ever enqueues.

    The writer thread is a daemon, so a writer stuck on a stderr nobody
    reads holds nothing but itself and cannot hold up the exit."""

    def __init__(self, stream=None, maxsize: int = QUEUE_LINES) -> None:
        self.queue: queue.Queue[str] = queue.Queue(maxsize)
        self.stream = stream
        self.dropped = 0
        self._reported = 0
        owner = self

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    line = self.format(record) + "\n"
                except Exception:                        # noqa: BLE001
                    owner.dropped += 1
                    return
                try:
                    owner.queue.put_nowait(line)
                except queue.Full:
                    owner.dropped += 1

            def handleError(self, record) -> None:      # noqa: N802
                # The default prints a traceback to stderr: the very write
                # this handler exists to keep off the server's thread.
                owner.dropped += 1

        self.handler = _Handler()
        self.handler.setFormatter(OneLine())
        self.handler.addFilter(SdkValidationDump())
        self.thread = threading.Thread(target=self._drain, daemon=True,
                                       name="ks4web-stderr-writer")
        self.thread.start()

    def _write(self, text: str) -> None:
        stream = self.stream if self.stream is not None else sys.stderr
        stream.write(text)
        stream.flush()

    def _drain(self) -> None:
        while True:
            line = self.queue.get()
            try:
                lost = self.dropped - self._reported
                if lost > 0:
                    self._reported += lost
                    self._write(f"WARNING:kitchensink4web:{lost} log lines "
                                f"dropped while stderr was not being read\n")
                self._write(line)
            except Exception:                            # noqa: BLE001
                pass            # a closed stderr is not the server's fault
            finally:
                self.queue.task_done()

    def flush(self, bound: float = 1.0) -> None:
        """Wait up to `bound` seconds for queued lines to reach stderr."""
        end = time.monotonic() + bound
        while self.queue.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.02)


#: The installed writer, and the handlers it replaced, for `uninstall`.
_WRITER: NonBlockingStderr | None = None
_REPLACED: list[tuple[logging.Logger, logging.Handler]] = []
_LOGGERS = ("", "fastmcp")


def install(stream=None) -> NonBlockingStderr:
    """Route the root and fastmcp loggers, and Python warnings, through one
    non-blocking writer. Idempotent; returns the writer."""
    global _WRITER
    if _WRITER is None:
        _WRITER = NonBlockingStderr(stream)
    writer = _WRITER
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler is not writer.handler:
                logger.removeHandler(handler)
                _REPLACED.append((logger, handler))
        if writer.handler not in logger.handlers:
            logger.addHandler(writer.handler)
    logging.captureWarnings(True)
    return writer


def installed() -> NonBlockingStderr | None:
    return _WRITER


def uninstall() -> None:
    """Undo `install` (tests). The writer thread is left to idle."""
    global _WRITER
    if _WRITER is None:
        return
    for name in _LOGGERS:
        logging.getLogger(name).removeHandler(_WRITER.handler)
    for logger, handler in _REPLACED:
        if handler not in logger.handlers:
            logger.addHandler(handler)
    _REPLACED.clear()
    logging.captureWarnings(False)
    _WRITER = None
