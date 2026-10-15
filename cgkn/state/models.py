from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from cgkn.execution import BlockExecutionResult
from cgkn.execution.contracts import utc_now


@dataclass
class NodeExecutionRecord:
    node_id: str
    status: str = "PENDING"
    attempts: list[str] = field(default_factory=list)
    latest_result_ref: str | None = None
    reused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "status": self.status, "attempts": list(self.attempts), "latest_result_ref": self.latest_result_ref, "reused": self.reused}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NodeExecutionRecord":
        return cls(str(value["node_id"]), str(value.get("status", "PENDING")), list(value.get("attempts", [])), value.get("latest_result_ref"), bool(value.get("reused", False)))


@dataclass
class RunState:
    project_id: str
    run_id: str
    status: str = "PENDING"
    nodes: dict[str, NodeExecutionRecord] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "CGKNRunState", "schema_version": self.schema_version, "project_id": self.project_id, "run_id": self.run_id, "status": self.status, "nodes": {key: value.as_dict() for key, value in self.nodes.items()}, "created_at": self.created_at, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunState":
        if value.get("kind") != "CGKNRunState" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported or corrupt run state")
        return cls(project_id=str(value["project_id"]), run_id=str(value["run_id"]), status=str(value.get("status", "PENDING")), nodes={key: NodeExecutionRecord.from_dict(item) for key, item in dict(value.get("nodes", {})).items()}, created_at=str(value["created_at"]), updated_at=str(value["updated_at"]))


@dataclass
class ProjectState:
    project_id: str
    goal: str
    latest_run_id: str
    constraints: tuple[str, ...] = ()
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "CGKNProjectState", "schema_version": self.schema_version, "project_id": self.project_id, "goal": self.goal, "latest_run_id": self.latest_run_id, "constraints": list(self.constraints)}


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    project_id: str
    run_id: str
    event_type: str
    node_id: str | None = None
    attempt_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "event_id": self.event_id, "project_id": self.project_id, "run_id": self.run_id, "event_type": self.event_type, "node_id": self.node_id, "attempt_id": self.attempt_id, "data": dict(self.data), "created_at": self.created_at}
