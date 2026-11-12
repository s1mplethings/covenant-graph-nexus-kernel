"""Validate archive members before trusted Windows host materialization."""
from pathlib import PurePosixPath

def safe_member(name):
    if not isinstance(name,str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("Unsafe archive/input member")
    path=PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe archive/input member")
    return path
