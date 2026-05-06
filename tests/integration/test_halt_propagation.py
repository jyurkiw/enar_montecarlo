"""Tests for HaltException pass-through through execute_run.

The framework does not catch HaltException -- that is the eventchain
library's job. This test pins the contract that if it escapes
eventchain into the framework, it propagates out cleanly and the run
row records ``terminated_reason='error'``.
"""

import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from enar_montecarlo.events import Event, RoundCompleteMarker
from enar_montecarlo.halt import HaltException
from enar_montecarlo.lifecycle import RunArgs, execute_run
from enar_montecarlo.persistence.schema import Run


def _minimal_sim(run_fn: Any) -> types.ModuleType:
    m = types.ModuleType("halt_sim")
    m.run = run_fn
    m.OUTCOMES = ["success", "failure"]
    m.SIM_NAME = "halt_sim"
    m.SIM_VERSION = "0.1.0"
    m.SYSTEM_NAME = "system"
    m.SYSTEM_VERSION = "0.1.0"
    return m


def _data_files(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "a.yaml"
    d = tmp_path / "d.yaml"
    a.write_text("metadata: {}\nactors: []\n", encoding="utf-8")
    d.write_text("metadata: {}\nactors: []\n", encoding="utf-8")
    return a, d


def test_halt_in_run_propagates_out_of_execute_run(tmp_path: Path) -> None:
    def run_fn(*, iteration_num: int, **_: Any) -> Iterator[Event]:
        if iteration_num == 1:
            raise HaltException("eventchain didn't catch me")
        yield RoundCompleteMarker(event_seq=1, iteration_num=iteration_num, round_num=1)

    a, d = _data_files(tmp_path)
    args = RunArgs(
        sim_module=_minimal_sim(run_fn),
        attackers_path=a,
        defenders_path=d,
        iterations=5,
        seed=1,
        postgres_url=None,
        output_dir=tmp_path / "runs",
    )

    with pytest.raises(HaltException, match="didn't catch me"):
        execute_run(args)


def test_halt_triggers_error_cleanup_path(tmp_path: Path) -> None:
    def run_fn(*, iteration_num: int, **_: Any) -> Iterator[Event]:
        if iteration_num == 2:
            raise HaltException("halt")
        yield RoundCompleteMarker(event_seq=1, iteration_num=iteration_num, round_num=1)

    a, d = _data_files(tmp_path)
    out_dir = tmp_path / "runs"
    args = RunArgs(
        sim_module=_minimal_sim(run_fn),
        attackers_path=a,
        defenders_path=d,
        iterations=5,
        seed=1,
        postgres_url=None,
        output_dir=out_dir,
    )

    with pytest.raises(HaltException):
        execute_run(args)

    # Run row must record the failure with iterations_completed reflecting
    # how far we got before halt.
    dbs = list(out_dir.glob("*.db"))
    assert len(dbs) == 1
    eng = create_engine(f"sqlite:///{dbs[0]}")
    with Session(eng) as sess:
        row = sess.execute(select(Run)).scalar_one()
        assert row.terminated_reason == "error"
        assert row.iterations_completed == 2
    eng.dispose()


def test_halt_is_a_regular_exception_subclass() -> None:
    """Subclass relationship with Exception (so generic except Exception
    catches it as the framework intends)."""
    assert issubclass(HaltException, Exception)
    assert not issubclass(HaltException, KeyboardInterrupt)
    assert not issubclass(HaltException, SystemExit)


def test_halt_in_setup_propagates_out(tmp_path: Path) -> None:
    """Halt raised in a setup hook also propagates through execute_run."""

    def run_fn(*, iteration_num: int, **_: Any) -> Iterator[Event]:
        yield RoundCompleteMarker(event_seq=1, iteration_num=iteration_num, round_num=1)

    def setup_hook(*, registry: Any, iteration_num: int, **_: Any) -> None:
        if iteration_num == 0:
            raise HaltException("setup halt")

    sim = _minimal_sim(run_fn)
    sim.setup = setup_hook

    a, d = _data_files(tmp_path)
    args = RunArgs(
        sim_module=sim,
        attackers_path=a,
        defenders_path=d,
        iterations=3,
        seed=1,
        postgres_url=None,
        output_dir=tmp_path / "runs",
    )

    with pytest.raises(HaltException, match="setup halt"):
        execute_run(args)
