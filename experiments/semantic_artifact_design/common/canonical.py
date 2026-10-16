from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


def canonical_json(value: Any) -> str:
    return json.dumps(thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def verify_content_hash(document: Mapping[str, Any], *, field: str = "content_hash") -> None:
    stated = str(document.get(field, ""))
    body = {key: thaw(value) for key, value in document.items() if key != field}
    if not stated or stated != canonical_hash(body):
        raise ValueError("semantic artifact hash mismatch")
