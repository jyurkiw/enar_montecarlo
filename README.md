# enar_montecarlo

Monte Carlo simulation framework for tabletop RPG combat (and related mechanical resolution) experiments. The framework drives sims through a lifecycle harness, persists their event data into a normalized SQL schema (SQLite or Postgres), and provides a uniform CLI surface (`run`, `template`, `validate`, `info`, `sync`, `purge`, `list-runs`). It deliberately knows nothing about rolls, hits, saves, or any other game-mechanical concept — those live in system libraries.

## Install

Python 3.12 or newer.

```bash
pip install -e .[dev]
```

For Postgres-backed runs, also install the `postgres` extra:

```bash
pip install -e .[dev,postgres]
```

## Hello world

A sim is a Python package whose `__init__.py` exports the required attributes (`SIM_NAME`, `SIM_VERSION`, `SYSTEM_NAME`, `SYSTEM_VERSION`, `OUTCOMES`, `run`) plus optional lifecycle hooks. The canonical fixture sim used by the test suite lives at `tests/integration/fixtures/echo_sim/` and is a complete working example.

Run it directly:

```bash
PYTHONPATH=tests/integration/fixtures \
  python -m echo_sim run \
    tests/integration/fixtures/echo_sim/attackers.yaml \
    tests/integration/fixtures/echo_sim/defenders.yaml \
    --iterations 5 --seed 12345 --output-dir ./runs
```

stdout on success is the run UUID and nothing else, so you can pipe it:

```bash
RUN_ID=$(PYTHONPATH=tests/integration/fixtures \
  python -m echo_sim run a.yaml d.yaml --iterations 5 --quiet)
python -m echo_sim list-runs --output-dir ./runs | grep "$RUN_ID"
```

For the full CLI surface and idiomatic invocation patterns, see `skills/run/SKILL.md`.

## Next steps

- [`DESIGN.md`](DESIGN.md) — the architectural reference (sim contract, data file format, registry, event schema, DB schema, CLI surface, reproducibility, trade-offs).
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — the phased build plan, with each task's acceptance criteria.
- [`skills/run/SKILL.md`](skills/run/SKILL.md) — agent-facing skill for driving runs from the CLI.

## Tests

```bash
pytest                           # full suite
pytest --cov=enar_montecarlo     # with coverage report
ruff check src tests             # lint
mypy src/enar_montecarlo         # strict type-check
```

Postgres-mode tests are gated behind `POSTGRES_TEST_URL`; they're skipped when the env var is unset.

## License

TBD. Until a license is committed, treat this code as all-rights-reserved.
