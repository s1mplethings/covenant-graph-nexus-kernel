from __future__ import annotations

import pytest

from cgkn.telemetry import RunTelemetry


def test_telemetry_is_deterministic_and_separates_agent_worker_and_reuse() -> None:
    telemetry = RunTelemetry()
    telemetry.record_provider("worker", {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}, attempts=2)
    telemetry.record_provider("agent", {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25})
    telemetry.record_node("b", executor="local.file@1", attempts=1, duration_ms=4, status="SUCCEEDED", reused=True, retryable=False)
    telemetry.record_node("a", executor="llm.cheap@1", attempts=2, duration_ms=8, status="SUCCEEDED", reused=False, retryable=True)
    value = telemetry.as_dict()
    assert list(value["provider_roles"]) == ["agent", "worker"]
    assert list(value["nodes"]) == ["a", "b"]
    assert value["summary"] == {"agent_calls": 1, "cheap_worker_calls": 1, "actual_executions": 1, "reused_nodes": 1}
    assert value["provider_roles"]["worker"]["attempts"] == 2


@pytest.mark.parametrize("role, attempts", [("provider", 1), ("worker", 0)])
def test_invalid_provider_telemetry_is_rejected(role: str, attempts: int) -> None:
    with pytest.raises(ValueError):
        RunTelemetry().record_provider(role, {}, attempts=attempts)


def test_duplicate_and_negative_node_telemetry_is_rejected() -> None:
    telemetry = RunTelemetry()
    telemetry.record_node("n", executor="local.file@1", attempts=1, duration_ms=0, status="SUCCEEDED", reused=False, retryable=False)
    with pytest.raises(ValueError):
        telemetry.record_node("n", executor="local.file@1", attempts=1, duration_ms=0, status="SUCCEEDED", reused=False, retryable=False)
    with pytest.raises(ValueError):
        RunTelemetry().record_node("n", executor="e", attempts=-1, duration_ms=0, status="FAILED", reused=False, retryable=False)
