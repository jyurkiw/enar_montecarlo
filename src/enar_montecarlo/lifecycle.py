"""Discover a sim module's lifecycle hooks and metadata constants.

The framework imports a sim module and reads documented attributes off
it to build a :class:`SimContract`. Required attributes missing on the
module raise :class:`ConfigurationError` with all missing names in the
message; optional attributes fall back to documented defaults.

Also defines :class:`RunArgs`, the bundle the CLI assembles from
argparse output and hands to the driver, and :func:`load_data_file`,
which parses an attacker / defender data file off disk.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from uuid import UUID, uuid4

import yaml

from enar_montecarlo.events import Event
from enar_montecarlo.persistence.files import store_file
from enar_montecarlo.persistence.sessions import close_context, create_context
from enar_montecarlo.persistence.sync import sync_to_postgres
from enar_montecarlo.persistence.values import (
    make_persist_fn,
    seed_framework_defaults,
)
from enar_montecarlo.persistence.writes import (
    create_run_row,
    update_run_completion,
    write_event,
)
from enar_montecarlo.registry import RegistryBuilder
from enar_montecarlo.seeding import derive_iteration_seed

DEFAULT_ITERATIONS = 500
"""Fallback for ``DEFAULT_ITERATIONS`` when the sim does not declare one."""


class ConfigurationError(Exception):
    """A sim module is missing one or more required attributes."""


class DataFileError(ValueError):
    """An actor data file failed to parse or has the wrong top-level shape."""


def load_data_file(path: Path) -> dict[str, Any]:
    """Load an attacker or defender data file from disk.

    File format is auto-detected by extension: ``.yaml`` and ``.yml``
    parse as YAML, ``.json`` as JSON. Anything else raises
    :class:`DataFileError`.

    The framework only checks two structural invariants -- top level is
    a dict, and an ``actors`` key is present. Everything else is
    system-specific and left to the sim to validate.
    """
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise DataFileError(f"failed to parse YAML in {path}: {exc}") from exc
    elif suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DataFileError(f"failed to parse JSON in {path}: {exc}") from exc
    else:
        raise DataFileError(
            f"unknown file extension {suffix!r} for {path} "
            "(expected .yaml / .yml / .json)"
        )

    if not isinstance(data, dict):
        raise DataFileError(
            f"top level of {path} must be a dict, got {type(data).__name__}"
        )
    if "actors" not in data:
        raise DataFileError(f"{path} missing required 'actors' key")
    return data


@dataclass
class RunArgs:
    """Argument bundle for a single run invocation.

    Built by the CLI from argparse output (or directly by tests / library
    callers) and passed to :func:`execute_run`. The CLI catches unknown
    flags after a ``--`` separator and bundles them into ``extra_args``;
    they flow through to every lifecycle hook as ``**extra_args``.
    """

    sim_module: ModuleType
    attackers_path: Path
    defenders_path: Path
    iterations: int
    seed: int
    postgres_url: str | None
    output_dir: Path
    quiet: bool = False
    progress_format: Literal["text", "json"] = "text"
    extra_args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimContract:
    run: Callable[..., Any]
    setup_once: Callable[..., Any] | None
    setup: Callable[..., Any] | None
    teardown: Callable[..., Any] | None
    teardown_once: Callable[..., Any] | None
    validate: Callable[..., Any] | None
    template: Callable[..., Any] | None
    sim_name: str
    sim_version: str
    system_name: str
    system_version: str
    outcomes: list[str]
    max_rounds: int | None
    default_iterations: int


_REQUIRED_ATTRS: tuple[str, ...] = (
    "run",
    "OUTCOMES",
    "SIM_NAME",
    "SIM_VERSION",
    "SYSTEM_NAME",
    "SYSTEM_VERSION",
)


def discover(sim_module: ModuleType) -> SimContract:
    """Read a sim module's documented attributes and return a SimContract.

    Required attributes (per DESIGN section 4.1): ``run``, ``OUTCOMES``,
    ``SIM_NAME``, ``SIM_VERSION``, ``SYSTEM_NAME``, ``SYSTEM_VERSION``.
    Missing any of these raises :class:`ConfigurationError`.

    Optional attributes (per DESIGN section 4.2) default as follows:

    * ``setup_once``, ``setup``, ``teardown``, ``teardown_once``,
      ``validate``, ``template`` -> ``None``
    * ``MAX_ROUNDS`` -> ``None``
    * ``DEFAULT_ITERATIONS`` -> :data:`DEFAULT_ITERATIONS` (500)
    """
    missing = [n for n in _REQUIRED_ATTRS if not hasattr(sim_module, n)]
    if missing:
        raise ConfigurationError(
            f"sim module {sim_module.__name__!r} is missing required "
            f"attribute(s): {', '.join(missing)}"
        )
    return SimContract(
        run=sim_module.run,
        setup_once=getattr(sim_module, "setup_once", None),
        setup=getattr(sim_module, "setup", None),
        teardown=getattr(sim_module, "teardown", None),
        teardown_once=getattr(sim_module, "teardown_once", None),
        validate=getattr(sim_module, "validate", None),
        template=getattr(sim_module, "template", None),
        sim_name=sim_module.SIM_NAME,
        sim_version=sim_module.SIM_VERSION,
        system_name=sim_module.SYSTEM_NAME,
        system_version=sim_module.SYSTEM_VERSION,
        outcomes=list(sim_module.OUTCOMES),
        max_rounds=getattr(sim_module, "MAX_ROUNDS", None),
        default_iterations=getattr(sim_module, "DEFAULT_ITERATIONS", DEFAULT_ITERATIONS),
    )


# --- default no-op hooks ----------------------------------------------------


def _make_default_setup_once(
    outcomes: list[str],
) -> Callable[..., Any]:
    """Construct a no-op ``setup_once`` for sims that don't declare one.

    Registers ``OUTCOMES`` under the ``outcome`` category, then freezes
    and returns the registry. This satisfies the contract that every
    run must have a frozen :class:`Registry` available before iteration
    begins (DESIGN section 4.2).
    """

    def _setup_once(
        *,
        attackers: dict[str, Any],  # noqa: ARG001
        defenders: dict[str, Any],  # noqa: ARG001
        registry_builder: RegistryBuilder,
        **extra_args: Any,  # noqa: ARG001
    ) -> Any:
        for outcome in outcomes:
            registry_builder.register("outcome", outcome)
        return registry_builder.freeze()

    return _setup_once


def _noop_per_iter(
    *,
    registry: Any,  # noqa: ARG001
    iteration_num: int,  # noqa: ARG001
    **extra_args: Any,  # noqa: ARG001
) -> None:
    return None


def _noop_teardown_once(
    *,
    registry: Any,  # noqa: ARG001
    **extra_args: Any,  # noqa: ARG001
) -> None:
    return None


# --- driver -----------------------------------------------------------------


def _serialize_cli_args(args: "RunArgs") -> dict[str, Any]:
    return {
        "iterations": args.iterations,
        "seed": args.seed,
        "postgres_url": args.postgres_url,
        "output_dir": str(args.output_dir),
        "attackers_path": str(args.attackers_path),
        "defenders_path": str(args.defenders_path),
        "quiet": args.quiet,
        "progress_format": args.progress_format,
        "extra_args": args.extra_args,
    }


def execute_run(args: RunArgs) -> UUID:
    """Drive a single run from start to finish.

    Steps (DESIGN section 4.4): generate run_id, load both data files,
    discover the sim contract, open the persistence context, seed
    framework defaults, store the actor files, build the registry,
    insert the runs row, call ``setup_once``, then iterate
    ``setup`` / ``run`` / ``teardown`` for each iteration writing every
    yielded event, call ``teardown_once``, mark the run complete, sync
    to Postgres if configured, close the context, and return the
    run_id.

    Partial-run state is recorded on the runs row regardless of how the
    loop exits: ``success`` on clean completion, ``error`` on
    exceptions, ``interrupted`` on KeyboardInterrupt. The original
    exception is re-raised after the runs row is updated.
    """
    run_id = uuid4()
    contract = discover(args.sim_module)
    attackers = load_data_file(args.attackers_path)
    defenders = load_data_file(args.defenders_path)

    ctx = create_context(
        run_id=run_id,
        postgres_url=args.postgres_url,
        output_dir=args.output_dir,
    )

    iterations_completed = 0
    terminated_reason = "error"
    success = False
    try:
        seed_framework_defaults(ctx)
        attacker_sha = store_file(ctx, attackers, args.attackers_path.name)
        defender_sha = store_file(ctx, defenders, args.defenders_path.name)
        builder = RegistryBuilder(persist=make_persist_fn(ctx))

        create_run_row(
            ctx,
            run_id=run_id,
            sim_name=contract.sim_name,
            sim_version=contract.sim_version,
            system_name=contract.system_name,
            system_version=contract.system_version,
            seed=args.seed,
            iterations_planned=args.iterations,
            attacker_file_id=attacker_sha,
            defender_file_id=defender_sha,
            cli_args=_serialize_cli_args(args),
        )

        setup_once = contract.setup_once or _make_default_setup_once(contract.outcomes)
        setup = contract.setup or _noop_per_iter
        teardown = contract.teardown or _noop_per_iter
        teardown_once = contract.teardown_once or _noop_teardown_once

        registry = setup_once(
            attackers=attackers,
            defenders=defenders,
            registry_builder=builder,
            **args.extra_args,
        )

        for iteration_num in range(args.iterations):
            # Per-iteration seed is computed for reproducibility; sims
            # that need it derive the same value via
            # derive_iteration_seed(args.seed, iteration_num).
            derive_iteration_seed(args.seed, iteration_num)
            setup(
                registry=registry,
                iteration_num=iteration_num,
                **args.extra_args,
            )
            try:
                events: Iterable[Event] = contract.run(
                    attackers=attackers,
                    defenders=defenders,
                    registry=registry,
                    iteration_num=iteration_num,
                    **args.extra_args,
                )
                for event in events:
                    write_event(ctx, run_id=run_id, event=event)
            finally:
                teardown(
                    registry=registry,
                    iteration_num=iteration_num,
                    **args.extra_args,
                )
            iterations_completed += 1

        teardown_once(registry=registry, **args.extra_args)

        terminated_reason = "success"
        success = True
    except KeyboardInterrupt:
        terminated_reason = "interrupted"
        raise
    except Exception:
        terminated_reason = "error"
        raise
    finally:
        update_run_completion(
            ctx,
            run_id=run_id,
            iterations_completed=iterations_completed,
            terminated_reason=terminated_reason,
        )
        if args.postgres_url is not None and success:
            sync_to_postgres(
                sqlite_path=ctx.sqlite_path,
                postgres_url=args.postgres_url,
            )
        close_context(ctx, success=success)

    return run_id
