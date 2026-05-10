"""echo_sim -- the canonical fixture sim for integration tests.

Also a runnable sim per the framework contract: ``python -m echo_sim
run a.yaml d.yaml`` works when the fixtures dir is on sys.path
(e.g., ``PYTHONPATH=tests/integration/fixtures``). The CLI wiring at
the end of this module is the same boilerplate every real sim package
will use.


Per DESIGN's contract a sim is a Python package whose ``__init__.py``
exports the required attributes plus optional hooks. This fixture
exercises every event type, every effect_type value, branch and
trigger gating, the ``always`` semantic, custom-effect notes payload,
both markers, and ``caused_by_seq`` chains -- so an end-to-end run
against it asserts the full event-to-row pipeline.

Per-iteration emission (8 yielded events, 6 DB rows -- markers do
not persist):

1. ResolutionEvent  outcome=pass, event_seq=1
2. EffectEvent      branch=pass,  caused_by_seq=1, event_seq=2  (no trigger)
3. EffectEvent      branch=pass,  caused_by_seq=1, event_seq=3
                                  trigger gated on extra_args["sneaky"]
                                  (when False -> trigger_result=False, amount=None)
4. ResolutionEvent  outcome=fail, event_seq=4, caused_by_seq=1
5. EffectEvent      branch=fail,  caused_by_seq=4, event_seq=5
6. EffectEvent      effect_type=custom, event_seq=6, caused_by_seq=1
                                  notes={"system_extra": ..., "iter": iteration_num}
7. RoundCompleteMarker
8. SimulationCompleteMarker
"""

from collections.abc import Iterator
from typing import Any

from enar_montecarlo import main
from enar_montecarlo.events import (
    EffectEvent,
    Event,
    ResolutionEvent,
    RoundCompleteMarker,
    SimulationCompleteMarker,
)
from enar_montecarlo.persistence.files import canonical_sha256
from enar_montecarlo.registry import RegistryBuilder

# --- required attributes (DESIGN section 4.1) -------------------------------

SIM_NAME = "echo_sim"
SIM_VERSION = "0.1.0"
SYSTEM_NAME = "echo_system"
SYSTEM_VERSION = "0.1.0"
OUTCOMES = ["pass", "fail"]

# --- optional attributes (DESIGN section 4.2) ------------------------------

DEFAULT_ITERATIONS = 1
MAX_ROUNDS = 1

# --- hot-path id cache populated in setup_once ------------------------------

_PASS_ID: int | None = None
_FAIL_ID: int | None = None
_DAMAGE_TYPE_FIRE_ID: int | None = None
_BRANCH_PASS_ID: int | None = None
_BRANCH_FAIL_ID: int | None = None
_EFFECT_TYPE_DAMAGE_ID: int | None = None
_EFFECT_TYPE_CUSTOM_ID: int | None = None
_TRIGGER_SNEAK_ID: int | None = None

# Actor file SHAs computed in setup_once. The framework hashes the
# attacker / defender data files via canonical_sha256 inside store_file;
# we replicate that derivation here so emitted events satisfy the
# actor_files FK without the framework having to thread the SHAs into
# the hook signatures.
_ATTACKER_SHA: str = ""
_DEFENDER_SHA: str = ""


# --- lifecycle hooks --------------------------------------------------------


def setup_once(
    *,
    attackers: dict[str, Any],
    defenders: dict[str, Any],
    registry_builder: RegistryBuilder,
    **_extra: Any,
) -> Any:
    global _PASS_ID, _FAIL_ID, _DAMAGE_TYPE_FIRE_ID
    global _BRANCH_PASS_ID, _BRANCH_FAIL_ID
    global _EFFECT_TYPE_DAMAGE_ID, _EFFECT_TYPE_CUSTOM_ID
    global _TRIGGER_SNEAK_ID
    global _ATTACKER_SHA, _DEFENDER_SHA

    _PASS_ID = registry_builder.register("outcome", "pass")
    _FAIL_ID = registry_builder.register("outcome", "fail")
    _DAMAGE_TYPE_FIRE_ID = registry_builder.register("damage_type", "fire")
    _BRANCH_PASS_ID = registry_builder.register("branch", "pass")
    _BRANCH_FAIL_ID = registry_builder.register("branch", "fail")
    _EFFECT_TYPE_DAMAGE_ID = registry_builder.register("effect_type", "damage")
    _EFFECT_TYPE_CUSTOM_ID = registry_builder.register("effect_type", "custom")
    _TRIGGER_SNEAK_ID = registry_builder.register("trigger", "sneak_attack_eligible")

    _ATTACKER_SHA = canonical_sha256(attackers)
    _DEFENDER_SHA = canonical_sha256(defenders)

    return registry_builder.freeze()


def setup(*, registry: Any, iteration_num: int, **_extra: Any) -> None:  # noqa: ARG001
    return None


def teardown(*, registry: Any, iteration_num: int, **_extra: Any) -> None:  # noqa: ARG001
    return None


def teardown_once(*, registry: Any, **_extra: Any) -> None:  # noqa: ARG001
    return None


def template() -> dict[str, Any]:
    return {
        "metadata": {"system": SYSTEM_NAME, "system_version": SYSTEM_VERSION},
        "actors": [{"name": "echo", "count": 1, "clumping": 1}],
    }


def validate(attackers: dict[str, Any], defenders: dict[str, Any]) -> list[str]:  # noqa: ARG001
    # Always clean -- echo_sim is a fixture, not a real sim.
    return []


def run(
    *,
    attackers: dict[str, Any],  # noqa: ARG001
    defenders: dict[str, Any],  # noqa: ARG001
    registry: Any,  # noqa: ARG001
    iteration_num: int,
    **extra: Any,
) -> Iterator[Event]:
    """Per-iteration emission. See module docstring for the full sequence."""
    assert _PASS_ID is not None  # pragma: no cover -- setup_once invariant

    sneaky = bool(extra.get("sneaky", False))

    # 1. resolution -> pass
    yield ResolutionEvent(
        event_seq=1,
        iteration_num=iteration_num,
        actor_file_id=_ATTACKER_SHA,
        actor_index=0,
        target_file_id=_DEFENDER_SHA,
        target_index=0,
        resolution_name="echo_pass",
        outcome_id=_PASS_ID,
        notes={"phase": "pass"},
    )
    # 2. effect on the pass branch (no trigger)
    yield EffectEvent(
        event_seq=2,
        iteration_num=iteration_num,
        actor_file_id=_ATTACKER_SHA,
        actor_index=0,
        target_file_id=_DEFENDER_SHA,
        target_index=0,
        effect_definition_name="pass_damage",
        effect_type_id=_EFFECT_TYPE_DAMAGE_ID,  # type: ignore[arg-type]
        damage_type_id=_DAMAGE_TYPE_FIRE_ID,
        amount=4.0,
        source_branch_id=_BRANCH_PASS_ID,  # type: ignore[arg-type]
        caused_by_seq=1,
    )
    # 3. effect on the pass branch, gated on extra_args["sneaky"]
    yield EffectEvent(
        event_seq=3,
        iteration_num=iteration_num,
        actor_file_id=_ATTACKER_SHA,
        actor_index=0,
        target_file_id=_DEFENDER_SHA,
        target_index=0,
        effect_definition_name="pass_sneak_bonus",
        effect_type_id=_EFFECT_TYPE_DAMAGE_ID,  # type: ignore[arg-type]
        damage_type_id=_DAMAGE_TYPE_FIRE_ID,
        amount=2.0 if sneaky else None,
        source_branch_id=_BRANCH_PASS_ID,  # type: ignore[arg-type]
        caused_by_seq=1,
        trigger_name="sneak_attack_eligible",
        trigger_result=sneaky,
    )
    # 4. resolution -> fail, caused by the first
    yield ResolutionEvent(
        event_seq=4,
        iteration_num=iteration_num,
        actor_file_id=_ATTACKER_SHA,
        actor_index=0,
        target_file_id=_DEFENDER_SHA,
        target_index=0,
        resolution_name="echo_fail",
        outcome_id=_FAIL_ID,  # type: ignore[arg-type]
        caused_by_seq=1,
        notes={"phase": "fail"},
    )
    # 5. effect on the fail branch
    yield EffectEvent(
        event_seq=5,
        iteration_num=iteration_num,
        actor_file_id=_ATTACKER_SHA,
        actor_index=0,
        target_file_id=_DEFENDER_SHA,
        target_index=0,
        effect_definition_name="fail_recoil",
        effect_type_id=_EFFECT_TYPE_DAMAGE_ID,  # type: ignore[arg-type]
        amount=1.0,
        source_branch_id=_BRANCH_FAIL_ID,  # type: ignore[arg-type]
        caused_by_seq=4,
    )
    # 6. custom-type effect with a system-specific notes payload
    yield EffectEvent(
        event_seq=6,
        iteration_num=iteration_num,
        actor_file_id=_ATTACKER_SHA,
        actor_index=0,
        effect_definition_name="echo_custom_marker",
        effect_type_id=_EFFECT_TYPE_CUSTOM_ID,  # type: ignore[arg-type]
        source_branch_id=_BRANCH_PASS_ID,  # type: ignore[arg-type]
        caused_by_seq=1,
        notes={"system_extra": "echo", "iter": iteration_num},
    )
    # 7-8. markers (not persisted)
    yield RoundCompleteMarker(event_seq=7, iteration_num=iteration_num, round_num=1)
    yield SimulationCompleteMarker(
        event_seq=8, iteration_num=iteration_num, rounds_executed=1
    )


# CLI entry point. With ``__name__ == "__main__"`` (i.e. via
# ``python -m echo_sim``) the framework introspects this module as
# the sim and dispatches the requested subcommand.
if __name__ == "__main__":  # pragma: no cover
    main()
