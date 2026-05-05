"""Category-keyed string -> integer FK ID registry.

Sims register every outcome / damage type / etc. once during
``setup_once``, then call ``freeze()`` to receive a namedtuple whose
fields are the category names and whose values are the per-category
``{name: id}`` dicts. The hot loop only ever touches the integers.
"""

import keyword
from collections import namedtuple
from collections.abc import Callable
from typing import Any

PersistFn = Callable[[str, str], int]
"""``(category, name) -> id``.

Implementations must be idempotent at the DB layer for the same
``(category, name)`` input. The builder caches in-process, but a fresh
builder will not see prior caches and relies on the persist callable
to return the stable existing ID.
"""


def _validate_category(category: str) -> None:
    if not category.isidentifier():
        raise ValueError(f"category {category!r} is not a valid Python identifier")
    if keyword.iskeyword(category):
        raise ValueError(f"category {category!r} is a Python keyword")
    if category.startswith("_"):
        raise ValueError(f"category {category!r} cannot start with an underscore")


class RegistryBuilder:
    """Mutable registry construction. Lives only during ``setup_once``."""

    def __init__(self, *, persist: PersistFn) -> None:
        self._persist = persist
        self._categories: dict[str, dict[str, int]] = {}

    def register(self, category: str, name: str) -> int:
        """Idempotently register ``name`` under ``category``; return its ID.

        The persist callable is invoked exactly once per unique
        ``(category, name)`` pair seen by this builder.
        """
        _validate_category(category)
        cat = self._categories.setdefault(category, {})
        if name not in cat:
            cat[name] = self._persist(category, name)
        return cat[name]

    def freeze(self) -> Any:
        """Return an immutable ``Registry`` namedtuple of category dicts.

        The returned namedtuple's class name is ``"Registry"`` and its
        fields are the registered category names in insertion order.
        Each field's value is the ``{name: id}`` dict for that category.
        """
        registry_cls = namedtuple("Registry", list(self._categories))  # type: ignore[misc]
        return registry_cls(**self._categories)
