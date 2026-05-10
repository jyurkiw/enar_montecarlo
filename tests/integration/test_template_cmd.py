"""Tests for the ``template`` CLI subcommand."""

import json
import types
from pathlib import Path
from typing import Any

import yaml
from click.testing import CliRunner

from enar_montecarlo.cli.main import _build_cli


def _sim(template_fn: Any = None) -> types.ModuleType:
    m = types.ModuleType("fixture_sim")
    m.run = lambda **_: iter(())
    m.OUTCOMES = ["success", "failure"]
    m.SIM_NAME = "fixture_sim"
    m.SIM_VERSION = "0.1.0"
    m.SYSTEM_NAME = "dnd5e_2024"
    m.SYSTEM_VERSION = "0.1.0"
    if template_fn is not None:
        m.template = template_fn
    return m


def test_default_yaml_template_to_stdout() -> None:
    runner = CliRunner()
    cli = _build_cli(sim_module=_sim())
    result = runner.invoke(cli, ["template"])
    assert result.exit_code == 0
    parsed = yaml.safe_load(result.output)
    assert parsed["metadata"]["system"] == "dnd5e_2024"
    assert parsed["metadata"]["system_version"] == "0.1.0"
    assert parsed["actors"][0]["name"] == "example"
    assert parsed["actors"][0]["count"] == 1
    assert parsed["actors"][0]["clumping"] == 1


def test_json_format_to_stdout() -> None:
    runner = CliRunner()
    cli = _build_cli(sim_module=_sim())
    result = runner.invoke(cli, ["template", "--format", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["metadata"]["system"] == "dnd5e_2024"


def test_output_writes_to_file(tmp_path: Path) -> None:
    out = tmp_path / "starter.yaml"
    runner = CliRunner()
    cli = _build_cli(sim_module=_sim())
    result = runner.invoke(cli, ["template", "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    parsed = yaml.safe_load(out.read_text())
    assert parsed["actors"][0]["name"] == "example"
    # stdout is empty when --output is given.
    assert result.output == ""


def test_output_json_writes_to_file(tmp_path: Path) -> None:
    out = tmp_path / "starter.json"
    runner = CliRunner()
    cli = _build_cli(sim_module=_sim())
    result = runner.invoke(cli, ["template", "--format", "json", "--output", str(out)])
    assert result.exit_code == 0
    assert json.loads(out.read_text())["actors"]


def test_sim_provided_template_used_when_present() -> None:
    custom = {
        "metadata": {"system": "custom_sys", "system_version": "9.9.9"},
        "actors": [{"name": "custom_actor", "count": 5, "clumping": 5}],
    }

    def template_fn() -> dict[str, Any]:
        return custom

    runner = CliRunner()
    cli = _build_cli(sim_module=_sim(template_fn=template_fn))
    result = runner.invoke(cli, ["template"])
    assert result.exit_code == 0
    parsed = yaml.safe_load(result.output)
    assert parsed == custom


def test_no_sim_attached_errors() -> None:
    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(cli, ["template"])
    assert result.exit_code != 0
    assert "no sim module attached" in result.output
