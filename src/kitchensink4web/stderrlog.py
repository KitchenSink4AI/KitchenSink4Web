"""Nothing in the server ever waits on the client's stderr.

THE FAILURE. The stdio binding lets a client "capture, forward, or ignore"
a server's stderr. A client that pipes it and never reads it leaves a pipe
that holds 4096 bytes on Windows (measured), and startup already writes
about 2.6 KB of it (the banner). Any write after the pipe is full blocks the
thread that made it, and in a stdio server that is the one event loop:
nothing is answered again, `initialize` included. The trigger first
reported was a dual-era client's `server/discover` probe sent before
`initialize`. The mcp SDK answers it correctly (JSON-RPC -32602, which the
2026-07-28 stdio binding treats as "legacy server, fall back"), and then
logs the whole pydantic error, about 8 KB for one probe, on the root logger.

Shortening the line only moves the wall: KitchenSink4XL first clipped every
record to one short line and its server still went silent after about 36
bad requests. Taking the write off the loop is not enough either, measured
on this server once that was done:

- A writer thread blocked in a write through `sys.stderr` holds the stderr
  buffer's lock, so interpreter shutdown, which flushes `sys.stderr`, waits
  on that lock and then fails writing "Fatal Python error" to the same full
  pipe: the process never exits.
- On Windows, while ANY write is pending on a full pipe, another process
  holding a handle to that pipe blocks the moment it queries it. A child
  that inherits stderr does that at startup without writing a byte (the
  Playwright driver does), so the first browser tool never answered.

THE DESIGN. The client's stderr is touched by exactly one thing: a daemon
writer thread, writing with `os.write` on a private duplicate of the
original descriptor, holding no lock anyone else needs. Everything else
writes somewhere that is always drained:

1. File descriptor 2, and the Windows standard error handle, are pointed at
   a pipe this module reads continuously. `print(file=sys.stderr)`, the
   startup banner, C-level writes, and every child process that inherits
   stderr write into that pipe, which never fills, so none of them can
   block and no child shares a handle with the stuck write.
2. Log records on the root logger (where the SDK logs) and on fastmcp's own
   logger (which does not propagate) go straight onto the same bounded
   queue, as one line each: no traceback, clipped to MAX_LINE bytes, and
   the SDK's validation dump collapsed to its first line plus the method.
3. Python warnings, unraisable exceptions and uncaught thread exceptions
   are routed through logging, so they take the same path.
4. The queue holds QUEUE_LINES lines. When it is full, lines are dropped
   and counted, and the writer says how many once stderr takes a write.

THE EXIT. The last thing the server says has to travel the pump and the
queue before the process ends, and daemon threads stop at interpreter
shutdown, so it is drained explicitly: `drain` flushes `sys.stderr`, writes
a drain mark behind it, waits for the pump to pass the mark, then lets the
writer empty the queue. It runs after `mcp.run()` returns, before the
deliberate refusal to start (`raise SystemExit(2)`), and from atexit, which
also covers a traceback printed for an exception escaping `main()`. It is
bounded (DRAIN_S in all) and stops as soon as the writer is stuck on a
stderr nobody reads, so exit never waits on such a client; that client
simply does not get those lines. `os._exit` skips atexit, and the server
does not call it. A process killed outright loses whatever is still queued.

THE PUMP. A fault while handling a chunk drops that chunk (counted) and the
pump carries on. If the pump stops anyway, it puts the client's stderr back
on descriptor 2 and the Windows standard error handle and says so in one
line: from then on writers reach the client directly, as before `install`,
which can block again on a client that never reads, but never on a pipe
nobody empties.

`uninstall` exists for tests only and leaves a few handles and two idle
threads behind per cycle; the server never calls it.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import re
import sys
import threading
import time
import traceback

#: The two warnings the mcp SDK emits for an unparseable message, verbatim
#: (`mcp/shared/session.py`, `_receive_loop`).
PREFIXES = ("Failed to validate request: ",
            "Failed to validate notification: ")

#: The most one log record may put on stderr, newline included.
MAX_LINE = 240

#: The most one line written by anything else (the banner, a child process)
#: may put on stderr. Wider than a log record because the banner's box
#: characters take three bytes each.
RAW_LINE = 1024

#: How many lines may wait for stderr before new ones are dropped.
QUEUE_LINES = 256

#: How long one write may take before `flush` treats the writer as stuck on
#: a stderr nobody reads and stops waiting for it.
STALL_S = 0.25

#: How long `drain` waits, in all, for the pump to pass everything
#: written to descriptor 2 before it and for the writer to deliver it.
DRAIN_S = 1.0

#: A line `drain` writes to descriptor 2 and the pump swallows: once the
#: pump has seen it, everything written before it has been queued.
DRAIN_MARK = b"\x1b[ks4web-drain]\x1b"

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
    """A logging handler whose `emit` only ever enqueues, and the one
    writer thread that empties the queue.

    The sink is either `fd` (a descriptor this object owns: the private
    duplicate of the client's stderr, written with `os.write`) or `stream`
    (any object with `write`, for tests). With neither, `sys.stderr`."""

    def __init__(self, stream=None, maxsize: int = QUEUE_LINES, *,
                 fd: int | None = None) -> None:
        self.queue: queue.Queue[str] = queue.Queue(maxsize)
        self.stream = stream
        self.fd = fd
        self.dropped = 0
        self._reported = 0
        self._drop_lock = threading.Lock()
        #: When the write in progress started; None while idle.
        self.busy_since: float | None = None
        #: Whether a pump is draining the redirected descriptor 2, and the
        #: signal it gives when a drain mark (see `drain`) comes through.
        self.pump_alive = False
        self.drained = threading.Event()
        owner = self

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    line = self.format(record) + "\n"
                except Exception:                        # noqa: BLE001
                    owner.drop()
                    return
                owner.offer(line)

            def handleError(self, record) -> None:      # noqa: N802
                # The default prints a traceback to stderr: the very write
                # this handler exists to keep off the caller's thread.
                owner.drop()

        self.handler = _Handler()
        self.handler.setFormatter(OneLine())
        self.handler.addFilter(SdkValidationDump())
        self.thread = threading.Thread(target=self._drain, daemon=True,
                                       name="ks4web-stderr-writer")
        self.thread.start()

    def drop(self) -> None:
        with self._drop_lock:
            self.dropped += 1

    def offer(self, line: str) -> None:
        """Queue one line, or drop and count it. Never blocks."""
        try:
            self.queue.put_nowait(line)
        except queue.Full:
            self.drop()

    def _write(self, text: str) -> None:
        if self.fd is not None:
            data = text.replace("\n", os.linesep).encode("utf-8", "replace")
            while data:
                data = data[os.write(self.fd, data):]
            return
        stream = self.stream if self.stream is not None else sys.stderr
        stream.write(text)
        stream.flush()

    def _drain(self) -> None:
        while True:
            line = self.queue.get()
            self.busy_since = time.monotonic()
            try:
                with self._drop_lock:
                    lost = self.dropped - self._reported
                    self._reported += lost
                if lost > 0:
                    self._write(f"WARNING:kitchensink4web:{lost} log lines "
                                f"dropped while stderr was not being read\n")
                self._write(line)
            except Exception:                            # noqa: BLE001
                pass            # a closed stderr is not the server's fault
            finally:
                self.busy_since = None
                self.queue.task_done()

    def flush(self, bound: float = 1.0, stall: float = STALL_S) -> None:
        """Wait up to `bound` seconds for queued lines to reach stderr, and
        not at all once one write has been stuck for `stall` seconds: a
        stderr nobody reads is not worth waiting for."""
        end = time.monotonic() + bound
        while self.queue.unfinished_tasks and time.monotonic() < end:
            since = self.busy_since
            if since is not None and time.monotonic() - since > stall:
                return
            time.sleep(0.02)

    def pump(self, rfd: int, on_exit=None) -> None:
        """Read everything written to the redirected descriptor 2 and queue
        it line by line. Runs on its own daemon thread and never blocks on
        anything but the read, so the pipe it reads never fills.

        A fault while handling a chunk drops that chunk (counted) and the
        pump carries on. If the pump stops anyway (the read fails, or
        something it cannot catch), `on_exit` runs, which puts the client's
        stderr back on descriptor 2: writes then go straight to the client
        again, as they did before `install`, rather than into a pipe nobody
        empties."""
        try:
            self._pump_loop(rfd)
        finally:
            self.pump_alive = False
            self.drained.set()
            if on_exit is not None:
                try:
                    on_exit(self)
                except Exception:                        # noqa: BLE001
                    pass

    def _pump_loop(self, rfd: int) -> None:
        pending = b""
        while True:
            try:
                chunk = os.read(rfd, 65536)
            except OSError:
                return
            if not chunk:
                return
            try:
                pending = self._lines(pending + chunk)
            except Exception:                            # noqa: BLE001
                pending = b""
                self.drop()

    def _lines(self, data: bytes) -> bytes:
        """Queue every complete line in `data`; return the unfinished tail,
        cut into RAW_LINE pieces once it is that long."""
        *complete, tail = data.split(b"\n")
        for line in complete:
            if line.endswith(DRAIN_MARK):
                if line[:-len(DRAIN_MARK)]:
                    self._raw(line[:-len(DRAIN_MARK)])
                self.drained.set()
                continue
            self._raw(line)
        while len(tail) >= RAW_LINE:
            self._raw(tail[:RAW_LINE])
            tail = tail[RAW_LINE:]
        return tail

    def _raw(self, data: bytes) -> None:
        text = data.decode("utf-8", "replace").rstrip("\r")
        self.offer(_clip(text, RAW_LINE - 1) + "\n")


def _log_unraisable(unraisable) -> None:
    exc = unraisable.exc_value
    try:
        where = repr(unraisable.object)
    except Exception:                                    # noqa: BLE001
        where = "an object"
    logging.getLogger("kitchensink4web").warning(
        "%s %s: %s: %s", unraisable.err_msg or "Exception ignored in",
        where, type(exc).__name__ if exc is not None else "unknown", exc)


def _log_thread_exception(args) -> None:
    if args.exc_type is SystemExit:
        return
    place = ""
    try:
        last = traceback.extract_tb(args.exc_traceback)[-1]
        place = f" (at {os.path.basename(last.filename)}:{last.lineno} " \
                f"in {last.name})"
    except Exception:                                    # noqa: BLE001
        pass
    name = args.thread.name if args.thread is not None else "a thread"
    logging.getLogger("kitchensink4web").error(
        "Exception in thread %s: %s: %s%s", name, args.exc_type.__name__,
        args.exc_value, place)


def _set_std_error_handle(fd: int) -> None:
    """Point the Windows standard error handle at `fd`, so a child started
    without an explicit stderr inherits it rather than the original."""
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetStdHandle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
    kernel32.SetStdHandle.restype = wintypes.BOOL
    kernel32.SetStdHandle(wintypes.DWORD(-12 & 0xFFFFFFFF),
                          wintypes.HANDLE(msvcrt.get_osfhandle(fd)))


def _redirect_descriptor_2() -> tuple[int, int] | None:
    """Keep a private duplicate of the client's stderr, then point
    descriptor 2 at a fresh pipe. Returns (original, read end), or None
    when there is no usable descriptor 2 (pythonw, a closed stderr)."""
    try:
        if sys.stderr is not None:
            sys.stderr.flush()
        original = os.dup(2)
    except (OSError, ValueError, AttributeError):
        return None
    try:
        read_end, write_end = os.pipe()
        os.dup2(write_end, 2)
        os.close(write_end)
        _set_std_error_handle(2)
    except Exception:                                    # noqa: BLE001
        os.close(original)
        return None
    return original, read_end


#: The installed writer, and what `install` replaced, for `uninstall`.
_WRITER: NonBlockingStderr | None = None
_REPLACED: list[tuple[logging.Logger, logging.Handler]] = []
_HOOKS: dict = {}
_ORIGINAL_FD: int | None = None
_LOGGERS = ("", "fastmcp")
_LOCK = threading.RLock()
_ATEXIT = False


def _restore_descriptor_2(writer: NonBlockingStderr) -> None:
    """The pump stopped: put the client's stderr back on descriptor 2 (and
    the Windows standard error handle) so writers reach the client directly
    instead of filling a pipe nobody empties. Only for the writer still
    installed, so a pump from an earlier install can never undo a later
    one."""
    with _LOCK:
        if _WRITER is not writer or _ORIGINAL_FD is None:
            return
        try:
            os.dup2(_ORIGINAL_FD, 2)
            _set_std_error_handle(2)
        except Exception:                                # noqa: BLE001
            return
    writer.offer("WARNING:kitchensink4web:the stderr pump stopped; stderr "
                 "is written directly again\n")


def drain(bound: float = DRAIN_S) -> None:
    """Deliver what has been written so far, as far as a client that reads
    stderr will take it, and never wait on one that does not. Runs at exit
    (atexit) and before a deliberate refusal to start, so the last thing
    the server says, a refusal or a traceback, is not lost in the pipe or
    the queue when the process ends.

    Order: flush `sys.stderr` into descriptor 2, write a drain mark behind
    it and wait for the pump to pass the mark (everything before it is then
    queued), then let the writer empty the queue, stopping at once if it is
    stuck on a stderr nobody reads."""
    writer = _WRITER
    if writer is None:
        return
    end = time.monotonic() + bound
    try:
        if sys.stderr is not None:
            sys.stderr.flush()
    except Exception:                                    # noqa: BLE001
        pass
    if writer.pump_alive:
        writer.drained.clear()
        try:
            os.write(2, DRAIN_MARK + b"\n")
            writer.drained.wait(max(0.0, end - time.monotonic()))
        except OSError:
            pass
    writer.flush(max(0.0, end - time.monotonic()))


def install(stream=None) -> NonBlockingStderr:
    """Make every stderr writer in the process non-blocking; returns the
    writer. Idempotent.

    With no `stream` (the server), descriptor 2 is redirected as described
    above and the writer owns the client's stderr. With a `stream` (tests),
    descriptor 2 is left alone and the writer writes to that object."""
    global _WRITER, _ORIGINAL_FD, _ATEXIT
    with _LOCK:
        if _WRITER is None:
            redirected = _redirect_descriptor_2() if stream is None else None
            if redirected is not None:
                _ORIGINAL_FD, read_end = redirected
                _WRITER = NonBlockingStderr(fd=_ORIGINAL_FD)
                _WRITER.pump_alive = True
                threading.Thread(target=_WRITER.pump,
                                 args=(read_end, _restore_descriptor_2),
                                 daemon=True,
                                 name="ks4web-stderr-pump").start()
                if not _ATEXIT:
                    atexit.register(drain)
                    _ATEXIT = True
            else:
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
    if not _HOOKS:
        _HOOKS["unraisable"] = sys.unraisablehook
        _HOOKS["thread"] = threading.excepthook
        sys.unraisablehook = _log_unraisable
        threading.excepthook = _log_thread_exception
    return writer


def installed() -> NonBlockingStderr | None:
    return _WRITER


def uninstall() -> None:
    """Undo `install` (tests only; the server never uninstalls). The writer
    thread is left to idle, and after a redirect so are the pump thread,
    the pipe's read end and the private duplicate: a few handles and two
    idle threads per install/uninstall cycle, which only a test that cycles
    many times would notice."""
    with _LOCK:
        _uninstall_locked()


def _uninstall_locked() -> None:
    global _WRITER, _ORIGINAL_FD
    if _WRITER is None:
        return
    for name in _LOGGERS:
        logging.getLogger(name).removeHandler(_WRITER.handler)
    for logger, handler in _REPLACED:
        if handler not in logger.handlers:
            logger.addHandler(handler)
    _REPLACED.clear()
    logging.captureWarnings(False)
    if _HOOKS:
        sys.unraisablehook = _HOOKS.pop("unraisable")
        threading.excepthook = _HOOKS.pop("thread")
    if _ORIGINAL_FD is not None:
        try:
            os.dup2(_ORIGINAL_FD, 2)
            _set_std_error_handle(2)
        except Exception:                                # noqa: BLE001
            pass
        _ORIGINAL_FD = None
    _WRITER = None
