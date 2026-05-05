"""Values-table seeding and the persist callable for RegistryBuilder.

When a remote (Postgres) session is present it is the source of truth
for IDs; the working SQLite mirrors each row with the same ID.
``INSERT ... ON CONFLICT (category, value) DO NOTHING`` is used in both
backends so registrations are idempotent at the DB layer.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from enar_montecarlo.persistence.schema import Value
from enar_montecarlo.persistence.sessions import PersistenceContext
from enar_montecarlo.registry import PersistFn

FRAMEWORK_EFFECT_TYPES: tuple[str, ...] = ("damage", "condition", "resource", "custom")
"""Effect-type values registered automatically (DESIGN section 6.4)."""

FRAMEWORK_BRANCHES: tuple[str, ...] = ("always",)
"""Branch values registered automatically; system outcomes added later."""


def _upsert_stmt(
    session: Session,
    category: str,
    value: str,
    *,
    with_id: int | None = None,
) -> Any:
    dialect = session.get_bind().dialect.name
    payload: dict[str, Any] = {"category": category, "value": value}
    if with_id is not None:
        payload["id"] = with_id
    stmt: Any
    if dialect == "postgresql":
        stmt = pg_insert(Value).values(**payload)
    else:
        stmt = sqlite_insert(Value).values(**payload)
    return stmt.on_conflict_do_nothing(index_elements=["category", "value"])


def _select_id(session: Session, category: str, value: str) -> int:
    return session.execute(
        select(Value.id).where(Value.category == category, Value.value == value)
    ).scalar_one()


def _upsert_value(ctx: PersistenceContext, category: str, value: str) -> int:
    """Insert ``(category, value)`` and return the canonical ID.

    With a remote present, the remote assigns the ID; SQLite mirrors
    that ID. Without a remote, SQLite's autoincrement assigns it.
    """
    if ctx.postgres is not None:
        ctx.postgres.execute(_upsert_stmt(ctx.postgres, category, value))
        ctx.postgres.commit()
        canonical_id = _select_id(ctx.postgres, category, value)
        ctx.sqlite.execute(
            _upsert_stmt(ctx.sqlite, category, value, with_id=canonical_id)
        )
        ctx.sqlite.commit()
        return canonical_id
    ctx.sqlite.execute(_upsert_stmt(ctx.sqlite, category, value))
    ctx.sqlite.commit()
    return _select_id(ctx.sqlite, category, value)


def seed_framework_defaults(ctx: PersistenceContext) -> None:
    """Insert framework-known values. Idempotent across re-invocations."""
    for et in FRAMEWORK_EFFECT_TYPES:
        _upsert_value(ctx, "effect_type", et)
    for br in FRAMEWORK_BRANCHES:
        _upsert_value(ctx, "branch", br)


def make_persist_fn(ctx: PersistenceContext) -> PersistFn:
    """Return a :data:`PersistFn` bound to ``ctx`` for use with RegistryBuilder."""

    def persist(category: str, value: str) -> int:
        return _upsert_value(ctx, category, value)

    return persist
