"""``list-runs`` subcommand stub. Implementation lands in P4.8."""

import click


@click.command(help="List runs from the configured backend.")
def list_runs_cmd() -> None:
    raise click.ClickException("list-runs subcommand not implemented yet (P4.8)")
