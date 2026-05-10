"""Persistence-context lifecycle: create / close SQLite + optional Postgres.

Postgres-mode (``postgres_url`` given) writes the working SQLite to
the OS temp dir so a crash leaves a recoverable file at a predictable
path. SQLite-only mode writes the working SQLite to ``output_dir`` and
treats the file itself as the run artifact.
"""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from enar_montecarlo.persistence.schema import (
    V_EVENTS_CREATE,
    V_EVENTS_DROP,
    Base,
)


@dataclass
class PersistenceContext:
    sqlite: Session
    postgres: Session | None
    sqlite_path: Path
    is_temp: bool
    sqlite_engine: Engine
    postgres_engine: Engine | None


def _default_temp_dir() -> Path:
    """Indirection so tests can monkeypatch the temp dir location."""
    return Path(tempfile.gettempdir())


def _make_sqlite(path: Path) -> tuple[Engine, Session]:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")

    # FK enforcement is off on SQLite by default and is per-connection;
    # the listener applies it to every connection drawn from the pool.
    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn: Any, _conn_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    _ensure_v_events_view(engine)
    return engine, Session(engine)


def _make_remote(url: str) -> tuple[Engine, Session]:
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    _ensure_v_events_view(engine)
    return engine, Session(engine)


def _ensure_v_events_view(engine: Engine) -> None:
    """(Re)create the v_events view. Idempotent across re-runs.

    Drop-then-create rather than ``CREATE VIEW IF NOT EXISTS`` (SQLite-only)
    or ``CREATE OR REPLACE VIEW`` (Postgres-only); the pair below works
    on both backends without dialect dispatch.
    """
    with engine.begin() as conn:
        conn.execute(text(V_EVENTS_DROP))
        conn.execute(text(V_EVENTS_CREATE))


def create_context(
    *,
    run_id: UUID,
    postgres_url: str | None,
    output_dir: Path,
) -> PersistenceContext:
    """Open the working SQLite (and optional Postgres) for a run.

    Schema is created on both backends if they don't already have it.
    Returns a context the driver passes to every persistence call.
    """
    is_temp = postgres_url is not None
    sqlite_path = (
        _default_temp_dir() / f"{run_id}.db" if is_temp else output_dir / f"{run_id}.db"
    )
    sqlite_engine, sqlite_session = _make_sqlite(sqlite_path)
    if postgres_url is not None:
        pg_engine, pg_session = _make_remote(postgres_url)
    else:
        pg_engine = None
        pg_session = None
    return PersistenceContext(
        sqlite=sqlite_session,
        postgres=pg_session,
        sqlite_path=sqlite_path,
        is_temp=is_temp,
        sqlite_engine=sqlite_engine,
        postgres_engine=pg_engine,
    )


def close_context(ctx: PersistenceContext, *, success: bool) -> None:
    """Close sessions and engines; delete the SQLite file iff temp + success.

    On failure (``success=False``) in temp mode the SQLite file is kept
    so ``sync`` can replay it into Postgres later (DESIGN section 9.3).
    """
    ctx.sqlite.close()
    ctx.sqlite_engine.dispose()
    if ctx.postgres is not None:
        ctx.postgres.close()
    if ctx.postgres_engine is not None:
        ctx.postgres_engine.dispose()
    if ctx.is_temp and success and ctx.sqlite_path.exists():
        os.remove(ctx.sqlite_path)
