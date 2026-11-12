"""Shared OS file lock; no state, scheduler or evidence ownership."""
import os
import pathlib
import time
from contextlib import contextmanager

class StateStoreError(RuntimeError):
    pass

@contextmanager
def exclusive_file(root, path, *, wait_seconds=0):
    path = pathlib.Path(path).resolve()
    if pathlib.Path(root).resolve() not in path.parents:
        raise StateStoreError('lock path escapes state root')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise StateStoreError('run already has an active coordinator') from exc
                time.sleep(.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

