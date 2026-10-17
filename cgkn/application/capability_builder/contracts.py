from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class CapabilityRisk(str, Enum):
    PURE = "PURE"
    READ_ONLY_LOCAL = "READ_ONLY_LOCAL"


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    version: str
    goal: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    examples: tuple[Mapping[str, Any], ...]
    acceptance: tuple[str, ...]
    risk: CapabilityRisk = CapabilityRisk.PURE
    allowed_dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id.strip() or not self.version.strip() or not self.goal.strip():
            raise ValueError("capability identity, version, and goal are required")
        if not self.examples or not self.acceptance:
            raise ValueError("capability examples and acceptance are required")
        if not isinstance(self.risk, CapabilityRisk):
            raise ValueError("only PURE and READ_ONLY_LOCAL capability risks are supported")
        if self.allowed_dependencies:
            raise ValueError("generated MVP capabilities cannot add external dependencies")
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))
        object.__setattr__(self, "examples", tuple(MappingProxyType(dict(item)) for item in self.examples))
        object.__setattr__(self, "acceptance", tuple(self.acceptance))

    @property
    def ref(self) -> str:
        return f"{self.capability_id}@{self.version}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id, "version": self.version, "goal": self.goal,
            "input_schema": dict(self.input_schema), "output_schema": dict(self.output_schema),
            "examples": [dict(item) for item in self.examples], "acceptance": list(self.acceptance),
            "risk": self.risk.value, "allowed_dependencies": list(self.allowed_dependencies),
        }


@dataclass(frozen=True)
class CapabilityPackage:
    spec: CapabilitySpec
    candidate_path: str
    component_ref: str
    executor_ref: str
    source_hash: str
    test_refs: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityBuildReceipt:
    capability_ref: str
    provider_id: str
    mode: str
    candidate_path: str
    provider_calls: int
    repair_rounds: int
    tests_passed: bool
    admitted: bool
    execution_passed: bool
    stored: bool
    manual_edits: int
    status: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CapabilityBuildReceipt", "schema_version": "1.0", **self.__dict__,
            "usage": dict(self.usage), "contains_credentials": False,
        }
