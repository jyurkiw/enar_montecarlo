"""CLI entry point for ``enar_montecarlo`` and sim packages.

Sims expose ``main`` as their ``__main__`` entry point::

    # my_sim/__init__.py
    from enar_montecarlo import main
    if __name__ == "__main__":
        main()

When invoked via ``python -m my_sim``, ``sys.modules['__main__']`` is
the sim module; ``main()`` reads it from there. When invoked as
``python -m enar_montecarlo`` the framework runs without a sim and
only the framework-level subcommands (sync, purge, list-runs) are
actually useful.
"""

import sys
from types import ModuleType

import click

from enar_montecarlo.cli.commands.info import info_cmd
from enar_montecarlo.cli.commands.list_runs import list_runs_cmd
from enar_montecarlo.cli.commands.purge import purge_cmd
from enar_montecarlo.cli.commands.run import run_cmd
from enar_montecarlo.cli.commands.sync import sync_cmd
from enar_montecarlo.cli.commands.template import template_cmd
from enar_montecarlo.cli.commands.validate import validate_cmd


def _build_cli(sim_module: ModuleType | None) -> click.Group:
    @click.group(help="enar_montecarlo CLI -- run a sim, manage runs.")
    @click.pass_context
    def cli(ctx: click.Context) -> None:
        ctx.ensure_object(dict)
        ctx.obj["sim_module"] = sim_module

    cli.add_command(run_cmd, name="run")
    cli.add_command(template_cmd, name="template")
    cli.add_command(validate_cmd, name="validate")
    cli.add_command(info_cmd, name="info")
    cli.add_command(sync_cmd, name="sync")
    cli.add_command(purge_cmd, name="purge")
    cli.add_command(list_runs_cmd, name="list-runs")
    return cli


def main(sim_module: ModuleType | None = None) -> None:
    """CLI entry point.

    If ``sim_module`` is None, attempts to discover the calling sim
    module from ``sys.modules['__main__']`` (set by ``python -m
    my_sim``). The framework's own ``__main__`` is recognized and
    treated as "no sim attached".
    """
    if sim_module is None:
        candidate = sys.modules.get("__main__")
        # Skip the framework's own __main__ so the CLI runs with no
        # sim attached when invoked as ``python -m enar_montecarlo``.
        if candidate is not None and getattr(candidate, "__package__", None) != "enar_montecarlo":
            sim_module = candidate
    cli = _build_cli(sim_module)
    cli()
