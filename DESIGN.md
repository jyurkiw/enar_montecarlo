# enar_montecarlo — Design Document

## 1. Purpose and Scope

`enar_montecarlo` is a Monte Carlo simulation framework for tabletop RPG combat (and related mechanical resolution) experiments. Its job is to drive sims, persist their event data, and provide a uniform CLI surface for running them.

### What the framework provides

- A lifecycle harness around a simulation program (`setup_once`, `setup`, `run`, `teardown`, `teardown_once`)
- A persistence pipeline that writes Pydantic-modeled events into a normalized SQL schema (SQLite or Postgres)
- A standardized CLI with subcommands (`run`, `template`, `validate`, `info`, `sync`, `purge`, `list-runs`)
- A small set of pure utilities (path resolver, branch translator, file-hash dedup, JSONL serialization)
- A dependency-injected `Registry` so simulations resolve outcome strings to integer FK IDs once, then operate on integers in the hot path

### What the framework does NOT provide

- Game-system mechanics — those live in system libraries (`enar_dnd5e_2024`, future `enar_pathfinder_2e`, etc.)
- Dice rolling — `enar_dieroller`
- Event/phase pump — `enar_eventchain`
- Combat resolution logic — written in each sim, against a system library
- Balance analysis or report generation — sim-level skills, deferred

The framework deliberately knows nothing about rolls, hits, saves, criticals, advantage, conditions, or any other game-mechanical concept. It only knows about `ResolutionEvent`, `EffectEvent`, and a few markers — opaque records produced by the sim and persisted by the framework.

## 2. The enar_ Library Family

| Library | Role | Status |
| --- | --- | --- |
| `enar_montecarlo` | Simulation framework (this project) | New |
| `enar_eventchain` | Phase/event pump: hook registration, ordered execution, `HaltException` | New, sibling project |
| `enar_dieroller` | Dice rolling (Rust/PyO3) | Existing |
| `enar_dnd5e_2024` | First system library (D&D 5e 2024 ruleset) | New, separate project |

Each is its own repo. Simulations are also their own repos and depend on the framework, eventchain, dieroller, and a system library.

## 3. Architecture Overview

```
                   CLI args
                      │
                      ▼
        ┌─────────────────────────────┐
        │  enar_montecarlo            │
        │  • argparse subcommands     │
        │  • file load (yaml/json)    │
        │  • lifecycle driver         │
        │  • Registry construction    │
        │  • generator iteration      │
        │  • SQL writes               │
        │  • progress UI              │
        └─────────────┬───────────────┘
                      │ imports sim module, discovers attrs
                      ▼
        ┌─────────────────────────────┐
        │  Sim package                │
        │  __init__.py:               │
        │    SIM_NAME, SIM_VERSION    │
        │    SYSTEM_NAME, …           │
        │    OUTCOMES                 │
        │    setup_once, setup, run,  │
        │    teardown, teardown_once  │
        │    validate?, template?     │
        └─────────────┬───────────────┘
                      │ imports
                      ▼
        ┌─────────────────────────────┐
        │  System library             │
        │  + enar_eventchain          │
        │  + enar_dieroller           │
        └─────────────────────────────┘
```

The framework is a generator-driver wrapped in a lifecycle harness. The sim's `run()` is a generator yielding Pydantic events. The framework iterates it, writes events to the database, and updates the progress UI.

## 4. Sim Contract

A sim is a Python package. Its `__init__.py` (or modules imported into it) exports the following attributes. The framework discovers them by attribute lookup on the imported module.

### 4.1 Required attributes

| Name | Type | Purpose |
| --- | --- | --- |
| `run` | callable, generator | Per-iteration combat resolution. Yields events. |
| `OUTCOMES` | iterable of str | Outcome vocabulary. Usually re-exported from system library. |
| `SIM_NAME` | str | Recorded on every run row. |
| `SIM_VERSION` | str | Recorded on every run row. |
| `SYSTEM_NAME` | str | Recorded on every run row. |
| `SYSTEM_VERSION` | str | Recorded on every run row. |

### 4.2 Optional attributes

| Name | Type | Default if absent |
| --- | --- | --- |
| `setup_once` | callable returning `Registry` | Framework calls a no-op stub that registers `OUTCOMES` and freezes |
| `teardown_once` | callable | No-op |
| `setup` | callable | No-op |
| `teardown` | callable | No-op |
| `validate` | callable | Framework's `validate` subcommand only does file-parse checks |
| `template` | callable returning dict | Framework default skeleton |
| `MAX_ROUNDS` | int \| None | None → progress bar uses dynamic estimate |
| `DEFAULT_ITERATIONS` | int | 500 |

### 4.3 Lifecycle hook signatures

```python
def setup_once(*, attackers, defenders, registry_builder, **extra_args) -> Registry: ...
def setup(*, registry, iteration_num, **extra_args) -> None: ...
def run(*, attackers, defenders, registry, iteration_num, **extra_args) -> Iterator[Event]: ...
def teardown(*, registry, iteration_num, **extra_args) -> None: ...
def teardown_once(*, registry, **extra_args) -> None: ...
```

All hooks use keyword-only arguments with an `**extra_args` catch-all so sims can declare additional kwargs (passed through from the CLI's `--` arg). The framework always passes the documented kwargs; anything else flows through `extra_args` for the sim to handle or ignore.

### 4.4 Lifecycle execution order

```
framework startup
  │
  ├─ load attacker file, defender file
  ├─ open SQLite (and Postgres if --postgres-url given)
  ├─ create RegistryBuilder seeded with framework defaults
  │
  ▼
sim.setup_once(attackers, defenders, registry_builder, **extra_args)
  └─ returns frozen Registry
  │
  ▼
for iteration_num in range(iterations):
    sim.setup(registry, iteration_num, **extra_args)
    try:
        for event in sim.run(attackers, defenders, registry, iteration_num, **extra_args):
            persistence.write(event)
            progress.update(event)
    finally:
        sim.teardown(registry, iteration_num, **extra_args)
  │
  ▼
sim.teardown_once(registry, **extra_args)
  │
  ▼
framework: sync to Postgres if configured, close DBs, print run UUID
```

`setup_once` runs exactly once per `run` invocation. `teardown_once` runs exactly once, after the final iteration's `teardown`, before the framework tears down DB connections.

### 4.5 Sim package layout

```
my_sim/
├── pyproject.toml
├── README.md
├── src/
│   └── my_sim/
│       ├── __init__.py        # Required attributes + hook re-exports
│       ├── __main__.py        # `python -m my_sim` entry point
│       ├── simulation.py      # run() and per-iteration logic
│       ├── chain.py           # EventChain construction
│       └── hooks.py           # Hook implementations
└── tests/
    ├── test_chain.py
    └── test_simulation.py
```

`__init__.py` does re-exports of the required attributes and lifecycle hooks:

```python
from .simulation import run, setup, teardown, setup_once, teardown_once
from enar_dnd5e_2024 import OUTCOMES

SIM_NAME = "fighter_vs_ogre"
SIM_VERSION = "0.1.0"
SYSTEM_NAME = "dnd5e_2024"
SYSTEM_VERSION = "0.1.0"
DEFAULT_ITERATIONS = 500
MAX_ROUNDS = 5
```

`__main__.py` is the `python -m my_sim` entry point. Python 3.13+ requires a real `__main__` submodule for `python -m <pkg>`; the `if __name__ == "__main__"` trick inside `__init__.py` is **not** sufficient. `__main__.py` imports the package and passes it explicitly so `main()` finds the sim attributes regardless of how the CLI was invoked:

```python
import my_sim
from enar_montecarlo import main

if __name__ == "__main__":
    main(sim_module=my_sim)
```

A worked example lives at `tests/integration/fixtures/echo_sim/__main__.py`.

`main()` is the framework's CLI entry point. With an explicit `sim_module` argument it uses that; otherwise it falls back to `sys.modules['__main__']` (which works for ad-hoc `python script.py` invocations but not `python -m`). `python -m my_sim run a.yaml d.yaml` runs the sim.

## 5. Data File Format

### 5.1 Top-level shape

A data file (attacker or defender) is a YAML or JSON document. The framework's only requirement is that the top level parses to a dict with two keys:

```yaml
metadata:
  system: dnd5e_2024
  system_version: "0.1.0"
actors:
  - name: fighter
    count: 1
    clumping: 1
    # ...system-specific stats below this line
  - name: archer
    count: 5
    clumping: 3
    # ...
```

`metadata` is recorded but not validated against the sim's `SYSTEM_NAME` / `SYSTEM_VERSION` — the framework records both versions on the run row and lets mismatches surface as exceptions inside the sim. The report layer flags them.

`actors` is a list. Each entry has, at minimum, `name`, `count`, and `clumping`. Everything else is system-specific and opaque to the framework.

The same file can be slotted as either attackers or defenders. There is no `attacker_fighter.json` vs `defender_fighter.json`; there is just `fighter.yaml`, used in whichever role the sim asks for.

### 5.2 Group semantics

Each actor entry represents `count` like-statted individuals. `clumping` is an integer indicating how many are in spell-area range when an AoE hits.

AoE attack actions declare an `area_score` (0.0–1.0) on their test config. The number of actors hit by an AoE equals `floor(clumping × area_score)`, with the specific individuals chosen randomly. A burning hands has a small `area_score`; a fireball has `1.0`.

Damage tracking is per-individual within a group, not aggregate at the group level. An "alive" individual is one whose damage taken has not exceeded the system-defined threshold (HP in 5e). Sim-internal concern.

### 5.3 Definitions

The actor-stat block contains a `definitions` map that the sim's resolution logic walks:

```yaml
actors:
  - name: assassin
    count: 1
    clumping: 1
    # … other system-specific stats …
    definitions:
      piercing_damage:
        type: damage
        damage_type: piercing
        amount: "1d4+3"

      poison_damage_full:
        type: damage
        damage_type: poison
        amount: "2d6"

      poison_damage_half:
        type: damage
        damage_type: poison
        amount: "1d6"

      sneak_attack:
        type: damage
        damage_type: piercing
        amount: "3d6"

      poison_save:
        type: save_action
        test_config:
          kind: save
          attribute: CON
          dc: 13
        branches:
          success: [poison_damage_half]
          failure: [poison_damage_full]
          always: []

      dagger:
        type: attack_action
        test_config:
          kind: attack
          to_hit: 6
        branches:
          success:
            - piercing_damage
            - poison_save
            - {ref: sneak_attack, trigger: sneak_attack_eligible}
          failure: []
          always: []

      assassin_turn:
        type: action_sequence
        members: [dagger, dagger]
```

### 5.4 Definition types

| `type` | Required fields | Notes |
| --- | --- | --- |
| `attack_action` | `test_config`, `branches` | `test_config` is opaque to framework |
| `save_action` | `test_config`, `branches` | Same |
| `test_action` | `test_config`, `branches` | Generic test for systems whose tests don't fit attack/save framing |
| `action_sequence` | `members` | List of references; can include any other definition type |
| `damage` | `damage_type`, `amount` | `amount` is a dice expression; resolved by sim |
| `condition` | `condition` (string) | Plus any system-specific fields |
| `resource` | system-specific | E.g. spell slots, ki points |
| `custom` | system-specific | Escape hatch |

`attack_action`, `save_action`, and `test_action` are functionally interchangeable from the framework's perspective — all three carry `test_config` (opaque) and `branches`. Three names exist for readability in data files.

### 5.5 Branch semantics

`branches` is a dict keyed by outcome strings. The keys must match strings declared by the system library's `OUTCOMES` (plus the special key `always`).

For 5e (`OUTCOMES = ["success", "failure"]`):

```yaml
branches:
  success: [...]
  failure: [...]
  always: [...]
```

For Pathfinder 2e (`OUTCOMES = ["critical_success", "success", "failure", "critical_failure"]`):

```yaml
branches:
  critical_success: []
  success: [...]
  failure: [...]
  critical_failure: [...]
  always: []
```

Branch entries are either a bare ref (string) or a `{ref, trigger}` object:

```yaml
success:
  - piercing_damage                                       # bare ref, always fires
  - {ref: sneak_attack, trigger: sneak_attack_eligible}   # gated by sim-defined function
```

A trigger is an opaque string. The sim's resolution logic looks the function up in the system library and calls it with whatever context it needs. When a trigger evaluates false, an effect row is still emitted with `amount=null` and `trigger_result=false` so the report layer can compute trigger-firing rates.

Missing branches are no-ops. If a 5e data file omits the `failure` branch, nothing fires on miss.

### 5.6 The "always" branch

`always` is a first-class branch the framework expands at execution time into entries appended to every other branch. The expansion is a pure function:

```python
def expand_always(branches: dict[str, list], outcomes: list[str]) -> dict[str, list]:
    always = branches.get("always", [])
    return {
        outcome: branches.get(outcome, []) + always
        for outcome in outcomes
    }
```

Tested in isolation with no DB or sim required. Data files stay readable; execution stays simple.

## 6. The Registry

The Registry maps category-keyed string identifiers (outcomes, damage types, effect types, etc.) to integer FK IDs. Sims use it to avoid string comparisons in the hot path.

### 6.1 RegistryBuilder

Mutable. Lives only during `setup_once`. Holds DB sessions; registrations persist immediately.

```python
class RegistryBuilder:
    def __init__(self, *, postgres_session=None, sqlite_session):
        self._pg = postgres_session
        self._sqlite = sqlite_session
        self._categories: dict[str, dict[str, int]] = {}

    def register(self, category: str, name: str) -> int:
        cat = self._categories.setdefault(category, {})
        if name not in cat:
            cat[name] = self._persist_value(category, name)
        return cat[name]

    def freeze(self) -> "Registry":
        Registry = namedtuple("Registry", list(self._categories))
        return Registry(**self._categories)
```

The framework calls `_persist_value` to insert into the `values` table. When a Postgres session is present, it inserts there first (canonical IDs), then mirrors into SQLite with the same IDs. When SQLite-only, it inserts directly.

`register` is idempotent at the DB layer (`INSERT … ON CONFLICT (category, name) DO NOTHING; SELECT id`).

### 6.2 Registry

Returned from `setup_once`. Immutable. Pickleable (with the future-parallelism caveat noted in §13).

Categories become attributes; values are dicts keyed by name:

```python
miss_id = registry.outcome["miss"]
fire_id = registry.damage_type["fire"]
```

The namedtuple is dynamically generated from the categories the sim registered. There is no static `Registry` class definition — each run produces its own.

### 6.3 Hot-path pattern

The sim caches registry IDs into module-level locals during `setup_once`:

```python
_HIT_ID = _MISS_ID = _FIRE_ID = None

def setup_once(*, attackers, defenders, registry_builder, **extra_args):
    for o in OUTCOMES:        registry_builder.register("outcome",     o)
    for d in DAMAGE_TYPES:    registry_builder.register("damage_type", d)

    registry = registry_builder.freeze()

    global _HIT_ID, _MISS_ID, _FIRE_ID
    _HIT_ID  = registry.outcome["hit"]
    _MISS_ID = registry.outcome["miss"]
    _FIRE_ID = registry.damage_type["fire"]

    return registry

def run(*, attackers, defenders, registry, iteration_num, **extra_args):
    yield ResolutionEvent(outcome_id=_HIT_ID, ...)
    yield EffectEvent(damage_type_id=_FIRE_ID, ...)
```

Single dict lookup at sim startup; everything after is local int access. For million-iteration runs this matters.

### 6.4 Categories

Category names are arbitrary strings, but they become namedtuple field names — so they must be valid Python identifiers (`[a-zA-Z_][a-zA-Z0-9_]*`). Convention: lowercase snake_case. The builder validates and raises on invalid names.

Framework-known categories (registered automatically with seed values during builder construction):

| Category | Default values |
| --- | --- |
| `effect_type` | `damage`, `condition`, `resource`, `custom` |
| `branch` | `always` (system outcomes added later) |

System-defined categories (registered by sim during `setup_once`):

| Category | Source |
| --- | --- |
| `outcome` | `OUTCOMES` from system library |
| `damage_type` | System library constants |
| `condition` | System library constants |
| `resource` | System library constants |
| `trigger` | System library constants |

Sims may register additional categories or values as they need.

## 7. Event Schema

### 7.1 Pydantic v2 models

```python
from pydantic import BaseModel, Field
from typing import Literal, Annotated, Union


class ResolutionEvent(BaseModel):
    type: Literal["resolution"] = "resolution"
    event_seq: int
    iteration_num: int
    round_num: int = 1
    actor_file_id: str
    actor_index: int
    target_file_id: str | None = None
    target_index: int | None = None
    resolution_name: str
    outcome_id: int
    caused_by_seq: int | None = None
    notes: dict = {}


class EffectEvent(BaseModel):
    type: Literal["effect"] = "effect"
    event_seq: int
    iteration_num: int
    round_num: int = 1
    actor_file_id: str
    actor_index: int
    target_file_id: str | None = None
    target_index: int | None = None
    effect_definition_name: str
    effect_type_id: int
    damage_type_id: int | None = None
    amount: float | None = None
    source_branch_id: int
    caused_by_seq: int
    trigger_name: str | None = None
    trigger_result: bool | None = None
    notes: dict = {}


class RoundCompleteMarker(BaseModel):
    type: Literal["round_complete"] = "round_complete"
    event_seq: int
    iteration_num: int
    round_num: int


class SimulationCompleteMarker(BaseModel):
    type: Literal["sim_complete"] = "sim_complete"
    event_seq: int
    iteration_num: int
    rounds_executed: int
    outcome_summary: dict = {}


Event = Annotated[
    Union[ResolutionEvent, EffectEvent, RoundCompleteMarker, SimulationCompleteMarker],
    Field(discriminator="type"),
]
```

### 7.2 event_seq

`event_seq` is per-iteration monotonic, framework-owned. Both `ResolutionEvent` and `EffectEvent` share the seq space within an iteration so causal chains are unambiguous: `caused_by_seq` references the parent event's seq, regardless of whether the parent was a resolution or an effect.

Markers carry `event_seq` too so they sort cleanly with everything else when iterating chronologically.

### 7.3 Causal chain reconstruction

A view over both tables gives chronological replay:

```sql
CREATE VIEW v_events AS
  SELECT run_id, iteration_num, round_num, event_seq, 'resolution' AS kind,
         resolution_name AS name, caused_by_seq
  FROM resolutions
  UNION ALL
  SELECT run_id, iteration_num, round_num, event_seq, 'effect',
         effect_definition_name, caused_by_seq
  FROM effects
  ORDER BY run_id, iteration_num, event_seq;
```

For per-iteration causal walking, recursive CTE or repeated SELECTs by `caused_by_seq`.

### 7.4 Extension policy

Sims do not subclass framework event models. System-specific extras (roll values, modifiers, save attribute used, tarot card drawn, whatever) go in the `notes: dict` blob. Reasons:

- DB schema stays stable across systems
- Persistence is a uniform write path
- Sims with truly system-specific event types end up writing them as `effect_type='custom'` rows with the specifics in `notes`

Report skills are sim- or system-level and know how to query `notes` for their target system.

## 8. Database Schema

Same schema in SQLite and Postgres. SQLAlchemy ORM. Fourth normal form: enum-like values are FK lookups into a unified `values` table.

### 8.1 Tables

#### `runs`

| Column | Type | Notes |
| --- | --- | --- |
| `run_id` | UUID4 (PK) | Generated by framework |
| `sim_name` | str | From sim module attr |
| `sim_version` | str | |
| `system_name` | str | |
| `system_version` | str | |
| `seed` | int | Master seed |
| `iterations_planned` | int | From CLI |
| `iterations_completed` | int | Updated on completion |
| `attacker_file_id` | str (FK → actor_files.sha256) | |
| `defender_file_id` | str (FK → actor_files.sha256) | |
| `started_at` | timestamp | |
| `completed_at` | timestamp \| null | |
| `cli_args` | JSON | Full argv snapshot |
| `terminated_reason` | str \| null | `success`, `error`, `interrupted` |

#### `actor_files`

| Column | Type | Notes |
| --- | --- | --- |
| `sha256` | str (PK, 64 chars) | Content hash, dedup key |
| `original_filename` | str | First filename ever ingested |
| `content_json` | JSON | Full file content |
| `first_seen_at` | timestamp | |

Files are content-addressed. Two runs using the same `fighter.yaml` reference the same row. Filename mismatch is irrelevant; the hash is the identity.

#### `values`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int (PK, autoincrement) | |
| `category` | str | E.g. `outcome`, `damage_type` |
| `value` | str | E.g. `success`, `fire` |

Unique constraint: `(category, value)`. Inserts use `ON CONFLICT (category, value) DO NOTHING; SELECT id`.

#### `resolutions`

| Column | Type | Notes |
| --- | --- | --- |
| `run_id` | UUID4 (FK → runs) | |
| `iteration_num` | int | |
| `round_num` | int | Default 1 |
| `event_seq` | int | Monotonic within iteration |
| `actor_file_id` | str (FK → actor_files) | |
| `actor_index` | int | Index into the file's `actors` list |
| `target_file_id` | str \| null (FK → actor_files) | |
| `target_index` | int \| null | |
| `resolution_name` | str | Definition name from data file |
| `outcome_id` | int (FK → values) | |
| `caused_by_seq` | int \| null | Parent event_seq |
| `notes` | JSON | System-specific extras |

PK: `(run_id, iteration_num, event_seq)`.

#### `effects`

| Column | Type | Notes |
| --- | --- | --- |
| `run_id` | UUID4 (FK → runs) | |
| `iteration_num` | int | |
| `round_num` | int | Default 1 |
| `event_seq` | int | Shared seq space with resolutions |
| `actor_file_id` | str (FK → actor_files) | |
| `actor_index` | int | |
| `target_file_id` | str \| null | |
| `target_index` | int \| null | |
| `effect_definition_name` | str | |
| `effect_type_id` | int (FK → values) | `damage` / `condition` / `resource` / `custom` |
| `damage_type_id` | int \| null (FK → values) | |
| `amount` | numeric \| null | Null when trigger failed |
| `source_branch_id` | int (FK → values) | Outcome string or `always` |
| `caused_by_seq` | int | Always set |
| `trigger_name` | str \| null | |
| `trigger_result` | bool \| null | False rows record trigger failure |
| `notes` | JSON | |

PK: `(run_id, iteration_num, event_seq)`.

### 8.2 Schema parity

SQLite and Postgres use the same DDL with minor type translations (Postgres `JSONB` ↔ SQLite `TEXT` carrying JSON, `UUID` ↔ `TEXT`). SQLAlchemy handles this. Same query layer works against either backend.

### 8.3 Indexes

Recommended (created at schema init):

- `resolutions(run_id, iteration_num, event_seq)` — PK
- `resolutions(run_id, iteration_num)` — per-iteration scans
- `resolutions(outcome_id)` — outcome-based aggregations
- `effects(run_id, iteration_num, event_seq)` — PK
- `effects(run_id, iteration_num)` — per-iteration scans
- `effects(effect_type_id)` — type-based aggregations
- `effects(damage_type_id)` — damage-type aggregations
- `actor_files(sha256)` — PK (already)

## 9. Persistence Flow

### 9.1 With `--postgres-url`

```
1. Open Postgres connection. Verify schema exists; create if not.
2. Create SQLite at /tmp/<run_id>.db. Apply same schema.
3. Build RegistryBuilder bound to BOTH sessions:
     - register against Postgres first (canonical IDs)
     - mirror into SQLite with INSERT OR REPLACE preserving the IDs
4. Sim setup_once registers system+sim values via the builder.
5. Sim emits events. Framework writes to SQLite (fast local).
6. After sim teardown_once: bulk copy from SQLite to Postgres.
7. On success: delete /tmp/<run_id>.db.
   On failure: keep /tmp/<run_id>.db for `sync` retry.
```

### 9.2 Without `--postgres-url`

```
1. Determine output path: --output-dir/<run_id>.db (default ./runs/).
2. Create SQLite at that path. Apply schema. Seed framework defaults.
3. Build RegistryBuilder bound to SQLite only.
4. Sim setup_once + run as normal. Writes go straight to the final SQLite.
5. No sync. File is the artifact.
```

### 9.3 The `sync` subcommand

```
enar_montecarlo sync <run_id> --postgres-url <url>
```

Looks for `/tmp/<run_id>.db`. If found, replays it into Postgres, deletes on success. Used to retry orphaned runs after Postgres outages.

### 9.4 Bulk copy implementation

SQLAlchemy with executemany or COPY (Postgres). The exact mechanism is an implementation detail; the framework MUST guarantee that:

- Value IDs in SQLite match their Postgres counterparts (handled by mirror-on-register, §6.1)
- Event ordering preserves `(iteration_num, event_seq)` so causal queries work post-sync

## 10. CLI Surface

Subcommand structure: `enar_montecarlo <subcommand> [args] [flags]`.

For sims, this is invoked as `python -m my_sim <subcommand>` because sims expose `main()` as their `__main__` entry point.

### 10.1 `run`

```
my_sim run <attackers_file> <defenders_file> [flags]
```

Flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--iterations N` | sim's `DEFAULT_ITERATIONS` or 500 | |
| `--seed N` | clock | Master seed; per-iteration seed = `hash(seed, iteration_num)` |
| `--postgres-url URL` | unset | If set, overrides `--output-dir` |
| `--output-dir PATH` | `./runs` | SQLite destination when no Postgres |
| `--quiet` | false | Suppress progress UI |
| `--progress json` | text | Switch progress to JSON Lines for cowork |
| `--workers N` | 1 | Parallel iterations (future; phase 2 of post-MVP) |

stdout on success: the run UUID and nothing else. stderr: progress UI (or JSON Lines).

Files are auto-detected by extension: `.yaml`, `.yml` → YAML; `.json` → JSON.

### 10.2 `template`

```
my_sim template [--format yaml|json] [--output PATH]
```

Emits a starter actor file. If the sim provides a `template()` callable, that's used; otherwise framework default skeleton:

```yaml
metadata:
  system: <system_name>
  system_version: <system_version>
actors:
  - name: example
    count: 1
    clumping: 1
    # …
```

Default output: stdout. With `--output`, writes to the given path.

### 10.3 `validate`

```
my_sim validate <file>
```

Runs file-parse checks (parseable, has `metadata` and `actors`, actor entries have name/count/clumping). If the sim provides `validate(attackers, defenders)`, that's called as well. Exit 0 on no issues, 1 on issues. Issues print to stderr.

### 10.4 `info`

```
my_sim info
```

Prints sim metadata as text or JSON (`--json`):

```
sim:    fighter_vs_ogre 0.1.0
system: dnd5e_2024 0.1.0
defaults:
  iterations: 500
  max_rounds: 5
```

### 10.5 `sync`

```
my_sim sync <run_id> --postgres-url <url>
```

Replays an orphaned `/tmp/<run_id>.db` into Postgres. See §9.3.

### 10.6 `purge`

```
my_sim purge <run_id>
```

Deletes `/tmp/<run_id>.db` if it exists. For cleaning up after manual recovery without syncing.

### 10.7 `list-runs`

```
my_sim list-runs [--postgres-url URL] [--output-dir PATH]
```

Lists runs from the configured backend. Quick dev convenience.

## 11. Progress and Output

### 11.1 Two Rich progress bars

- **Iterations bar.** Total = `--iterations`. Updates on `SimulationCompleteMarker`.
- **Rounds bar.** Total = `MAX_ROUNDS × iterations` if sim provides `MAX_ROUNDS`; otherwise indeterminate, switching to a dynamic estimate after the first iteration completes (`estimated_total = completed_rounds × iterations / completed_iterations`). Updates on `RoundCompleteMarker`.

Both bars share a single Rich `Progress` group on stderr.

### 11.2 `--quiet`

Suppresses progress UI. stdout (UUID on success) is unaffected.

### 11.3 `--progress json`

Switches from Rich UI to JSON Lines on stderr:

```jsonl
{"event":"iteration_complete","iteration_num":47,"rounds":4,"elapsed_s":0.012}
{"event":"sim_complete","total_iterations":500,"total_rounds":1923,"elapsed_s":6.4}
```

Cowork-friendly. Also works in CI/log-shipping pipelines.

### 11.4 stdout contract

On `run` success: a single line containing the run UUID. Nothing else. `my_sim run a.yaml d.yaml | xargs my_sim sync` works.

## 12. Reproducibility

### 12.1 Seeding

- Master `--seed`. If omitted, derived from clock at run start, recorded on `runs.seed`.
- Per-iteration seed: `hash(master_seed, iteration_num)` (concrete impl: `hashlib.sha256(...).digest()` truncated, or a stable Python `hash` derivative — TBD in implementation, but must be stable across Python sessions).
- Iteration 47 of seed `12345` produces the same events whether you ran 50 iterations or 5000.

### 12.2 File snapshotting

`actor_files.content_json` holds the full file content keyed by SHA256. To reproduce a run:

1. Pull `runs.attacker_file_id` and `runs.defender_file_id`.
2. Write the corresponding `content_json` to disk.
3. Re-run with `--seed <stored seed>` against those files.

Identical results.

### 12.3 Version recording

`runs` records both `sim_version` and `system_version`. The report layer surfaces mismatches but the framework does not enforce them — sim runs until exception.

## 13. Trade-offs and Future Work

### 13.1 Knowingly punted

| Item | Notes |
| --- | --- |
| Parallel iterations | Day-1 is serial. Schema and generator API are shaped to allow `Pool.imap_unordered` later without changes. Module-level cache of registry IDs needs a per-worker rebuild path. |
| Pickling dynamic `Registry` namedtuple | When parallel ships, Registry needs picklable form. Workaround: workers receive `dict[str, dict[str, int]]` and rebuild via the same `freeze` logic. |
| Report skills | Likely sim- or system-level. Will query `notes` JSON for system-specific extras. |
| Version-upgrade skills | Live in system library repos, not the framework. |
| Web/UI | Out of scope. |

### 13.2 Conscious limitations

- **No subclassing of event models.** Use `notes`. Trade: stable schema vs. richer typed events.
- **Files are stored whole, not per-actor.** Trade: simple reproducibility vs. per-actor query convenience. A helper `extract_actor(file_id, name)` covers the rare per-actor lookup.
- **Outcomes are arbitrary strings.** Trade: maximum system flexibility (PF2e degrees of success, FATE shifts, Daggerheart hope/fear) vs. typo risk. Mitigated by sim's `OUTCOMES` constant being the authoritative source.
- **Framework knows nothing about rolls.** Trade: reduced surface area, system independence vs. no built-in roll-event recording. Sims that want roll values record them in `notes`.

### 13.3 Cross-cutting non-goals

The framework will not provide:

- Any UI other than CLI + Rich progress
- A REPL or live-update mode
- Multi-tenancy / concurrent runs against the same Postgres
- Built-in encryption or auth
- A web dashboard

## 14. Testing Strategy

### 14.1 Framework unit tests

- `expand_always` — pure function, table-driven tests with various branch shapes
- `resolve_path(target, dotted)` — including missing keys with default, nested misses
- `RegistryBuilder.register` idempotency at the application layer
- `RegistryBuilder.freeze` — output is a namedtuple, attribute access works, dict access works
- Hash dedup helper — same content → same SHA256, different content → different
- JSONL serialization round-trip — Pydantic model → str → Pydantic model
- Per-iteration seed derivation stability across Python sessions
- Always-branch translator on N-outcome systems (5e, PF2e shapes)

### 14.2 Persistence tests

- Schema creation in SQLite and Postgres (ephemeral test DBs)
- Value registration ID alignment: register in Postgres, mirror to SQLite, assert IDs match
- Bulk sync from SQLite → Postgres preserves event ordering
- ON CONFLICT handles duplicate (category, value) without error
- Constraint violations (missing FK target) raise expected errors
- File hash storage: same content → same row, no duplicate insert

### 14.3 Lifecycle tests

- All hooks called in correct order with correct kwargs
- Missing optional hooks substituted with no-ops
- `setup_once` raising propagates and skips iterations
- `teardown_once` runs even when iteration loop raises
- HaltException from a hook stops further hooks on that phase (eventchain library responsibility, but framework integration test confirms it bubbles correctly)

### 14.4 Integration tests

A fixture sim (`tests/fixtures/echo_sim/`) that:

- Has all required and most optional attributes
- Produces exactly one of every event type
- Uses every `effect_type`, two outcomes, two damage types
- Has `always` branches, gated triggers (one passing, one failing), nested action sequences

Runs against an in-memory SQLite. Asserts row counts and content per table.

### 14.5 Smoke test

After every `run` invocation (in test mode), open the resulting SQLite and verify:

- `runs` row exists, `iterations_completed == iterations_planned`, `terminated_reason == 'success'`
- `resolutions` row count > 0
- All FK references resolve
- View `v_events` returns rows in `event_seq` order

## 15. Open Items

Resolution status as of v0.1.0:

1. **Per-iteration seed function — RESOLVED.** Implemented in `src/enar_montecarlo/seeding.py` as `derive_iteration_seed(master_seed, iteration_num)` returning `int.from_bytes(sha256(f"{master}:{iter}".encode()).digest()[:8], "big")`. Stable across processes / sessions / OS; result fits in `u64` so non-Python RNG backends can consume it. The constant `derive_iteration_seed(12345, 47) == 10769382246859689114` is locked in by a regression test; changing the formula invalidates reproducibility for every historical `runs.seed`.
2. **JSON Lines progress format — RESOLVED.** Wire format documented inline in `src/enar_montecarlo/cli/progress.py` and pinned by `tests/integration/test_progress_json.py`: one `{"event": "iteration_complete", "iteration_num": ..., "rounds": ..., "elapsed_s": ...}` line per `SimulationCompleteMarker`, plus a final `{"event": "sim_complete", "total_iterations": ..., "total_rounds": ..., "elapsed_s": ...}` summary. Round / resolution / effect events emit no lines.
3. **`validate` subcommand `ValidationIssue` shape — DEFERRED.** v0.1 sim hooks return `list[str]`; the CLI joins them one-per-stderr-line. A typed `ValidationIssue` Pydantic model is a candidate for v0.2 once a real sim's `validate()` shows what structure is actually needed (severity? location? code?).
4. **`template` single vs. two files — CONFIRMED single.** The CLI's `template` subcommand emits one file (matching the data-file symmetry — the same file can serve as either attackers or defenders). Sims that want two distinct templates can override `template()` to return a tuple and wrap their own CLI entry point.
5. **EventChain library API shape — STILL OPEN.** Lives in the `enar_eventchain` repo (not yet bootstrapped). The framework imports `HaltException` via `enar_montecarlo.halt` (a local stub); when eventchain ships, that module re-exports the upstream class.
