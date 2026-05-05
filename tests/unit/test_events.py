"""Tests for ``enar_montecarlo.events``.

Covers per-model parsing, validation errors, discriminated-union dispatch,
JSON round-trips, and default values for optional fields.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from enar_montecarlo.events import (
    EffectEvent,
    Event,
    EventAdapter,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)

# --- ResolutionEvent ---------------------------------------------------------


def _resolution_kwargs() -> dict[str, object]:
    return {
        "event_seq": 1,
        "iteration_num": 0,
        "actor_file_id": "deadbeef",
        "actor_index": 0,
        "resolution_name": "dagger",
        "outcome_id": 7,
    }


def test_resolution_event_minimum_fields_uses_defaults() -> None:
    ev = ResolutionEvent(**_resolution_kwargs())  # type: ignore[arg-type]
    assert ev.type == "resolution"
    assert ev.round_num == 1
    assert ev.target_file_id is None
    assert ev.target_index is None
    assert ev.caused_by_seq is None
    assert ev.notes == {}


def test_resolution_event_all_fields() -> None:
    ev = ResolutionEvent(
        event_seq=3,
        iteration_num=2,
        round_num=4,
        actor_file_id="aaa",
        actor_index=0,
        target_file_id="bbb",
        target_index=1,
        resolution_name="dagger",
        outcome_id=9,
        caused_by_seq=2,
        notes={"roll": 17},
    )
    assert ev.target_file_id == "bbb"
    assert ev.notes == {"roll": 17}


def test_resolution_event_missing_required_field_raises() -> None:
    kwargs = _resolution_kwargs()
    del kwargs["outcome_id"]
    with pytest.raises(ValidationError) as exc:
        ResolutionEvent(**kwargs)  # type: ignore[arg-type]
    assert "outcome_id" in str(exc.value)


def test_resolution_event_wrong_type_raises() -> None:
    kwargs = _resolution_kwargs()
    kwargs["event_seq"] = "not-an-int"
    with pytest.raises(ValidationError):
        ResolutionEvent(**kwargs)  # type: ignore[arg-type]


def test_resolution_notes_default_is_independent_per_instance() -> None:
    a = ResolutionEvent(**_resolution_kwargs())  # type: ignore[arg-type]
    b = ResolutionEvent(**_resolution_kwargs())  # type: ignore[arg-type]
    a.notes["x"] = 1
    assert b.notes == {}


# --- EffectEvent -------------------------------------------------------------


def _effect_kwargs() -> dict[str, object]:
    return {
        "event_seq": 2,
        "iteration_num": 0,
        "actor_file_id": "deadbeef",
        "actor_index": 0,
        "effect_definition_name": "piercing_damage",
        "effect_type_id": 1,
        "source_branch_id": 11,
        "caused_by_seq": 1,
    }


def test_effect_event_minimum_fields_uses_defaults() -> None:
    ev = EffectEvent(**_effect_kwargs())  # type: ignore[arg-type]
    assert ev.type == "effect"
    assert ev.round_num == 1
    assert ev.damage_type_id is None
    assert ev.amount is None
    assert ev.trigger_name is None
    assert ev.trigger_result is None
    assert ev.notes == {}


def test_effect_event_with_trigger_failure() -> None:
    ev = EffectEvent(
        **_effect_kwargs(),  # type: ignore[arg-type]
        trigger_name="sneak_attack_eligible",
        trigger_result=False,
        amount=None,
    )
    assert ev.trigger_result is False
    assert ev.amount is None


def test_effect_event_missing_caused_by_seq_raises() -> None:
    kwargs = _effect_kwargs()
    del kwargs["caused_by_seq"]
    with pytest.raises(ValidationError) as exc:
        EffectEvent(**kwargs)  # type: ignore[arg-type]
    assert "caused_by_seq" in str(exc.value)


# --- RoundCompleteMarker -----------------------------------------------------


def test_round_complete_marker_requires_round_num() -> None:
    ev = RoundCompleteMarker(event_seq=10, iteration_num=0, round_num=2)
    assert ev.type == "round_complete"
    assert ev.round_num == 2

    with pytest.raises(ValidationError):
        RoundCompleteMarker(event_seq=10, iteration_num=0)  # type: ignore[call-arg]


# --- SimulationCompleteMarker ------------------------------------------------


def test_sim_complete_marker_defaults_outcome_summary() -> None:
    ev = SimulationCompleteMarker(event_seq=99, iteration_num=0, rounds_executed=3)
    assert ev.type == "sim_complete"
    assert ev.outcome_summary == {}


def test_sim_complete_marker_carries_outcome_summary() -> None:
    ev = SimulationCompleteMarker(
        event_seq=99,
        iteration_num=0,
        rounds_executed=3,
        outcome_summary={"hit": 4, "miss": 1},
    )
    assert ev.outcome_summary == {"hit": 4, "miss": 1}


# --- Discriminated union dispatch -------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_cls"),
    [
        (
            {**_resolution_kwargs(), "type": "resolution"},
            ResolutionEvent,
        ),
        (
            {**_effect_kwargs(), "type": "effect"},
            EffectEvent,
        ),
        (
            {"type": "round_complete", "event_seq": 1, "iteration_num": 0, "round_num": 1},
            RoundCompleteMarker,
        ),
        (
            {
                "type": "sim_complete",
                "event_seq": 1,
                "iteration_num": 0,
                "rounds_executed": 2,
            },
            SimulationCompleteMarker,
        ),
    ],
)
def test_event_adapter_dispatches_to_correct_subclass(
    payload: dict[str, object],
    expected_cls: type[Event],
) -> None:
    parsed = EventAdapter.validate_python(payload)
    assert isinstance(parsed, expected_cls)


def test_event_adapter_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        EventAdapter.validate_python({"type": "bogus", "event_seq": 1, "iteration_num": 0})


def test_event_adapter_rejects_missing_type() -> None:
    with pytest.raises(ValidationError):
        EventAdapter.validate_python({"event_seq": 1, "iteration_num": 0})


# --- JSON round-trip ---------------------------------------------------------


def test_resolution_event_json_round_trip() -> None:
    original = ResolutionEvent(**_resolution_kwargs())  # type: ignore[arg-type]
    raw = original.model_dump_json()
    # Compact JSON: no spaces between separators.
    assert ", " not in raw and ": " not in raw
    parsed = ResolutionEvent.model_validate_json(raw)
    assert parsed == original


def test_effect_event_json_round_trip_via_adapter() -> None:
    original = EffectEvent(**_effect_kwargs())  # type: ignore[arg-type]
    raw = original.model_dump_json()
    parsed = EventAdapter.validate_json(raw)
    assert isinstance(parsed, EffectEvent)
    assert parsed == original


def test_marker_json_round_trips_via_adapter() -> None:
    for marker in (
        RoundCompleteMarker(event_seq=4, iteration_num=0, round_num=1),
        SimulationCompleteMarker(event_seq=5, iteration_num=0, rounds_executed=1),
    ):
        raw = marker.model_dump_json()
        # Type discriminator survives JSON.
        assert json.loads(raw)["type"] == marker.type
        parsed = EventAdapter.validate_json(raw)
        assert parsed == marker
