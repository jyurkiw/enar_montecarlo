"""SQLAlchemy ORM schema for the run database.

The same DDL is used in SQLite and Postgres; the few dialect-translatable
types (``Uuid``, ``JSON``) are SQLAlchemy generics so the query layer
works against either backend (DESIGN section 8.2).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models in the persistence layer."""


class ActorFile(Base):
    """Content-addressed actor data file (DESIGN section 8.1).

    The SHA-256 of the canonical-JSON-serialized content is the PK and
    the deduplication key. Two runs using the same file share one row.
    """

    __tablename__ = "actor_files"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Run(Base):
    """One ``run`` invocation. ``run_id`` flows to every event row."""

    __tablename__ = "runs"

    run_id: Mapped[Any] = mapped_column(Uuid, primary_key=True)
    sim_name: Mapped[str] = mapped_column(String, nullable=False)
    sim_version: Mapped[str] = mapped_column(String, nullable=False)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    system_version: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    iterations_planned: Mapped[int] = mapped_column(Integer, nullable=False)
    iterations_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attacker_file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_files.sha256"), nullable=False
    )
    defender_file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_files.sha256"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cli_args: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    terminated_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class Value(Base):
    """Unified enum-like lookup table (DESIGN section 8.1).

    All registry-managed identifiers (outcomes, damage types, effect
    types, etc.) are rows here. ``(category, value)`` is unique;
    inserts use ``INSERT ... ON CONFLICT DO NOTHING; SELECT id``.
    """

    __tablename__ = "values"
    __table_args__ = (UniqueConstraint("category", "value", name="uq_values_category_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)


class Resolution(Base):
    """A resolved test (attack / save / generic test) emitted by a sim."""

    __tablename__ = "resolutions"
    __table_args__ = (
        Index("ix_resolutions_run_iter", "run_id", "iteration_num"),
        Index("ix_resolutions_outcome_id", "outcome_id"),
    )

    run_id: Mapped[Any] = mapped_column(Uuid, ForeignKey("runs.run_id"), primary_key=True)
    iteration_num: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    actor_file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_files.sha256"), nullable=False
    )
    actor_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_file_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("actor_files.sha256"), nullable=True
    )
    target_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_name: Mapped[str] = mapped_column(String, nullable=False)
    outcome_id: Mapped[int] = mapped_column(Integer, ForeignKey("values.id"), nullable=False)
    caused_by_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Effect(Base):
    """A consequence triggered by a resolution branch or a parent effect.

    Shares the ``event_seq`` namespace with ``resolutions`` within a
    single iteration so causal chains via ``caused_by_seq`` are
    unambiguous (DESIGN section 7.2).
    """

    __tablename__ = "effects"
    __table_args__ = (
        Index("ix_effects_run_iter", "run_id", "iteration_num"),
        Index("ix_effects_effect_type_id", "effect_type_id"),
        Index("ix_effects_damage_type_id", "damage_type_id"),
    )

    run_id: Mapped[Any] = mapped_column(Uuid, ForeignKey("runs.run_id"), primary_key=True)
    iteration_num: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    actor_file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_files.sha256"), nullable=False
    )
    actor_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_file_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("actor_files.sha256"), nullable=True
    )
    target_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effect_definition_name: Mapped[str] = mapped_column(String, nullable=False)
    effect_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("values.id"), nullable=False)
    damage_type_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("values.id"), nullable=True
    )
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_branch_id: Mapped[int] = mapped_column(Integer, ForeignKey("values.id"), nullable=False)
    caused_by_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_name: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger_result: Mapped[bool | None] = mapped_column(nullable=True)
    notes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


# --- v_events view ----------------------------------------------------------
#
# UNION ALL of resolutions and effects for chronological replay
# (DESIGN section 7.3). Created as raw SQL after the tables exist.
#
# ``CREATE VIEW IF NOT EXISTS`` is SQLite-only -- Postgres does not
# support that clause. ``CREATE OR REPLACE VIEW`` is Postgres-only.
# The drop-then-create pair below works identically on both backends:
# DROP IF EXISTS is supported in both, and a fresh CREATE always
# succeeds because we just dropped any prior definition.

V_EVENTS_DROP = "DROP VIEW IF EXISTS v_events;"

V_EVENTS_CREATE = """\
CREATE VIEW v_events AS
  SELECT run_id, iteration_num, round_num, event_seq,
         'resolution' AS kind,
         resolution_name AS name,
         caused_by_seq
    FROM resolutions
  UNION ALL
  SELECT run_id, iteration_num, round_num, event_seq,
         'effect',
         effect_definition_name,
         caused_by_seq
    FROM effects;
"""
