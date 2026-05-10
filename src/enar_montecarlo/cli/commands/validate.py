"""``validate`` subcommand: framework checks + optional sim validate hook."""

from pathlib import Path
from typing import Any

import click

from enar_montecarlo.lifecycle import DataFileError, load_data_file


def _framework_checks(data: dict[str, Any]) -> list[str]:
    """Structural checks that complement load_data_file's basic shape.

    load_data_file already verified ``data`` is a dict with an ``actors``
    key, so here we walk into actors and verify the per-actor fields.
    """
    issues: list[str] = []
    actors = data.get("actors")
    if not isinstance(actors, list):
        issues.append("'actors' must be a list")
        return issues
    for i, actor in enumerate(actors):
        if not isinstance(actor, dict):
            issues.append(f"actor[{i}] must be a dict")
            continue
        for required in ("name", "count", "clumping"):
            if required not in actor:
                issues.append(f"actor[{i}] missing required key {required!r}")
    return issues


@click.command(help="Validate an actor data file.")
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.pass_context
def validate_cmd(ctx: click.Context, file: Path) -> None:
    sim_module = ctx.obj.get("sim_module") if ctx.obj else None

    issues: list[str] = []

    try:
        data = load_data_file(file)
    except DataFileError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(1)

    issues.extend(_framework_checks(data))

    # Optional sim hook. Per DESIGN section 10.3 the signature is
    # ``validate(attackers, defenders)``; the CLI takes one file so we
    # pass the same data as both. Sims that care can branch on
    # ``attackers is defenders``.
    if sim_module is not None:
        sim_validate = getattr(sim_module, "validate", None)
        if callable(sim_validate):
            try:
                sim_issues = sim_validate(data, data)
            except Exception as exc:  # noqa: BLE001
                issues.append(f"sim.validate raised: {exc}")
            else:
                if sim_issues:
                    issues.extend(str(s) for s in sim_issues)

    if issues:
        for issue in issues:
            click.echo(issue, err=True)
        ctx.exit(1)
