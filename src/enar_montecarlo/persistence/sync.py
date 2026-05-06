"""SQLite -> Postgres bulk copy.

Copies all rows from a working SQLite into the configured remote
database, in FK-dependency order, with ``ON CONFLICT DO NOTHING`` on
each PK so the operation is idempotent at the DB level (re-running
sync on the same SQLite file produces no duplicates).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Session

from enar_montecarlo.persistence.schema import (
    ActorFile,
    Base,
    Effect,
    Resolution,
    Run,
    Value,
)

# FK-dependency order: parents first.
_TABLES_IN_ORDER: tuple[type[DeclarativeBase], ...] = (
    ActorFile,
    Value,
    Run,
    Resolution,
    Effect,
)

_PK_COLUMNS: dict[type[DeclarativeBase], list[str]] = {
    ActorFile: ["sha256"],
    Value: ["id"],
    Run: ["run_id"],
    Resolution: ["run_id", "iteration_num", "event_seq"],
    Effect: ["run_id", "iteration_num", "event_seq"],
}


def _bulk_upsert_stmt(
    dst_engine: Engine,
    model: type[DeclarativeBase],
    payloads: Sequence[dict[str, Any]],
    pk_cols: list[str],
) -> Any:
    stmt: Any
    if dst_engine.dialect.name == "postgresql":
        stmt = pg_insert(model).values(list(payloads))
    else:
        stmt = sqlite_insert(model).values(list(payloads))
    return stmt.on_conflict_do_nothing(index_elements=pk_cols)


def sync_to_postgres(*, sqlite_path: Path, postgres_url: str) -> None:
    """Copy all rows from ``sqlite_path`` into ``postgres_url``.

    Schema is created in the destination if it does not already exist.
    Tables are copied in FK-dependency order; each insert uses ON
    CONFLICT DO NOTHING on the table's PK so re-runs do not duplicate.
    Original IDs and ``(iteration_num, event_seq)`` ordering are
    preserved -- causal queries against the destination produce the
    same results as against the source.
    """
    src_engine = create_engine(f"sqlite:///{sqlite_path}")
    dst_engine = create_engine(postgres_url)
    Base.metadata.create_all(dst_engine)
    try:
        with Session(src_engine) as src, Session(dst_engine) as dst:
            for model in _TABLES_IN_ORDER:
                pk_cols = _PK_COLUMNS[model]
                rows = src.execute(select(model)).scalars().all()
                if not rows:
                    continue
                payloads: list[dict[str, Any]] = [
                    {c.name: getattr(r, c.name) for c in model.__table__.columns}
                    for r in rows
                ]
                dst.execute(_bulk_upsert_stmt(dst_engine, model, payloads, pk_cols))
            dst.commit()
    finally:
        src_engine.dispose()
        dst_engine.dispose()
