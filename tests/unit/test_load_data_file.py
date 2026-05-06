"""Tests for load_data_file."""

import json
from pathlib import Path

import pytest

from enar_montecarlo.lifecycle import DataFileError, load_data_file

_VALID = {
    "metadata": {"system": "dnd5e_2024", "system_version": "0.1.0"},
    "actors": [{"name": "fighter", "count": 1, "clumping": 1}],
}


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


# --- happy paths -------------------------------------------------------------


def test_loads_yaml(tmp_path: Path) -> None:
    yaml_text = (
        "metadata:\n"
        "  system: dnd5e_2024\n"
        "actors:\n"
        "  - name: fighter\n"
        "    count: 1\n"
        "    clumping: 1\n"
    )
    p = _write(tmp_path / "f.yaml", yaml_text)
    data = load_data_file(p)
    assert data["actors"][0]["name"] == "fighter"


def test_loads_yml_extension(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.yml", "actors: []\n")
    assert load_data_file(p) == {"actors": []}


def test_loads_json(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.json", json.dumps(_VALID))
    data = load_data_file(p)
    assert data == _VALID


def test_extension_match_is_case_insensitive(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.YAML", "actors: []\n")
    assert load_data_file(p) == {"actors": []}


# --- structural invariants ---------------------------------------------------


def test_non_dict_top_level_raises(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.yaml", "- 1\n- 2\n- 3\n")
    with pytest.raises(DataFileError, match="must be a dict"):
        load_data_file(p)


def test_missing_actors_key_raises(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.yaml", "metadata:\n  system: x\n")
    with pytest.raises(DataFileError, match="actors"):
        load_data_file(p)


# --- parse / extension errors ------------------------------------------------


def test_unknown_extension_raises(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.txt", "anything")
    with pytest.raises(DataFileError, match="unknown file extension"):
        load_data_file(p)


def test_broken_yaml_raises(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.yaml", "key: : :\nactors: [\n")
    with pytest.raises(DataFileError, match="failed to parse YAML"):
        load_data_file(p)


def test_broken_json_raises(tmp_path: Path) -> None:
    p = _write(tmp_path / "f.json", "{ not valid json }")
    with pytest.raises(DataFileError, match="failed to parse JSON"):
        load_data_file(p)


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_data_file(tmp_path / "missing.yaml")
