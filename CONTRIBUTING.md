# Contributing

This document captures the working agreement that produced the
v0.1.0 codebase. Subsequent contributors are expected to keep to
the same shape unless there's a deliberate decision to change it.

## Working agreement

- **Python 3.12+**. Type-annotate aggressively. Pydantic v2.
- **Test as you go.** No task is "complete" without its tests passing. Coverage on touched modules should remain at 100% unless there's an explicit reason otherwise.
- **One commit per task minimum.** Use task IDs in commit messages: `[P1.3] add RegistryBuilder`.
- **When ambiguous, surface the question** instead of guessing. Note the resolution in the relevant commit message and (if the contract is affected) in `DESIGN.md`.
- **Do not invent features beyond `DESIGN.md`.** If something seems missing, ask.
- **Do not skip the "always" branch translator's exhaustive test cases.** That function is foundational; bugs there corrupt every event downstream.

## Workflow

Tasks land on short-lived `task/Px.y-*` branches and are merged into `main` with `--no-ff` so the phase boundaries stay visible in the log:

```bash
git checkout -b task/P9.1-some-feature
# ... implement, test, lint, type-check ...
git add -A && git commit -m "[P9.1] short summary"
git checkout main && git merge --no-ff task/P9.1-some-feature -m "Merge ..."
git push origin main
git branch -d task/P9.1-some-feature
```

## Required checks before merging

```bash
ruff check src tests             # lint
mypy src/enar_montecarlo         # strict type-check
pytest --cov=enar_montecarlo     # tests + coverage
```

CI runs these on every push and PR (`.github/workflows/ci.yml`) against Python 3.12 and 3.13.

## Postgres-mode tests

Postgres connectivity tests are gated behind the `POSTGRES_TEST_URL` environment variable and are skipped when it's unset. Before tagging a release, run the full suite once with a real Postgres URL set so the gated tests actually exercise.

## Architectural reference

`DESIGN.md` is the source of truth for the framework's contract — sim hooks, data file format, registry semantics, event schema, DB schema, CLI surface, reproducibility, and trade-offs. If your change conflicts with it, update `DESIGN.md` in the same commit and call it out in the commit message.

## License

TBD; see `README.md`.
