"""Tests for the ``purge`` CLI subcommand."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner

from enar_montecarlo.cli.main import _build_cli
from enar_montecarlo.persistence import sessions as sess_mod


def _put_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, Path]:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    run_id = uuid4()
    path = tmp_path / f"{run_id}.db"
    path.write_bytes(b"fake-sqlite-content")
    return run_id, path


def test_purge_with_yes_deletes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, path = _put_file(tmp_path, monkeypatch)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["purge", str(run_id), "--yes"])
    assert result.exit_code == 0
    assert "deleted" in result.output
    assert not path.exists()


def test_purge_missing_file_is_noop_with_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sess_mod, "_default_temp_dir", lambda: tmp_path)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["purge", str(uuid4()), "--yes"])
    assert result.exit_code == 0
    assert "no SQLite file found" in result.output


def test_purge_confirm_prompt_y_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, path = _put_file(tmp_path, monkeypatch)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["purge", str(run_id)], input="y\n")
    assert result.exit_code == 0
    assert not path.exists()


def test_purge_confirm_prompt_n_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, path = _put_file(tmp_path, monkeypatch)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["purge", str(run_id)], input="n\n")
    assert result.exit_code != 0  # click.confirm(abort=True) -> Abort
    assert path.exists()


def test_purge_invalid_uuid_errors(tmp_path: Path) -> None:
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["purge", "not-a-uuid", "--yes"])
    assert result.exit_code != 0


def test_purge_does_not_require_sim_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _ = _put_file(tmp_path, monkeypatch)
    cli = _build_cli(sim_module=None)
    result = CliRunner().invoke(cli, ["purge", str(run_id), "--yes"])
    assert result.exit_code == 0
