"""Tests for the ``validate`` CLI subcommand."""

import types
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from enar_montecarlo.cli.main import _build_cli


def _sim(validate_fn: Any = None) -> types.ModuleType:
    m = types.ModuleType("fixture_sim")
    m.run = lambda **_: iter(())
    m.OUTCOMES = ["success", "failure"]
    m.SIM_NAME = "fixture"
    m.SIM_VERSION = "0.1.0"
    m.SYSTEM_NAME = "test"
    m.SYSTEM_VERSION = "0.1.0"
    if validate_fn is not None:
        m.validate = validate_fn
    return m


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


_VALID_YAML = (
    "metadata:\n"
    "  system: dnd5e_2024\n"
    "actors:\n"
    "  - name: fighter\n"
    "    count: 1\n"
    "    clumping: 1\n"
)


def _invoke(args: list[str], sim: types.ModuleType | None = None) -> Any:
    # click 8.2+ always separates stderr; pass no mix_stderr kwarg.
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    return runner.invoke(cli, args)


# --- valid file -------------------------------------------------------------


def test_valid_file_exits_zero(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", _VALID_YAML)
    result = _invoke(["validate", str(f)])
    assert result.exit_code == 0
    assert result.output == ""
    assert result.stderr == ""


# --- file-shape errors ------------------------------------------------------


def test_broken_yaml_exits_one_with_message(tmp_path: Path) -> None:
    f = _write(tmp_path / "broken.yaml", "key: : :\nactors: [\n")
    result = _invoke(["validate", str(f)])
    assert result.exit_code != 0
    assert "failed to parse YAML" in result.stderr


def test_missing_actors_key_exits_one(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", "metadata:\n  system: x\n")
    result = _invoke(["validate", str(f)])
    assert result.exit_code != 0
    assert "actors" in result.stderr


# --- per-actor checks -------------------------------------------------------


def test_actor_missing_name_exits_one(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "f.yaml",
        "actors:\n  - count: 1\n    clumping: 1\n",
    )
    result = _invoke(["validate", str(f)])
    assert result.exit_code != 0
    assert "name" in result.stderr


def test_actor_missing_count_and_clumping_lists_both(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", "actors:\n  - name: bob\n")
    result = _invoke(["validate", str(f)])
    assert result.exit_code != 0
    assert "count" in result.stderr
    assert "clumping" in result.stderr


def test_actor_not_a_dict_exits_one(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", "actors:\n  - just_a_string\n")
    result = _invoke(["validate", str(f)])
    assert result.exit_code != 0
    assert "must be a dict" in result.stderr


def test_actors_not_a_list_exits_one(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", "actors: not_a_list\n")
    result = _invoke(["validate", str(f)])
    assert result.exit_code != 0
    assert "must be a list" in result.stderr


# --- sim hook ---------------------------------------------------------------


def test_sim_validate_hook_issues_appended(tmp_path: Path) -> None:
    def sim_validate(attackers: Any, defenders: Any) -> list[str]:
        return ["actor too weak", "missing CR"]

    f = _write(tmp_path / "f.yaml", _VALID_YAML)
    result = _invoke(["validate", str(f)], sim=_sim(validate_fn=sim_validate))
    assert result.exit_code != 0
    assert "actor too weak" in result.stderr
    assert "missing CR" in result.stderr


def test_sim_validate_returning_empty_is_clean(tmp_path: Path) -> None:
    def sim_validate(attackers: Any, defenders: Any) -> list[str]:
        return []

    f = _write(tmp_path / "f.yaml", _VALID_YAML)
    result = _invoke(["validate", str(f)], sim=_sim(validate_fn=sim_validate))
    assert result.exit_code == 0


def test_sim_validate_raising_is_recorded_as_issue(tmp_path: Path) -> None:
    def sim_validate(attackers: Any, defenders: Any) -> list[str]:
        raise RuntimeError("blew up")

    f = _write(tmp_path / "f.yaml", _VALID_YAML)
    result = _invoke(["validate", str(f)], sim=_sim(validate_fn=sim_validate))
    assert result.exit_code != 0
    assert "sim.validate raised" in result.stderr


def test_no_sim_validate_hook_only_framework_checks_run(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", _VALID_YAML)
    result = _invoke(["validate", str(f)], sim=_sim())
    assert result.exit_code == 0


def test_no_sim_attached_framework_checks_still_run(tmp_path: Path) -> None:
    f = _write(tmp_path / "f.yaml", _VALID_YAML)
    result = _invoke(["validate", str(f)], sim=None)
    assert result.exit_code == 0
