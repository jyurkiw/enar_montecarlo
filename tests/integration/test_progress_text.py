"""Tests for ProgressDriver text mode (Rich Progress group)."""

import io

from enar_montecarlo.cli.progress import ProgressDriver
from enar_montecarlo.events import (
    EffectEvent,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)


def _drive(
    *,
    total_iterations: int,
    max_rounds: int | None,
    rounds_per_iter: int,
) -> tuple[ProgressDriver, io.StringIO]:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=total_iterations,
        max_rounds=max_rounds,
        mode="text",
        stderr=sink,
    )
    for it in range(total_iterations):
        for r in range(rounds_per_iter):
            driver.on_event(
                RoundCompleteMarker(event_seq=r * 2 + 1, iteration_num=it, round_num=r + 1)
            )
        driver.on_event(
            SimulationCompleteMarker(
                event_seq=99,
                iteration_num=it,
                rounds_executed=rounds_per_iter,
            )
        )
    driver.close()
    return driver, sink


def test_text_mode_renders_progress_to_stderr() -> None:
    _, sink = _drive(total_iterations=3, max_rounds=2, rounds_per_iter=2)
    out = sink.getvalue()
    # Both bars are labelled.
    assert "iterations" in out
    assert "rounds" in out
    # Final state shows the totals.
    assert "3/3" in out
    assert "6/6" in out


def test_text_mode_with_unknown_max_rounds_uses_dynamic_estimate() -> None:
    """No MAX_ROUNDS -> rounds bar starts indeterminate; total is refined
    after the first iteration completes."""
    driver, sink = _drive(total_iterations=2, max_rounds=None, rounds_per_iter=3)
    out = sink.getvalue()
    assert "iterations" in out
    assert "rounds" in out
    # At end: 2 iters complete, 6 rounds total. Estimate is exact at convergence.
    assert "2/2" in out
    assert "6/6" in out


def test_text_mode_ignores_resolution_and_effect_events() -> None:
    """Per-event ResolutionEvent / EffectEvent must not move the bars."""
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=1,
        max_rounds=1,
        mode="text",
        stderr=sink,
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
    # No iteration / round markers fired -> bars stay at 0.
    driver.close()
    out = sink.getvalue()
    # Iterations bar shows 0 of 1.
    assert "0/1" in out


def test_text_mode_no_deadlock_with_very_fast_iterations() -> None:
    """Tight loop with no per-iteration work; refresh_per_second cap on
    Rich's redraw thread keeps this fast and deadlock-free."""
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=500,
        max_rounds=1,
        mode="text",
        stderr=sink,
    )
    for it in range(500):
        driver.on_event(
            RoundCompleteMarker(event_seq=1, iteration_num=it, round_num=1)
        )
        driver.on_event(
            SimulationCompleteMarker(
                event_seq=2, iteration_num=it, rounds_executed=1
            )
        )
    driver.close()
    out = sink.getvalue()
    assert "500/500" in out
