"""``sync`` subcommand: replay an orphaned temp SQLite into Postgres."""

import os
from uuid import UUID

import click

from enar_montecarlo.persistence import sessions as sess_mod
from enar_montecarlo.persistence.sync import sync_to_postgres


@click.command(help="Replay an orphaned temp SQLite into Postgres.")
@click.argument("run_id", type=click.UUID)
@click.option(
    "--postgres-url",
    required=True,
    help="Destination Postgres URL.",
)
def sync_cmd(run_id: UUID, postgres_url: str) -> None:
    """Look in the OS temp dir for ``<run_id>.db``, replay it into the
    given Postgres URL, and delete the file on success (DESIGN section
    9.3). Used to retry runs that crashed mid-postgres-mode before the
    framework had a chance to sync."""
    sqlite_path = sess_mod._default_temp_dir() / f"{run_id}.db"
    if not sqlite_path.exists():
        raise click.ClickException(
            f"no orphaned SQLite found at {sqlite_path}"
        )
    sync_to_postgres(sqlite_path=sqlite_path, postgres_url=postgres_url)
    os.remove(sqlite_path)
    click.echo(f"synced {run_id} -> {postgres_url}")
