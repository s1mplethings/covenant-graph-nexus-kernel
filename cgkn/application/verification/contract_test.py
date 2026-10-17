from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from cgkn.application.requirements.obligation import FrozenMapping, canonical_hash, thaw


_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


@dataclass(frozen=True)
class ContractTestSpec:
    test_id: str
    obligation_ids: tuple[str, ...]
    oracle_ids: tuple[str, ...]
    test_kind: str
    target_path: str
    test_name: str
    setup: FrozenMapping = field(default_factory=FrozenMapping)
    operation: FrozenMapping = field(default_factory=FrozenMapping)
    expected: FrozenMapping = field(default_factory=FrozenMapping)
    dependency_policy_refs: tuple[str, ...] = ()
    provenance: FrozenMapping = field(default_factory=FrozenMapping)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.test_id) or not self.obligation_ids or not self.oracle_ids:
            raise ValueError("contract test requires stable identity and semantic references")
        for name in ("obligation_ids", "oracle_ids", "dependency_policy_refs"):
            values = tuple(sorted(str(item) for item in getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")
            object.__setattr__(self, name, values)
        if not self.target_path.startswith("tests/") or not self.test_name.startswith("test_"):
            raise ValueError("contract test must target a public pytest test")
        for name in ("setup", "operation", "expected", "provenance"):
            value = getattr(self, name)
            object.__setattr__(self, name, value if isinstance(value, FrozenMapping) else FrozenMapping(value))
        if self.schema_version != "1.0":
            raise ValueError("unsupported ContractTestSpec schema")

    def as_dict(self) -> dict[str, Any]:
        value = {
            "test_id": self.test_id, "obligation_ids": list(self.obligation_ids), "oracle_ids": list(self.oracle_ids),
            "test_kind": self.test_kind, "target_path": self.target_path, "test_name": self.test_name,
            "setup": thaw(self.setup), "operation": thaw(self.operation), "expected": thaw(self.expected),
            "dependency_policy_refs": list(self.dependency_policy_refs), "provenance": thaw(self.provenance),
            "schema_version": self.schema_version,
        }
        return value | {"test_hash": canonical_hash(value)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractTestSpec":
        result = cls(
            str(value["test_id"]), tuple(value["obligation_ids"]), tuple(value["oracle_ids"]),
            str(value["test_kind"]), str(value["target_path"]), str(value["test_name"]),
            FrozenMapping(value.get("setup", {})), FrozenMapping(value.get("operation", {})),
            FrozenMapping(value.get("expected", {})), tuple(value.get("dependency_policy_refs", ())),
            FrozenMapping(value.get("provenance", {})), str(value.get("schema_version", "1.0")),
        )
        if value.get("test_hash") not in (None, result.as_dict()["test_hash"]):
            raise ValueError("ContractTestSpec hash mismatch")
        return result


@dataclass(frozen=True)
class ContractTestPlan:
    plan_id: str
    source_obligation_set_hash: str
    source_oracle_plan_hash: str
    tests: tuple[ContractTestSpec, ...]
    renderer_version: str = "csv-contract-renderer@1"
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        tests = tuple(sorted(self.tests, key=lambda item: item.test_id))
        if not _ID.fullmatch(self.plan_id) or not tests or len({item.test_id for item in tests}) != len(tests):
            raise ValueError("invalid or duplicate contract test plan identity")
        if len({item.test_name for item in tests}) != len(tests):
            raise ValueError("duplicate contract test name")
        if not self.source_obligation_set_hash.startswith("sha256:") or not self.source_oracle_plan_hash.startswith("sha256:"):
            raise ValueError("contract test plan requires source hashes")
        object.__setattr__(self, "tests", tests)

    def as_dict(self) -> dict[str, Any]:
        value = {
            "plan_id": self.plan_id, "source_obligation_set_hash": self.source_obligation_set_hash,
            "source_oracle_plan_hash": self.source_oracle_plan_hash, "tests": [item.as_dict() for item in self.tests],
            "renderer_version": self.renderer_version, "schema_version": self.schema_version,
        }
        return value | {"plan_hash": canonical_hash(value)}

    @property
    def plan_hash(self) -> str:
        return self.as_dict()["plan_hash"]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractTestPlan":
        result = cls(str(value["plan_id"]), str(value["source_obligation_set_hash"]), str(value["source_oracle_plan_hash"]),
                     tuple(ContractTestSpec.from_dict(item) for item in value["tests"]), str(value.get("renderer_version", "csv-contract-renderer@1")), str(value.get("schema_version", "1.0")))
        if value.get("plan_hash") not in (None, result.plan_hash):
            raise ValueError("ContractTestPlan hash mismatch")
        return result
