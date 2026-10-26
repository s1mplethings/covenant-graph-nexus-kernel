from __future__ import annotations

import re


_NUMERIC_VERSION = re.compile(r"^(0|[1-9]\d*)(?:\.(0|[1-9]\d*))*$")


def semantic_version_key(value: str) -> tuple[int, ...]:
    """Return a deterministic key for the numeric SemVer subset used by MVP capabilities."""
    text = str(value).strip()
    if not _NUMERIC_VERSION.fullmatch(text):
        raise ValueError(f"unsupported capability version: {value!r}")
    parts = [int(part) for part in text.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)
