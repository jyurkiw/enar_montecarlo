"""Progress UI for ``execute_run`` -- text, JSON, or quiet.

Driven by :class:`ProgressDriver`, which the lifecycle driver calls
``on_event`` for every yielded event and ``close`` once the run ends.
Resolution / Effect events are ignored at the progress layer; only
``RoundCompleteMarker`` and ``SimulationCompleteMarker`` move the bars
or emit lines.

Three modes (DESIGN section 11):

* ``text``   -- Rich Progress group on stderr with two bars.
* ``json``   -- JSON Lines on stderr, one line per iteration plus a
  final ``sim_complete`` summary.
* ``quiet``  -- no output. ``on_event`` is a true no-op.
"""

import json
import sys
import time
from typing import Any, Literal, TextIO

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from enar_montecarlo.events import (
    Event,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)

Mode = Literal["text", "json", "quiet"]


class ProgressDriver:
    """Per-run progress UI. One instance per ``execute_run`` invocation."""

    def __init__(
        self,
        *,
        total_iterations: int,
        max_rounds: int | None,
        mode: Mode,
        stderr: TextIO | None = None,
    ) -> None:
        self._total_iterations = total_iterations
        self._max_rounds = max_rounds
        self._mode: Mode = mode
        self._stderr: TextIO = stderr if stderr is not None else sys.stderr

        self._iterations_completed = 0
        self._rounds_completed = 0
        # Snapshot of rounds_completed at the moment each iteration ends;
        # used by the dynamic-estimate path so the rate is computed only
        # over fully-completed iterations.
        self._rounds_at_last_iter_complete = 0
        self._iteration_start_time = time.monotonic()
        self._sim_start_time = time.monotonic()

        self._progress: Progress | None = None
        self._iter_task_id: Any = None
        self._round_task_id: Any = None

        if mode == "text":
            self._init_text_mode()

    # --- text mode ----------------------------------------------------------

    def _init_text_mode(self) -> None:
        # refresh_per_second caps Rich's internal repaint thread so a
        # tight per-iteration loop cannot starve the main thread or
        # cause runaway terminal redraws.
        console = Console(file=self._stderr, stderr=True)
        self._progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
            refresh_per_second=10,
            transient=False,
        )
        self._progress.start()
        self._iter_task_id = self._progress.add_task(
            "iterations", total=self._total_iterations
        )
        rounds_total: int | None
        if self._max_rounds is not None:
            rounds_total = self._max_rounds * self._total_iterations
        else:
            rounds_total = None
        self._round_task_id = self._progress.add_task("rounds", total=rounds_total)

    # --- public surface -----------------------------------------------------

    def on_event(self, event: Event) -> None:
        """Consume one event from the iteration loop."""
        if isinstance(event, RoundCompleteMarker):
            self._rounds_completed += 1
            self._on_round()
        elif isinstance(event, SimulationCompleteMarker):
            self._on_iteration(event)
            self._iterations_completed += 1
            self._rounds_at_last_iter_complete = self._rounds_completed
        # Resolution / Effect events do not drive the progress UI.

    def close(self) -> None:
        """Tear down the UI and emit any final summary."""
        total_elapsed = time.monotonic() - self._sim_start_time
        if self._mode == "text" and self._progress is not None:
            self._progress.stop()
        elif self._mode == "json":
            self._stderr.write(
                json.dumps(
                    {
                        "event": "sim_complete",
                        "total_iterations": self._iterations_completed,
                        "total_rounds": self._rounds_completed,
                        "elapsed_s": round(total_elapsed, 6),
                    }
                )
                + "\n"
            )
            self._stderr.flush()
        # quiet: nothing.

    # --- internal -----------------------------------------------------------

    def _on_round(self) -> None:
        if self._mode != "text" or self._progress is None:
            return
        # Dynamic-estimate path: when MAX_ROUNDS is unknown, project
        # total = avg(rounds-per-completed-iter) * total_iterations.
        # Using rounds-per-COMPLETED-iter (not running total) keeps the
        # estimate stable while the current iteration is in flight.
        if self._max_rounds is None and self._iterations_completed > 0:
            avg = (
                self._rounds_at_last_iter_complete / self._iterations_completed
            )
            est_total = int(avg * self._total_iterations)
            self._progress.update(
                self._round_task_id, total=est_total, advance=1
            )
        else:
            self._progress.update(self._round_task_id, advance=1)

    def _on_iteration(self, event: SimulationCompleteMarker) -> None:
        elapsed = time.monotonic() - self._iteration_start_time
        self._iteration_start_time = time.monotonic()
        if self._mode == "text" and self._progress is not None:
            self._progress.update(self._iter_task_id, advance=1)
        elif self._mode == "json":
            self._stderr.write(
                json.dumps(
                    {
                        "event": "iteration_complete",
                        "iteration_num": event.iteration_num,
                        "rounds": event.rounds_executed,
                        "elapsed_s": round(elapsed, 6),
                    }
                )
                + "\n"
            )
            self._stderr.flush()
        # quiet: nothing.
