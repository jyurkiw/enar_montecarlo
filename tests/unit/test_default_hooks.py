"""Unit tests for the framework's default no-op hooks.

The substitution behavior at the driver level is exercised in
``tests/integration/test_execute_run.py``. These are direct unit
tests of the helpers themselves -- pinning the contract that
``_make_default_setup_once`` registers OUTCOMES and returns a frozen
Registry, and that the per-iteration / teardown_once defaults are
true no-ops.
"""

from typing import Any

from enar_montecarlo.lifecycle import (
    _make_default_setup_once,
    _noop_per_iter,
    _noop_teardown_once,
)
from enar_montecarlo.registry import RegistryBuilder


def _builder() -> RegistryBuilder:
    counter = 0

    def persist(_cat: str, _name: str) -> int:
        nonlocal counter
        counter += 1
        return counter

    return RegistryBuilder(persist=persist)


def test_default_setup_once_registers_outcomes_and_freezes() -> None:
    setup_once = _make_default_setup_once(["success", "failure"])
    builder = _builder()
    registry = setup_once(
        attackers={"actors": []},
        defenders={"actors": []},
        registry_builder=builder,
    )
    assert type(registry).__name__ == "Registry"
    assert registry.outcome == {"success": 1, "failure": 2}


def test_default_setup_once_supports_pf2e_outcome_set() -> None:
    pf2e = ["critical_success", "success", "failure", "critical_failure"]
    setup_once = _make_default_setup_once(pf2e)
    builder = _builder()
    registry = setup_once(
        attackers={},
        defenders={},
        registry_builder=builder,
    )
    assert set(registry.outcome) == set(pf2e)


def test_default_setup_once_accepts_extra_args() -> None:
    setup_once = _make_default_setup_once(["success"])
    builder = _builder()
    # Sim authors might pass arbitrary extra kwargs from the CLI's --
    # arg; the default must accept them silently.
    registry = setup_once(
        attackers={},
        defenders={},
        registry_builder=builder,
        my_flag="value",
        other=42,
    )
    assert registry.outcome == {"success": 1}


def test_noop_per_iter_returns_none_and_takes_extra_args() -> None:
    assert _noop_per_iter(registry=object(), iteration_num=0) is None
    assert (
        _noop_per_iter(registry=object(), iteration_num=5, my_flag="x", n=3)
        is None
    )


def test_noop_teardown_once_returns_none_and_takes_extra_args() -> None:
    assert _noop_teardown_once(registry=object()) is None
    assert _noop_teardown_once(registry=object(), arbitrary=True) is None


def test_default_setup_once_is_idempotent_on_outcome_re_registration() -> None:
    """If a sim's setup_once also registers the same outcomes, IDs match."""
    setup_once = _make_default_setup_once(["success", "failure"])
    builder = _builder()
    setup_once(attackers={}, defenders={}, registry_builder=builder)
    # Re-registering the same outcomes returns the same IDs (RegistryBuilder
    # idempotency); a second freeze would shadow the first but the framework
    # only freezes once per run.
    assert builder.register("outcome", "success") == 1
    assert builder.register("outcome", "failure") == 2


def test_default_hooks_match_documented_signatures() -> None:
    """Defaults accept the exact kwargs the driver passes."""
    import inspect

    so = _make_default_setup_once(["x"])
    so_sig = inspect.signature(so)
    so_params = set(so_sig.parameters)
    # Driver passes attackers, defenders, registry_builder, plus **extra_args.
    assert {"attackers", "defenders", "registry_builder"}.issubset(so_params)

    pi_sig = inspect.signature(_noop_per_iter)
    pi_params = set(pi_sig.parameters)
    # Driver passes registry, iteration_num, plus **extra_args.
    assert {"registry", "iteration_num"}.issubset(pi_params)

    to_sig = inspect.signature(_noop_teardown_once)
    to_params = set(to_sig.parameters)
    # Driver passes registry, plus **extra_args.
    assert "registry" in to_params


def test_minimal_sim_completes_run_via_defaults(tmp_path: Any) -> None:
    """Acceptance test from P3.4: a sim with only `run` + required constants
    completes a run successfully via the framework-supplied defaults."""
    import types
    from collections.abc import Iterator

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from enar_montecarlo.events import Event, RoundCompleteMarker
    from enar_montecarlo.lifecycle import RunArgs, execute_run
    from enar_montecarlo.persistence.schema import Run

    a = tmp_path / "a.yaml"
    d = tmp_path / "d.yaml"
    a.write_text("metadata: {}\nactors: []\n", encoding="utf-8")
    d.write_text("metadata: {}\nactors: []\n", encoding="utf-8")

    def run_fn(*, iteration_num: int, **_: Any) -> Iterator[Event]:
        yield RoundCompleteMarker(event_seq=1, iteration_num=iteration_num, round_num=1)

    sim = types.ModuleType("minimal")
    sim.run = run_fn
    sim.OUTCOMES = ["success", "failure"]
    sim.SIM_NAME = "minimal"
    sim.SIM_VERSION = "0.1.0"
    sim.SYSTEM_NAME = "system"
    sim.SYSTEM_VERSION = "0.1.0"

    out_dir = tmp_path / "runs"
    args = RunArgs(
        sim_module=sim,
        attackers_path=a,
        defenders_path=d,
        iterations=2,
        seed=1,
        postgres_url=None,
        output_dir=out_dir,
    )
    run_id = execute_run(args)

    eng = create_engine(f"sqlite:///{out_dir / f'{run_id}.db'}")
    with Session(eng) as sess:
        row = sess.execute(select(Run).where(Run.run_id == run_id)).scalar_one()
        assert row.terminated_reason == "success"
        assert row.iterations_completed == 2
    eng.dispose()
