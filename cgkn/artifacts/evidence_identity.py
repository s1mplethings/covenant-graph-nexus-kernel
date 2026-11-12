"""Existing evidence encodings, preserved byte-for-byte across owner relocation.

These hashes identify stored records; they do not grant acceptance.
"""
import hashlib
import json
from pathlib import Path
from collections.abc import Mapping

def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def digest(value):
    def plain(item):
        if isinstance(item, Mapping):
            return {k: plain(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [plain(v) for v in item]
        return item
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(root, path):
    path = Path(path).resolve()
    return {'path':path.relative_to(Path(root).resolve()).as_posix(), 'sha256':file_hash(path)}

