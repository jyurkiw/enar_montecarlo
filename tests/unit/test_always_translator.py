"""Tests for ``expand_always`` -- foundational, exhaustively covered.

Cases mirror the acceptance criteria from the implementation plan:
empty/absent always, 5e and PF2e shapes, unknown branch keys, missing
outcomes, and input-immutability guarantees.
"""

import copy

import pytest

from enar_montecarlo.utils.always_translator import expand_always

OUTCOMES_5E = ["success", "failure"]
OUTCOMES_PF2E = ["critical_success", "success", "failure", "critical_failure"]


# --- happy paths -------------------------------------------------------------


def test_empty_always_is_noop_for_5e_shape() -> None:
    branches = {"success": ["a"], "failure": ["b"], "always": []}
    assert expand_always(branches, OUTCOMES_5E) == {"success": ["a"], "failure": ["b"]}


def test_always_absent_returns_branches_for_listed_outcomes() -> None:
    branches = {"success": ["a"], "failure": ["b"]}
    assert expand_always(branches, OUTCOMES_5E) == {"success": ["a"], "failure": ["b"]}


def test_always_with_one_entry_and_5e_shape() -> None:
    branches = {"success": ["a"], "failure": ["b"], "always": ["log"]}
    assert expand_always(branches, OUTCOMES_5E) == {
        "success": ["a", "log"],
        "failure": ["b", "log"],
    }


def test_always_with_two_entries_and_pf2e_shape() -> None:
    branches = {
        "critical_success": ["c"],
        "success": ["s"],
        "failure": ["f"],
        "critical_failure": ["cf"],
        "always": ["x", "y"],
    }
    assert expand_always(branches, OUTCOMES_PF2E) == {
        "critical_success": ["c", "x", "y"],
        "success": ["s", "x", "y"],
        "failure": ["f", "x", "y"],
        "critical_failure": ["cf", "x", "y"],
    }


# --- missing-outcome cases ---------------------------------------------------


def test_outcome_listed_but_missing_from_branches_gets_always_only() -> None:
    branches = {"success": ["a"], "always": ["log"]}
    assert expand_always(branches, OUTCOMES_5E) == {
        "success": ["a", "log"],
        "failure": ["log"],
    }


def test_outcome_listed_but_missing_with_no_always_gets_empty_list() -> None:
    branches = {"success": ["a"]}
    assert expand_always(branches, OUTCOMES_5E) == {"success": ["a"], "failure": []}


# --- pass-through of unknown branch keys -------------------------------------


def test_unknown_branch_key_passes_through_unchanged() -> None:
    branches = {"success": ["a"], "weird_key": ["w"], "always": ["log"]}
    assert expand_always(branches, OUTCOMES_5E) == {
        "success": ["a", "log"],
        "failure": ["log"],
        "weird_key": ["w"],
    }


def test_no_outcomes_and_no_always_returns_passthrough_only() -> None:
    branches = {"unknown": ["u"]}
    assert expand_always(branches, []) == {"unknown": ["u"]}


def test_no_outcomes_and_always_present_does_not_orphan_always() -> None:
    # ``always`` is consumed; with no outcomes, no branch receives it.
    branches = {"always": ["log"]}
    assert expand_always(branches, []) == {}


def test_always_key_never_appears_in_result() -> None:
    branches = {"success": ["a"], "always": ["log"]}
    assert "always" not in expand_always(branches, ["success"])


# --- purity / immutability ---------------------------------------------------


def test_does_not_mutate_input_branches() -> None:
    branches = {"success": ["a"], "failure": ["b"], "always": ["log"]}
    snapshot = copy.deepcopy(branches)
    expand_always(branches, OUTCOMES_5E)
    assert branches == snapshot


def test_does_not_mutate_input_outcomes() -> None:
    branches = {"success": ["a"], "always": ["log"]}
    outcomes = list(OUTCOMES_5E)
    snapshot = list(outcomes)
    expand_always(branches, outcomes)
    assert outcomes == snapshot


def test_named_outcome_lists_are_independent_of_input_lists() -> None:
    success_list = ["a"]
    always_list = ["log"]
    branches = {"success": success_list, "always": always_list}
    result = expand_always(branches, ["success"])
    result["success"].append("mutated")
    assert success_list == ["a"]
    assert always_list == ["log"]


def test_passthrough_lists_are_independent_of_input_lists() -> None:
    weird = ["w"]
    branches = {"weird_key": weird}
    result = expand_always(branches, [])
    result["weird_key"].append("mutated")
    assert weird == ["w"]


# --- table-driven sanity check ----------------------------------------------


@pytest.mark.parametrize(
    ("branches", "outcomes", "expected"),
    [
        # Empty always, 5e
        (
            {"success": [1], "failure": [2], "always": []},
            OUTCOMES_5E,
            {"success": [1], "failure": [2]},
        ),
        # Single always, 5e
        (
            {"success": [1], "failure": [2], "always": [9]},
            OUTCOMES_5E,
            {"success": [1, 9], "failure": [2, 9]},
        ),
        # Multiple always, PF2e
        (
            {
                "critical_success": [1],
                "success": [2],
                "failure": [3],
                "critical_failure": [4],
                "always": [9, 10],
            },
            OUTCOMES_PF2E,
            {
                "critical_success": [1, 9, 10],
                "success": [2, 9, 10],
                "failure": [3, 9, 10],
                "critical_failure": [4, 9, 10],
            },
        ),
        # Heterogeneous entries (str + dict, per DESIGN section 5.5)
        (
            {
                "success": ["bare_ref", {"ref": "gated", "trigger": "trig"}],
                "failure": [],
                "always": [],
            },
            OUTCOMES_5E,
            {
                "success": ["bare_ref", {"ref": "gated", "trigger": "trig"}],
                "failure": [],
            },
        ),
    ],
)
def test_expand_always_table_driven(
    branches: dict[str, list[object]],
    outcomes: list[str],
    expected: dict[str, list[object]],
) -> None:
    assert expand_always(branches, outcomes) == expected
