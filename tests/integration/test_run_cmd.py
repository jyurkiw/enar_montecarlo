"""Tests for the ``run`` CLI subcommand."""

import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from enar_montecarlo.cli.commands.run import _parse_extra_args
from enar_montecarlo.cli.main import _build_cli
from enar_montecarlo.events import Event, RoundCompleteMarker
from enar_montecarlo.persistence.schema import Run


def _last_line_uuid(output: str) -> UUID:
    """Extract the run UUID from the last line of CliRunner output.

    click 8.3+'s CliRunner.result.output contains stderr + stdout
    interleaved (real-user stdout/stderr separation still holds in
    actual terminal usage). The UUID is always the last thing
    written to stdout, so taking the last non-empty line is robust.
    """
    return UUID(output.strip().splitlines()[-1])


def _minimal_sim() -> types.ModuleType:
    def run_fn(*, iteration_num: int, **_: Any) -> Iterator[Event]:
        yield RoundCompleteMarker(event_seq=1, iteration_num=iteration_num, round_num=1)

    m = types.ModuleType("fixture_sim")
    m.run = run_fn
    m.OUTCOMES = ["success", "failure"]
    m.SIM_NAME = "fixture_sim"
    m.SIM_VERSION = "0.1.0"
    m.SYSTEM_NAME = "test"
    m.SYSTEM_VERSION = "0.1.0"
    m.DEFAULT_ITERATIONS = 5
    return m


def _data_files(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "a.yaml"
    d = tmp_path / "d.yaml"
    a.write_text("metadata: {}\nactors: []\n", encoding="utf-8")
    d.write_text("metadata: {}\nactors: []\n", encoding="utf-8")
    return a, d


# --- _parse_extra_args ------------------------------------------------------


def test_parse_extras_key_value_pair() -> None:
    assert _parse_extra_args(("--foo", "bar")) == {"foo": "bar"}


def test_parse_extras_equals_form() -> None:
    assert _parse_extra_args(("--foo=bar",)) == {"foo": "bar"}


def test_parse_extras_bare_flag_at_end() -> None:
    assert _parse_extra_args(("--flag",)) == {"flag": True}


def test_parse_extras_bare_flag_followed_by_another_flag() -> None:
    assert _parse_extra_args(("--a", "--b", "v")) == {"a": True, "b": "v"}


def test_parse_extras_mixed() -> None:
    extras = ("--name", "value", "--debug", "--count=3")
    assert _parse_extra_args(extras) == {"name": "value", "debug": True, "count": "3"}


def test_parse_extras_skips_non_dashed_tokens() -> None:
    # Stray positional tokens between flags are silently ignored.
    assert _parse_extra_args(("--a", "1", "stray", "--b", "2")) == {"a": "1", "b": "2"}


def test_parse_extras_empty() -> None:
    assert _parse_extra_args(()) == {}


# --- run subcommand end-to-end ---------------------------------------------


def test_run_prints_uuid_and_creates_sqlite(tmp_path: Path) -> None:
    sim = _minimal_sim()
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli,
        [
            "run",
            str(a),
            str(d),
            "--iterations",
            "3",
            "--seed",
            "12345",
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    # stdout contract: the UUID is the LAST thing written (progress UI
    # writes to stderr, which CliRunner.result.output interleaves but
    # real users see on a separate FD).
    parsed_uuid = _last_line_uuid(result.output)
    assert (out_dir / f"{parsed_uuid}.db").exists()


def test_run_records_iterations_and_seed(tmp_path: Path) -> None:
    sim = _minimal_sim()
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli,
        [
            "run",
            str(a),
            str(d),
            "--iterations",
            "4",
            "--seed",
            "999",
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    run_id = _last_line_uuid(result.output)

    eng = create_engine(f"sqlite:///{out_dir / f'{run_id}.db'}")
    with Session(eng) as sess:
        row = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.iterations_completed == 4
        assert row.seed == 999
        assert row.terminated_reason == "success"
    eng.dispose()


def test_run_default_iterations_uses_sim_constant(tmp_path: Path) -> None:
    sim = _minimal_sim()  # DEFAULT_ITERATIONS = 5
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli, ["run", str(a), str(d), "--seed", "1", "--output-dir", str(out_dir)]
    )
    assert result.exit_code == 0
    run_id = _last_line_uuid(result.output)

    eng = create_engine(f"sqlite:///{out_dir / f'{run_id}.db'}")
    with Session(eng) as sess:
        row = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.iterations_planned == 5
    eng.dispose()


def test_run_default_seed_is_clock_derived(tmp_path: Path) -> None:
    sim = _minimal_sim()
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    # No --seed.
    result = runner.invoke(
        cli, ["run", str(a), str(d), "--iterations", "1", "--output-dir", str(out_dir)]
    )
    assert result.exit_code == 0
    run_id = _last_line_uuid(result.output)

    eng = create_engine(f"sqlite:///{out_dir / f'{run_id}.db'}")
    with Session(eng) as sess:
        row = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        # Just verify a seed was assigned (not the sentinel None).
        assert row.seed is not None
        assert row.seed > 0
    eng.dispose()


def test_run_seed_determinism_produces_same_outcome(tmp_path: Path) -> None:
    """Two runs with the same --seed should record the same seed value
    and produce identical event sequences (here: marker-only, so identical
    iterations_completed)."""
    sim = _minimal_sim()
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)

    def _run() -> UUID:
        result = runner.invoke(
            cli,
            [
                "run",
                str(a),
                str(d),
                "--iterations",
                "3",
                "--seed",
                "42",
                "--output-dir",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0
        return _last_line_uuid(result.output)

    run_a = _run()
    run_b = _run()
    assert run_a != run_b  # different run UUIDs

    eng = create_engine(f"sqlite:///{out_dir / f'{run_a}.db'}")
    eng_b = create_engine(f"sqlite:///{out_dir / f'{run_b}.db'}")
    with Session(eng) as sa, Session(eng_b) as sb:
        ra = sa.execute(select(Run).where(Run.run_id == run_a)).scalar_one()
        rb = sb.execute(select(Run).where(Run.run_id == run_b)).scalar_one()
        assert ra.seed == rb.seed == 42
        assert ra.iterations_completed == rb.iterations_completed == 3
    eng.dispose()
    eng_b.dispose()


def test_run_quiet_does_not_change_stdout(tmp_path: Path) -> None:
    sim = _minimal_sim()
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli,
        [
            "run",
            str(a),
            str(d),
            "--iterations",
            "2",
            "--seed",
            "1",
            "--quiet",
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    # Still the UUID on stdout. (Progress UI is P5.)
    _last_line_uuid(result.output)


def test_run_unknown_args_pass_through_to_sim(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def run_fn(*, iteration_num: int, **extra: Any) -> Iterator[Event]:
        captured.update(extra)
        yield RoundCompleteMarker(event_seq=1, iteration_num=iteration_num, round_num=1)

    sim = _minimal_sim()
    sim.run = run_fn
    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli,
        [
            "run",
            str(a),
            str(d),
            "--iterations",
            "1",
            "--seed",
            "1",
            "--output-dir",
            str(out_dir),
            # Unknown flags after the documented ones flow into extra_args.
            "--my-flag",
            "value",
            "--debug",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("my-flag") == "value"
    assert captured.get("debug") is True


def test_run_without_sim_module_errors(tmp_path: Path) -> None:
    a, d = _data_files(tmp_path)
    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(
        cli, ["run", str(a), str(d), "--iterations", "1", "--seed", "1"]
    )
    assert result.exit_code != 0
    assert "no sim module attached" in result.output


def test_run_missing_attackers_file_errors(tmp_path: Path) -> None:
    sim = _minimal_sim()
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli, ["run", str(tmp_path / "missing.yaml"), str(tmp_path / "also.yaml")]
    )
    assert result.exit_code != 0


def test_run_postgres_mode_syncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from enar_montecarlo.persistence import sessions as sess_mod

    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"

    sim = _minimal_sim()
    a, d = _data_files(tmp_path)
    runner = CliRunner()
    cli = _build_cli(sim_module=sim)
    result = runner.invoke(
        cli,
        [
            "run",
            str(a),
            str(d),
            "--iterations",
            "2",
            "--seed",
            "1",
            "--postgres-url",
            pg_url,
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = _last_line_uuid(result.output)
    # Temp SQLite was deleted on success.
    assert not (tmp_path / f"{run_id}.db").exists()
    # Run row exists in the "remote".
    eng = create_engine(pg_url)
    with Session(eng) as sess:
        row = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.terminated_reason == "success"
    eng.dispose()
