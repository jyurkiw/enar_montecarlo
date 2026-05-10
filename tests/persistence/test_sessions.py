"""Tests for persistence-context lifecycle.

Real Postgres connectivity is gated behind POSTGRES_TEST_URL. Path /
file-deletion logic is exercised here using a sqlite:// URL as a
stand-in for the "remote" backend, which is sufficient because that
logic depends only on whether postgres_url is None, not on the
specific dialect.
"""

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.schema import Value
from enar_montecarlo.persistence.sessions import close_context, create_context


def test_default_temp_dir_returns_real_tempfile_location() -> None:
    # Direct call so coverage hits the un-monkeypatched body.
    assert sess_mod._default_temp_dir() == Path(tempfile.gettempdir())

# --- SQLite-only mode --------------------------------------------------------


def test_sqlite_only_writes_to_output_dir(tmp_path: Path) -> None:
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=None, output_dir=tmp_path)
    try:
        assert ctx.sqlite_path == tmp_path / f"{run_id}.db"
        assert ctx.sqlite_path.exists()
        assert not ctx.is_temp
        assert ctx.postgres is None
        assert ctx.postgres_engine is None
    finally:
        close_context(ctx, success=True)


def test_sqlite_only_close_keeps_file(tmp_path: Path) -> None:
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=None, output_dir=tmp_path)
    sqlite_path = ctx.sqlite_path
    close_context(ctx, success=True)
    # Non-temp files are the artifact; never deleted on close.
    assert sqlite_path.exists()


def test_sqlite_only_create_then_use_session(tmp_path: Path) -> None:
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=None, output_dir=tmp_path)
    try:
        ctx.sqlite.add(Value(category="outcome", value="hit"))
        ctx.sqlite.commit()
        rows = ctx.sqlite.execute(select(Value)).scalars().all()
        assert len(rows) == 1
    finally:
        close_context(ctx, success=True)


def test_sqlite_only_creates_missing_output_dir(tmp_path: Path) -> None:
    deeper = tmp_path / "runs" / "nested"
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=None, output_dir=deeper)
    try:
        assert deeper.exists()
        assert ctx.sqlite_path.parent == deeper
    finally:
        close_context(ctx, success=True)


# --- Postgres mode (using a sqlite:// URL stand-in) -------------------------


def test_temp_mode_writes_sqlite_to_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    run_id = uuid4()
    ctx = create_context(run_id=run_id, postgres_url=pg_url, output_dir=tmp_path)
    try:
        assert ctx.is_temp
        assert ctx.sqlite_path == tmp_path / f"{run_id}.db"
        assert ctx.sqlite_path.exists()
        assert ctx.postgres is not None
        assert ctx.postgres_engine is not None
    finally:
        close_context(ctx, success=True)


def test_temp_mode_close_with_success_deletes_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    ctx = create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)
    sqlite_path = ctx.sqlite_path
    assert sqlite_path.exists()
    close_context(ctx, success=True)
    assert not sqlite_path.exists()


def test_temp_mode_close_with_failure_keeps_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    ctx = create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)
    sqlite_path = ctx.sqlite_path
    close_context(ctx, success=False)
    # Failure must leave the SQLite for sync-replay (DESIGN section 9.3).
    assert sqlite_path.exists()


def test_temp_mode_close_when_file_missing_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On Windows the SQLite engine holds the file handle until dispose, so
    # we simulate "file vanished" via monkeypatching exists() rather than
    # deleting it pre-close.
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    ctx = create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)
    sqlite_path = ctx.sqlite_path
    # Pretend the file does not exist; close_context must not raise.
    monkeypatch.setattr(Path, "exists", lambda self: False)
    close_context(ctx, success=True)
    # File still actually exists on disk because we lied about exists().
    monkeypatch.undo()
    if sqlite_path.exists():
        sqlite_path.unlink()


# --- Real Postgres (gated) --------------------------------------------------
#
# The ``postgres_url`` fixture (in conftest.py) skips when
# POSTGRES_TEST_URL is unset, creates the named DB if it does not
# exist, and drops it after the test.


def test_real_postgres_round_trip(tmp_path: Path, postgres_url: str) -> None:
    ctx = create_context(run_id=uuid4(), postgres_url=postgres_url, output_dir=tmp_path)
    try:
        assert ctx.postgres is not None
        ctx.postgres.execute(select(Value))  # smoke
    finally:
        close_context(ctx, success=True)
