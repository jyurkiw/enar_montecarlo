"""Tests for values seeding + persist callable."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.schema import Value
from enar_montecarlo.persistence.sessions import (
    PersistenceContext,
    close_context,
    create_context,
)
from enar_montecarlo.persistence.values import (
    FRAMEWORK_BRANCHES,
    FRAMEWORK_EFFECT_TYPES,
    make_persist_fn,
    seed_framework_defaults,
)


def _ctx_sqlite_only(tmp_path: Path) -> PersistenceContext:
    return create_context(run_id=uuid4(), postgres_url=None, output_dir=tmp_path)


def _ctx_with_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> PersistenceContext:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    return create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)


# --- seed_framework_defaults ----------------------------------------------


def test_seed_inserts_effect_types_and_branches(tmp_path: Path) -> None:
    ctx = _ctx_sqlite_only(tmp_path)
    try:
        seed_framework_defaults(ctx)
        rows = set(ctx.sqlite.execute(select(Value.category, Value.value)).all())
        for et in FRAMEWORK_EFFECT_TYPES:
            assert ("effect_type", et) in rows
        for br in FRAMEWORK_BRANCHES:
            assert ("branch", br) in rows
    finally:
        close_context(ctx, success=True)


def test_seed_is_idempotent(tmp_path: Path) -> None:
    ctx = _ctx_sqlite_only(tmp_path)
    try:
        seed_framework_defaults(ctx)
        first = len(ctx.sqlite.execute(select(Value)).all())
        seed_framework_defaults(ctx)
        second = len(ctx.sqlite.execute(select(Value)).all())
        assert first == second
        # And matches the static expected count.
        assert first == len(FRAMEWORK_EFFECT_TYPES) + len(FRAMEWORK_BRANCHES)
    finally:
        close_context(ctx, success=True)


# --- make_persist_fn (sqlite-only) ------------------------------------------


def test_persist_fn_returns_int_id(tmp_path: Path) -> None:
    ctx = _ctx_sqlite_only(tmp_path)
    try:
        persist = make_persist_fn(ctx)
        assert isinstance(persist("outcome", "miss"), int)
    finally:
        close_context(ctx, success=True)


def test_persist_fn_idempotent_same_id(tmp_path: Path) -> None:
    ctx = _ctx_sqlite_only(tmp_path)
    try:
        persist = make_persist_fn(ctx)
        ids = [persist("outcome", "miss") for _ in range(5)]
        assert len(set(ids)) == 1
    finally:
        close_context(ctx, success=True)


def test_persist_fn_distinct_pairs_distinct_ids(tmp_path: Path) -> None:
    ctx = _ctx_sqlite_only(tmp_path)
    try:
        persist = make_persist_fn(ctx)
        ids = {
            persist("outcome", "miss"),
            persist("outcome", "hit"),
            persist("damage_type", "fire"),
        }
        assert len(ids) == 3
    finally:
        close_context(ctx, success=True)


def test_persist_fn_concurrent_pairs_resolve_to_same_id(tmp_path: Path) -> None:
    # Two builders sharing the same context register the same pair.
    ctx = _ctx_sqlite_only(tmp_path)
    try:
        persist_a = make_persist_fn(ctx)
        persist_b = make_persist_fn(ctx)
        a = persist_a("outcome", "miss")
        b = persist_b("outcome", "miss")
        assert a == b
    finally:
        close_context(ctx, success=True)


# --- remote mode mirroring --------------------------------------------------


def test_remote_mode_id_matches_in_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx_with_remote(tmp_path, monkeypatch)
    try:
        persist = make_persist_fn(ctx)
        the_id = persist("outcome", "miss")
        assert ctx.postgres is not None
        sqlite_id = ctx.sqlite.execute(
            select(Value.id).where(
                Value.category == "outcome", Value.value == "miss"
            )
        ).scalar_one()
        remote_id = ctx.postgres.execute(
            select(Value.id).where(
                Value.category == "outcome", Value.value == "miss"
            )
        ).scalar_one()
        assert the_id == sqlite_id == remote_id
    finally:
        close_context(ctx, success=True)


def test_remote_mode_seed_runs_on_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx_with_remote(tmp_path, monkeypatch)
    try:
        seed_framework_defaults(ctx)
        sqlite_count = len(ctx.sqlite.execute(select(Value)).all())
        assert ctx.postgres is not None
        remote_count = len(ctx.postgres.execute(select(Value)).all())
        expected = len(FRAMEWORK_EFFECT_TYPES) + len(FRAMEWORK_BRANCHES)
        assert sqlite_count == remote_count == expected
    finally:
        close_context(ctx, success=True)


def test_remote_mode_idempotent_no_id_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx_with_remote(tmp_path, monkeypatch)
    try:
        persist = make_persist_fn(ctx)
        first = persist("outcome", "miss")
        again = persist("outcome", "miss")
        assert first == again
    finally:
        close_context(ctx, success=True)


# --- dialect dispatch (unit) -------------------------------------------------


def test_upsert_stmt_postgres_branch_uses_pg_insert() -> None:
    """Direct unit test of the postgres dialect branch.

    Tests above all use SQLite (even the "remote" stand-in), so this
    guards the never-otherwise-exercised pg branch in _upsert_stmt.
    """
    from sqlalchemy.dialects.postgresql.dml import Insert as PGInsert

    from enar_montecarlo.persistence.values import _upsert_stmt

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _FakeSession:
        def get_bind(self) -> _Bind:
            return _Bind()

    stmt = _upsert_stmt(_FakeSession(), "outcome", "miss")  # type: ignore[arg-type]
    # on_conflict_do_nothing returns a wrapped object; the underlying
    # insert is the postgres-specific subclass.
    assert isinstance(stmt, PGInsert)
