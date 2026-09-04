"""The tools.

Phase 0 registers the LITE CORE only, as stubs. Every stub carries its real
docstring (the description budget binds from day one, which is how the lite
bill stays under 1,500 tokens) and refuses with NOT_IMPLEMENTED, because a
tool that returns plausible output without an engine behind it is exactly
the silent-false-success disease this product exists to argue against.

This package may import from `policy/` and `engine/`. `policy/` may not
import from here.
"""
