"""``list-runs`` subcommand: tabular summary of runs from a backend."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from enar_montecarlo.persistence.schema import Base, Run

DEFAULT_OUTPUT_DIR = Path("./runs")


def _query_runs(url: str) -> list[tuple[UUID, str, str, int, int, str | None, datetime]]:
    engine = create_engine(url)
    # Ensure schema exists so we don't crash on a stale / fresh DB; the
    # query just sees an empty table if no runs landed yet.
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as sess:
            rows = sess.execute(select(Run).order_by(Run.started_at.desc())).scalars().all()
            return [
                (
                    r.run_id,
                    r.sim_name,
                    r.sim_version,
                    r.iterations_completed,
                    r.iterations_planned,
                    r.terminated_reason,
                    r.started_at,
                )
                for r in rows
            ]
    finally:
        engine.dispose()


@click.command(help="List runs from the configured backend.")
@click.option(
    "--postgres-url",
    default=None,
    help="Query Postgres; if unset, scans --output-dir for SQLite artifacts.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Directory of SQLite artifacts (one DB per run).",
)
def list_runs_cmd(postgres_url: str | None, output_dir: Path) -> None:
    rows: list[Any] = []
    if postgres_url is not None:
        rows = _query_runs(postgres_url)
    else:
        if output_dir.exists():
            for db_path in sorted(output_dir.glob("*.db")):
                rows.extend(_query_runs(f"sqlite:///{db_path}"))
        rows.sort(key=lambda r: r[6], reverse=True)

    if not rows:
        click.echo("no runs")
        return

    console = Console()
    table = Table()
    table.add_column("run_id")
    table.add_column("sim")
    table.add_column("done/planned")
    table.add_column("status")
    table.add_column("started_at")
    for run_id, sim_name, sim_version, done, planned, reason, started in rows:
        table.add_row(
            str(run_id),
            f"{sim_name} {sim_version}",
            f"{done}/{planned}",
            reason or "(running)",
            str(started),
        )
    console.print(table)
