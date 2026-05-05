"""Tests for lifecycle.discover and SimContract."""

import dataclasses
import types
from typing import Any

import pytest

from enar_montecarlo.lifecycle import (
    DEFAULT_ITERATIONS,
    ConfigurationError,
    SimContract,
    discover,
)


def _minimal_module(name: str = "fake_sim") -> types.ModuleType:
    """Synthetic sim module with only the required attributes set."""
    m = types.ModuleType(name)
    m.run = lambda **_: iter(())
    m.OUTCOMES = ["success", "failure"]
    m.SIM_NAME = "fake"
    m.SIM_VERSION = "0.1.0"
    m.SYSTEM_NAME = "system_x"
    m.SYSTEM_VERSION = "1.0.0"
    return m


# --- happy paths -------------------------------------------------------------


def test_discover_populates_required_fields() -> None:
    m = _minimal_module()
    c = discover(m)
    assert c.run is m.run
    assert c.outcomes == ["success", "failure"]
    assert c.sim_name == "fake"
    assert c.sim_version == "0.1.0"
    assert c.system_name == "system_x"
    assert c.system_version == "1.0.0"


def test_discover_returns_sim_contract_instance() -> None:
    c = discover(_minimal_module())
    assert isinstance(c, SimContract)


def test_discover_outcomes_normalizes_tuple_to_list() -> None:
    m = _minimal_module()
    m.OUTCOMES = ("success", "failure")
    c = discover(m)
    assert c.outcomes == ["success", "failure"]
    assert isinstance(c.outcomes, list)


def test_discover_outcomes_does_not_share_storage_with_sim() -> None:
    # Post-discovery sim mutations of OUTCOMES must not affect the
    # frozen contract.
    m = _minimal_module()
    sim_outcomes = ["success", "failure"]
    m.OUTCOMES = sim_outcomes
    c = discover(m)
    assert c.outcomes is not sim_outcomes
    sim_outcomes.append("crit")
    assert "crit" not in c.outcomes


# --- optional attributes default correctly -----------------------------------


def test_optional_hooks_default_to_None() -> None:
    c = discover(_minimal_module())
    assert c.setup_once is None
    assert c.setup is None
    assert c.teardown is None
    assert c.teardown_once is None
    assert c.validate is None
    assert c.template is None


def test_max_rounds_defaults_to_None() -> None:
    c = discover(_minimal_module())
    assert c.max_rounds is None


def test_default_iterations_falls_back_to_500() -> None:
    c = discover(_minimal_module())
    assert c.default_iterations == 500
    assert DEFAULT_ITERATIONS == 500


# --- optional attributes are picked up when set ------------------------------


def test_optional_hooks_picked_up_when_set() -> None:
    m = _minimal_module()

    def _hook(**_: Any) -> None:
        return None

    def _validate(*_: Any) -> None:
        return None

    def _template() -> dict[str, Any]:
        return {}

    m.setup_once = _hook
    m.setup = _hook
    m.teardown = _hook
    m.teardown_once = _hook
    m.validate = _validate
    m.template = _template
    c = discover(m)
    assert c.setup_once is _hook
    assert c.setup is _hook
    assert c.teardown is _hook
    assert c.teardown_once is _hook
    assert c.validate is _validate
    assert c.template is _template


def test_max_rounds_picked_up_when_set() -> None:
    m = _minimal_module()
    m.MAX_ROUNDS = 5
    assert discover(m).max_rounds == 5


def test_default_iterations_picked_up_when_set() -> None:
    m = _minimal_module()
    m.DEFAULT_ITERATIONS = 123
    assert discover(m).default_iterations == 123


# --- missing required attributes --------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["run", "OUTCOMES", "SIM_NAME", "SIM_VERSION", "SYSTEM_NAME", "SYSTEM_VERSION"],
)
def test_missing_required_raises_with_attr_in_message(missing: str) -> None:
    m = _minimal_module()
    delattr(m, missing)
    with pytest.raises(ConfigurationError) as exc:
        discover(m)
    assert missing in str(exc.value)


def test_missing_required_lists_all_missing_attrs() -> None:
    m = _minimal_module()
    delattr(m, "run")
    delattr(m, "OUTCOMES")
    delattr(m, "SIM_VERSION")
    with pytest.raises(ConfigurationError) as exc:
        discover(m)
    msg = str(exc.value)
    assert "run" in msg
    assert "OUTCOMES" in msg
    assert "SIM_VERSION" in msg


def test_missing_required_includes_module_name_in_message() -> None:
    m = _minimal_module(name="my_broken_sim")
    delattr(m, "run")
    with pytest.raises(ConfigurationError, match="my_broken_sim"):
        discover(m)


# --- frozen dataclass --------------------------------------------------------


def test_sim_contract_is_frozen() -> None:
    c = discover(_minimal_module())
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.sim_name = "hacked"  # type: ignore[misc]
