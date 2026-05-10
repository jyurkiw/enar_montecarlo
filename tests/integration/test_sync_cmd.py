"""Tests for the ``sync`` CLI subcommand."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from enar_montecarlo.cli.main import _build_cli
from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.schema import ActorFile, Run
from enar_montecarlo.persistence.sessions import close_context, create_context
from enar_montecarlo.persistence.values import seed_framework_defaults
from enar_montecarlo.persistence.writes import create_run_row


def _populate_temp_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[UUID, Path]:
    """Create a SQLite at <tempdir>/<run_id>.db with some rows, then close."""
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'unused.db'}"  # remote URL keeps file in tempdir
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=pg_url, output_dir=tmp_path)
    a = store_file(ctx, {"role": "atk"}, "a.yaml")
    d = store_file(ctx, {"role": "def"}, "d.yaml")
    seed_framework_defaults(ctx)
    create_run_row(
        ctx,
        run_id=run_id,
        sim_name="x",
        sim_version="0.1.0",
        system_name="y",
        system_version="0.1.0",
        seed=1,
        iterations_planned=1,
        attacker_file_id=a,
        defender_file_id=d,
        cli_args={},
    )
    sqlite_path = ctx.sqlite_path
    close_context(ctx, success=False)  # success=False keeps the temp file
    assert sqlite_path.exists()
    return run_id, sqlite_path


def test_sync_replays_into_postgres_and_deletes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, src_path = _populate_temp_sqlite(tmp_path, monkeypatch)
    dst_path = tmp_path / "dst.db"
    dst_url = f"sqlite:///{dst_path}"

    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(
        cli, ["sync", str(run_id), "--postgres-url", dst_url]
    )
    assert result.exit_code == 0, result.output
    assert str(run_id) in result.output

    # Source SQLite was deleted on success.
    assert not src_path.exists()

    # Destination has the rows.
    eng = create_engine(dst_url)
    with Session(eng) as sess:
        assert sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert len(sess.execute(select(ActorFile)).all()) == 2
    eng.dispose()


def test_sync_missing_file_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(
        cli,
        [
            "sync",
            str(uuid4()),  # no SQLite file at this run_id
            "--postgres-url",
            f"sqlite:///{tmp_path / 'dst.db'}",
        ],
    )
    assert result.exit_code != 0
    assert "no orphaned SQLite" in result.output


def test_sync_invalid_uuid_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(
        cli,
        ["sync", "not-a-uuid", "--postgres-url", f"sqlite:///{tmp_path / 'd.db'}"],
    )
    assert result.exit_code != 0


def test_sync_missing_postgres_url_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(cli, ["sync", str(uuid4())])
    assert result.exit_code != 0
    assert "postgres-url" in result.output.lower()


def test_sync_does_not_require_sim_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sync is a framework-level subcommand; runs without a sim attached."""
    run_id, _ = _populate_temp_sqlite(tmp_path, monkeypatch)
    dst_url = f"sqlite:///{tmp_path / 'dst.db'}"
    runner = CliRunner()
    cli = _build_cli(sim_module=None)
    result = runner.invoke(
        cli, ["sync", str(run_id), "--postgres-url", dst_url]
    )
    assert result.exit_code == 0
