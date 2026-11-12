from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    """Return the stable RFC-8259 JSON projection used for artifact identity."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(content: Any) -> str:
    payload = canonical_json(content).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def source_identity(function):
    """Bind both source bytes and actually loaded callable code, not its name."""
    import inspect
    import marshal
    from pathlib import Path
    path = inspect.getsourcefile(function)
    if not path or not Path(path).is_file():
        return 'UNKNOWN'
    code = getattr(function, '__code__', None)
    if code is None:
        return 'UNKNOWN'
    return content_hash([hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        hashlib.sha256(marshal.dumps(code, 0)).hexdigest(), function.__module__, function.__qualname__])


def file_hash(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        raise ValueError('OUTPUT_BINDING_REJECT: missing file or symlink')
    return hashlib.sha256(p.read_bytes()).hexdigest()


