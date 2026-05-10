"""``run`` subcommand: drive a single sim run and print the UUID."""

import time
from pathlib import Path
from typing import Any

import click

from enar_montecarlo.lifecycle import RunArgs, discover, execute_run

DEFAULT_OUTPUT_DIR = Path("./runs")


def _parse_extra_args(extras: tuple[str, ...]) -> dict[str, Any]:
    """Parse a tail of ``--key value`` / ``--key=value`` / ``--flag`` tokens.

    Token forms supported:
    * ``--key value`` -> ``{"key": "value"}``
    * ``--key=value`` -> ``{"key": "value"}``
    * ``--flag`` (no value, end-of-list or followed by another ``--token``)
      -> ``{"flag": True}``

    Underscore / hyphen convention preserved as-given; sims see exactly
    what the operator typed.
    """
    out: dict[str, Any] = {}
    i = 0
    n = len(extras)
    while i < n:
        token = extras[i]
        if not token.startswith("--"):
            i += 1
            continue
        body = token[2:]
        if "=" in body:
            key, value = body.split("=", 1)
            out[key] = value
            i += 1
        elif i + 1 < n and not extras[i + 1].startswith("--"):
            out[body] = extras[i + 1]
            i += 2
        else:
            out[body] = True
            i += 1
    return out


@click.command(
    help="Run a sim against the given attacker / defender data files.",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument(
    "attackers_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "defenders_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--iterations",
    type=int,
    default=None,
    help="Iteration count. Default: sim's DEFAULT_ITERATIONS or 500.",
)
@click.option(
    "--seed",
    type=int,
    default=None,
    help="Master seed. Default: nanosecond clock.",
)
@click.option(
    "--postgres-url",
    default=None,
    help="If set, write canonical rows to Postgres and use a temp SQLite.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Where to write the SQLite artifact when --postgres-url is unset.",
)
@click.option("--quiet", is_flag=True, default=False, help="Suppress progress UI.")
@click.option(
    "--progress",
    "progress_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Progress UI format. JSON Lines on stderr for cowork integration.",
)
@click.option(
    "--workers",
    type=int,
    default=1,
    show_default=True,
    help="Parallel iterations (post-MVP; currently ignored).",
)
@click.pass_context
def run_cmd(
    ctx: click.Context,
    attackers_file: Path,
    defenders_file: Path,
    iterations: int | None,
    seed: int | None,
    postgres_url: str | None,
    output_dir: Path,
    quiet: bool,
    progress_format: str,
    workers: int,  # noqa: ARG001
) -> None:
    sim_module = ctx.obj.get("sim_module") if ctx.obj else None
    if sim_module is None:
        raise click.ClickException(
            "no sim module attached -- invoke via `python -m my_sim run ...`"
        )

    contract = discover(sim_module)

    if iterations is None:
        iterations = contract.default_iterations
    if seed is None:
        seed = time.time_ns()

    extra_args = _parse_extra_args(tuple(ctx.args))

    args = RunArgs(
        sim_module=sim_module,
        attackers_path=attackers_file,
        defenders_path=defenders_file,
        iterations=iterations,
        seed=seed,
        postgres_url=postgres_url,
        output_dir=output_dir,
        quiet=quiet,
        progress_format="json" if progress_format == "json" else "text",
        extra_args=extra_args,
    )
    run_id = execute_run(args)
    # stdout contract: just the UUID.
    click.echo(str(run_id))
