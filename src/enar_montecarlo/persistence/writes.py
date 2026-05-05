"""Run-row and event writes."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update

from enar_montecarlo.events import EffectEvent, Event, ResolutionEvent
from enar_montecarlo.persistence.schema import Effect, Resolution, Run
from enar_montecarlo.persistence.sessions import PersistenceContext


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --- run rows ----------------------------------------------------------------


def create_run_row(
    ctx: PersistenceContext,
    *,
    run_id: UUID,
    sim_name: str,
    sim_version: str,
    system_name: str,
    system_version: str,
    seed: int,
    iterations_planned: int,
    attacker_file_id: str,
    defender_file_id: str,
    cli_args: dict[str, Any],
) -> None:
    """Insert the runs row at the start of execute_run.

    ``iterations_completed`` starts at 0; ``completed_at`` and
    ``terminated_reason`` are null until the run finishes.
    """
    payload: dict[str, Any] = {
        "run_id": run_id,
        "sim_name": sim_name,
        "sim_version": sim_version,
        "system_name": system_name,
        "system_version": system_version,
        "seed": seed,
        "iterations_planned": iterations_planned,
        "iterations_completed": 0,
        "attacker_file_id": attacker_file_id,
        "defender_file_id": defender_file_id,
        "started_at": _now_utc_naive(),
        "completed_at": None,
        "cli_args": cli_args,
        "terminated_reason": None,
    }
    ctx.sqlite.add(Run(**payload))
    ctx.sqlite.commit()
    if ctx.postgres is not None:
        ctx.postgres.add(Run(**payload))
        ctx.postgres.commit()


def update_run_completion(
    ctx: PersistenceContext,
    *,
    run_id: UUID,
    iterations_completed: int,
    terminated_reason: str,
) -> None:
    """Mark the runs row complete with final state.

    ``terminated_reason`` is one of ``success``, ``error``,
    ``interrupted`` (DESIGN section 8.1).
    """
    completed_at = _now_utc_naive()
    stmt = (
        update(Run)
        .where(Run.run_id == run_id)
        .values(
            iterations_completed=iterations_completed,
            completed_at=completed_at,
            terminated_reason=terminated_reason,
        )
    )
    ctx.sqlite.execute(stmt)
    ctx.sqlite.commit()
    if ctx.postgres is not None:
        ctx.postgres.execute(stmt)
        ctx.postgres.commit()


# --- events ------------------------------------------------------------------


def _resolution_row(run_id: UUID, ev: ResolutionEvent) -> Resolution:
    return Resolution(
        run_id=run_id,
        iteration_num=ev.iteration_num,
        round_num=ev.round_num,
        event_seq=ev.event_seq,
        actor_file_id=ev.actor_file_id,
        actor_index=ev.actor_index,
        target_file_id=ev.target_file_id,
        target_index=ev.target_index,
        resolution_name=ev.resolution_name,
        outcome_id=ev.outcome_id,
        caused_by_seq=ev.caused_by_seq,
        notes=ev.notes,
    )


def _effect_row(run_id: UUID, ev: EffectEvent) -> Effect:
    return Effect(
        run_id=run_id,
        iteration_num=ev.iteration_num,
        round_num=ev.round_num,
        event_seq=ev.event_seq,
        actor_file_id=ev.actor_file_id,
        actor_index=ev.actor_index,
        target_file_id=ev.target_file_id,
        target_index=ev.target_index,
        effect_definition_name=ev.effect_definition_name,
        effect_type_id=ev.effect_type_id,
        damage_type_id=ev.damage_type_id,
        amount=ev.amount,
        source_branch_id=ev.source_branch_id,
        caused_by_seq=ev.caused_by_seq,
        trigger_name=ev.trigger_name,
        trigger_result=ev.trigger_result,
        notes=ev.notes,
    )


def write_event(ctx: PersistenceContext, *, run_id: UUID, event: Event) -> None:
    """Write a single event. Markers (round_complete / sim_complete) are
    no-ops at the DB layer (they are progress signals only)."""
    if isinstance(event, ResolutionEvent):
        ctx.sqlite.add(_resolution_row(run_id, event))
        ctx.sqlite.commit()
        if ctx.postgres is not None:
            ctx.postgres.add(_resolution_row(run_id, event))
            ctx.postgres.commit()
    elif isinstance(event, EffectEvent):
        ctx.sqlite.add(_effect_row(run_id, event))
        ctx.sqlite.commit()
        if ctx.postgres is not None:
            ctx.postgres.add(_effect_row(run_id, event))
            ctx.postgres.commit()
    # Markers are not persisted.


def write_events_bulk(
    ctx: PersistenceContext,
    *,
    run_id: UUID,
    events: Iterable[Event],
) -> None:
    """Write a batch of events in a single transaction per backend.

    Markers in ``events`` are skipped silently; if any persisted row
    violates a constraint, the entire batch rolls back.
    """
    sqlite_rows: list[Resolution | Effect] = []
    pg_rows: list[Resolution | Effect] = []
    for event in events:
        if isinstance(event, ResolutionEvent):
            sqlite_rows.append(_resolution_row(run_id, event))
            if ctx.postgres is not None:
                pg_rows.append(_resolution_row(run_id, event))
        elif isinstance(event, EffectEvent):
            sqlite_rows.append(_effect_row(run_id, event))
            if ctx.postgres is not None:
                pg_rows.append(_effect_row(run_id, event))
        # Markers ignored.
    ctx.sqlite.add_all(sqlite_rows)
    ctx.sqlite.commit()
    if ctx.postgres is not None:
        ctx.postgres.add_all(pg_rows)
        ctx.postgres.commit()
