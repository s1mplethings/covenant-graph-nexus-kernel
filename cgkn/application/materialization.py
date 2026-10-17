from __future__ import annotations

import pathlib
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any


def materialize_json(value: Any) -> Any:
    """Recursively convert application semantic values to JSON primitives."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return materialize_json(value.value)
    if isinstance(value, pathlib.PurePath):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): materialize_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [materialize_json(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: materialize_json(getattr(value, item.name)) for item in fields(value)}
    raise TypeError(f"cannot materialize {type(value).__name__} as JSON")
