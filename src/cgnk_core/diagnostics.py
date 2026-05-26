from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CGNK_SCHEMA_INVALID = "CGNK_SCHEMA_INVALID"
CGNK_REF_INVALID = "CGNK_REF_INVALID"
CGNK_DUPLICATE_REF = "CGNK_DUPLICATE_REF"
CGNK_MODULE_NOT_FOUND = "CGNK_MODULE_NOT_FOUND"
CGNK_ARTIFACT_NOT_FOUND = "CGNK_ARTIFACT_NOT_FOUND"
CGNK_POLICY_NOT_FOUND = "CGNK_POLICY_NOT_FOUND"
CGNK_FLOW_NOT_FOUND = "CGNK_FLOW_NOT_FOUND"
CGNK_EDGE_TYPE_MISMATCH = "CGNK_EDGE_TYPE_MISMATCH"
CGNK_ENDPOINT_DIRECTION_INVALID = "CGNK_ENDPOINT_DIRECTION_INVALID"
CGNK_INPUT_UNBOUND = "CGNK_INPUT_UNBOUND"
CGNK_OUTPUT_UNUSED = "CGNK_OUTPUT_UNUSED"
CGNK_POLICY_EFFECT_DENIED = "CGNK_POLICY_EFFECT_DENIED"
CGNK_POLICY_CAPABILITY_DENIED = "CGNK_POLICY_CAPABILITY_DENIED"
CGNK_GATE_PREDICATE_INVALID = "CGNK_GATE_PREDICATE_INVALID"
CGNK_PROPOSAL_INVALID = "CGNK_PROPOSAL_INVALID"
CGNK_CONTRACT_PACK_INVALID = "CGNK_CONTRACT_PACK_INVALID"
CGNK_MIGRATION_PROOF_MISSING = "CGNK_MIGRATION_PROOF_MISSING"

CGNK_INPUT_MULTI_PRODUCER = "CGNK_INPUT_MULTI_PRODUCER"
CGNK_GRAPH_CYCLE = "CGNK_GRAPH_CYCLE"
CGNK_NODE_NOT_FOUND = "CGNK_NODE_NOT_FOUND"
CGNK_PORT_NOT_FOUND = "CGNK_PORT_NOT_FOUND"
CGNK_POLICY_RISK_EXCEEDED = "CGNK_POLICY_RISK_EXCEEDED"
CGNK_POLICY_WRITE_DENIED = "CGNK_POLICY_WRITE_DENIED"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    path: str
    message: str
    expected: Any = None
    actual: Any = None
    involved_ref: str | None = None
    source: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    repair_hints: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.involved_ref is not None:
            out["involved_ref"] = self.involved_ref
        if self.source is not None:
            out["source"] = self.source
        if self.target is not None:
            out["target"] = self.target
        if self.repair_hints is not None:
            out["repair_hints"] = self.repair_hints
        return out
