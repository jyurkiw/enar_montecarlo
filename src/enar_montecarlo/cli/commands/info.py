"""``info`` subcommand: print sim metadata as text or JSON."""

import json

import click

from enar_montecarlo.lifecycle import discover


@click.command(help="Print sim metadata.")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit JSON instead of human-readable text.",
)
@click.pass_context
def info_cmd(ctx: click.Context, as_json: bool) -> None:
    sim_module = ctx.obj.get("sim_module") if ctx.obj else None
    if sim_module is None:
        raise click.ClickException(
            "no sim module attached -- invoke via `python -m my_sim info`"
        )
    contract = discover(sim_module)

    if as_json:
        payload = {
            "sim": {"name": contract.sim_name, "version": contract.sim_version},
            "system": {
                "name": contract.system_name,
                "version": contract.system_version,
            },
            "defaults": {
                "iterations": contract.default_iterations,
                "max_rounds": contract.max_rounds,
            },
            "outcomes": contract.outcomes,
        }
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(f"sim:    {contract.sim_name} {contract.sim_version}")
    click.echo(f"system: {contract.system_name} {contract.system_version}")
    click.echo("defaults:")
    click.echo(f"  iterations: {contract.default_iterations}")
    click.echo(f"  max_rounds: {contract.max_rounds}")
