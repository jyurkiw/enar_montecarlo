"""Tests for derive_iteration_seed.

The locked-in constant guards against accidental changes to the
derivation -- changing it invalidates reproducibility for every
historical run. If this test ever needs to change, every existing
``runs.seed`` value in the database is no longer reproducible.
"""

import pytest

from enar_montecarlo.seeding import derive_iteration_seed

# Captured from the reference implementation. DO NOT update without
# bumping a major version and migrating historical reproducibility data.
LOCKED_IN_12345_47 = 10769382246859689114


def test_locked_in_constant() -> None:
    assert derive_iteration_seed(12345, 47) == LOCKED_IN_12345_47


def test_idempotent_within_session() -> None:
    assert derive_iteration_seed(99, 7) == derive_iteration_seed(99, 7)


def test_re_import_produces_same_seed() -> None:
    # Stability across re-imports (proxies cross-session stability since
    # the digest is derived from sha256 of a deterministic byte string).
    import importlib

    from enar_montecarlo import seeding

    first = seeding.derive_iteration_seed(42, 100)
    importlib.reload(seeding)
    second = seeding.derive_iteration_seed(42, 100)
    assert first == second


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ((0, 0), (0, 1)),
        ((0, 1), (1, 0)),
        ((12345, 47), (12345, 48)),
        ((12345, 47), (12346, 47)),
        ((-1, 0), (1, 0)),
    ],
)
def test_distinct_inputs_yield_distinct_seeds(
    a: tuple[int, int],
    b: tuple[int, int],
) -> None:
    assert derive_iteration_seed(*a) != derive_iteration_seed(*b)


def test_iteration_zero_works() -> None:
    seed = derive_iteration_seed(7, 0)
    assert isinstance(seed, int)
    assert seed >= 0


def test_negative_master_seed_works() -> None:
    seed = derive_iteration_seed(-1, 0)
    assert isinstance(seed, int)
    assert seed >= 0


def test_large_iteration_number_works() -> None:
    seed = derive_iteration_seed(0, 10_000_000)
    assert 0 <= seed < 2**64


def test_result_fits_in_8_bytes() -> None:
    # Output must fit in u64 so callers can safely convert to seed types
    # in other languages (e.g. for the Rust dieroller backend).
    for master in (-(2**63), -1, 0, 1, 2**63 - 1):
        for it in (0, 1, 2**31 - 1):
            seed = derive_iteration_seed(master, it)
            assert 0 <= seed < 2**64
