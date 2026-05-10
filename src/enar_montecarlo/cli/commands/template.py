"""``template`` subcommand: emit a starter actor data file."""

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import click
import yaml

from enar_montecarlo.lifecycle import discover


def _default_template(sim_module: ModuleType) -> dict[str, Any]:
    contract = discover(sim_module)
    return {
        "metadata": {
            "system": contract.system_name,
            "system_version": contract.system_version,
        },
        "actors": [
            {"name": "example", "count": 1, "clumping": 1},
        ],
    }


def _render(data: dict[str, Any], fmt: str) -> str:
    if fmt == "yaml":
        return yaml.safe_dump(data, sort_keys=False)
    return json.dumps(data, indent=2)


@click.command(help="Emit a starter actor data file.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write to PATH instead of stdout.",
)
@click.pass_context
def template_cmd(ctx: click.Context, fmt: str, output: Path | None) -> None:
    sim_module = ctx.obj.get("sim_module") if ctx.obj else None
    if sim_module is None:
        raise click.ClickException(
            "no sim module attached -- invoke via `python -m my_sim template`"
        )

    sim_template_fn = getattr(sim_module, "template", None)
    data = (
        sim_template_fn()
        if callable(sim_template_fn)
        else _default_template(sim_module)
    )

    text = _render(data, fmt)

    if output is not None:
        output.write_text(text, encoding="utf-8")
    else:
        click.echo(text, nl=False)
