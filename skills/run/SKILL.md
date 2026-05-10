---
name: run-enar-sim
description: Use when the user asks to run an enar_montecarlo simulation, execute a sim package, perform Monte Carlo simulation runs against attacker / defender data files, capture run UUIDs, recover orphaned runs after a Postgres outage, inspect sim metadata, or list previous run results from the configured backend.
---

# Run an enar_montecarlo simulation

This skill walks an agent through driving an `enar_montecarlo`-based sim package from the command line: launching a run, capturing the UUID, recovering orphaned runs, and inspecting state.

Sims are Python packages whose `__init__.py` exports `main()` from the framework and wires it as the `__main__` entry point. Every CLI invocation is `python -m <sim_package> <subcommand> [args]`.

## When to use this skill

- The user wants to **run** a sim against attacker / defender data files (`run`).
- The user wants to **inspect** a sim's metadata, defaults, and outcome vocabulary (`info`).
- The user wants to **validate** a data file's shape before running (`validate`).
- The user wants to **emit a starter** data file from the sim's template (`template`).
- The user wants to **recover an orphaned run** after a Postgres outage (`sync`) or **delete one without syncing** (`purge`).
- The user wants to **list previous runs** in the configured backend (`list-runs`).

If the user is asking about installing the framework, designing a new sim package, or extending the schema, this skill is the wrong fit — point them at `DESIGN.md` and `IMPLEMENTATION_PLAN.md` in the repo.

## Run a simulation

Basic invocation:

```bash
python -m my_sim run path/to/attackers.yaml path/to/defenders.yaml
```

stdout on success is **only the run UUID**. That makes it pipe-friendly:

```bash
python -m my_sim run a.yaml d.yaml | xargs -I{} python -m my_sim sync {} --postgres-url $PG
```

Common flags (full list under `python -m my_sim run --help`):

| Flag | Default | Purpose |
| --- | --- | --- |
| `--iterations N` | sim's `DEFAULT_ITERATIONS` or 500 | How many iterations to run |
| `--seed N` | nanosecond clock | Master seed for reproducibility |
| `--postgres-url URL` | unset | Write canonical rows to Postgres; SQLite becomes a working temp |
| `--output-dir PATH` | `./runs` | Where the SQLite artifact lands when no Postgres |
| `--quiet` | false | Suppress the progress UI |
| `--progress json` | text | JSON Lines on stderr (cowork-friendly) |

Anything passed after the documented flags is parsed into `extra_args` and flows to every lifecycle hook. Three forms accepted:

```bash
python -m my_sim run a.yaml d.yaml --my-flag value      # key + value
python -m my_sim run a.yaml d.yaml --my-flag=value      # equals form
python -m my_sim run a.yaml d.yaml --debug              # bare flag (-> True)
```

## Capture the run UUID

stdout is exactly one line — the UUID. Capture it directly:

```bash
RUN_ID=$(python -m my_sim run a.yaml d.yaml --quiet)
echo "ran $RUN_ID"
```

Use `--quiet` to avoid the Rich progress bars on stderr cluttering the user's terminal when scripting. The stdout contract is unaffected by `--quiet`.

For automation, prefer `--progress json`: every `iteration_complete` event lands as one JSON Lines record on stderr, with a final `sim_complete` summary. The UUID is still on stdout.

## Inspect a sim

```bash
python -m my_sim info
```

Prints sim + system name and version, default iteration count, MAX_ROUNDS (or `None` if dynamic), and outcome vocabulary. Add `--json` for machine-readable output:

```bash
python -m my_sim info --json
# {"sim": {"name": "...", "version": "..."}, "system": {...}, "defaults": {...}, "outcomes": [...]}
```

## Validate a data file

```bash
python -m my_sim validate path/to/file.yaml
```

Exits 0 on no issues. Exits 1 with one issue per stderr line otherwise. Framework checks the file parses (YAML / JSON by extension), the top level is a dict with `actors`, and each actor has `name` / `count` / `clumping`. The sim's own `validate(attackers, defenders)` hook (if defined) runs after framework checks; the CLI passes the same file as both args.

## Emit a starter data file

```bash
python -m my_sim template                   # YAML to stdout
python -m my_sim template --format json     # JSON to stdout
python -m my_sim template --output start.yaml   # write to file
```

If the sim defines its own `template()` callable, that's what you get; otherwise the framework default skeleton (`metadata` + a single `example` actor with the system's name pre-filled).

## Choose between SQLite and Postgres

**SQLite-only** (default). Each run produces `<output_dir>/<run_id>.db` — a self-contained file you can ship around. Good for local experimentation.

**Postgres canonical** with `--postgres-url`. The framework writes a working SQLite to the OS temp dir for fast local writes, then bulk-syncs into Postgres at the end and deletes the temp file. Good for shared run history. Schema is identical in both backends.

## Recover an orphaned run

If a Postgres-mode run crashes before the bulk-sync completes, the working SQLite remains in `<tempdir>/<run_id>.db`. Two ways to handle it:

```bash
python -m my_sim sync <run_id> --postgres-url $PG     # replay into Postgres + delete the temp
python -m my_sim purge <run_id>                       # delete without syncing (prompts; --yes skips)
```

`sync` is idempotent at the DB layer; running it on an already-synced file is safe. `purge` exits 0 with an informative message if the file doesn't exist.

## List previous runs

```bash
python -m my_sim list-runs                              # scan ./runs/ (default --output-dir)
python -m my_sim list-runs --output-dir /path/to/runs   # scan a specific dir
python -m my_sim list-runs --postgres-url $PG           # query Postgres instead
```

Renders a Rich table sorted by `started_at` descending. Empty backend prints `no runs` literally so scripts can grep for it.

## Sample task

Goal: run 1000 iterations of `fighter_vs_ogre` with seed `42`, capture the UUID, and confirm the run completed cleanly.

```bash
RUN_ID=$(python -m fighter_vs_ogre run \
  fixtures/fighter.yaml fixtures/ogre.yaml \
  --iterations 1000 --seed 42 --quiet)

# Confirm via list-runs (search the table for the UUID).
python -m fighter_vs_ogre list-runs | grep "$RUN_ID"
```

The grep should return a single row showing `1000/1000` and `success`.

## Anti-patterns

- **Don't** treat stderr as part of the stdout contract. Progress UI / JSONL events go to stderr; only the UUID goes to stdout.
- **Don't** pass arbitrary positional arguments after the two file paths — they get silently swallowed by the extra-args parser. Use `--key value` form.
- **Don't** delete the working SQLite manually before `sync` finishes; use `purge` if you really mean to discard a run.
- **Don't** assume the seed is recorded only when explicit — if `--seed` is omitted, the framework records a clock-derived value on the run row (so reproducibility is always possible).
