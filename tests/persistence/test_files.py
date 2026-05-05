"""Tests for SHA-256-keyed actor file storage."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.schema import ActorFile
from enar_montecarlo.persistence.sessions import (
    PersistenceContext,
    close_context,
    create_context,
)


def _ctx(tmp_path: Path) -> PersistenceContext:
    return create_context(run_id=uuid4(), postgres_url=None, output_dir=tmp_path)


def _ctx_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PersistenceContext:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    return create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)


# --- core dedup contract ----------------------------------------------------


def test_same_content_returns_same_sha_and_one_row(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        sha1 = store_file(ctx, {"a": 1, "b": 2}, "fighter.yaml")
        sha2 = store_file(ctx, {"a": 1, "b": 2}, "fighter.yaml")
        assert sha1 == sha2
        rows = ctx.sqlite.execute(select(ActorFile)).scalars().all()
        assert len(rows) == 1
    finally:
        close_context(ctx, success=True)


def test_different_content_distinct_sha_and_two_rows(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        sha1 = store_file(ctx, {"a": 1}, "f1.yaml")
        sha2 = store_file(ctx, {"a": 2}, "f2.yaml")
        assert sha1 != sha2
        rows = ctx.sqlite.execute(select(ActorFile)).scalars().all()
        assert len(rows) == 2
    finally:
        close_context(ctx, success=True)


def test_filename_mismatch_same_content_one_row_first_wins(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        sha1 = store_file(ctx, {"a": 1}, "fighter.yaml")
        sha2 = store_file(ctx, {"a": 1}, "different_name.yaml")
        assert sha1 == sha2
        row = ctx.sqlite.execute(select(ActorFile)).scalar_one()
        assert row.original_filename == "fighter.yaml"
    finally:
        close_context(ctx, success=True)


def test_canonical_sha_invariant_to_key_order(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        sha1 = store_file(ctx, {"a": 1, "b": 2}, "f.yaml")
        sha2 = store_file(ctx, {"b": 2, "a": 1}, "f.yaml")
        assert sha1 == sha2
        rows = ctx.sqlite.execute(select(ActorFile)).scalars().all()
        assert len(rows) == 1
    finally:
        close_context(ctx, success=True)


def test_returned_sha_matches_stored_row(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        sha = store_file(ctx, {"x": [1, 2, 3]}, "f.yaml")
        row = ctx.sqlite.execute(select(ActorFile)).scalar_one()
        assert row.sha256 == sha
        assert len(sha) == 64  # hex SHA-256
    finally:
        close_context(ctx, success=True)


# --- realistic-size content -------------------------------------------------


def test_large_statblock_round_trip(tmp_path: Path) -> None:
    # Roughly 100 KB worth of content.
    actors: dict[str, Any] = {
        "metadata": {"system": "dnd5e_2024", "system_version": "0.1.0"},
        "actors": [
            {
                "name": f"actor_{i}",
                "count": 1,
                "clumping": 1,
                "definitions": {
                    f"def_{j}": {"type": "damage", "damage_type": "fire", "amount": "1d6"}
                    for j in range(10)
                },
            }
            for i in range(500)
        ],
    }
    ctx = _ctx(tmp_path)
    try:
        sha = store_file(ctx, actors, "big.yaml")
        row = ctx.sqlite.execute(select(ActorFile)).scalar_one()
        assert row.sha256 == sha
        assert row.content_json == actors
    finally:
        close_context(ctx, success=True)


# --- remote-mode mirroring --------------------------------------------------


def test_remote_mode_stores_in_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx_remote(tmp_path, monkeypatch)
    try:
        sha = store_file(ctx, {"a": 1}, "f.yaml")
        sqlite_rows = ctx.sqlite.execute(select(ActorFile)).scalars().all()
        assert ctx.postgres is not None
        remote_rows = ctx.postgres.execute(select(ActorFile)).scalars().all()
        assert len(sqlite_rows) == len(remote_rows) == 1
        assert sqlite_rows[0].sha256 == remote_rows[0].sha256 == sha
    finally:
        close_context(ctx, success=True)


# --- dialect dispatch (unit) ------------------------------------------------


def test_upsert_stmt_postgres_branch_uses_pg_insert() -> None:
    """Direct unit test of the postgres dialect branch."""
    from sqlalchemy.dialects.postgresql.dml import Insert as PGInsert

    from enar_montecarlo.persistence.files import _upsert_stmt

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _FakeSession:
        def get_bind(self) -> _Bind:
            return _Bind()

    stmt = _upsert_stmt(_FakeSession(), "abc", "f.yaml", {})  # type: ignore[arg-type]
    assert isinstance(stmt, PGInsert)
