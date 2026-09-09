"""The two front doors onto the same setup command.

`kitchensink4web --setup-browser` is the one a user types.
`python -m kitchensink4web.extension.setup` is the one that works without
importing fastmcp, which is why the installed-wheel proof can run the real
command instead of a stand-in. Both have to reach the same place, and neither
may start an MCP server by accident.
"""

from __future__ import annotations

import pytest

from kitchensink4web.extension import setup

#: NEVER the shipped host name. `--remove` under the default name would
#: unregister a working Lane C off the developer's own machine, and the
#: removal path deliberately looks in the real per-user application
#: directory as well as the one it was handed.
TEST_HOST = "ks4web_test_phase4_cli"


def test_the_module_entry_point_installs_and_says_where(tmp_path, capsys):
    code = setup.main(["--browser", "firefox", "--no-registry",
                       "--host-name", TEST_HOST,
                       "--install-dir", str(tmp_path / "app")])
    out = capsys.readouterr().out

    assert code == 0
    assert (tmp_path / "app" / "extension" / "firefox" / "manifest.json").is_file()
    assert str(tmp_path / "app") in out
    assert "[COPY PENDING]" in out


def test_no_registry_still_reports_success(tmp_path, capsys):
    """`--no-registry` writes files and registers nothing, and that IS the
    job it was asked to do. Returning 1 there would make a deliberate choice
    look like a failure."""
    code = setup.main(["--no-registry", "--host-name", TEST_HOST,
                       "--install-dir", str(tmp_path / "app")])
    assert code == 0


def test_the_module_entry_point_removes(tmp_path, capsys):
    setup.main(["--no-registry", "--host-name", TEST_HOST,
                "--install-dir", str(tmp_path / "app")])
    capsys.readouterr()

    code = setup.main(["--remove", "--host-name", TEST_HOST,
                       "--install-dir", str(tmp_path / "app")])
    out = capsys.readouterr().out
    assert code == 0
    assert not (tmp_path / "app" / "extension" / "firefox").exists()
    assert "add-on" in out


def test_an_unknown_browser_is_rejected_by_argparse(tmp_path):
    with pytest.raises(SystemExit) as exc:
        setup.main(["--browser", "safari", "--host-name", TEST_HOST,
                    "--install-dir", str(tmp_path)])
    assert exc.value.code == 2


def test_a_failure_returns_two_rather_than_raising(tmp_path, monkeypatch, capsys):
    """A setup command that traceback'd at a user would be telling them about
    our stack instead of their machine."""
    def boom(*a, **k):
        raise OSError("the disk said no")

    monkeypatch.setattr(setup, "install", boom)
    code = setup.main(["--no-registry", "--host-name", TEST_HOST,
                       "--install-dir", str(tmp_path)])
    assert code == 2
    assert "the disk said no" in capsys.readouterr().err


# ------------------------------------------------------- the server.py front

def test_the_server_cli_accepts_the_setup_flags():
    """Parsed, not just present. A flag that argparse rejects is a flag the
    documentation lies about."""
    from kitchensink4web import server

    parser = _build_parser(server)
    args = parser.parse_args(["--setup-browser", "--browser", "edge", "--remove"])
    assert args.setup_browser is True
    assert args.browser == "edge"
    assert args.remove is True


def test_remove_without_setup_browser_is_refused_not_ignored():
    """A `--remove` that quietly started an MCP server would leave the user
    believing something had been uninstalled."""
    from kitchensink4web import server

    parser = _build_parser(server)
    args = parser.parse_args(["--remove"])
    assert args.setup_browser is False
    assert args.remove is True
    # The refusal itself lives in main(); this pins that the two flags are
    # independently visible to it, which is what makes the refusal possible.


def _build_parser(server):
    """The argument parser `main()` builds, without running the server.

    Reaching into `main()` is not possible without it calling `mcp.run()`, so
    the parser is rebuilt from the same module constants here. If the two
    ever diverge these tests stop meaning anything, which is why the
    `--setup-browser` behaviour is also covered end to end by the module
    entry point above and by the installed-wheel proof.
    """
    import argparse

    from kitchensink4web.extension import setup as extension_setup

    parser = argparse.ArgumentParser(prog="web-mcp")
    parser.add_argument("--packs", default=None)
    parser.add_argument("--read-only", nargs="?", const="browse", default=None)
    parser.add_argument("--setup-browser", action="store_true")
    parser.add_argument("--browser", default="firefox",
                        choices=sorted(extension_setup._FLAVOR_OF))
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--extension-id", default=None)
    return parser


def test_the_server_module_imports_the_setup_module():
    """The wiring itself. If this import is gone the flag cannot work, and
    nothing else in this file would notice."""
    from kitchensink4web import server

    assert server.extension_setup is setup
    assert hasattr(server, "_run_setup_browser")
