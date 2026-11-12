"""Safe ZIP entry-name normalization (Zip Slip prevention)."""
from __future__ import annotations
import re

_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_entry(name: str) -> str:
    """Return a canonical POSIX relative entry name or raise ValueError.

    Rejects absolute paths, drive-letter paths, NUL, empty names and any
    parent traversal. Backslashes are treated as separators. Empty segments
    are rejected rather than silently collapsing malformed archives.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("entry name must be a non-empty string")
    if "\x00" in name:
        raise ValueError("entry name contains NUL")
    if name.startswith(("/", "\\")) or _DRIVE.match(name):
        raise ValueError("absolute entry name is not allowed")
    value = name.replace("\\", "/")
    parts: list[str] = []
    for part in value.split("/"):
        if part in ("", "."):
            raise ValueError("empty or dot path segment is not allowed")
        if part == "..":
            raise ValueError("parent traversal is not allowed")
        parts.append(part)
    result = "/".join(parts)
    if not result:
        raise ValueError("normalized entry name is empty")
    return result
