"""Confirm ``python -m echo_sim run`` works as a real CLI invocation.

Subprocess test (slower than the in-process drives) so the P7 phase-end
checkbox "echo_sim is real and runnable as ``python -m echo_sim``"
has a green test backing it.
"""

import subprocess
import sys
from pathlib import Path
from uuid import UUID

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_python_dash_m_echo_sim_help_lists_subcommands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "echo_sim", "--help"],
        env={**dict(__import__("os").environ), "PYTHONPATH": str(_FIXTURES_DIR)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Commands:" in result.stdout
    for sub in ("run", "info", "list-runs", "purge", "sync", "template", "validate"):
        assert sub in result.stdout


def test_python_dash_m_echo_sim_run_emits_uuid_and_creates_sqlite(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "runs"
    a = _FIXTURES_DIR / "echo_sim" / "attackers.yaml"
    d = _FIXTURES_DIR / "echo_sim" / "defenders.yaml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "echo_sim",
            "run",
            str(a),
            str(d),
            "--iterations",
            "2",
            "--seed",
            "1",
            "--quiet",
            "--output-dir",
            str(out_dir),
        ],
        env={**dict(__import__("os").environ), "PYTHONPATH": str(_FIXTURES_DIR)},
        capture_output=True,
        text=True,
        check=True,
    )
    # stdout contract: a single line with the UUID.
    line = result.stdout.strip().splitlines()[-1]
    run_id = UUID(line)
    assert (out_dir / f"{run_id}.db").exists()


def test_python_dash_m_echo_sim_info_prints_metadata() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "echo_sim", "info"],
        env={**dict(__import__("os").environ), "PYTHONPATH": str(_FIXTURES_DIR)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "echo_sim" in result.stdout
    assert "echo_system" in result.stdout
