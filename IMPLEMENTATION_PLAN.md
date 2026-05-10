# enar_montecarlo — Implementation Plan

This document is for claude-code (or another implementation agent). It assumes `DESIGN.md` is the authoritative reference and breaks the work into discrete, sequenced tasks with clear acceptance criteria.

## Reading order

1. `DESIGN.md` — read fully before starting any task
2. This file — work tasks in order; do not skip phases
3. Per-phase READMEs (created during P0) — phase-specific notes

## Working agreement

- Use Python 3.12+. Type-annotate aggressively. Pydantic v2.
- Test as you go. No task is "complete" without its tests passing.
- One commit per task minimum. Use task IDs in commit messages: `[P1.3] add RegistryBuilder`.
- When ambiguous, surface the question instead of guessing. Note the resolution in the relevant phase README.
- Do not invent features beyond `DESIGN.md`. If something is missing, ask.
- Do not skip the "always" branch translator's exhaustive test cases. That function is foundational; bugs there corrupt every event downstream.

## Repo layout

```
enar_montecarlo/
├── pyproject.toml
├── README.md
├── DESIGN.md
├── IMPLEMENTATION_PLAN.md          (this file)
├── src/
│   └── enar_montecarlo/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py             (entry point)
│       │   ├── commands/           (one module per subcommand)
│       │   │   ├── run.py
│       │   │   ├── template.py
│       │   │   ├── validate.py
│       │   │   ├── info.py
│       │   │   ├── sync.py
│       │   │   ├── purge.py
│       │   │   └── list_runs.py
│       │   └── progress.py         (Rich progress bars)
│       ├── events.py               (Pydantic event models)
│       ├── registry.py             (RegistryBuilder, Registry namedtuple factory)
│       ├── lifecycle.py            (hook discovery, lifecycle driver)
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── schema.py           (SQLAlchemy ORM models)
│       │   ├── sessions.py         (SQLite + Postgres connection mgmt)
│       │   ├── values.py           (values table seeding + registration)
│       │   ├── files.py            (actor_files SHA256 storage)
│       │   ├── writes.py           (event writers)
│       │   └── sync.py             (SQLite → Postgres bulk copy)
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── path_resolver.py
│       │   ├── always_translator.py
│       │   └── jsonl.py
│       └── seeding.py              (per-iteration seed derivation)
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_path_resolver.py
│   │   ├── test_always_translator.py
│   │   ├── test_registry.py
│   │   ├── test_events.py
│   │   ├── test_jsonl.py
│   │   ├── test_seeding.py
│   │   └── test_lifecycle.py
│   ├── persistence/
│   │   ├── test_schema.py
│   │   ├── test_values.py
│   │   ├── test_files.py
│   │   └── test_sync.py
│   ├── integration/
│   │   ├── test_run_end_to_end.py
│   │   └── fixtures/
│   │       └── echo_sim/           (fixture sim, see DESIGN §14.4)
│   └── smoke/
│       └── test_post_run_db.py
├── skills/
│   └── run/
│       └── SKILL.md                (run skill for cowork)
└── docs/
    └── (developer notes, generated as needed)
```

---

# Phases

Phases are sequential. P0 → P1 → P2 → ... Each phase has:

- A goal statement
- A list of tasks with IDs (`P{phase}.{task}`)
- Per-task: deliverable, acceptance criteria, dependencies
- A phase-end checklist before moving on

Estimated rough sizing in parens after each task is for ordering purposes only.

---

## P0 — Project Bootstrap

**Goal:** A clean, installable, testable skeleton with all dependencies resolved.

### P0.1 Initialize repository (S) — [x] Done

- Create the repo layout above (empty modules, `__init__.py` files, empty test files).
- `pyproject.toml` with:
  - Build backend: hatchling
  - Python ≥ 3.12
  - `src/` layout
  - Project metadata (name=`enar_montecarlo`, version=`0.1.0`)
  - Dependencies: `pydantic >= 2.6`, `sqlalchemy >= 2.0`, `pyyaml`, `rich`, `click` OR stdlib argparse (decide; click is recommended for subcommand ergonomics)
  - Optional dependencies: `psycopg[binary]` under `[postgres]`, `docker` under `[docker]`
  - Dev dependencies under `[dev]`: `pytest`, `pytest-cov`, `mypy`, `ruff`
- `.gitignore` for Python projects (`__pycache__`, `dist/`, `.venv/`, `.pytest_cache`, `*.db` in repo root for stray test DBs).
- `README.md` with one paragraph + a pointer to `DESIGN.md`.

**Acceptance:** `pip install -e .[dev]` succeeds in a fresh venv. `pytest` runs (zero tests, zero failures).

### P0.2 Lint and type-check baseline (S) — [x] Done

- `ruff` config: project's preferred rules (suggest `E`, `F`, `I`, `UP`, `B`, `SIM`).
- `mypy` config: strict on `src/enar_montecarlo`.
- Pre-commit config (optional but recommended).

**Acceptance:** `ruff check src tests` and `mypy src/enar_montecarlo` both clean on the empty skeleton.

### P0.3 CI minimum (S, optional but recommended) — [x] Done

- GitHub Actions workflow running `pytest`, `ruff`, `mypy` on push/PR.

**Acceptance:** Workflow file exists; passes on the empty skeleton.

### P0 phase-end checklist

- [x] Layout in place
- [x] `pip install -e .[dev]` works
- [x] `pytest` runs
- [x] `ruff` and `mypy` clean

---

## P1 — Core Data Models and Pure Utilities

**Goal:** All the pieces that don't touch a database. Pure Python, fully unit-tested. These are the foundation everything else depends on.

### P1.1 Pydantic event models (M) — [x] Done

**Module:** `src/enar_montecarlo/events.py`

Implement `ResolutionEvent`, `EffectEvent`, `RoundCompleteMarker`, `SimulationCompleteMarker`, and the `Event` discriminated union per `DESIGN §7.1`.

**Acceptance:**
- Each model parses valid input, rejects invalid input with clear errors
- Discriminated union round-trips: `Event.model_validate(json_dict)` returns the right concrete subclass for each `type` value
- `model_dump_json()` produces compact JSON
- 100% test coverage on `events.py`
- Tests in `tests/unit/test_events.py`

### P1.2 The "always" branch translator (S) — [x] Done

**Module:** `src/enar_montecarlo/utils/always_translator.py`

Pure function per `DESIGN §5.6`:

```python
def expand_always(branches: dict[str, list], outcomes: list[str]) -> dict[str, list]:
    ...
```

**Acceptance:**
- Table-driven test in `tests/unit/test_always_translator.py` covering:
  - Empty `always`, no-op
  - `always` with 1 entry, 2 outcomes (5e shape)
  - `always` with 2 entries, 4 outcomes (PF2e shape)
  - Outcomes present in `branches` but not in `outcomes` list — should pass through unchanged (don't drop them; sim author error to surface elsewhere)
  - Outcome present in `outcomes` but missing from `branches` — appears in result with just the always entries
  - `always` absent entirely — input returned unchanged structurally
- Function is pure (no I/O, no mutation of input)

### P1.3 Dot-notation path resolver (S) — [x] Done

**Module:** `src/enar_montecarlo/utils/path_resolver.py`

```python
def resolve_path(target: dict, dotted: str, *, default: Any = _SENTINEL) -> Any:
    ...
```

Behavior: navigate `target` by `.`-separated keys. If any key missing and no default provided, raise `KeyError`. If default provided, return it.

**Acceptance:**
- Tests cover: simple `"a.b.c"`, missing key with default, missing key without default raises, single key (`"a"`), empty string raises, non-dict intermediate raises.

### P1.4 Per-iteration seeding (S) — [x] Done

**Module:** `src/enar_montecarlo/seeding.py`

Implement a stable function:

```python
def derive_iteration_seed(master_seed: int, iteration_num: int) -> int:
    ...
```

Use `hashlib.sha256(f"{master_seed}:{iteration_num}".encode()).digest()` truncated to 8 bytes, interpreted as a `int.from_bytes` value. Stable across Python sessions and OS.

**Acceptance:**
- Tests assert that `derive_iteration_seed(12345, 47)` produces a known constant (capture the constant on first run, lock it in)
- Different `(master, iter)` pairs produce different seeds
- Same `(master, iter)` produces same seed across re-imports

### P1.5 JSONL serialization (S) — [x] Done

**Module:** `src/enar_montecarlo/utils/jsonl.py`

```python
def dumps_event(event: Event) -> str: ...
def loads_event(line: str) -> Event: ...
```

Uses Pydantic's `model_dump_json` + `Event.model_validate_json`.

**Acceptance:**
- Round-trip test for each event type
- Loaded event equals original

### P1.6 RegistryBuilder and Registry factory (M) — [x] Done

**Module:** `src/enar_montecarlo/registry.py`

Implement `RegistryBuilder` per `DESIGN §6.1`. The `_persist_value` method is an injected callable so the builder is testable without a real DB.

```python
PersistFn = Callable[[str, str], int]   # (category, name) -> id

class RegistryBuilder:
    def __init__(self, *, persist: PersistFn):
        self._persist = persist
        self._categories: dict[str, dict[str, int]] = {}

    def register(self, category: str, name: str) -> int: ...
    def freeze(self): ...   # returns dynamically named "Registry" namedtuple
```

Validate that `category` is a valid Python identifier; raise `ValueError` if not.

**Acceptance:**
- Tests use a fake `persist` that returns sequential integers
- `register` is idempotent within a single builder (same category+name → same int)
- `register` calls `persist` exactly once per unique `(category, name)`
- `freeze()` returns an object whose type is named `"Registry"`
- Registry attribute access returns dicts: `r.outcome["miss"] == 1`
- Registry attribute reassignment raises (namedtuple immutability)
- Invalid category names raise `ValueError`
- `copy.deepcopy(registry)` works and produces independent state

### P1.7 Lifecycle hook discovery (S) — [x] Done

**Module:** `src/enar_montecarlo/lifecycle.py`

```python
@dataclass
class SimContract:
    run: Callable
    setup_once: Callable | None
    setup: Callable | None
    teardown: Callable | None
    teardown_once: Callable | None
    validate: Callable | None
    template: Callable | None
    sim_name: str
    sim_version: str
    system_name: str
    system_version: str
    outcomes: list[str]
    max_rounds: int | None
    default_iterations: int

def discover(sim_module) -> SimContract:
    ...
```

Reads attributes from a sim module. Raises `ConfigurationError` with a clear message if a required attribute is missing.

**Acceptance:**
- Tests use synthetic modules (created via `types.ModuleType`) covering:
  - All attributes present → SimContract populated
  - Missing required attribute → ConfigurationError with attribute name in message
  - Missing optional attributes → corresponding fields are None or default (e.g. default_iterations defaults to 500)

### P1 phase-end checklist

- [x] All P1 modules exist
- [x] All unit tests in `tests/unit/` pass
- [x] Coverage on P1 modules ≥ 95%
- [x] No mypy errors
- [x] No ruff errors

---

## P2 — Persistence Layer

**Goal:** A working SQL backend that can be seeded, written to, and synced. SQLite first, Postgres parity verified before phase end.

### P2.1 SQLAlchemy schema (M) — [x] Done

**Module:** `src/enar_montecarlo/persistence/schema.py`

ORM models for `runs`, `actor_files`, `values`, `resolutions`, `effects` per `DESIGN §8.1`.

Use SQLAlchemy 2.0 declarative style. Type annotations everywhere.

**Acceptance:**
- `tests/persistence/test_schema.py` creates schema in an in-memory SQLite, queries `sqlite_master` to confirm all tables and indexes exist
- All FK constraints declared
- Unique constraint on `values(category, value)`
- PK on resolutions and effects is `(run_id, iteration_num, event_seq)`

### P2.2 Session management (S) — [x] Done

**Module:** `src/enar_montecarlo/persistence/sessions.py`

```python
@dataclass
class PersistenceContext:
    sqlite: Session
    postgres: Session | None
    sqlite_path: Path        # /tmp/<run_id>.db or output_dir/<run_id>.db
    is_temp: bool            # True if Postgres mode

def create_context(*, run_id: UUID, postgres_url: str | None, output_dir: Path) -> PersistenceContext: ...
def close_context(ctx: PersistenceContext, *, success: bool) -> None: ...
```

`close_context` deletes the SQLite file if `is_temp and success`. Otherwise leaves it.

**Acceptance:**
- Tests using `tmp_path` fixture verify file location logic
- File deletion behavior covered
- Postgres-mode test gated behind a `POSTGRES_TEST_URL` env var; skipped when unset

### P2.3 Values table seeding and registration (M) — [x] Done

**Module:** `src/enar_montecarlo/persistence/values.py`

```python
def seed_framework_defaults(ctx: PersistenceContext) -> None:
    """Inserts effect_type rows (damage/condition/resource/custom)
       and the 'always' branch row. Idempotent."""

def make_persist_fn(ctx: PersistenceContext) -> PersistFn:
    """Returns a callable for RegistryBuilder. Inserts to Postgres
       first if present, mirrors to SQLite with same ID, returns ID."""
```

Both use `INSERT ... ON CONFLICT (category, value) DO NOTHING; SELECT id` semantics. SQLite uses `INSERT OR IGNORE` plus a follow-up `SELECT`.

**Acceptance:**
- `tests/persistence/test_values.py`:
  - `seed_framework_defaults` runs twice without error and produces same row count
  - `make_persist_fn`-returned callable is idempotent
  - With Postgres present (gated test): Postgres insert is the source of truth, SQLite gets the same ID
  - SQLite-only mode: IDs are assigned by SQLite's autoincrement
  - Concurrent registrations of same (category, value) end up with the same ID

### P2.4 Actor files storage (S) — [x] Done

**Module:** `src/enar_montecarlo/persistence/files.py`

```python
def store_file(ctx: PersistenceContext, content_dict: dict, original_filename: str) -> str:
    """Compute SHA256 of canonical-JSON-serialized content, insert if new,
       return the SHA256 string."""
```

Canonical serialization: `json.dumps(content, sort_keys=True, separators=(',', ':'))`.

**Acceptance:**
- Same content → same SHA256 → no duplicate row
- Different content → different SHA256 → two rows
- Filename mismatch with same content → still one row
- Test with a 100KB-ish realistic statblock to confirm it stores

### P2.5 Run row writes (S) — [x] Done

**Module:** `src/enar_montecarlo/persistence/writes.py` (run-row functions)

```python
def create_run_row(ctx, *, run_id, sim_name, sim_version, system_name, system_version,
                   seed, iterations_planned, attacker_file_id, defender_file_id, cli_args) -> None: ...
def update_run_completion(ctx, *, run_id, iterations_completed, terminated_reason) -> None: ...
```

**Acceptance:** Tests insert and update; verify row contents match.

### P2.6 Event writes (M) — [x] Done

**Module:** `src/enar_montecarlo/persistence/writes.py` (event functions)

```python
def write_event(ctx, *, run_id, event: Event) -> None: ...
def write_events_bulk(ctx, *, run_id, events: Iterable[Event]) -> None: ...
```

`write_event` dispatches by `event.type`:

- `resolution` → row in `resolutions`
- `effect` → row in `effects`
- `round_complete`, `sim_complete` → no DB row (markers are progress signals only); the framework consumes them but does not persist

Wait — confirm with design: markers don't go to DB? Re-reading DESIGN §7.1, markers carry event_seq but no table is specified. Confirmed: markers do not persist; they drive progress UI and `runs.iterations_completed` tracking.

**Acceptance:**
- Tests cover both event types being written
- Bulk write executes a single transaction
- FK references resolve (test fails if `outcome_id` doesn't exist in `values`)
- Markers do not insert any rows

### P2.7 SQLite → Postgres sync (M) — [x] Done

**Module:** `src/enar_montecarlo/persistence/sync.py`

```python
def sync_to_postgres(*, sqlite_path: Path, postgres_url: str) -> None:
    """Bulk copy from SQLite at sqlite_path into Postgres. Preserves
       all values, IDs, and event ordering. Idempotent at the DB level."""
```

Uses SQLAlchemy reflection on SQLite + `INSERT ... ON CONFLICT DO NOTHING` on Postgres.

**Acceptance:**
- End-to-end test: write rows to SQLite, sync, query Postgres, assert content matches
- Re-running sync on the same SQLite file does not duplicate rows
- Event ordering preserved (`(iteration_num, event_seq)`)

### P2 phase-end checklist

- [x] Schema creates cleanly in SQLite
- [x] Schema creates cleanly in Postgres (gated test)
- [x] All persistence tests pass in both modes
- [x] Value ID alignment verified across backends
- [x] No raw SQL strings outside the persistence module

---

## P3 — Lifecycle Driver

**Goal:** The function that takes a sim module + arguments and produces a completed run, hitting the persistence layer correctly.

### P3.1 Argument bundle (S) — [x] Done

**Module:** `src/enar_montecarlo/lifecycle.py` (extending P1.7)

```python
@dataclass
class RunArgs:
    sim_module: ModuleType
    attackers_path: Path
    defenders_path: Path
    iterations: int
    seed: int
    postgres_url: str | None
    output_dir: Path
    quiet: bool
    progress_format: Literal["text", "json"]
    extra_args: dict[str, Any]
```

Built by the CLI from argparse output. Passed into the driver.

### P3.2 File loading (S) — [x] Done

```python
def load_data_file(path: Path) -> dict:
    """Auto-detect yaml vs json by extension. Parse and return dict."""
```

Reject anything that isn't a top-level dict. Reject if missing `actors` key. (Don't validate further; that's sim's job.)

**Acceptance:** Tests cover `.yaml`, `.yml`, `.json`, unknown extension (raise), bad parse (raise with helpful message).

### P3.3 The driver (L) — [x] Done

```python
def execute_run(args: RunArgs) -> UUID:
    """Top-level driver. Returns run_id."""
```

Steps:

1. Generate `run_id`. Derive master `seed` if not provided.
2. Load attacker file, defender file.
3. Discover sim contract (P1.7).
4. Open persistence context (P2.2).
5. Seed framework defaults (P2.3).
6. Store actor files, get SHA256 IDs (P2.4).
7. Build RegistryBuilder using `make_persist_fn` (P2.3).
8. Create run row (P2.5).
9. Call `sim.setup_once`, get Registry.
10. Initialize progress UI (placeholder for P5).
11. For each iteration: `sim.setup` → `sim.run` (iterating generator) → `sim.teardown`.
    - Per-iteration seed = `derive_iteration_seed(seed, iteration_num)`.
    - Each yielded event: `write_event` (P2.6) and update progress.
12. Call `sim.teardown_once`.
13. Update run row to completed.
14. Sync to Postgres if configured (P2.7).
15. Close context (delete temp on success).
16. Return `run_id`.

Wrap the iteration loop in a try/except so partial-run state is recorded. On exception, `terminated_reason='error'` and `iterations_completed` reflects how far we got. KeyboardInterrupt → `terminated_reason='interrupted'`.

**Acceptance:**
- `tests/integration/test_run_end_to_end.py` runs a fixture sim and asserts run completes
- Crash mid-run produces a row with `terminated_reason='error'`, partial events persisted
- Interrupted run is recoverable via `sync` subcommand

### P3.4 Default no-op hooks (S) — [x] Done

If `sim_module` is missing optional hooks (`setup`, `teardown`, `setup_once`, `teardown_once`), the driver substitutes no-op callables. `setup_once` no-op still must register `OUTCOMES` and freeze, returning a Registry. Implement a `_default_setup_once` helper.

**Acceptance:** Test: a sim module with only `run` and the required constants completes a run successfully.

### P3.5 HaltException pass-through (S) — [x] Done

The framework imports `HaltException` from `enar_eventchain` (or, until that lib exists, defines a stub locally and adopts the upstream class when ready). Hooks raising `HaltException` are caught at the eventchain level, not the framework. The framework only needs to ensure the exception propagates cleanly through the generator iteration if it escapes (i.e., do not swallow it in the iteration loop).

**Acceptance:** Test that an exception raised inside `run()` propagates out of `execute_run` and triggers the `error` cleanup path.

### P3 phase-end checklist

- [x] Fixture sim runs end-to-end, produces expected DB rows
- [x] Crash recovery path tested
- [x] No-op default hooks tested
- [x] Per-iteration seed derivation actually used in the driver

---

## P4 — CLI

**Goal:** All subcommands working against the lifecycle driver. Sim authors can `python -m my_sim run a.yaml d.yaml` and get a UUID.

### P4.1 CLI scaffold (S) — [x] Done

**Module:** `src/enar_montecarlo/cli/main.py`

`main()` function discoverable from sim modules. Uses argparse with subparsers (or click; pick one in P0.1, stick with it).

**Acceptance:** `python -m enar_montecarlo --help` lists all subcommands. Same when invoked through a sim's `__main__`.

### P4.2 `run` subcommand (M)

**Module:** `src/enar_montecarlo/cli/commands/run.py`

Flags per `DESIGN §10.1`. Builds `RunArgs`, calls `execute_run`, prints UUID to stdout.

**Acceptance:**
- `python -m fixture_sim run a.yaml d.yaml` prints a UUID and produces a SQLite file
- `--seed 12345` produces deterministic output (re-run with same seed, compare event_seq → outcome_id mapping; should match)
- `--iterations 3 --quiet` runs silent
- Unknown args go into `extra_args`

### P4.3 `template` subcommand (S)

**Module:** `src/enar_montecarlo/cli/commands/template.py`

Calls `sim.template()` if present, else default skeleton. Format flag for yaml/json. Output flag for path.

**Acceptance:** Default invocation prints YAML to stdout. `--format json` prints JSON. `--output path` writes to file.

### P4.4 `validate` subcommand (S)

**Module:** `src/enar_montecarlo/cli/commands/validate.py`

Loads file, runs framework checks, then sim's `validate` if present. Exit 0 / 1.

**Acceptance:** Tests cover valid file, broken yaml, missing actors key, sim-defined validation issues.

### P4.5 `info` subcommand (S)

**Module:** `src/enar_montecarlo/cli/commands/info.py`

Prints sim metadata. `--json` flag.

**Acceptance:** Output matches DESIGN §10.4 format.

### P4.6 `sync` subcommand (S)

**Module:** `src/enar_montecarlo/cli/commands/sync.py`

Takes `<run_id>` + `--postgres-url`. Calls `sync_to_postgres` against `/tmp/<run_id>.db`.

**Acceptance:** Test with a deliberately orphaned SQLite file → sync → file deleted, Postgres has rows.

### P4.7 `purge` subcommand (S)

**Module:** `src/enar_montecarlo/cli/commands/purge.py`

Deletes `/tmp/<run_id>.db` if present. Confirmation prompt unless `--yes`.

**Acceptance:** File removed; missing file is a no-op with informative message.

### P4.8 `list-runs` subcommand (S)

**Module:** `src/enar_montecarlo/cli/commands/list_runs.py`

Queries `runs` table. Prints a tabular summary (rich Table is fine).

**Acceptance:** Empty DB returns "no runs". Non-empty returns rows sorted by `started_at` desc.

### P4 phase-end checklist

- [ ] All subcommands implemented
- [ ] CLI integration tests cover happy paths
- [ ] `python -m fixture_sim <subcommand> --help` works for all
- [ ] stdout contract enforced: `run` outputs only the UUID on success

---

## P5 — Progress UI

**Goal:** Two Rich progress bars driven off marker events. JSON Lines mode for cowork.

### P5.1 Rich text mode (M)

**Module:** `src/enar_montecarlo/cli/progress.py`

```python
class ProgressDriver:
    def __init__(self, *, total_iterations: int, max_rounds: int | None, mode: Literal["text", "json", "quiet"]): ...
    def on_event(self, event: Event) -> None: ...
    def close(self) -> None: ...
```

In text mode: Rich `Progress` group with two bars (iterations + rounds). Iterations bar total is known. Rounds bar uses `MAX_ROUNDS × iterations` if available, else dynamic estimate post-first-iteration.

**Acceptance:** Manual smoke test confirms bars update sensibly. Automated test: stub Rich's `Progress` and assert update calls.

### P5.2 JSON Lines mode (S)

In `mode='json'`: emit JSONL to stderr per `DESIGN §11.3`. One line per `iteration_complete` and one final `sim_complete`.

**Acceptance:** Test captures stderr, parses JSONL, asserts one line per iteration plus final summary.

### P5.3 Quiet mode (S)

In `mode='quiet'`: no output. `on_event` is a no-op.

**Acceptance:** Stderr is empty under `--quiet`.

### P5 phase-end checklist

- [ ] Three modes work (text / json / quiet)
- [ ] Progress driver consumes markers without altering main event flow
- [ ] No deadlocks when iterations are very fast

---

## P6 — Run Skill

**Goal:** A `SKILL.md` file in `skills/run/` that teaches cowork (or any skill-aware agent) how to run a sim.

### P6.1 Run skill content (M)

**File:** `skills/run/SKILL.md`

Per skill-creator conventions. Should cover:

- Trigger description (when to use this skill)
- How to invoke `python -m <sim_package> run <attackers> <defenders>`
- File format expectations (point at sim's own README for system specifics)
- How to capture the UUID (it's the only thing on stdout)
- How to inspect or sync orphaned runs
- How to read `info` output
- How to choose between SQLite and Postgres (CLI flags)

Keep it under ~200 lines. Skill-creator best practices: be specific in the description, give concrete examples in the body.

**Acceptance:**
- File parses as valid skill markdown (use skill-creator's validator if available)
- Manual review: a fresh agent given this skill can complete a sample run task

### P6 phase-end checklist

- [ ] SKILL.md exists, follows skill-creator conventions
- [ ] One sample task documented as reference

---

## P7 — Integration and Smoke Tests

**Goal:** A fixture sim that exercises every code path, plus the post-run smoke test enforced in CI.

### P7.1 Fixture echo_sim (M)

**Path:** `tests/integration/fixtures/echo_sim/`

A minimal sim with:

- Required attributes (SIM_NAME, etc., OUTCOMES = `["pass", "fail"]`)
- All optional hooks (each is short)
- A `run()` that for each iteration emits exactly:
  - 1 `ResolutionEvent` with `outcome_id = pass_id`
  - 2 `EffectEvent`s in the `pass` branch (one with trigger=null, one with trigger gated on a flag in extra_args)
  - 1 `ResolutionEvent` with `outcome_id = fail_id`, `caused_by_seq` pointing at the first
  - 1 `EffectEvent` in the `fail` branch
  - 1 `EffectEvent` with `effect_type='custom'` and notes including a system-specific extra
  - 1 `RoundCompleteMarker`
  - 1 `SimulationCompleteMarker`

Total: 6 DB rows per iteration (4 effects, 2 resolutions; markers don't persist).

### P7.2 End-to-end test (M)

**File:** `tests/integration/test_run_end_to_end.py`

Runs `execute_run(args)` on `echo_sim` with 5 iterations against in-memory SQLite. Asserts:

- `runs` row exists, `iterations_completed=5`, `terminated_reason='success'`
- `resolutions` row count = 10 (2 per iter × 5)
- `effects` row count = 20 (4 per iter × 5)
- `caused_by_seq` chains resolve correctly
- `notes` column on the custom effect contains expected payload
- All FK references resolve

### P7.3 Smoke test (S)

**File:** `tests/smoke/test_post_run_db.py`

A pytest fixture that runs after any successful `execute_run` and verifies basic invariants:

- `runs` row exists and is consistent
- `resolutions` and `effects` row counts > 0
- All FKs resolve
- `v_events` view returns rows in event_seq order (per iteration)

Imported into integration tests as a helper.

### P7 phase-end checklist

- [ ] echo_sim is real and runnable as `python -m echo_sim run a.yaml d.yaml`
- [ ] End-to-end test green
- [ ] Smoke checks pass on every integration run

---

## P8 — Documentation Polish

**Goal:** README, examples, contributor guide.

### P8.1 README.md (S)

Top-level README with:

- One-paragraph intro
- Install instructions
- Hello-world example (point at echo_sim)
- Pointer to DESIGN.md and IMPLEMENTATION_PLAN.md
- License (TBD)

### P8.2 Contributor guide (S, optional)

`CONTRIBUTING.md` with the working agreement from the top of this doc.

### P8.3 Phase READMEs sweep (S)

Walk through each phase's notes file (created during P0) and consolidate any open questions or design notes that should propagate back into DESIGN.md.

### P8 phase-end checklist

- [ ] README accurate and current
- [ ] Open items from §15 of DESIGN.md re-checked

---

# Out of scope for 1.0

Per `DESIGN §13.1` and `§13.3`:

- Parallel iterations (schema is shaped to accept them later)
- Pickling-safe Registry (workaround documented)
- Web UI / REPL / live dashboard
- Multi-tenant Postgres concurrency
- Encryption / auth
- Report skill (will be sim-level, separate work)
- System-version migration skills (live in system library repos)

These should not appear in commits against this implementation plan.

# Definition of done for 1.0

- [ ] All P0–P7 phase checklists complete
- [ ] `pytest --cov=src/enar_montecarlo` shows ≥ 90% coverage
- [ ] `mypy src/enar_montecarlo` clean
- [ ] `ruff check` clean
- [ ] echo_sim runs from a fresh checkout in a fresh venv
- [ ] Postgres-mode tests pass against a real Postgres (manual verification before tag)
- [ ] DESIGN.md and IMPLEMENTATION_PLAN.md reflect any decisions made during implementation
- [ ] Run skill validated by a manual cowork test session
- [ ] Tag `v0.1.0`, push to PyPI (TestPyPI first, then prod)
