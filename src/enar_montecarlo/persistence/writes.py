"""Run-row and event writes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update

from enar_montecarlo.persistence.schema import Run
from enar_montecarlo.persistence.sessions import PersistenceContext


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
