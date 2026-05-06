"""Discover a sim module's lifecycle hooks and metadata constants.

The framework imports a sim module and reads documented attributes off
it to build a :class:`SimContract`. Required attributes missing on the
module raise :class:`ConfigurationError` with all missing names in the
message; optional attributes fall back to documented defaults.

Also defines :class:`RunArgs`, the bundle the CLI assembles from
argparse output and hands to the driver.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

DEFAULT_ITERATIONS = 500
"""Fallback for ``DEFAULT_ITERATIONS`` when the sim does not declare one."""


class ConfigurationError(Exception):
    """A sim module is missing one or more required attributes."""


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
