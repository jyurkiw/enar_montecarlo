"""Tests for the CLI scaffold + main() entry point."""

import sys
import types

import click
import pytest
from click.testing import CliRunner

from enar_montecarlo import main as exported_main
from enar_montecarlo.cli.main import _build_cli, main


def test_main_is_re_exported_from_package() -> None:
    from enar_montecarlo.cli.main import main as canonical

    assert exported_main is canonical


def test_dunder_main_module_importable() -> None:
    """``python -m enar_montecarlo`` works because __main__ imports main."""
    import enar_montecarlo.__main__ as dunder_main
    from enar_montecarlo.cli.main import main as canonical

    assert dunder_main.main is canonical


def test_help_lists_all_subcommands() -> None:
    cli = _build_cli(sim_module=None)
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for sub in ("run", "template", "validate", "info", "sync", "purge", "list-runs"):
        assert sub in result.output


@pytest.mark.parametrize(
    "subcommand",
    ["run", "template", "validate", "info", "sync", "purge", "list-runs"],
)
def test_subcommand_help_works(subcommand: str) -> None:
    cli = _build_cli(sim_module=None)
    runner = CliRunner()
    result = runner.invoke(cli, [subcommand, "--help"])
    assert result.exit_code == 0
    assert "--help" in result.output


def test_sim_module_threaded_through_context() -> None:
    """A sim_module passed to main() should be visible to subcommands via
    ctx.obj."""
    sim = types.ModuleType("fake_sim")
    sim.SIM_NAME = "fake"
    cli = _build_cli(sim_module=sim)

    captured: dict[str, object] = {}

    @click.command(name="peek")
    @click.pass_context
    def peek(ctx: click.Context) -> None:
        captured["sim_module"] = ctx.obj["sim_module"]

    cli.add_command(peek)

    runner = CliRunner()
    result = runner.invoke(cli, ["peek"])
    assert result.exit_code == 0, result.output
    assert captured["sim_module"] is sim


def test_main_skips_framework_main_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m enar_montecarlo`` -- main() must NOT treat the
    framework's own __main__ as a sim."""
    fake_main = types.ModuleType("__main__")
    fake_main.__package__ = "enar_montecarlo"
    monkeypatch.setitem(sys.modules, "__main__", fake_main)

    captured: dict[str, object | None] = {}

    def fake_build(sim_module: types.ModuleType | None) -> object:
        captured["sim_module"] = sim_module

        # Return a no-op invocable so main() doesn't crash.
        def _noop() -> None:
            pass

        return _noop

    monkeypatch.setattr("enar_montecarlo.cli.main._build_cli", fake_build)
    main()
    assert captured["sim_module"] is None


def test_main_picks_up_sim_module_from_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """When __main__ is a real sim package, main() should pick it up."""
    sim = types.ModuleType("__main__")
    sim.__package__ = "my_sim"
    sim.SIM_NAME = "my_sim"
    monkeypatch.setitem(sys.modules, "__main__", sim)

    captured: dict[str, object | None] = {}

    def fake_build(sim_module: types.ModuleType | None) -> object:
        captured["sim_module"] = sim_module

        def _noop() -> None:
            pass

        return _noop

    monkeypatch.setattr("enar_montecarlo.cli.main._build_cli", fake_build)
    main()
    assert captured["sim_module"] is sim


