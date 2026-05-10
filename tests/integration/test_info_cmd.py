"""Tests for the ``info`` CLI subcommand."""

import json
import types

from click.testing import CliRunner

from enar_montecarlo.cli.main import _build_cli


def _sim(*, max_rounds: int | None = None, default_iterations: int = 500) -> types.ModuleType:
    m = types.ModuleType("fixture_sim")
    m.run = lambda **_: iter(())
    m.OUTCOMES = ["success", "failure"]
    m.SIM_NAME = "fighter_vs_ogre"
    m.SIM_VERSION = "0.1.0"
    m.SYSTEM_NAME = "dnd5e_2024"
    m.SYSTEM_VERSION = "0.1.0"
    m.DEFAULT_ITERATIONS = default_iterations
    if max_rounds is not None:
        m.MAX_ROUNDS = max_rounds
    return m


def test_text_format_default() -> None:
    cli = _build_cli(sim_module=_sim(max_rounds=5))
    result = CliRunner().invoke(cli, ["info"])
    assert result.exit_code == 0
    assert "sim:    fighter_vs_ogre 0.1.0" in result.output
    assert "system: dnd5e_2024 0.1.0" in result.output
    assert "iterations: 500" in result.output
    assert "max_rounds: 5" in result.output


def test_text_format_when_max_rounds_unset() -> None:
    cli = _build_cli(sim_module=_sim())
    result = CliRunner().invoke(cli, ["info"])
    assert result.exit_code == 0
    assert "max_rounds: None" in result.output


def test_json_format() -> None:
    cli = _build_cli(sim_module=_sim(max_rounds=5, default_iterations=250))
    result = CliRunner().invoke(cli, ["info", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["sim"] == {"name": "fighter_vs_ogre", "version": "0.1.0"}
    assert payload["system"] == {"name": "dnd5e_2024", "version": "0.1.0"}
    assert payload["defaults"] == {"iterations": 250, "max_rounds": 5}
    assert payload["outcomes"] == ["success", "failure"]


def test_json_with_null_max_rounds() -> None:
    cli = _build_cli(sim_module=_sim())
    result = CliRunner().invoke(cli, ["info", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["defaults"]["max_rounds"] is None


def test_no_sim_attached_errors() -> None:
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["info"])
    assert result.exit_code != 0
    assert "no sim module attached" in result.output
