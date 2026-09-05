<!-- DRAFT SCAFFOLD (Phase 8 config work, item c). Every English sentence
     in this file is FLAGGED for author/Fable review before publication,
     per the no-agent-product-copy rule. The Phase 9 packaging pass owns
     the full README; this scaffold exists so the install section and the
     Claude Desktop permissions tip have a home before then. -->

# KitchenSink4Web

Kitchen-sink browser MCP server: a cheap first read of any page, durable
refs, and a shipped safety layer.

## Install

Claude Desktop: install the `.mcpb` bundle and pick what you want on the
install screen. The checkboxes are the whole configuration: one to allow
clicking and typing (off means read-only browsing, the shipped default),
and one per capability pack. Launching the bundle requires `uv` (the `uvx`
command) on your machine; the server itself is fetched from PyPI on first
launch and drives its own bundled Chromium, never your browser or your
profile.

Any other MCP client:

```
uvx kitchensink4web
```

or

```
pip install kitchensink4web
python -m kitchensink4web.server
```

Packs and read-only mode are chosen at launch (`--packs`, `KS4WEB_MODE`,
`KS4WEB_ALLOW_ACTING`) and are identical for every connection to the
process.

> **Tip for Claude Desktop:** in Tool permissions, set this server's
> **Read-only tools** group to **Always Allow**. Those tools cannot change
> anything on any page, and it stops most permission prompts.
