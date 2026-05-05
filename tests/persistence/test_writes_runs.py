"""Tests for run-row writes (create_run_row + update_run_completion)."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.schema import Run
from enar_montecarlo.persistence.sessions import (
    PersistenceContext,
    close_context,
    create_context,
)
from enar_montecarlo.persistence.writes import create_run_row, update_run_completion


def _ctx(tmp_path: Path) -> PersistenceContext:
    return create_context(run_id=uuid4(), postgres_url=None, output_dir=tmp_path)


def _ctx_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PersistenceContext:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    return create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)


def _setup_files(ctx: PersistenceContext) -> tuple[str, str]:
    a = store_file(ctx, {"role": "attacker", "actors": []}, "attackers.yaml")
    d = store_file(ctx, {"role": "defender", "actors": []}, "defenders.yaml")
    return a, d


def test_create_run_row_persists_all_fields(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        a, d = _setup_files(ctx)
        run_id = uuid4()
        create_run_row(
            ctx,
            run_id=run_id,
            sim_name="fighter_vs_ogre",
            sim_version="0.1.0",
            system_name="dnd5e_2024",
            system_version="0.1.0",
            seed=12345,
            iterations_planned=500,
            attacker_file_id=a,
            defender_file_id=d,
            cli_args={"--iterations": 500},
        )
        row = ctx.sqlite.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.sim_name == "fighter_vs_ogre"
        assert row.sim_version == "0.1.0"
        assert row.system_name == "dnd5e_2024"
        assert row.system_version == "0.1.0"
        assert row.seed == 12345
        assert row.iterations_planned == 500
        assert row.iterations_completed == 0
        assert row.attacker_file_id == a
        assert row.defender_file_id == d
        assert row.started_at is not None
        assert row.completed_at is None
        assert row.cli_args == {"--iterations": 500}
        assert row.terminated_reason is None
    finally:
        close_context(ctx, success=True)


def test_update_run_completion_sets_final_fields(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        a, d = _setup_files(ctx)
        run_id = uuid4()
        create_run_row(
            ctx,
            run_id=run_id,
            sim_name="x",
            sim_version="0.1.0",
            system_name="y",
            system_version="0.1.0",
            seed=1,
            iterations_planned=10,
            attacker_file_id=a,
            defender_file_id=d,
            cli_args={},
        )
        update_run_completion(
            ctx, run_id=run_id, iterations_completed=10, terminated_reason="success"
        )
        row = ctx.sqlite.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.iterations_completed == 10
        assert row.terminated_reason == "success"
        assert row.completed_at is not None
    finally:
        close_context(ctx, success=True)


def test_update_run_completion_partial_iterations_on_error(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        a, d = _setup_files(ctx)
        run_id = uuid4()
        create_run_row(
            ctx,
            run_id=run_id,
            sim_name="x",
            sim_version="0.1.0",
            system_name="y",
            system_version="0.1.0",
            seed=1,
            iterations_planned=100,
            attacker_file_id=a,
            defender_file_id=d,
            cli_args={},
        )
        update_run_completion(
            ctx, run_id=run_id, iterations_completed=37, terminated_reason="error"
        )
        row = ctx.sqlite.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.iterations_completed == 37
        assert row.terminated_reason == "error"
    finally:
        close_context(ctx, success=True)


def test_remote_mode_writes_run_to_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx_remote(tmp_path, monkeypatch)
    try:
        a, d = _setup_files(ctx)
        run_id = uuid4()
        create_run_row(
            ctx,
            run_id=run_id,
            sim_name="x",
            sim_version="0.1.0",
            system_name="y",
            system_version="0.1.0",
            seed=1,
            iterations_planned=10,
            attacker_file_id=a,
            defender_file_id=d,
            cli_args={},
        )
        update_run_completion(
            ctx, run_id=run_id, iterations_completed=10, terminated_reason="success"
        )
        sqlite_row = ctx.sqlite.execute(
            select(Run).where(Run.run_id == run_id)
        ).scalar_one()
        assert ctx.postgres is not None
        remote_row = ctx.postgres.execute(
            select(Run).where(Run.run_id == run_id)
        ).scalar_one()
        assert sqlite_row.iterations_completed == remote_row.iterations_completed == 10
        assert sqlite_row.terminated_reason == remote_row.terminated_reason == "success"
    finally:
        close_context(ctx, success=True)
