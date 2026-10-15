from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
from typing import Any


PLAN_KIND = "ORBIT360Plan"
UNIT_KIND = "ORBIT360WorkUnit"
REGISTRY_KIND = "ORBIT360InterfaceRegistry"
RECEIPT_KIND = "ORBIT360BoundaryReceipt"
CHECKPOINT_KIND = "ORBIT360Checkpoint"
RUN_REPORT_KIND = "ORBIT360RunReport"
REPAIR_REPORT_KIND = "ORBIT360RepairReport"
SCHEMA_VERSION = "1.0"


class OrbitError(RuntimeError):
    pass


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: nested for key, nested in value.items() if key != field}


def add_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = canonical_hash(result)
    return result


def verify_hash(value: dict[str, Any], field: str) -> bool:
    return value.get(field) == canonical_hash(without_hash(value, field))


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OrbitError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OrbitError(f"JSON object required: {path}")
    return value


def write_json(path: pathlib.Path, value: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = pathlib.Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
