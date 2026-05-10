"""``purge`` subcommand stub. Implementation lands in P4.7."""

import click


@click.command(help="Delete an orphaned temp SQLite file.")
def purge_cmd() -> None:
    raise click.ClickException("purge subcommand not implemented yet (P4.7)")
