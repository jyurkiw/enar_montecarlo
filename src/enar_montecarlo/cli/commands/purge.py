"""``purge`` subcommand: delete an orphaned temp SQLite without syncing."""

import os
from uuid import UUID

import click

from enar_montecarlo.persistence import sessions as sess_mod


@click.command(help="Delete an orphaned temp SQLite file.")
@click.argument("run_id", type=click.UUID)
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
def purge_cmd(run_id: UUID, yes: bool) -> None:
    """Delete ``<tempdir>/<run_id>.db`` if present.

    Use after a manual recovery where you don't want to sync the
    orphaned SQLite into Postgres. Missing file is a no-op with an
    informative message; existing file requires confirmation unless
    ``--yes`` is passed.
    """
    sqlite_path = sess_mod._default_temp_dir() / f"{run_id}.db"
    if not sqlite_path.exists():
        click.echo(f"no SQLite file found at {sqlite_path}")
        return
    if not yes:
        click.confirm(f"Delete {sqlite_path}?", abort=True)
    os.remove(sqlite_path)
    click.echo(f"deleted {sqlite_path}")
