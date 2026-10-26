from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from cgkn.application.requirements.obligation import FrozenMapping, canonical_hash, thaw


_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


class InterfaceContractStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class InterfaceContractEvidence:
    evidence_id: str
    contract_id: str
    status: InterfaceContractStatus
    expected: FrozenMapping
    observed: FrozenMapping
    failure_class: str | None = None
    required_action: str | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.evidence_id) or not _ID.fullmatch(self.contract_id):
            raise ValueError("evidence and contract ids must be stable uppercase identifiers")
        for name in ("expected", "observed"):
            value = getattr(self, name)
            object.__setattr__(self, name, value if isinstance(value, FrozenMapping) else FrozenMapping(value))
        if self.status is InterfaceContractStatus.PASS and (self.failure_class or self.required_action):
            raise ValueError("PASS evidence cannot contain failure details")
        if self.status is not InterfaceContractStatus.PASS and not self.failure_class:
            raise ValueError("non-PASS evidence requires failure_class")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "evidence_id": self.evidence_id, "contract_id": self.contract_id, "status": self.status.value,
            "expected": thaw(self.expected), "observed": thaw(self.observed),
            "failure_class": self.failure_class, "required_action": self.required_action,
            "schema_version": self.schema_version,
        }
        return value | {"evidence_hash": canonical_hash(value)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InterfaceContractEvidence":
        result = cls(
            str(value["evidence_id"]), str(value["contract_id"]), InterfaceContractStatus(str(value["status"])),
            FrozenMapping(value.get("expected", {})), FrozenMapping(value.get("observed", {})),
            value.get("failure_class"), value.get("required_action"), str(value.get("schema_version", "1.0")),
        )
        supplied = value.get("evidence_hash")
        if supplied is not None and supplied != result.as_dict()["evidence_hash"]:
            raise ValueError("interface evidence hash mismatch")
        return result
