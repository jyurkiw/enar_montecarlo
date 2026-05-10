"""Tests for ProgressDriver quiet mode (DESIGN section 11.2)."""

import io

from enar_montecarlo.cli.progress import ProgressDriver
from enar_montecarlo.events import (
    EffectEvent,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)


def test_quiet_emits_nothing_for_any_event() -> None:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=3, max_rounds=2, mode="quiet", stderr=sink
    )
    for it in range(3):
        for r in range(2):
            driver.on_event(
                RoundCompleteMarker(event_seq=r + 1, iteration_num=it, round_num=r + 1)
            )
        driver.on_event(
            SimulationCompleteMarker(
                event_seq=99, iteration_num=it, rounds_executed=2
            )
        )
    driver.close()
    assert sink.getvalue() == ""


def test_quiet_ignores_resolution_and_effect_events() -> None:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=1, max_rounds=1, mode="quiet", stderr=sink
    )
    driver.on_event(
        ResolutionEvent(
            event_seq=1,
            iteration_num=0,
            actor_file_id="x",
            actor_index=0,
            resolution_name="r",
            outcome_id=1,
        )
    )
    driver.on_event(
        EffectEvent(
            event_seq=2,
            iteration_num=0,
            actor_file_id="x",
            actor_index=0,
            effect_definition_name="d",
            effect_type_id=1,
            source_branch_id=1,
            caused_by_seq=1,
        )
    )
    driver.close()
    assert sink.getvalue() == ""


def test_quiet_close_is_noop() -> None:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=0, max_rounds=None, mode="quiet", stderr=sink
    )
    driver.close()
    assert sink.getvalue() == ""


def test_quiet_internal_counters_still_advance() -> None:
    """Even though no UI is rendered, on_event still walks the counters
    so callers can introspect state (e.g. for debugging)."""
    driver = ProgressDriver(
        total_iterations=2, max_rounds=2, mode="quiet"
    )
    driver.on_event(
        RoundCompleteMarker(event_seq=1, iteration_num=0, round_num=1)
    )
    driver.on_event(
        SimulationCompleteMarker(
            event_seq=2, iteration_num=0, rounds_executed=1
        )
    )
    assert driver._iterations_completed == 1
    assert driver._rounds_completed == 1
    driver.close()
