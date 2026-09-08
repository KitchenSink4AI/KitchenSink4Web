# KitchenSink4Web Architecture

How the pieces fit, for people who want to understand the system rather than
just use it.

## Packs: tools are chosen at launch

The server starts with a small core (navigate, the readers, session
management) and seven optional packs: extraction, capture, network, cookies
and logins, files, diagnostics, and workflows, plus the accessibility audit.
Packs are fixed for the life of the process: what was not chosen at launch
does not exist, is not listed, and cannot be talked into existing
mid-session. That is a security shape, not a convenience: a malicious page
cannot lure the model toward a tool the process never loaded. It is also why
every tool your AI does carry costs working memory, so the default install
carries the reading product and nothing else.

## Read-only and acting: two products in one process

Out of the box the acting tools (click, type, submit) are absent the same
way unchosen packs are absent. Turning them on is one checkbox, and even
then a consent ladder stands between the model and the world: the scope you
chose decides what proceeds without asking (out of the box, reads and
query-shaped searches), and an irreducible set (payments, credentials, posts
that reach people, deletions, legal assent) asks a human every time, under
every configuration, with no pre-authorization that covers it. The gate
sentences name the action in plain words, because the human saying yes
deserves to know what they are saying yes to.

## Lanes: real browsers, honestly

A lane is which browser engine does the browsing: the bundled Chromium
(reproducible, parallel-safe), or your real installed Firefox, Chrome, or
Edge on a KS4Web-owned profile. Sites that block automated browsers mostly
fingerprint the tool, not the behavior, so the same polite read can be
refused on one lane and served on another. The lane database records which
lanes worked on which hosts, on your machine, hostnames and dates only, and
the server advises from it but never switches a lane on its own. What KS4Web
deliberately does not do is disguise a lane: no spoofed user agents, no
forged fingerprints. It will be any real browser you have; it will not
pretend to be one it is not.

## Headed and headless: the attendance signal

A headless browser has no window; a headed one is visible on your desktop.
Sites read that difference as a crude signal of whether a human is present,
and KS4Web keeps the signal truthful: it runs headless when it is genuinely
unattended automation, and it goes headed exactly when a human takes over,
through the handoff that gives you the window for logins, checks, and
anything only a person should pass. Running a headed browser nobody is
watching, purely to wear the signal, would be the same lie as a spoofed
fingerprint, and the product does not do it.

## The envelope and the vault: defense against the page

Everything a page authored arrives wrapped in a nonce-bounded envelope that
marks it as data, never instructions, so hidden text telling the model to
"ignore your instructions" is stripped, counted, and reported instead of
obeyed. The vault watches values that were observed being set (cookies,
credentials) and redacts them from every later surface, including error
messages three calls downstream. URLs of handed-off and payment pages are
redacted from status surfaces, because a checkout URL is a capability, and
the monitoring channel must not leak what the handoff exists to protect.

## Budgets and the completeness ledger: honest economics

Every read runs under a token budget it never exceeds, and every response
accounts for what it did not include: cut for budget, hidden by the page, or
unreachable, each with a count and a reason. Sessions carry action and
navigation budgets so a runaway loop dies of arithmetic rather than
enthusiasm. The published costs on the product page are measured by scripts
that ship with the source, and tests fail if the published numbers drift
from the measured ones.

## What lives on your machine

The lane database, saved logins, monitors, workflows, and the audit trail
are files on your machine. Nothing is uploaded, no telemetry exists, and
the one outbound call that is not your browsing is a version check against
PyPI at most once every seven days, disclosed in its own payload and
disabled with one switch. Knowledge artifacts learn locally or not at all:
KS4Web ships capabilities and formats, never managed data.
