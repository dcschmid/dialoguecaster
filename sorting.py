"""Small utility sorting module used by tests.

Provides a simple, well-documented `sorting_algorithm` function that wraps
Python's built-in `sorted()` for predictable, stable sorting behavior.
"""

from typing import Iterable, List, TypeVar

T = TypeVar("T")


def sorting_algorithm(items: Iterable[T]) -> List[T]:
    """Return a sorted list from the given iterable.

    This function intentionally returns a new list and does not mutate the
    input. It relies on Python's built-in `sorted()` which produces a stable
    sort and supports mixed comparable types (e.g. ints, floats, strings).
    """
    if items is None:
        return []
    return sorted(list(items))
