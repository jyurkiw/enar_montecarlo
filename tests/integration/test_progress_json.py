"""Tests for ProgressDriver JSON Lines mode (DESIGN section 11.3)."""

import io
import json

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
    rounds_per_iter: int,
    max_rounds: int | None = None,
) -> list[dict[str, object]]:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=total_iterations,
        max_rounds=max_rounds,
        mode="json",
        stderr=sink,
    )
    for it in range(total_iterations):
        for r in range(rounds_per_iter):
            driver.on_event(
                RoundCompleteMarker(
                    event_seq=r * 2 + 1, iteration_num=it, round_num=r + 1
                )
            )
        driver.on_event(
            SimulationCompleteMarker(
                event_seq=99,
                iteration_num=it,
                rounds_executed=rounds_per_iter,
            )
        )
    driver.close()
    return [json.loads(line) for line in sink.getvalue().splitlines() if line]


# --- per-event emission -----------------------------------------------------


def test_json_one_line_per_iteration_plus_sim_complete() -> None:
    lines = _drive(total_iterations=3, rounds_per_iter=2)
    assert len(lines) == 4  # 3 iteration_complete + 1 sim_complete
    assert [line["event"] for line in lines] == [
        "iteration_complete",
        "iteration_complete",
        "iteration_complete",
        "sim_complete",
    ]


def test_json_iteration_complete_carries_iteration_num_and_rounds() -> None:
    lines = _drive(total_iterations=2, rounds_per_iter=4)
    iters = [line for line in lines if line["event"] == "iteration_complete"]
    assert iters[0]["iteration_num"] == 0
    assert iters[0]["rounds"] == 4
    assert iters[1]["iteration_num"] == 1
    assert iters[1]["rounds"] == 4
    # Each carries an elapsed_s float >= 0.
    for line in iters:
        assert isinstance(line["elapsed_s"], (int, float))
        assert line["elapsed_s"] >= 0


def test_json_sim_complete_summary() -> None:
    lines = _drive(total_iterations=4, rounds_per_iter=3)
    summary = lines[-1]
    assert summary["event"] == "sim_complete"
    assert summary["total_iterations"] == 4
    assert summary["total_rounds"] == 12
    assert isinstance(summary["elapsed_s"], (int, float))


def test_json_round_marker_does_not_emit_a_line() -> None:
    """Rounds advance counters but emit nothing; only iteration markers
    produce JSONL lines (DESIGN section 11.3)."""
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=1,
        max_rounds=5,
        mode="json",
        stderr=sink,
    )
    for r in range(5):
        driver.on_event(
            RoundCompleteMarker(event_seq=r + 1, iteration_num=0, round_num=r + 1)
        )
    # No lines yet.
    assert sink.getvalue() == ""

    driver.on_event(
        SimulationCompleteMarker(event_seq=99, iteration_num=0, rounds_executed=5)
    )
    driver.close()
    lines = [json.loads(line) for line in sink.getvalue().splitlines() if line]
    assert len(lines) == 2  # iteration_complete + sim_complete


def test_json_resolution_and_effect_events_emit_nothing() -> None:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=1, max_rounds=1, mode="json", stderr=sink
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
    # Only sim_complete (no iteration markers fired -> 0 iterations).
    lines = [json.loads(line) for line in sink.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["event"] == "sim_complete"
    assert lines[0]["total_iterations"] == 0


def test_json_lines_are_valid_compact_json() -> None:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=1, max_rounds=1, mode="json", stderr=sink
    )
    driver.on_event(
        SimulationCompleteMarker(
            event_seq=1, iteration_num=0, rounds_executed=1
        )
    )
    driver.close()
    raw = sink.getvalue()
    # Each line ends with a single newline; no embedded newlines mid-line.
    for line in raw.splitlines():
        assert "\n" not in line
        json.loads(line)  # raises if malformed


def test_json_zero_iterations_only_sim_complete() -> None:
    sink = io.StringIO()
    driver = ProgressDriver(
        total_iterations=0, max_rounds=None, mode="json", stderr=sink
    )
    driver.close()
    lines = [json.loads(line) for line in sink.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["event"] == "sim_complete"
    assert lines[0]["total_iterations"] == 0
    assert lines[0]["total_rounds"] == 0
