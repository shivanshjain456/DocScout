"""Runtime-checked coercions for database row values.

psycopg types a row as `tuple[object, ...]`, so every value read out of a cursor is
statically `object` and mypy rejects `int(value)`. The usual escape is `cast`, which
silences the checker without checking anything: if a migration changes a column's type,
a cast keeps compiling and the wrong value flows into a metric.

These helpers narrow with a real isinstance test instead, so that case raises at the
boundary where it can still be diagnosed, naming the value it got.
"""

from __future__ import annotations


def as_int(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError(f"expected an integer column, got bool {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        return int(value)
    raise TypeError(f"expected an integer column, got {type(value).__name__} {value!r}")


def as_float(value: object) -> float:
    if isinstance(value, bool):
        raise TypeError(f"expected a numeric column, got bool {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise TypeError(f"expected a numeric column, got {type(value).__name__} {value!r}")


def as_str(value: object) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"expected a text column, got {type(value).__name__} {value!r}")
