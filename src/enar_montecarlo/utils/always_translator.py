"""Expand the ``always`` branch in a definition's ``branches`` dict.

See DESIGN section 5.6. Pure function; the framework calls it once per
definition at execution time. Bugs here corrupt every event downstream,
so this module is exhaustively tested.
"""

from typing import Any


def expand_always(
    branches: dict[str, list[Any]],
    outcomes: list[str],
) -> dict[str, list[Any]]:
    """Append the ``always`` branch's entries to each named outcome's branch.

    The ``always`` key is consumed and does not appear in the result.

    Branch keys present in ``branches`` but not in ``outcomes`` are passed
    through unchanged: the framework does not validate that data files use
    the system's outcome vocabulary -- that mismatch is surfaced by the
    report layer or by the sim itself raising at execution time.

    Outcomes listed in ``outcomes`` but missing from ``branches`` appear in
    the result with just the ``always`` entries (or an empty list when
    ``always`` is absent or empty).

    The function does not mutate either input. Returned lists are fresh and
    do not share storage with the input lists.
    """
    always = branches.get("always", [])
    result: dict[str, list[Any]] = {
        outcome: list(branches.get(outcome, [])) + list(always) for outcome in outcomes
    }
    for key, value in branches.items():
        if key == "always":
            continue
        if key not in result:
            result[key] = list(value)
    return result
