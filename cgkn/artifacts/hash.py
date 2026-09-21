from __future__ import annotations

import hashlib
import json
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
