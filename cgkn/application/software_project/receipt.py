from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import canonical_hash


@dataclass(frozen=True)
class ProjectGenerationReceipt:
    values: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        body = {"kind": "CGKNProjectGenerationReceipt", "schema_version": "1.0", **dict(self.values)}
        return body | {"receipt_hash": canonical_hash(body)}
