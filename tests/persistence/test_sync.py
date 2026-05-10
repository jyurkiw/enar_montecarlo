"""Tests for SQLite -> Postgres sync.

Real Postgres is gated behind POSTGRES_TEST_URL. The cross-table
copy + idempotency + ordering contract is exercised against a
sqlite:// destination, which runs the same on-conflict and ordering
machinery without requiring a live Postgres.
"""

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from enar_montecarlo.events import EffectEvent, ResolutionEvent
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.schema import (
    ActorFile,
    Effect,
    Resolution,
    Run,
    Value,
)
from enar_montecarlo.persistence.sessions import close_context, create_context
from enar_montecarlo.persistence.sync import sync_to_postgres
from enar_montecarlo.persistence.values import (
    make_persist_fn,
    seed_framework_defaults,
)
from enar_montecarlo.persistence.writes import (
    create_run_row,
    update_run_completion,
    write_event,
)

# --- helpers ----------------------------------------------------------------


def _build_populated_sqlite(tmp_path: Path) -> tuple[Path, UUID, str, str]:
    """Create a sqlite-only context, populate it, close, return the file path
    plus the run_id and the two actor file SHAs."""
    out = tmp_path / "out"
    ctx = create_context(run_id=uuid4(), postgres_url=None, output_dir=out)
    a = store_file(ctx, {"role": "atk", "n": 1}, "a.yaml")
    d = store_file(ctx, {"role": "def", "n": 2}, "d.yaml")
    seed_framework_defaults(ctx)
    persist = make_persist_fn(ctx)
    miss = persist("outcome", "miss")
    persist("outcome", "hit")
    persist("damage_type", "fire")
    branch_success = persist("branch", "success")
    eff_dmg = persist("effect_type", "damage")

    run_id = uuid4()
    create_run_row(
        ctx,
        run_id=run_id,
        sim_name="x",
        sim_version="0.1.0",
        system_name="y",
        system_version="0.1.0",
        seed=12345,
        iterations_planned=1,
        attacker_file_id=a,
        defender_file_id=d,
        cli_args={"--seed": 12345},
    )
    # Insert events in non-monotonic order to verify ordering is restored
    # from (iteration_num, event_seq) at query time after sync.
    write_event(
        ctx,
        run_id=run_id,
        event=ResolutionEvent(
            event_seq=3,
            iteration_num=0,
            actor_file_id=a,
            actor_index=0,
            resolution_name="r3",
            outcome_id=miss,
        ),
    )
    write_event(
        ctx,
        run_id=run_id,
        event=ResolutionEvent(
            event_seq=1,
            iteration_num=0,
            actor_file_id=a,
            actor_index=0,
            resolution_name="r1",
            outcome_id=miss,
        ),
    )
    write_event(
        ctx,
        run_id=run_id,
        event=EffectEvent(
            event_seq=2,
            iteration_num=0,
            actor_file_id=a,
            actor_index=0,
            effect_definition_name="e2",
            effect_type_id=eff_dmg,
            source_branch_id=branch_success,
            caused_by_seq=1,
        ),
    )
    update_run_completion(
        ctx, run_id=run_id, iterations_completed=1, terminated_reason="success"
    )
    sqlite_path = ctx.sqlite_path
    close_context(ctx, success=True)  # non-temp, file persists
    return sqlite_path, run_id, a, d


def _open_dst(url: str) -> tuple[Engine, Session]:
    eng = create_engine(url)
    return eng, Session(eng)


# --- end-to-end sync --------------------------------------------------------


def test_sync_copies_all_tables(tmp_path: Path) -> None:
    src_path, run_id, a, d = _build_populated_sqlite(tmp_path)
    dst_url = f"sqlite:///{tmp_path / 'dst.db'}"

    sync_to_postgres(sqlite_path=src_path, postgres_url=dst_url)

    eng, sess = _open_dst(dst_url)
    try:
        actor_shas = {
            af.sha256 for af in sess.execute(select(ActorFile)).scalars().all()
        }
        assert actor_shas == {a, d}

        run = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert run.iterations_completed == 1
        assert run.terminated_reason == "success"
        assert run.seed == 12345
        assert run.cli_args == {"--seed": 12345}

        assert len(sess.execute(select(Resolution)).all()) == 2
        assert len(sess.execute(select(Effect)).all()) == 1
        # values: 4 framework effect_type + 1 framework branch
        # + outcome.miss + outcome.hit + damage_type.fire + branch.success
        # + effect_type.damage already in framework, so persist of "damage" hits
        # the existing row -> 4 + 1 + 2 + 1 + 1 = 9
        assert len(sess.execute(select(Value)).all()) == 9
    finally:
        sess.close()
        eng.dispose()


def test_sync_is_idempotent(tmp_path: Path) -> None:
    src_path, _, _, _ = _build_populated_sqlite(tmp_path)
    dst_url = f"sqlite:///{tmp_path / 'dst.db'}"

    sync_to_postgres(sqlite_path=src_path, postgres_url=dst_url)
    sync_to_postgres(sqlite_path=src_path, postgres_url=dst_url)

    eng, sess = _open_dst(dst_url)
    try:
        # Row counts after two syncs must match counts after one.
        assert len(sess.execute(select(ActorFile)).all()) == 2
        assert len(sess.execute(select(Run)).all()) == 1
        assert len(sess.execute(select(Resolution)).all()) == 2
        assert len(sess.execute(select(Effect)).all()) == 1
    finally:
        sess.close()
        eng.dispose()


def test_sync_preserves_event_ordering(tmp_path: Path) -> None:
    src_path, run_id, _, _ = _build_populated_sqlite(tmp_path)
    dst_url = f"sqlite:///{tmp_path / 'dst.db'}"

    sync_to_postgres(sqlite_path=src_path, postgres_url=dst_url)

    eng, sess = _open_dst(dst_url)
    try:
        # ORDER BY (iteration_num, event_seq) returns the canonical
        # chronological order regardless of insertion order.
        rows = (
            sess.execute(
                select(Resolution.event_seq)
                .where(Resolution.run_id == run_id)
                .order_by(Resolution.iteration_num, Resolution.event_seq)
            )
            .scalars()
            .all()
        )
        assert rows == [1, 3]
    finally:
        sess.close()
        eng.dispose()


def test_sync_preserves_value_ids(tmp_path: Path) -> None:
    src_path, _, _, _ = _build_populated_sqlite(tmp_path)
    dst_url = f"sqlite:///{tmp_path / 'dst.db'}"

    src_engine = create_engine(f"sqlite:///{src_path}")
    with Session(src_engine) as src:
        src_values = {
            (v.id, v.category, v.value)
            for v in src.execute(select(Value)).scalars().all()
        }
    src_engine.dispose()

    sync_to_postgres(sqlite_path=src_path, postgres_url=dst_url)

    eng, sess = _open_dst(dst_url)
    try:
        dst_values = {
            (v.id, v.category, v.value)
            for v in sess.execute(select(Value)).scalars().all()
        }
        assert src_values == dst_values
    finally:
        sess.close()
        eng.dispose()


def test_sync_handles_empty_tables(tmp_path: Path) -> None:
    # Source has only schema, no rows. Should sync without error.
    src_path = tmp_path / "empty.db"
    from enar_montecarlo.persistence.schema import Base

    src_engine = create_engine(f"sqlite:///{src_path}")
    Base.metadata.create_all(src_engine)
    src_engine.dispose()

    dst_url = f"sqlite:///{tmp_path / 'dst.db'}"
    sync_to_postgres(sqlite_path=src_path, postgres_url=dst_url)

    eng, sess = _open_dst(dst_url)
    try:
        assert sess.execute(select(ActorFile)).all() == []
        assert sess.execute(select(Run)).all() == []
    finally:
        sess.close()
        eng.dispose()


# --- dialect dispatch (unit) ------------------------------------------------


def test_bulk_upsert_stmt_postgres_branch() -> None:
    from sqlalchemy.dialects.postgresql.dml import Insert as PGInsert

    from enar_montecarlo.persistence.sync import _bulk_upsert_stmt

    class _Dialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _Dialect()

    stmt = _bulk_upsert_stmt(
        _FakeEngine(),  # type: ignore[arg-type]
        Value,
        [{"category": "outcome", "value": "miss"}],
        ["category", "value"],
    )
    assert isinstance(stmt, PGInsert)


# --- real Postgres (gated) --------------------------------------------------
#
# The ``postgres_url`` fixture (in conftest.py) skips when
# POSTGRES_TEST_URL is unset, creates the named DB if it does not
# exist, and drops it after the test.


def test_real_postgres_round_trip(tmp_path: Path, postgres_url: str) -> None:
    src_path, run_id, _, _ = _build_populated_sqlite(tmp_path)
    sync_to_postgres(sqlite_path=src_path, postgres_url=postgres_url)
    # Smoke check via a fresh connection.
    eng, sess = _open_dst(postgres_url)
    try:
        run = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert run.iterations_completed == 1
    finally:
        sess.close()
        eng.dispose()
