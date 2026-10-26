from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RequiredCapability:
    capability_ref: str
    purpose: str
    required_before_node: str
    risk_expectation: str

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ProjectGoal:
    project_id: str
    goal: str
    package_name: str
    required_capabilities: tuple[RequiredCapability, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "goal": self.goal, "package_name": self.package_name, "required_capabilities": [item.as_dict() for item in self.required_capabilities]}


@dataclass(frozen=True)
class ProjectProductionResult:
    status: str
    workspace: str
    package_path: str
    receipt: Mapping[str, Any]

