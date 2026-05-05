"""Tests for RegistryBuilder and the dynamic Registry namedtuple."""

import copy
from typing import Any

import pytest

from enar_montecarlo.registry import RegistryBuilder


def _seq_persist() -> tuple[Any, list[tuple[str, str]]]:
    """Sequential persist for tests. Records each call. Same (cat, name)
    returns the same id (mimics DB ON CONFLICT semantics)."""
    calls: list[tuple[str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    counter = 0

    def persist(category: str, name: str) -> int:
        nonlocal counter
        calls.append((category, name))
        key = (category, name)
        if key not in seen:
            counter += 1
            seen[key] = counter
        return seen[key]

    return persist, calls


# --- register ---------------------------------------------------------------


def test_register_returns_persist_assigned_id() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    assert b.register("outcome", "miss") == 1
    assert b.register("outcome", "hit") == 2


def test_register_idempotent_within_builder() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    first = b.register("outcome", "miss")
    again = b.register("outcome", "miss")
    assert first == again


def test_register_calls_persist_exactly_once_per_unique_pair() -> None:
    persist, calls = _seq_persist()
    b = RegistryBuilder(persist=persist)
    b.register("outcome", "miss")
    b.register("outcome", "miss")  # cache hit -> no call
    b.register("outcome", "hit")
    b.register("damage_type", "fire")
    b.register("damage_type", "fire")  # cache hit -> no call
    assert calls == [
        ("outcome", "miss"),
        ("outcome", "hit"),
        ("damage_type", "fire"),
    ]


@pytest.mark.parametrize(
    "bad_category",
    ["", "1starts_with_digit", "has-dash", "has space", "with.dot", "no/slash"],
)
def test_register_invalid_identifier_category_raises(bad_category: str) -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    with pytest.raises(ValueError, match="not a valid Python identifier"):
        b.register(bad_category, "value")


@pytest.mark.parametrize("kw", ["class", "for", "import", "lambda"])
def test_register_python_keyword_category_raises(kw: str) -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    with pytest.raises(ValueError, match="keyword"):
        b.register(kw, "value")


def test_register_underscore_prefix_category_raises() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    with pytest.raises(ValueError, match="underscore"):
        b.register("_private", "value")


def test_invalid_category_does_not_persist() -> None:
    persist, calls = _seq_persist()
    b = RegistryBuilder(persist=persist)
    with pytest.raises(ValueError):
        b.register("bad-name", "value")
    assert calls == []


# --- freeze ----------------------------------------------------------------


def test_freeze_class_name_is_Registry() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    b.register("outcome", "miss")
    r = b.freeze()
    assert type(r).__name__ == "Registry"


def test_registry_attribute_returns_category_dict() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    b.register("outcome", "miss")
    b.register("outcome", "hit")
    b.register("damage_type", "fire")
    r = b.freeze()
    assert r.outcome == {"miss": 1, "hit": 2}
    assert r.outcome["miss"] == 1
    assert r.damage_type == {"fire": 3}


def test_registry_field_order_matches_registration_order() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    b.register("damage_type", "fire")
    b.register("outcome", "miss")
    r = b.freeze()
    assert r._fields == ("damage_type", "outcome")


def test_registry_attribute_reassignment_raises() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    b.register("outcome", "miss")
    r = b.freeze()
    with pytest.raises(AttributeError):
        r.outcome = {"hacked": 99}


def test_registry_deepcopy_produces_independent_state() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    b.register("outcome", "miss")
    r = b.freeze()
    rc = copy.deepcopy(r)
    rc.outcome["new"] = 99
    assert "new" not in r.outcome
    assert rc.outcome["new"] == 99


def test_freeze_with_no_registrations_is_empty_namedtuple() -> None:
    persist, _ = _seq_persist()
    b = RegistryBuilder(persist=persist)
    r = b.freeze()
    assert type(r).__name__ == "Registry"
    assert tuple(r) == ()
    assert r._fields == ()


