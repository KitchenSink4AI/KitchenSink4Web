"""Native dialogs and file choosers: the desk that records them, the posture
that answers them, and the heuristics that decide which answers a human owns.

A native dialog (`alert`, `confirm`, `prompt`, `beforeunload`) stops the
page's script dead until something answers it. Every read and every action
against that page hangs meanwhile, which is why the pending-dialog check runs
at the session manager's `locate()` rather than inside each tool: one place
observes the condition, so no tool can forget to.

**The default posture, stated rather than discovered.** Playwright dismisses
native dialogs itself when no listener is attached, and attaching a listener
takes that behavior away: a recorded-but-unanswered dialog leaves the page
frozen. So the desk attaches a listener at session open, records what the
dialog was, and then reproduces the old behavior exactly by dismissing it
immediately. That is the shipped default and it is what a `confirm()` sees
as Cancel. Nothing about the default changed when this module landed; what
changed is that the dismissal is now recorded, reported, and overridable.

Three dispositions can be armed for the next dialog on a page:

    dismiss   the default; answer Cancel as soon as it opens
    accept    answer OK, with `prompt_text` where the dialog takes input
    hold      leave it OPEN so it can be read and then answered

`hold` is the one that makes a pending dialog exist at all, and it is
deliberately bounded: a held dialog older than `HOLD_TTL_S` is dismissed by
the next call that looks at the desk, because a page frozen forever because
nobody came back is a worse outcome than an answered Cancel.

**beforeunload is its own case.** It is not asking about the page's content,
it is asking whether to leave with work unsaved, and accepting it discards
whatever the page has not written down. So an arm for `any` dialog type never
answers a beforeunload: it has to be named. Its default is dismissal, which
keeps the page where it is.

**A dialog message is page-authored text.** Whatever a site puts in a
`confirm()` string arrives here verbatim, so every surface that quotes one
(payloads, refusals, and the sentence a human reads in a confirmation prompt)
carries it inside the `pagedata` labeled envelope rather than as bare prose
the server appears to be saying.

**Accepting is where the human is.** `gate_reason_for_accept` decides whether
answering OK needs a confirmation, and it is written to gate on doubt: an
alert has only one outcome so accepting it changes nothing, but a `confirm`
whose message this server does not recognize as inert gets a gate with the
reason stated plainly. The recognized-destructive patterns supply a better
reason, never a shortcut past the gate.

File choosers ride here too, for a related reason: the desk attaches a
`filechooser` listener at session open, which is what keeps a click on a file
input from reaching the operating system's own picker. With no upload armed
the chooser is recorded and left unfilled, which the page sees as a cancelled
selection. `upload_file(via='chooser')` is the route that fills one, and it
runs the same sandbox read-check and the same `file_upload` confirmation as
the direct-input route, because the choke point is the same choke point.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from dataclasses import dataclass, field

from . import pagedata

#: The four native dialog types, exactly as the driver names them.
DIALOG_TYPES: tuple[str, ...] = ("alert", "confirm", "prompt", "beforeunload")

#: Dialog types a `dialog_type='any'` arm covers. `beforeunload` is missing on
#: purpose: it asks about leaving with unsaved work rather than about anything
#: on the page, so it is answered only by an arm that names it.
GENERIC_TYPES: tuple[str, ...] = ("alert", "confirm", "prompt")

#: What can be armed for the next dialog on a page.
DISPOSITIONS: tuple[str, ...] = ("accept", "dismiss", "hold")

#: The shipped posture with nothing armed. This is the behavior the driver
#: had before this module existed; it is written down here so it is a decision
#: rather than a default nobody chose.
DEFAULT_DISPOSITION = "dismiss"

ENV_HOLD_TTL = "KS4WEB_DIALOG_HOLD_S"

#: How long a held dialog stays open before the desk dismisses it. Generous
#: enough for a read and an answer, finite always: a page frozen on a dialog
#: nobody came back to is not a state to keep.
DEFAULT_HOLD_TTL_S = 60.0

#: How many answered dialogs a session remembers per page.
HISTORY_MAX = 20

#: What the history says about a dialog nothing was armed for. It is the
#: shipped posture written down, and it is the sentence the caller reads when
#: they wonder why a confirm() came back false.
DEFAULT_WHY = (
    "nothing was armed for this page, so the default posture answered it: "
    "the dialog was dismissed as soon as it opened, which a confirm() reads "
    "as Cancel and a prompt() reads as no input. Arm handle_dialog before "
    "the click that raises it to answer differently."
)

#: What the history says about a hold nobody came back to.
EXPIRED_WHY = (
    "it was held open for reading and no answer arrived within the hold "
    "window, so it was dismissed to let the page run again"
)

#: Message text is page-authored and can be any length. These are the caps for
#: the two surfaces that quote it.
MESSAGE_CAP_PAYLOAD = 2000
MESSAGE_CAP_REFUSAL = 400


def hold_ttl_s() -> float:
    try:
        return max(1.0, float(os.environ.get(ENV_HOLD_TTL,
                                             DEFAULT_HOLD_TTL_S)))
    except ValueError:
        return DEFAULT_HOLD_TTL_S


# ------------------------------------------------------------- heuristics

#: Message shapes whose accept commits something a human would want to have
#: been asked about. Each carries the plain-language reason the gate prompt
#: quotes, so the human reads why they are being asked rather than a pattern
#: name. The list is a source of BETTER REASONS, never of exemptions: a
#: message that matches nothing here still gates (see gate_reason_for_accept).
DESTRUCTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(delete|deleting|remove|removing|erase|wipe|purge|destroy)\b",
     "the message says something will be deleted or removed"),
    (r"\b(permanent(ly)?|irreversible|cannot be undone|can't be undone|"
     r"no undo)\b",
     "the message says the result cannot be undone"),
    (r"\b(submit|submitting|send|sending|post|publish|publishing)\b",
     "the message says something will be submitted or sent"),
    (r"\b(pay|paying|payment|purchase|buy|checkout|charge|charged|order|"
     r"transfer|withdraw)\b",
     "the message describes a payment or a transfer"),
    (r"\b(overwrite|overwriting|replace|replacing|discard|discarding|"
     r"reset|clear|clearing)\b",
     "the message says existing data will be replaced or discarded"),
    (r"\b(cancel subscription|unsubscribe|deactivate|close (your )?account|"
     r"sign out|log ?out|revoke)\b",
     "the message describes ending an account, a session, or an access grant"),
    (r"\b(share|sharing|grant|granting|allow|approve|authorize|authorise)\b",
     "the message describes granting access or approval"),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), why)
                  for p, why in DESTRUCTIVE_PATTERNS)


def destructive_reason(message: str) -> str | None:
    """The first recognized consequential shape in a dialog message, or None.

    Matching is over page-authored text and the result is used only to WORD a
    confirmation prompt, never to skip one."""
    for pattern, why in _COMPILED:
        if pattern.search(message or ""):
            return why
    return None


def gate_reason_for_accept(dialog_type: str, message: str) -> str | None:
    """Why answering OK to this dialog needs a human, or None when it does
    not. Dismissal never lands here: answering Cancel is the posture the
    server already has with nothing armed.

    An `alert` has a single button, so accepting one closes a box and does
    nothing else; that is the only case that comes back None. Everything else
    gates, and the return value is the sentence the human reads."""
    kind = (dialog_type or "").strip().lower()
    if kind == "alert":
        return None
    if kind == "beforeunload":
        return ("accepting leaves the page, and the page is asking because it "
                "has something unsaved")
    reason = destructive_reason(message or "")
    if reason:
        return reason
    return ("this server does not recognize the message as one where OK and "
            "Cancel do the same thing, and OK commits whatever the page does "
            "next")


# ------------------------------------------------------------ the records


@dataclass
class Arm:
    """A disposition waiting for the next dialog on one page."""

    disposition: str
    dialog_type: str = "any"
    prompt_text: str | None = None
    once: bool = True
    armed_at: float = field(default_factory=time.monotonic)
    gate: str | None = None          # the gate token that allowed an accept

    def covers(self, kind: str) -> bool:
        if self.dialog_type == "any":
            return kind in GENERIC_TYPES
        return kind == self.dialog_type


@dataclass
class Pending:
    """A dialog the desk is holding open, and everything known about it."""

    dialog_id: str
    kind: str
    message: str
    default_value: str
    page: str
    url: str
    opened: float = field(default_factory=time.monotonic)
    driver: object | None = None

    @property
    def has_prompt_input(self) -> bool:
        return self.kind == "prompt"

    def age_s(self) -> float:
        return time.monotonic() - self.opened


@dataclass
class Chooser:
    """A file chooser the page opened, recorded whether or not it is filled."""

    chooser_id: str
    page: str
    url: str
    multiple: bool
    opened: float = field(default_factory=time.monotonic)
    filled: list[str] = field(default_factory=list)


def _clip(text, cap: int) -> str:
    s = "" if text is None else str(text)
    s = s.replace("\r\n", "\n")
    return s if len(s) <= cap else s[:cap] + "..."


def untrusted_block(kind: str, message: str, default_value: str = "",
                    cap: int = MESSAGE_CAP_PAYLOAD) -> str:
    """The page-authored half of a dialog, gathered into ONE block so a single
    envelope covers all of it. The type is the driver's word and is included
    for context; everything else in here is whatever the site typed."""
    lines = [f"dialog type: {kind}", f"message: {_clip(message, cap)}"]
    if default_value:
        lines.append(f"prefilled value: {_clip(default_value, 200)}")
    return "\n".join(lines)


def describe(pending: Pending) -> dict:
    """The payload shape for one pending dialog: the machine-readable facts
    the server vouches for, plus the page's own words inside the labeled
    envelope with the note that teaches it."""
    wrapped, note = pagedata.wrap(
        untrusted_block(pending.kind, pending.message, pending.default_value),
        url=pending.url)
    return {
        "dialog_id": pending.dialog_id,
        "type": pending.kind,
        "has_prompt_input": pending.has_prompt_input,
        "page": pending.page,
        "open_for_s": round(pending.age_s(), 1),
        "dialog_text": wrapped,
        "page_data": note,
    }


def describe_line(pending: Pending) -> str:
    """The one-string form for a refusal message, label included."""
    return pagedata.wrap_line(
        untrusted_block(pending.kind, pending.message, pending.default_value,
                        cap=MESSAGE_CAP_REFUSAL),
        url=pending.url)


def held_refusal(pending: Pending, *, interrupted: str | None = None) -> str:
    """The refusal text for a held dialog, shared by every surface that meets
    one: the pre-flight check at `locate`, and the acting tools whose own
    driver call is the thing the dialog stopped.

    It names WHAT is open, WHY nothing finished, and the exact next call, and
    the dialog's own words ride the labeled envelope, because the string in a
    dialog is written by the page."""
    answer = (f"handle_dialog(page='{pending.page}', action='accept', "
              f"prompt_text='...')" if pending.has_prompt_input
              else f"handle_dialog(page='{pending.page}', action='accept')")
    opening = (
        f"{interrupted} raised a native {pending.kind} dialog and the dialog "
        f"is being held open, so the call could not finish: a dialog stops "
        f"the page's script until something answers it."
        if interrupted else
        f"a native {pending.kind} dialog is open on {pending.page} and it is "
        f"being held for reading, so nothing ran: while a dialog is open the "
        f"page's script is stopped and any read or action would wait for its "
        f"timeout and then report the timeout instead of the dialog.")
    return (
        f"{opening} Answer it with {answer} or "
        f"handle_dialog(page='{pending.page}', action='dismiss'), then read "
        f"the page to see where the answer left it. Answering OK requires a "
        f"human confirmation wherever OK would commit something. The hold "
        f"expires on its own after {int(hold_ttl_s())}s and the dialog is "
        f"dismissed then. {describe_line(pending)}")


def gate_summary(kind: str, message: str, url: str) -> str:
    """The sentence a human reads in the confirmation prompt. The message is
    the page's, so it rides labeled here too: the prompt must not read as
    though the server is the one making the claim."""
    return pagedata.wrap_line(
        untrusted_block(kind, message, cap=MESSAGE_CAP_REFUSAL), url=url)


# --------------------------------------------------------------- the desk


class DialogDesk:
    """One session's dialog and file-chooser state.

    Held on the Session object, like the console and download stores, so it
    dies with the session that owns it."""

    def __init__(self) -> None:
        self.armed: dict[str, Arm] = {}
        self.pending: dict[str, Pending] = {}
        self.choosers: dict[str, Chooser] = {}
        self.history: list[dict] = []
        self.seq = 0
        #: Strong references to the hold-expiry tasks. A task the event loop
        #: is the only holder of can be collected mid-sleep, and a hold whose
        #: bound quietly disappeared is an unbounded hold.
        self.tasks: set = set()

    # ------------------------------------------------------------- arming

    def arm(self, page: str, disposition: str, *, dialog_type: str = "any",
            prompt_text: str | None = None, once: bool = True,
            gate: str | None = None) -> Arm:
        arm = Arm(disposition=disposition, dialog_type=dialog_type,
                  prompt_text=prompt_text, once=once, gate=gate)
        self.armed[page] = arm
        return arm

    def disarm(self, page: str) -> Arm | None:
        return self.armed.pop(page, None)

    def arm_for(self, page: str) -> Arm | None:
        return self.armed.get(page)

    # ------------------------------------------------------------ pending

    def note_pending(self, pending: Pending) -> None:
        self.pending[pending.page] = pending

    def pending_for(self, page: str) -> Pending | None:
        """The dialog held open on this page, if any. Callers that need the
        hold TTL enforced sweep first; this is the plain lookup."""
        return self.pending.get(page)

    def expired(self, page: str) -> Pending | None:
        """The held dialog on this page IF its hold has run out. The caller
        does the dismissing, because answering a dialog is an await and this
        module stays synchronous."""
        held = self.pending.get(page)
        if held is not None and held.age_s() > hold_ttl_s():
            return held
        return None

    def resolve_pending(self, page: str) -> Pending | None:
        return self.pending.pop(page, None)

    # ------------------------------------------------------------ history

    def next_id(self, stem: str) -> str:
        self.seq += 1
        return f"{stem}{self.seq}-{secrets.token_hex(2)}"

    def record(self, pending: Pending, answered: str, *,
               prompt_text: str | None = None, why: str = "") -> dict:
        """Append what happened to one dialog. The message is kept RAW here
        and enveloped at every surface that emits it, so the record stays a
        faithful copy of what the page said."""
        row = {
            "dialog_id": pending.dialog_id,
            "type": pending.kind,
            "page": pending.page,
            "url": pending.url,
            "message": pending.message,
            "has_prompt_input": pending.has_prompt_input,
            "answered": answered,
            "prompt_text_sent": prompt_text,
            "why": why,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.history.append(row)
        if len(self.history) > HISTORY_MAX * 4:
            del self.history[:HISTORY_MAX]
        return row

    def history_rows(self, page: str | None = None, limit: int = HISTORY_MAX
                     ) -> list[dict]:
        rows = [r for r in self.history if page is None or r["page"] == page]
        return rows[-max(1, limit):]

    def reported_history(self, page: str | None = None,
                         limit: int = HISTORY_MAX) -> list[dict]:
        """History for a payload: the page's words go back inside an envelope
        on the way out, one per row, because each row is a different page's
        text at a different moment."""
        out = []
        for row in self.history_rows(page, limit):
            wrapped, note = pagedata.wrap(
                untrusted_block(row["type"], row["message"]),
                url=row["url"])
            out.append({
                "dialog_id": row["dialog_id"], "type": row["type"],
                "page": row["page"], "answered": row["answered"],
                "has_prompt_input": row["has_prompt_input"],
                "why": row["why"], "at": row["at"],
                "dialog_text": wrapped, "page_data": note,
            })
        return out

    # ------------------------------------------------------------ choosers

    def note_chooser(self, chooser: Chooser) -> None:
        self.choosers[chooser.page] = chooser

    def chooser_for(self, page: str) -> Chooser | None:
        return self.choosers.get(page)

    def reported_choosers(self, page: str | None = None) -> list[dict]:
        """The LAST file chooser each page opened, filled or not. It is a
        record rather than a queue: a chooser does not stop the page the way a
        dialog does, so there is nothing here to answer and nothing to
        expire. `files_set` empty means the page opened a picker and got no
        selection, which is what a cancelled chooser looks like."""
        return [
            {"chooser_id": c.chooser_id, "page": c.page,
             "accepts_multiple": c.multiple,
             "opened_s_ago": round(time.monotonic() - c.opened, 1),
             "files_set": list(c.filled)}
            for handle, c in self.choosers.items()
            if page is None or handle == page
        ]


def desk(session) -> DialogDesk:
    """The desk for one session, created on first use. Same lazy-store shape
    the console and download recorders use."""
    existing = getattr(session, "_dialogs", None)
    if existing is None:
        existing = session._dialogs = DialogDesk()
    return existing
