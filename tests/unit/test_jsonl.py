"""Round-trip tests for JSONL event serialization."""

import pytest

from enar_montecarlo.events import (
    EffectEvent,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)
from enar_montecarlo.utils.jsonl import dumps_event, loads_event


@pytest.fixture
def resolution() -> ResolutionEvent:
    return ResolutionEvent(
        event_seq=1,
        iteration_num=0,
        actor_file_id="aaa",
        actor_index=0,
        target_file_id="bbb",
        target_index=2,
        resolution_name="dagger",
        outcome_id=7,
        caused_by_seq=None,
        notes={"roll": 17, "modifiers": ["sharp"]},
    )


@pytest.fixture
def effect() -> EffectEvent:
    return EffectEvent(
        event_seq=2,
        iteration_num=0,
        actor_file_id="aaa",
        actor_index=0,
        target_file_id="bbb",
        target_index=2,
        effect_definition_name="piercing_damage",
        effect_type_id=1,
        damage_type_id=4,
        amount=6.5,
        source_branch_id=11,
        caused_by_seq=1,
        trigger_name="sneak_attack_eligible",
        trigger_result=True,
        notes={"crit": False},
    )


def test_resolution_round_trip(resolution: ResolutionEvent) -> None:
    parsed = loads_event(dumps_event(resolution))
    assert isinstance(parsed, ResolutionEvent)
    assert parsed == resolution


def test_effect_round_trip(effect: EffectEvent) -> None:
    parsed = loads_event(dumps_event(effect))
    assert isinstance(parsed, EffectEvent)
    assert parsed == effect


def test_round_complete_marker_round_trip() -> None:
    marker = RoundCompleteMarker(event_seq=10, iteration_num=0, round_num=2)
    parsed = loads_event(dumps_event(marker))
    assert isinstance(parsed, RoundCompleteMarker)
    assert parsed == marker


def test_sim_complete_marker_round_trip() -> None:
    marker = SimulationCompleteMarker(
        event_seq=99,
        iteration_num=0,
        rounds_executed=3,
        outcome_summary={"hit": 4, "miss": 1},
    )
    parsed = loads_event(dumps_event(marker))
    assert isinstance(parsed, SimulationCompleteMarker)
    assert parsed == marker


def test_dumps_produces_single_line(resolution: ResolutionEvent) -> None:
    # JSONL invariant: one event per line.
    assert "\n" not in dumps_event(resolution)
