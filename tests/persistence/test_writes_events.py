"""Tests for event writes (write_event + write_events_bulk)."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from enar_montecarlo.events import (
    EffectEvent,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)
from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.schema import Effect, Resolution
from enar_montecarlo.persistence.sessions import (
    PersistenceContext,
    close_context,
    create_context,
)
from enar_montecarlo.persistence.values import (
    make_persist_fn,
    seed_framework_defaults,
)
from enar_montecarlo.persistence.writes import (
    create_run_row,
    write_event,
    write_events_bulk,
)

# --- fixtures ---------------------------------------------------------------


def _setup(tmp_path: Path) -> tuple[PersistenceContext, UUID, str, dict[str, int]]:
    """Create context + actor files + run row + seeded values.

    Returns (ctx, run_id, attacker_file_id, value_ids).
    """
    ctx = create_context(run_id=uuid4(), postgres_url=None, output_dir=tmp_path)
    a = store_file(ctx, {"role": "attacker"}, "attackers.yaml")
    d = store_file(ctx, {"role": "defender"}, "defenders.yaml")
    seed_framework_defaults(ctx)
    persist = make_persist_fn(ctx)
    value_ids = {
        "outcome.miss": persist("outcome", "miss"),
        "outcome.hit": persist("outcome", "hit"),
        "damage_type.fire": persist("damage_type", "fire"),
        "branch.success": persist("branch", "success"),
        "effect_type.damage": persist("effect_type", "damage"),
    }
    run_id = uuid4()
    create_run_row(
        ctx,
        run_id=run_id,
        sim_name="x",
        sim_version="0.1.0",
        system_name="y",
        system_version="0.1.0",
        seed=1,
        iterations_planned=10,
        attacker_file_id=a,
        defender_file_id=d,
        cli_args={},
    )
    return ctx, run_id, a, value_ids


def _setup_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[PersistenceContext, UUID, str, dict[str, int]]:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    pg_url = f"sqlite:///{tmp_path / 'remote.db'}"
    ctx = create_context(run_id=uuid4(), postgres_url=pg_url, output_dir=tmp_path)
    a = store_file(ctx, {"role": "attacker"}, "a.yaml")
    d = store_file(ctx, {"role": "defender"}, "d.yaml")
    seed_framework_defaults(ctx)
    persist = make_persist_fn(ctx)
    value_ids = {
        "outcome.miss": persist("outcome", "miss"),
        "branch.success": persist("branch", "success"),
        "effect_type.damage": persist("effect_type", "damage"),
    }
    run_id = uuid4()
    create_run_row(
        ctx,
        run_id=run_id,
        sim_name="x",
        sim_version="0.1.0",
        system_name="y",
        system_version="0.1.0",
        seed=1,
        iterations_planned=10,
        attacker_file_id=a,
        defender_file_id=d,
        cli_args={},
    )
    return ctx, run_id, a, value_ids


# --- write_event: resolutions -----------------------------------------------


def test_write_resolution_event(tmp_path: Path) -> None:
    ctx, run_id, a, vids = _setup(tmp_path)
    try:
        ev = ResolutionEvent(
            event_seq=1,
            iteration_num=0,
            actor_file_id=a,
            actor_index=0,
            resolution_name="dagger",
            outcome_id=vids["outcome.hit"],
            notes={"roll": 17},
        )
        write_event(ctx, run_id=run_id, event=ev)
        row = ctx.sqlite.execute(select(Resolution)).scalar_one()
        assert row.resolution_name == "dagger"
        assert row.outcome_id == vids["outcome.hit"]
        assert row.notes == {"roll": 17}
        assert row.event_seq == 1
    finally:
        close_context(ctx, success=True)


def test_write_effect_event(tmp_path: Path) -> None:
    ctx, run_id, a, vids = _setup(tmp_path)
    try:
        ev = EffectEvent(
            event_seq=2,
            iteration_num=0,
            actor_file_id=a,
            actor_index=0,
            effect_definition_name="piercing_damage",
            effect_type_id=vids["effect_type.damage"],
            damage_type_id=vids["damage_type.fire"],
            amount=6.5,
            source_branch_id=vids["branch.success"],
            caused_by_seq=1,
        )
        write_event(ctx, run_id=run_id, event=ev)
        row = ctx.sqlite.execute(select(Effect)).scalar_one()
        assert row.effect_definition_name == "piercing_damage"
        assert row.amount == 6.5
        assert row.caused_by_seq == 1
    finally:
        close_context(ctx, success=True)


# --- markers do not persist --------------------------------------------------


def test_round_complete_marker_does_not_persist(tmp_path: Path) -> None:
    ctx, run_id, _a, _vids = _setup(tmp_path)
    try:
        write_event(
            ctx,
            run_id=run_id,
            event=RoundCompleteMarker(event_seq=10, iteration_num=0, round_num=1),
        )
        assert ctx.sqlite.execute(select(Resolution)).all() == []
        assert ctx.sqlite.execute(select(Effect)).all() == []
    finally:
        close_context(ctx, success=True)


def test_sim_complete_marker_does_not_persist(tmp_path: Path) -> None:
    ctx, run_id, _a, _vids = _setup(tmp_path)
    try:
        write_event(
            ctx,
            run_id=run_id,
            event=SimulationCompleteMarker(
                event_seq=99, iteration_num=0, rounds_executed=3
            ),
        )
        assert ctx.sqlite.execute(select(Resolution)).all() == []
        assert ctx.sqlite.execute(select(Effect)).all() == []
    finally:
        close_context(ctx, success=True)


# --- FK enforcement ----------------------------------------------------------


def test_unknown_outcome_id_raises_integrity_error(tmp_path: Path) -> None:
    ctx, run_id, a, _vids = _setup(tmp_path)
    try:
        ev = ResolutionEvent(
            event_seq=1,
            iteration_num=0,
            actor_file_id=a,
            actor_index=0,
            resolution_name="dagger",
            outcome_id=99999,  # not in values
        )
        with pytest.raises(IntegrityError):
            write_event(ctx, run_id=run_id, event=ev)
    finally:
        close_context(ctx, success=False)


# --- bulk write -------------------------------------------------------------


def test_bulk_write_inserts_resolutions_and_effects_skips_markers(
    tmp_path: Path,
) -> None:
    ctx, run_id, a, vids = _setup(tmp_path)
    try:
        events = [
            ResolutionEvent(
                event_seq=1,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                resolution_name="dagger",
                outcome_id=vids["outcome.miss"],
            ),
            EffectEvent(
                event_seq=2,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                effect_definition_name="dmg",
                effect_type_id=vids["effect_type.damage"],
                source_branch_id=vids["branch.success"],
                caused_by_seq=1,
            ),
            RoundCompleteMarker(event_seq=3, iteration_num=0, round_num=1),
            SimulationCompleteMarker(event_seq=4, iteration_num=0, rounds_executed=1),
        ]
        write_events_bulk(ctx, run_id=run_id, events=events)
        assert len(ctx.sqlite.execute(select(Resolution)).all()) == 1
        assert len(ctx.sqlite.execute(select(Effect)).all()) == 1
    finally:
        close_context(ctx, success=True)


def test_bulk_write_rolls_back_on_fk_violation(tmp_path: Path) -> None:
    ctx, run_id, a, vids = _setup(tmp_path)
    try:
        events = [
            ResolutionEvent(
                event_seq=1,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                resolution_name="ok",
                outcome_id=vids["outcome.miss"],
            ),
            ResolutionEvent(
                event_seq=2,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                resolution_name="bad",
                outcome_id=99999,
            ),
        ]
        with pytest.raises(IntegrityError):
            write_events_bulk(ctx, run_id=run_id, events=events)
        ctx.sqlite.rollback()
        # Atomic batch: neither row was committed.
        assert ctx.sqlite.execute(select(Resolution)).all() == []
    finally:
        close_context(ctx, success=False)


# --- remote-mode parity -----------------------------------------------------


def test_remote_mode_write_event_resolution_to_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, run_id, a, vids = _setup_remote(tmp_path, monkeypatch)
    try:
        write_event(
            ctx,
            run_id=run_id,
            event=ResolutionEvent(
                event_seq=1,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                resolution_name="dagger",
                outcome_id=vids["outcome.miss"],
            ),
        )
        assert ctx.postgres is not None
        assert len(ctx.sqlite.execute(select(Resolution)).all()) == 1
        assert len(ctx.postgres.execute(select(Resolution)).all()) == 1
    finally:
        close_context(ctx, success=True)


def test_remote_mode_write_event_effect_to_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, run_id, a, vids = _setup_remote(tmp_path, monkeypatch)
    try:
        write_event(
            ctx,
            run_id=run_id,
            event=EffectEvent(
                event_seq=1,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                effect_definition_name="dmg",
                effect_type_id=vids["effect_type.damage"],
                source_branch_id=vids["branch.success"],
                caused_by_seq=1,
            ),
        )
        assert ctx.postgres is not None
        assert len(ctx.sqlite.execute(select(Effect)).all()) == 1
        assert len(ctx.postgres.execute(select(Effect)).all()) == 1
    finally:
        close_context(ctx, success=True)


def test_remote_mode_bulk_write_to_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, run_id, a, vids = _setup_remote(tmp_path, monkeypatch)
    try:
        events = [
            ResolutionEvent(
                event_seq=1,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                resolution_name="dagger",
                outcome_id=vids["outcome.miss"],
            ),
            EffectEvent(
                event_seq=2,
                iteration_num=0,
                actor_file_id=a,
                actor_index=0,
                effect_definition_name="dmg",
                effect_type_id=vids["effect_type.damage"],
                source_branch_id=vids["branch.success"],
                caused_by_seq=1,
            ),
            RoundCompleteMarker(event_seq=3, iteration_num=0, round_num=1),
        ]
        write_events_bulk(ctx, run_id=run_id, events=events)
        assert ctx.postgres is not None
        assert len(ctx.sqlite.execute(select(Resolution)).all()) == 1
        assert len(ctx.sqlite.execute(select(Effect)).all()) == 1
        assert len(ctx.postgres.execute(select(Resolution)).all()) == 1
        assert len(ctx.postgres.execute(select(Effect)).all()) == 1
    finally:
        close_context(ctx, success=True)
