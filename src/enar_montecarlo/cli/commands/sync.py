"""``sync`` subcommand stub. Implementation lands in P4.6."""

import click


@click.command(help="Replay an orphaned temp SQLite into Postgres.")
def sync_cmd() -> None:
    raise click.ClickException("sync subcommand not implemented yet (P4.6)")
