from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class RunTelemetry:
    """Deterministic projection over existing events/results; never an event authority."""

    provider_roles: dict[str, dict[str, int]] = field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record_provider(self, role: str, usage: Mapping[str, Any], *, attempts: int = 1) -> None:
        if role not in {"agent", "worker"} or attempts < 1:
            raise ValueError("invalid provider telemetry")
        target = self.provider_roles.setdefault(role, {"calls": 0, "attempts": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        target["calls"] += 1; target["attempts"] += attempts
        for source, destination in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"), ("total_tokens", "total_tokens")):
            value = usage.get(source, 0)
            if isinstance(value, int) and value >= 0: target[destination] += value

    def record_node(self, node_id: str, *, executor: str, attempts: int, duration_ms: int, status: str, reused: bool, retryable: bool) -> None:
        if not node_id or attempts < 0 or duration_ms < 0 or node_id in self.nodes:
            raise ValueError("invalid or duplicate node telemetry")
        self.nodes[node_id] = {"executor": executor, "attempts": attempts, "duration_ms": duration_ms, "status": status, "reused": reused, "retryable": retryable}

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "CGKNRunTelemetry", "schema_version": "1.0", "provider_roles": {key: dict(self.provider_roles[key]) for key in sorted(self.provider_roles)}, "nodes": {key: dict(self.nodes[key]) for key in sorted(self.nodes)}, "summary": {"agent_calls": self.provider_roles.get("agent", {}).get("calls", 0), "cheap_worker_calls": self.provider_roles.get("worker", {}).get("calls", 0), "actual_executions": sum(not item["reused"] for item in self.nodes.values()), "reused_nodes": sum(bool(item["reused"]) for item in self.nodes.values())}}
