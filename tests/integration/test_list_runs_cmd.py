"""Tests for the ``list-runs`` CLI subcommand."""

import time
from pathlib import Path
from uuid import UUID, uuid4

from click.testing import CliRunner

from enar_montecarlo.cli.main import _build_cli
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.sessions import close_context, create_context
from enar_montecarlo.persistence.values import seed_framework_defaults
from enar_montecarlo.persistence.writes import create_run_row, update_run_completion


def _create_run(
    out_dir: Path, *, sim_name: str = "x", terminated: str | None = "success"
) -> UUID:
    """Create a run-row in a sqlite-only mode artifact."""
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=None, output_dir=out_dir)
    a = store_file(ctx, {"r": "a"}, "a.yaml")
    d = store_file(ctx, {"r": "d"}, "d.yaml")
    seed_framework_defaults(ctx)
    create_run_row(
        ctx,
        run_id=run_id,
        sim_name=sim_name,
        sim_version="0.1.0",
        system_name="sys",
        system_version="0.1.0",
        seed=1,
        iterations_planned=10,
        attacker_file_id=a,
        defender_file_id=d,
        cli_args={},
    )
    if terminated is not None:
        update_run_completion(
            ctx, run_id=run_id, iterations_completed=10, terminated_reason=terminated
        )
    close_context(ctx, success=True)
    return run_id


def test_empty_output_dir_says_no_runs(tmp_path: Path) -> None:
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(
        cli, ["list-runs", "--output-dir", str(tmp_path / "runs")]
    )
    assert result.exit_code == 0
    assert "no runs" in result.output


def test_missing_output_dir_says_no_runs(tmp_path: Path) -> None:
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(
        cli, ["list-runs", "--output-dir", str(tmp_path / "missing")]
    )
    assert result.exit_code == 0
    assert "no runs" in result.output


def test_single_run_appears_in_table(tmp_path: Path) -> None:
    out_dir = tmp_path / "runs"
    run_id = _create_run(out_dir, sim_name="solo")
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["list-runs", "--output-dir", str(out_dir)])
    assert result.exit_code == 0
    # Rich may abbreviate UUIDs in narrow terminals; check first 8 hex chars.
    assert str(run_id)[:8] in result.output
    assert "solo" in result.output
    assert "10/10" in result.output
    assert "success" in result.output


def test_multiple_runs_sorted_by_started_at_desc(tmp_path: Path) -> None:
    out_dir = tmp_path / "runs"
    first = _create_run(out_dir, sim_name="first")
    time.sleep(0.05)  # ensure distinct started_at timestamps
    second = _create_run(out_dir, sim_name="second")
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["list-runs", "--output-dir", str(out_dir)])
    assert result.exit_code == 0
    # Newer run appears before older in the rendered table.
    pos_second = result.output.find("second")
    pos_first = result.output.find("first")
    assert pos_second != -1 and pos_first != -1
    assert pos_second < pos_first
    # Both UUIDs visible (first 8 chars).
    assert str(first)[:8] in result.output
    assert str(second)[:8] in result.output


def test_in_progress_run_shows_running(tmp_path: Path) -> None:
    out_dir = tmp_path / "runs"
    _create_run(out_dir, sim_name="midway", terminated=None)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["list-runs", "--output-dir", str(out_dir)])
    assert result.exit_code == 0
    assert "running" in result.output


def test_postgres_url_queries_remote(tmp_path: Path) -> None:
    out_dir = tmp_path / "runs"
    _create_run(out_dir, sim_name="local")
    # Stand-in "remote" -- separate sqlite that has no runs.
    remote_url = f"sqlite:///{tmp_path / 'remote.db'}"
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(
        cli, ["list-runs", "--postgres-url", remote_url]
    )
    assert result.exit_code == 0
    # The local artifact must NOT show up because we queried the remote.
    assert "local" not in result.output
    assert "no runs" in result.output


def test_does_not_require_sim_module(tmp_path: Path) -> None:
    out_dir = tmp_path / "runs"
    _create_run(out_dir)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["list-runs", "--output-dir", str(out_dir)])
    assert result.exit_code == 0
