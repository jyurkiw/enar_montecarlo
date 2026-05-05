"""Tests for resolve_path."""

import pytest

from enar_montecarlo.utils.path_resolver import resolve_path

# --- happy paths -------------------------------------------------------------


def test_simple_three_level_path() -> None:
    target = {"a": {"b": {"c": 42}}}
    assert resolve_path(target, "a.b.c") == 42


def test_single_key_path() -> None:
    assert resolve_path({"foo": "bar"}, "foo") == "bar"


def test_falsy_values_pass_through_unchanged() -> None:
    # Sentinel must distinguish "missing" from "explicitly falsy".
    assert resolve_path({"a": {"b": 0}}, "a.b") == 0
    assert resolve_path({"a": {"b": ""}}, "a.b") == ""
    assert resolve_path({"a": {"b": None}}, "a.b") is None
    assert resolve_path({"a": {"b": []}}, "a.b") == []
    assert resolve_path({"a": {"b": {}}}, "a.b") == {}


# --- missing keys ------------------------------------------------------------


def test_missing_key_with_default_returns_default() -> None:
    assert resolve_path({"a": {"b": 1}}, "a.missing", default=99) == 99


def test_missing_key_with_default_none_returns_none() -> None:
    # Sentinel must allow None as an explicit default.
    assert resolve_path({"a": {"b": 1}}, "a.missing", default=None) is None


def test_top_level_missing_key_with_default() -> None:
    assert resolve_path({"a": 1}, "missing", default="fallback") == "fallback"


def test_missing_key_without_default_raises_key_error() -> None:
    with pytest.raises(KeyError) as exc:
        resolve_path({"a": {"b": 1}}, "a.missing")
    # Full path is in the error so the caller can locate the failure.
    assert "a.missing" in str(exc.value)


def test_top_level_missing_key_without_default_raises_key_error() -> None:
    with pytest.raises(KeyError):
        resolve_path({"a": 1}, "missing")


# --- structural errors (always raise; default does not suppress) -------------


def test_empty_path_raises_value_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        resolve_path({"a": 1}, "")


def test_empty_path_raises_value_error_even_with_default() -> None:
    with pytest.raises(ValueError, match="empty"):
        resolve_path({"a": 1}, "", default="ignored")


def test_non_dict_intermediate_raises_type_error() -> None:
    with pytest.raises(TypeError, match="non-dict"):
        resolve_path({"a": [1, 2, 3]}, "a.b")


def test_non_dict_intermediate_raises_type_error_even_with_default() -> None:
    with pytest.raises(TypeError, match="non-dict"):
        resolve_path({"a": "string-not-dict"}, "a.b", default="ignored")


def test_non_dict_at_deeper_level_raises() -> None:
    with pytest.raises(TypeError):
        resolve_path({"a": {"b": 5}}, "a.b.c")
