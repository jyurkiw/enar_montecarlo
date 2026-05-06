"""Tests for the RunArgs argument bundle."""

import types
from pathlib import Path

from enar_montecarlo.lifecycle import RunArgs


def _module() -> types.ModuleType:
    return types.ModuleType("fake_sim")


def test_run_args_required_fields_only() -> None:
    args = RunArgs(
        sim_module=_module(),
        attackers_path=Path("a.yaml"),
        defenders_path=Path("d.yaml"),
        iterations=500,
        seed=12345,
        postgres_url=None,
        output_dir=Path("./runs"),
    )
    assert args.iterations == 500
    assert args.seed == 12345
    assert args.postgres_url is None
    assert args.quiet is False
    assert args.progress_format == "text"
    assert args.extra_args == {}


def test_run_args_quiet_and_json_progress() -> None:
    args = RunArgs(
        sim_module=_module(),
        attackers_path=Path("a.yaml"),
        defenders_path=Path("d.yaml"),
        iterations=10,
        seed=1,
        postgres_url=None,
        output_dir=Path("."),
        quiet=True,
        progress_format="json",
    )
    assert args.quiet is True
    assert args.progress_format == "json"


def test_run_args_extra_args_default_independent_per_instance() -> None:
    a = RunArgs(
        sim_module=_module(),
        attackers_path=Path("a.yaml"),
        defenders_path=Path("d.yaml"),
        iterations=1,
        seed=1,
        postgres_url=None,
        output_dir=Path("."),
    )
    b = RunArgs(
        sim_module=_module(),
        attackers_path=Path("a.yaml"),
        defenders_path=Path("d.yaml"),
        iterations=1,
        seed=1,
        postgres_url=None,
        output_dir=Path("."),
    )
    a.extra_args["x"] = 1
    assert b.extra_args == {}


def test_run_args_extra_args_carries_through() -> None:
    args = RunArgs(
        sim_module=_module(),
        attackers_path=Path("a.yaml"),
        defenders_path=Path("d.yaml"),
        iterations=1,
        seed=1,
        postgres_url=None,
        output_dir=Path("."),
        extra_args={"--my-flag": "value"},
    )
    assert args.extra_args == {"--my-flag": "value"}


def test_run_args_postgres_url_round_trip() -> None:
    args = RunArgs(
        sim_module=_module(),
        attackers_path=Path("a.yaml"),
        defenders_path=Path("d.yaml"),
        iterations=1,
        seed=1,
        postgres_url="postgresql://user:pass@host/db",
        output_dir=Path("."),
    )
    assert args.postgres_url == "postgresql://user:pass@host/db"
