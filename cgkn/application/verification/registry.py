from __future__ import annotations

from dataclasses import dataclass

from .contracts import OracleEvidence, OraclePlan, OracleSpec


@dataclass(frozen=True)
class OracleRegistry:
    plan: OraclePlan

    def get(self, oracle_id: str) -> OracleSpec:
        for spec in self.plan.specs:
            if spec.oracle_id == oracle_id:
                return spec
        raise KeyError(oracle_id)

    def for_obligation(self, obligation_id: str) -> tuple[OracleSpec, ...]:
        if obligation_id not in self.plan.source_obligation_ids:
            raise KeyError(obligation_id)
        return tuple(spec for spec in self.plan.specs if obligation_id in spec.obligation_ids)

    def validate_evidence(self, evidence: OracleEvidence) -> None:
        spec = self.get(evidence.oracle_id)
        if evidence.obligation_ids != spec.obligation_ids:
            raise ValueError("OracleEvidence obligation references do not match OracleSpec")
