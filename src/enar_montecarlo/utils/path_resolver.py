"""Dot-notation path resolution for nested dicts.

Used by sims walking the ``definitions`` map in actor data files.
"""

from typing import Any, Final

_MISSING: Final[object] = object()


def resolve_path(
    target: dict[str, Any],
    dotted: str,
    *,
    default: Any = _MISSING,
) -> Any:
    """Walk ``target`` by ``.``-separated keys.

    - Returns the value at the path on success.
    - Returns ``default`` on a missing key when ``default`` was provided;
      otherwise raises ``KeyError`` naming the full path.
    - Raises ``ValueError`` for an empty path (always; ``default`` does
      not suppress it -- an empty path is a programming error, not
      missing data).
    - Raises ``TypeError`` when the traversal hits a non-dict before
      consuming all path segments (always; same rationale as above --
      this is a schema mismatch, not missing data).
    """
    if dotted == "":
        raise ValueError("path must not be empty")
    current: Any = target
    for key in dotted.split("."):
        if not isinstance(current, dict):
            raise TypeError(
                f"cannot descend into non-dict ({type(current).__name__}) "
                f"at key {key!r} of path {dotted!r}"
            )
        if key not in current:
            if default is not _MISSING:
                return default
            raise KeyError(dotted)
        current = current[key]
    return current
