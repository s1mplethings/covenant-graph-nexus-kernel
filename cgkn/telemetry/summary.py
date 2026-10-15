from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class RunTelemetry:
    """Deterministic projection over existing events/results; never an event authority."""

    provider_roles: dict[str, dict[str, int]] = field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record_provider(self, role: str, usage: Mapping[str, Any], *, attempts: int = 1, duration_ms: int = 0, context_chars: int = 0) -> None:
        if role not in {"agent", "worker"} or attempts < 1 or duration_ms < 0 or context_chars < 0:
            raise ValueError("invalid provider telemetry")
        target = self.provider_roles.setdefault(role, {"calls": 0, "attempts": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "duration_ms": 0, "context_chars": 0})
        target["calls"] += 1; target["attempts"] += attempts
        target["duration_ms"] += duration_ms; target["context_chars"] += context_chars
        for source, destination in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"), ("total_tokens", "total_tokens")):
            value = usage.get(source, 0)
            if isinstance(value, int) and value >= 0: target[destination] += value

    def record_node(self, node_id: str, *, executor: str, attempts: int, duration_ms: int, status: str, reused: bool, retryable: bool) -> None:
        if not node_id or attempts < 0 or duration_ms < 0 or node_id in self.nodes:
            raise ValueError("invalid or duplicate node telemetry")
        self.nodes[node_id] = {"executor": executor, "attempts": attempts, "duration_ms": duration_ms, "status": status, "reused": reused, "retryable": retryable}

    def as_dict(self) -> dict[str, Any]:
        provider_calls = sum(item["calls"] for item in self.provider_roles.values())
        total_tokens = sum(item["total_tokens"] for item in self.provider_roles.values())
        actual = sum(not item["reused"] for item in self.nodes.values())
        reused = sum(bool(item["reused"]) for item in self.nodes.values())
        return {"kind": "CGKNRunTelemetry", "schema_version": "1.0", "provider_roles": {key: dict(self.provider_roles[key]) for key in sorted(self.provider_roles)}, "nodes": {key: dict(self.nodes[key]) for key in sorted(self.nodes)}, "summary": {"agent_calls": self.provider_roles.get("agent", {}).get("calls", 0), "cheap_worker_calls": self.provider_roles.get("worker", {}).get("calls", 0), "provider_calls": provider_calls, "total_tokens": total_tokens, "actual_executions": actual, "reused_nodes": reused, "rerun_nodes": sum(item["attempts"] > 1 and not item["reused"] for item in self.nodes.values()), "retry_attempts": sum(max(0, item["attempts"] - 1) for item in self.nodes.values()), "affected_subgraph_ratio": round(actual / len(self.nodes), 6) if self.nodes else 0.0}}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunTelemetry":
        if value.get("kind") != "CGKNRunTelemetry" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported telemetry document")
        result = cls()
        for role, row in dict(value.get("provider_roles", {})).items():
            if role not in {"agent", "worker"} or not isinstance(row, Mapping):
                raise ValueError("invalid provider telemetry document")
            expected = {"calls", "attempts", "input_tokens", "output_tokens", "total_tokens", "duration_ms", "context_chars"}
            if set(row) != expected or any(not isinstance(row[key], int) or row[key] < 0 for key in expected):
                raise ValueError("invalid provider telemetry document")
            result.provider_roles[role] = dict(row)
        for node_id, row in dict(value.get("nodes", {})).items():
            if not isinstance(row, Mapping):
                raise ValueError("invalid node telemetry document")
            result.record_node(str(node_id), executor=str(row["executor"]), attempts=int(row["attempts"]), duration_ms=int(row["duration_ms"]), status=str(row["status"]), reused=bool(row["reused"]), retryable=bool(row["retryable"]))
        return result
