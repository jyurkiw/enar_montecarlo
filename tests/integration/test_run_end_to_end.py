"""End-to-end: drive echo_sim through execute_run and assert row state.

This is the canonical "does the whole pipeline work?" test for the
framework. Per the plan: 5 iterations, 6 persisted rows per iteration
(2 resolutions, 4 effects -- markers do not persist), exact content
checks on caused_by_seq chains and the custom-effect notes payload,
all FKs resolve.
"""

import sys
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Ensure the echo_sim fixture is importable.
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(_FIXTURES_DIR))

import echo_sim  # noqa: E402

from enar_montecarlo.lifecycle import RunArgs, execute_run  # noqa: E402
from enar_montecarlo.persistence.schema import (  # noqa: E402
    ActorFile,
    Effect,
    Resolution,
    Run,
    Value,
)
from tests.smoke.test_post_run_db import (  # noqa: E402
    assert_post_run_invariants,
)


@pytest.fixture
def run_id_and_db(tmp_path: Path) -> tuple[UUID, Path]:
    """Run echo_sim end-to-end and return (run_id, sqlite_path)."""
    out_dir = tmp_path / "runs"
    args = RunArgs(
        sim_module=echo_sim,
        attackers_path=_FIXTURES_DIR / "echo_sim" / "attackers.yaml",
        defenders_path=_FIXTURES_DIR / "echo_sim" / "defenders.yaml",
        iterations=5,
        seed=12345,
        postgres_url=None,
        output_dir=out_dir,
        quiet=True,
    )
    run_id = execute_run(args)
    return run_id, out_dir / f"{run_id}.db"


# --- runs row ---------------------------------------------------------------


def test_run_row_complete_and_successful(run_id_and_db: tuple[UUID, Path]) -> None:
    run_id, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        row = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.iterations_planned == 5
        assert row.iterations_completed == 5
        assert row.terminated_reason == "success"
        assert row.completed_at is not None
        assert row.sim_name == "echo_sim"
        assert row.system_name == "echo_system"
    eng.dispose()


# --- exact row counts -------------------------------------------------------


def test_resolutions_row_count_is_two_per_iteration(
    run_id_and_db: tuple[UUID, Path],
) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        rows = sess.execute(select(Resolution)).scalars().all()
        assert len(rows) == 10  # 2 per iter * 5 iters
    eng.dispose()


def test_effects_row_count_is_four_per_iteration(
    run_id_and_db: tuple[UUID, Path],
) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        rows = sess.execute(select(Effect)).scalars().all()
        assert len(rows) == 20  # 4 per iter * 5 iters
    eng.dispose()


def test_markers_do_not_persist(run_id_and_db: tuple[UUID, Path]) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        # Total persisted = 10 resolutions + 20 effects = 30. echo_sim
        # yields 8 events per iteration (40 over 5 iters); 10 of those
        # are markers and must not persist.
        total = len(sess.execute(select(Resolution)).all()) + len(
            sess.execute(select(Effect)).all()
        )
        assert total == 30
    eng.dispose()


# --- causal chains ----------------------------------------------------------


def test_caused_by_seq_chains_resolve(run_id_and_db: tuple[UUID, Path]) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        # In every iteration: fail-resolution (event_seq=4) is caused by
        # pass-resolution (event_seq=1). Verify the chain holds across
        # all 5 iterations.
        for it in range(5):
            fail_res = sess.execute(
                select(Resolution).where(
                    Resolution.iteration_num == it,
                    Resolution.resolution_name == "echo_fail",
                )
            ).scalar_one()
            assert fail_res.caused_by_seq == 1

            # Effect on fail branch (event_seq=5) is caused by event 4.
            fail_eff = sess.execute(
                select(Effect).where(
                    Effect.iteration_num == it,
                    Effect.effect_definition_name == "fail_recoil",
                )
            ).scalar_one()
            assert fail_eff.caused_by_seq == 4

            # Effects on pass branch (event_seq=2,3) and custom (6) are
            # caused by event 1.
            pass_effects = sess.execute(
                select(Effect).where(
                    Effect.iteration_num == it,
                    Effect.effect_definition_name.in_(
                        ["pass_damage", "pass_sneak_bonus", "echo_custom_marker"]
                    ),
                )
            ).scalars().all()
            assert len(pass_effects) == 3
            for eff in pass_effects:
                assert eff.caused_by_seq == 1
    eng.dispose()


# --- custom-effect notes payload --------------------------------------------


def test_custom_effect_notes_payload_present(
    run_id_and_db: tuple[UUID, Path],
) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        custom_effects = sess.execute(
            select(Effect).where(Effect.effect_definition_name == "echo_custom_marker")
        ).scalars().all()
        assert len(custom_effects) == 5  # one per iter
        for it, eff in enumerate(
            sorted(custom_effects, key=lambda e: e.iteration_num)
        ):
            assert eff.notes == {"system_extra": "echo", "iter": it}
    eng.dispose()


# --- trigger gating recorded in DB ------------------------------------------


def test_trigger_gated_effect_records_failure_when_sneaky_unset(
    run_id_and_db: tuple[UUID, Path],
) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        gated = sess.execute(
            select(Effect).where(Effect.effect_definition_name == "pass_sneak_bonus")
        ).scalars().all()
        assert len(gated) == 5
        # No --sneaky in extra_args -> trigger_result False, amount None
        # (DESIGN section 5.5: "an effect row is still emitted with
        # amount=null and trigger_result=false").
        for eff in gated:
            assert eff.trigger_name == "sneak_attack_eligible"
            assert eff.trigger_result is False
            assert eff.amount is None
    eng.dispose()


# --- FK integrity -----------------------------------------------------------


def test_all_actor_file_fks_resolve(run_id_and_db: tuple[UUID, Path]) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        sha_set = {
            af.sha256 for af in sess.execute(select(ActorFile)).scalars().all()
        }
        # Every resolution and effect references an existing actor file.
        for r in sess.execute(select(Resolution)).scalars().all():
            assert r.actor_file_id in sha_set
            if r.target_file_id is not None:
                assert r.target_file_id in sha_set
        for e in sess.execute(select(Effect)).scalars().all():
            assert e.actor_file_id in sha_set
            if e.target_file_id is not None:
                assert e.target_file_id in sha_set
    eng.dispose()


def test_all_value_id_fks_resolve(run_id_and_db: tuple[UUID, Path]) -> None:
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        value_ids = {
            v.id for v in sess.execute(select(Value)).scalars().all()
        }
        for r in sess.execute(select(Resolution)).scalars().all():
            assert r.outcome_id in value_ids
        for e in sess.execute(select(Effect)).scalars().all():
            assert e.effect_type_id in value_ids
            assert e.source_branch_id in value_ids
            if e.damage_type_id is not None:
                assert e.damage_type_id in value_ids
    eng.dispose()


# --- extra_args carries through to gated effects ---------------------------


def test_sneaky_flag_via_extra_args_fires_trigger(tmp_path: Path) -> None:
    """Re-run with ``sneaky=True`` and confirm the gated effect fires."""
    out_dir = tmp_path / "runs"
    args = RunArgs(
        sim_module=echo_sim,
        attackers_path=_FIXTURES_DIR / "echo_sim" / "attackers.yaml",
        defenders_path=_FIXTURES_DIR / "echo_sim" / "defenders.yaml",
        iterations=2,
        seed=1,
        postgres_url=None,
        output_dir=out_dir,
        quiet=True,
        extra_args={"sneaky": True},
    )
    run_id = execute_run(args)
    eng = create_engine(f"sqlite:///{out_dir / f'{run_id}.db'}")
    with Session(eng) as sess:
        gated = sess.execute(
            select(Effect).where(Effect.effect_definition_name == "pass_sneak_bonus")
        ).scalars().all()
        for eff in gated:
            assert eff.trigger_result is True
            assert eff.amount == 2.0
    eng.dispose()


# --- exact event_seq layout per iteration ----------------------------------


def test_smoke_invariants_pass_on_e2e_run(
    run_id_and_db: tuple[UUID, Path],
) -> None:
    """The post-run smoke helper must pass on every successful e2e run."""
    run_id, db_path = run_id_and_db
    assert_post_run_invariants(db_path, run_id)


def test_event_seq_layout_per_iteration(run_id_and_db: tuple[UUID, Path]) -> None:
    """Both resolutions land at seq 1 and 4; effects at seq 2, 3, 5, 6."""
    _, db_path = run_id_and_db
    eng = create_engine(f"sqlite:///{db_path}")
    with Session(eng) as sess:
        for it in range(5):
            res_seqs = sorted(
                sess.execute(
                    select(Resolution.event_seq).where(
                        Resolution.iteration_num == it
                    )
                )
                .scalars()
                .all()
            )
            assert res_seqs == [1, 4]
            eff_seqs = sorted(
                sess.execute(
                    select(Effect.event_seq).where(Effect.iteration_num == it)
                )
                .scalars()
                .all()
            )
            assert eff_seqs == [2, 3, 5, 6]
    eng.dispose()
