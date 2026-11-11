"""Canonical local resource identity guard shared by file capabilities."""
import os
from pathlib import Path


def same_resource(left, right):
    a,b=Path(left).resolve(),Path(right).resolve()
    if os.path.normcase(str(a)) == os.path.normcase(str(b)):
        return True
    try:
        return a.samefile(b)
    except FileNotFoundError:
        return False


def guard_output(inputs, output, *, atomic_inplace=False):
    collisions=[str(path) for path in inputs if same_resource(path,output)]
    if collisions and not atomic_inplace:
        raise PermissionError('INPUT_OUTPUT_IDENTITY_COLLISION: '+str(output))
    return collisions
