"""Stable per-iteration seed derivation.

Iteration N of a given master seed must produce identical events whether
the run executed 50 iterations or 50,000. We hash ``master:iter`` rather
than relying on Python's ``hash()`` (salt-randomized) so the derivation
is stable across processes, sessions, and platforms.
"""

import hashlib

_BYTES = 8


def derive_iteration_seed(master_seed: int, iteration_num: int) -> int:
    """Derive a stable seed for ``iteration_num`` from ``master_seed``.

    Uses SHA-256 of ``f"{master_seed}:{iteration_num}"`` truncated to the
    first 8 bytes, interpreted big-endian. Returns a non-negative int
    in ``[0, 2**64)``.
    """
    digest = hashlib.sha256(f"{master_seed}:{iteration_num}".encode()).digest()
    return int.from_bytes(digest[:_BYTES], byteorder="big")
