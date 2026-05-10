"""Sanity tests for the echo_sim fixture itself.

These guard the fixture's per-iteration emission shape so the broader
P7.2 end-to-end test can rely on exact row counts and content.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Make the fixtures dir importable as a top-level package.
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(_FIXTURES_DIR))

import echo_sim  # noqa: E402  (sys.path mutation above)

from enar_montecarlo.events import (  # noqa: E402
    EffectEvent,
    Event,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)
from enar_montecarlo.registry import RegistryBuilder  # noqa: E402


@pytest.fixture
def primed_sim() -> Iterator[Any]:
    """Run setup_once on a fresh registry so the module-level id cache
    is populated before tests touch run()."""
    counter = 0

    def persist(_cat: str, _name: str) -> int:
        nonlocal counter
        counter += 1
        return counter

    builder = RegistryBuilder(persist=persist)
    registry = echo_sim.setup_once(
        attackers={"actors": [{"name": "a"}]},
        defenders={"actors": [{"name": "d"}]},
        registry_builder=builder,
    )
    yield registry


def _events(registry: Any, sneaky: bool = False, iteration: int = 0) -> list[Event]:
    return list(
        echo_sim.run(
            attackers={},
            defenders={},
            registry=registry,
            iteration_num=iteration,
            sneaky=sneaky,
        )
    )


# --- attribute surface ------------------------------------------------------


def test_required_attributes_present() -> None:
    for attr in ("run", "OUTCOMES", "SIM_NAME", "SIM_VERSION", "SYSTEM_NAME", "SYSTEM_VERSION"):
        assert hasattr(echo_sim, attr)


def test_optional_hooks_all_present() -> None:
    for hook in ("setup_once", "setup", "teardown", "teardown_once", "validate", "template"):
        assert callable(getattr(echo_sim, hook))


def test_outcomes_are_pass_fail() -> None:
    assert echo_sim.OUTCOMES == ["pass", "fail"]


# --- per-iteration shape ----------------------------------------------------


def test_run_emits_eight_events_per_iteration(primed_sim: Any) -> None:
    events = _events(primed_sim)
    assert len(events) == 8


def test_run_event_types_in_order(primed_sim: Any) -> None:
    events = _events(primed_sim)
    types = [type(e).__name__ for e in events]
    assert types == [
        "ResolutionEvent",  # outcome=pass
        "EffectEvent",  # branch=pass, no trigger
        "EffectEvent",  # branch=pass, gated
        "ResolutionEvent",  # outcome=fail
        "EffectEvent",  # branch=fail
        "EffectEvent",  # custom type
        "RoundCompleteMarker",
        "SimulationCompleteMarker",
    ]


def test_event_seqs_are_one_through_eight(primed_sim: Any) -> None:
    events = _events(primed_sim)
    assert [e.event_seq for e in events] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_caused_by_seq_chain(primed_sim: Any) -> None:
    events = _events(primed_sim)
    # event 4 (fail resolution) caused by event 1 (pass resolution)
    assert isinstance(events[3], ResolutionEvent)
    assert events[3].caused_by_seq == 1
    # event 2 effect caused by event 1
    assert isinstance(events[1], EffectEvent)
    assert events[1].caused_by_seq == 1
    # event 5 effect caused by event 4
    assert isinstance(events[4], EffectEvent)
    assert events[4].caused_by_seq == 4
    # event 6 custom effect caused by event 1
    assert isinstance(events[5], EffectEvent)
    assert events[5].caused_by_seq == 1


# --- trigger gating ---------------------------------------------------------


def test_gated_effect_when_sneaky_false_records_trigger_failure(primed_sim: Any) -> None:
    events = _events(primed_sim, sneaky=False)
    gated = events[2]
    assert isinstance(gated, EffectEvent)
    assert gated.trigger_name == "sneak_attack_eligible"
    assert gated.trigger_result is False
    assert gated.amount is None


def test_gated_effect_when_sneaky_true_fires(primed_sim: Any) -> None:
    events = _events(primed_sim, sneaky=True)
    gated = events[2]
    assert isinstance(gated, EffectEvent)
    assert gated.trigger_result is True
    assert gated.amount == 2.0


# --- custom-type effect notes ----------------------------------------------


def test_custom_effect_notes_payload(primed_sim: Any) -> None:
    events = _events(primed_sim, iteration=7)
    custom = events[5]
    assert isinstance(custom, EffectEvent)
    assert custom.notes == {"system_extra": "echo", "iter": 7}


# --- markers ----------------------------------------------------------------


def test_round_and_sim_markers_carry_iteration_num(primed_sim: Any) -> None:
    events = _events(primed_sim, iteration=3)
    rcm = events[6]
    scm = events[7]
    assert isinstance(rcm, RoundCompleteMarker)
    assert isinstance(scm, SimulationCompleteMarker)
    assert rcm.iteration_num == 3
    assert scm.iteration_num == 3
    assert scm.rounds_executed == 1
