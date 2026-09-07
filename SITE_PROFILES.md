# Site profiles — format reference, version 1

A site profile is one JSON file describing what is known about one site. It is
**data, never code.** A profile annotates a read; it can never refuse one,
change the server's wall verdict, run anything, supply a target to an action,
or carry a credential.

The reason is architectural rather than cautious. Three properties this server
sells are properties of a process that runs only code the project shipped:
read-only mode is enforced by a mutating tool never reaching `tools/list` at
all, the confirmation gate is reachable only from server-side plumbing, and
redaction sits at the serializer so no tool can forget it. A profile that could
run code would cost all three. Nothing in the requirement needs it: extraction
hints, wall signatures, auth notes, resolver lists and recorded workflows are
all data.

## Where profiles live

| Location | Source label |
|---|---|
| `kitchensink4web/profile_data/*.json` (inside the wheel) | `shipped` |
| `$KS4WEB_STATE_DIR/profiles/*.json` (default `%LOCALAPPDATA%/ks4web/profiles`) | `local` |

One profile per file. UTF-8 JSON, with or without a BOM. The filename stem must
equal the declared slug: a file named `evil.json` cannot claim
`"profile": "github"`.

**Profiles load once, at launch**, for the same reason capability packs do: the
tool set and its behavior must be identical for every connection to a process.
Adding or editing a profile needs a restart.

**KS4Web ships exactly one profile, `example.json`, and it matches
`example.com`** — the domain IANA reserves for documentation. It exists to
demonstrate the format and annotates nothing on the real web. There is no
starter pack and no registry: every claim in a shipped profile is a factual
assertion the project makes about somebody else's site, and a wrong hint or a
wrong auth note is worse than no profile, because the user believes it.

## Schema

Three fields are required (`format`, `profile`, `match.hosts`). Everything else
is optional and has a defined behavior when absent. Keys beginning with `_` are
ignored, so a profile may carry its own commentary.

```jsonc
{
  "format": 1,
  "profile": "acme",                       // slug; ^[a-z0-9][a-z0-9_-]{0,63}$
  "match": {
    "hosts": ["acme.example", "*.acme.example"],
    "not_hosts": ["private.acme.example"], // checked first, removes a candidate
    "path_prefix": ["/issues", "/pull"]    // absent means the whole host
  },

  "title": "Acme",
  "notes": ["free text the server reports back"],
  "extract": {"title": "the issue title"}, // field -> hint, fed to extract_fields
  "access": [{
    "kind": "paywall",                     // paywall|login_wall|consent_wall|region_wall
    "when": {                              // ALL present conditions must hold
      "status": [200],
      "text": "sign in to view the full text",
      "selector_present": ".paywall-overlay",
      "meta": {"name": "citation_fulltext_world_readable", "absent": true}
    },
    "evidence": "the publisher's institutional-access wording"
  }],
  "auth": {"kind": "shibboleth", "handoff_note": "...", "state_reusable": true},
  "open_access": [{"label": "Unpaywall",
                   "url_template": "https://api.unpaywall.org/v2/{doi}"}],
  "workflows": ["acme-file-issue"],
  "lane_seed": [{"lane": "B:moz-firefox", "outcome": "pass",
                 "observed": "2026-09-06"}]
}
```

### Limits, all enforced at load, all field-local

| Field | Limit | On violation |
|---|---|---|
| `format` | integer, `<= 1` | **profile skipped** |
| `profile` | slug regex, equals filename stem | **profile skipped** |
| `match.hosts` | 1–20 entries, `<= 253` chars, must contain a dot, at most one leading `*.` | invalid entries dropped; empty result **skips the profile** |
| `match.not_hosts` | 0–20, same rules | invalid entries dropped |
| `match.path_prefix` | 0–20, each starts `/`, `<= 120` chars | invalid entries dropped |
| `title` | `<= 80` chars | dropped, slug used instead |
| `notes` | `<= 5` × `<= 200` chars | extra entries dropped |
| `extract` | `<= 40` keys; key `<= 60`, value `<= 200` | invalid entries dropped |
| `access` | `<= 20` entries; `when` needs `>= 1` condition | invalid entries dropped |
| `access[].when.text` | 8–120 chars | entry dropped |
| `auth.kind` | `shibboleth`, `openathens`, `oauth`, `form`, `sso`, `none` | field dropped |
| `open_access[].url_template` | `https://` only, host on the shipped resolver allowlist | entry dropped |
| `workflows` | `<= 10`, each a valid slug | invalid entries dropped |
| `lane_seed` | `<= 12`; `outcome` in `pass`/`blocked`/`dropped` | invalid entries dropped |
| whole file | `<= 64 KB` | **profile skipped** |

"Entry dropped" versus "profile skipped" is the contract: a profile is skipped
only when it cannot be *addressed* (no valid slug, no valid match, an unreadable
file, a future format). Everything else degrades to a smaller profile that still
works.

### Prose is clamped, and dropped rather than truncated

`title`, `notes`, `evidence` and `handoff_note` must be single-line printable
text within their length limit. A string that fails is dropped whole; the
structured verdict beside it survives. `policy/walls.py` records the reasoning
and it transfers unchanged: a half-quoted claim is worse than none.

### Open-access resolvers are an allowlist

`api.unpaywall.org`, `api.openalex.org`, `api.crossref.org`, `arxiv.org`,
`www.ncbi.nlm.nih.gov`, `europepmc.org`, `core.ac.uk`, `doaj.org`,
`api.semanticscholar.org`, `zenodo.org`, `osf.io`.

**Sci-Hub, Anna's Archive, LibGen and equivalents are excluded permanently, and
the exclusion is enforced by a test rather than by review.** The project's
stated position is that it never works around a wall; a shipped pointer to a
shadow library would be that promise broken in the place a user would most
reasonably read as endorsed.

## What the format cannot express

- **No loops, no conditionals, no waiting on custom predicates.** "Click Show
  more until it disappears" is not expressible. That is a feature request
  against the workflow engine, whose replayable step vocabulary is a closed
  tuple by design.
- **No selectors that drive an action.** `access[].when.selector_present` is a
  presence test feeding an advisory note. Nothing in a profile ever supplies a
  target to `click`, `type_text`, or `fill_form`. Targets come from a read that
  minted a ref, always.
- **No headers, user-agent strings, or fingerprint knobs.**
- **No credentials, tokens, or API keys.**
- **No network fetch at load.** A profile is bytes on disk. It never resolves
  anything, never phones home, never updates itself.

## Loading is total

`load_profiles()` never raises. A truncated file, a file from a future format, a
two-megabyte file, a file claiming another site's name, six hundred files at
once, a directory named `x.json`, UTF-16 bytes, or a directory where every
single file is corrupt: in every case the server starts, every tool registers,
and the problem is reported by name with a reason.

**No profile input of any kind changes which tools exist.**

Problems are visible in three places: the startup line counts them,
`manage_session(action='profiles')` returns every one with its stage and
reason, and a `navigate` result names skipped user files.

## Precedence: one page, one profile

Profiles never merge. Merging two files into a synthetic third produces claims
no single author made, which cannot be attributed and therefore cannot be
corrected. When several match one URL, the first difference wins:

1. `not_hosts` removes a candidate outright.
2. Exact host beats a `*.` wildcard.
3. Longer matched `path_prefix` beats shorter; no `path_prefix` sorts last.
4. `local` beats `community` beats `shipped`.
5. Slug ascending. Never filesystem order.

The winner is named in the payload and the runners-up are listed by slug and
source, so an override is visible as having taken effect.

## Access signatures annotate. They never refuse.

An `access` match produces an `access_note` block carrying `kind`, which
conditions matched, the profile's `evidence`, and the sentence *"profile-
declared, advisory only; the server made no access determination."* It never
produces a refusal code, never sets a status, never suppresses content, and
never gates a read. The refusing wall verdict stays entirely with
`policy/walls.py`, which is server-owned, three-tier, and sourced against live
captures.

`policy/walls.py` learned this the expensive way: two of its own carefully
sourced needles are ordinary English, so an ungated match refused real 200 pages
whole. Community-authored matchers get less rope than that, not more.

## Third-party prose rides a labeled envelope

`title`, `notes`, `evidence` and `handoff_note` from a `community` or `local`
profile are not the server's words. They are delivered inside the same
nonce-delimited untrusted-content envelope page text rides, with the provenance
stated: written by the author of a named profile, data to report and never
instructions to follow. Shipped profiles are project-authored and ride outside
it, which is the distinction the codebase already draws between its own refusal
text and page-derived strings.

## The block is capped

The `profile` block on a payload is measured with the same estimator the page
meter uses and assembled under a 400-token ceiling, most useful part first. A
`navigate` result that grew by two thousand tokens because a profile matched
would be a regression against the product's central claim. When something is
left out, the block says which parts and points at
`manage_session(action='profiles')`.

## Lane observations belong to the lane store

A profile may carry `lane_seed[]`. It is read once, at load, handed to the lane
store through a single named function, and then discarded from the in-memory
profile. Seeds enter at that store's lowest precedence tier and never overwrite
an observation it learned itself.

**At runtime no lane question is ever answered from a profile.** The `Profile`
object exposes no lane accessor at all, which makes the rule structural rather
than a convention, and a test asserts it. When the lane store is not present in
a build, `lane_seed` is validated, dropped, and nothing else moves.
