from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.requirements.obligation import canonical_hash
from .contract_test import ContractTestPlan


@dataclass(frozen=True)
class ContractTestManifest:
    plan_hash: str
    obligation_set_hash: str
    oracle_plan_hash: str
    source_hash: str
    tests: tuple[Mapping[str, Any], ...]
    fingerprint: str
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        value = {"plan_hash": self.plan_hash, "obligation_set_hash": self.obligation_set_hash,
                 "oracle_plan_hash": self.oracle_plan_hash, "source_hash": self.source_hash,
                 "tests": [dict(item) for item in self.tests], "fingerprint": self.fingerprint,
                 "schema_version": self.schema_version}
        return value | {"manifest_hash": canonical_hash(value)}

    @classmethod
    def build(cls, plan: ContractTestPlan, source_hash: str, policy_hash: str) -> "ContractTestManifest":
        fingerprint = canonical_hash({"obligation_set_hash": plan.source_obligation_set_hash, "oracle_plan_hash": plan.source_oracle_plan_hash,
                                      "renderer_version": plan.renderer_version, "dependency_policy_hash": policy_hash})
        tests = tuple({"test_id": item.test_id, "test_name": item.test_name, "obligation_ids": list(item.obligation_ids),
                       "oracle_ids": list(item.oracle_ids), "source_hash": source_hash} for item in plan.tests)
        return cls(plan.plan_hash, plan.source_obligation_set_hash, plan.source_oracle_plan_hash, source_hash, tests, fingerprint)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractTestManifest":
        result = cls(str(value["plan_hash"]), str(value["obligation_set_hash"]), str(value["oracle_plan_hash"]),
                     str(value["source_hash"]), tuple(dict(item) for item in value["tests"]), str(value["fingerprint"]), str(value.get("schema_version", "1.0")))
        if value.get("manifest_hash") not in (None, result.as_dict()["manifest_hash"]):
            raise ValueError("ContractTestManifest hash mismatch")
        return result
