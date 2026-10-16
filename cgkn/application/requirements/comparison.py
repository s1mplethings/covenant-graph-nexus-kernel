from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from cgkn.providers import CompletionClient, ModelRoleConfig

from .dag import ObligationDAGService
from .direct import DirectAgentService


class RecordingClient:
    def __init__(self, delegate: CompletionClient):
        self.delegate = delegate
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> Any:
        result = self.delegate.complete(**kwargs)
        self.calls.append({"model": kwargs["config"].model, "role": kwargs["config"].role, "usage": dict(result.usage), "request_id": result.request_id})
        return result


@dataclass(frozen=True)
class StrategyComparison:
    runs: tuple[Mapping[str, Any], ...]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        direct = [item for item in self.runs if item["strategy"] == "DIRECT_AGENT"]
        dag = [item for item in self.runs if item["strategy"] == "COMPOSED_DAG"]
        def aggregate(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
            return {
                "runs": len(rows), "successes": sum(item["status"] == "PASS" for item in rows),
                "success_rate": sum(item["status"] == "PASS" for item in rows) / len(rows) if rows else 0.0,
                "provider_calls": sum(int(item["provider_calls"]) for item in rows),
                "tokens": sum(int(item["tokens"]) for item in rows),
                "wall_time_ms": sum(int(item["wall_time_ms"]) for item in rows),
                "repair_rounds": sum(int(item["repair_rounds"]) for item in rows),
                "hidden_passes": sum(item["hidden_acceptance"] == "PASS" for item in rows),
                "manual_edits": sum(int(item["manual_edits"]) for item in rows),
                "whole_replans": sum(int(item["whole_replans"]) for item in rows),
            }
        return {
            "kind": "CGKNExecutionStrategyComparison", "schema_version": "1.0", "created_at": self.created_at,
            "runs": [dict(item) for item in self.runs], "direct": aggregate(direct), "dag": aggregate(dag),
            "orchestration_value": "POSITIVE" if aggregate(dag)["success_rate"] >= aggregate(direct)["success_rate"] else "NEGATIVE",
        }


def compare_csv_strategies(root: pathlib.Path, output: pathlib.Path, client: CompletionClient,
                           high: ModelRoleConfig, worker: ModelRoleConfig, repeats: int) -> StrategyComparison:
    if repeats < 1 or repeats > 3:
        raise ValueError("comparison repeats must be one to three")
    runs: list[Mapping[str, Any]] = []
    for index in range(repeats):
        direct_client = RecordingClient(client)
        direct = DirectAgentService(root, direct_client, high).run_csv(output / f"direct-{index + 1}" / "workspace", output / f"direct-{index + 1}" / "run")
        value = direct.as_dict() | {"provider_calls": len(direct_client.calls), "high_model_tokens": direct.tokens, "cheap_worker_tokens": 0}
        runs.append(value)
        dag_client = RecordingClient(client)
        dag = ObligationDAGService(root, dag_client, worker).run_csv(output / f"dag-{index + 1}" / "workspace", output / f"dag-{index + 1}" / "run")
        value = dag.as_dict() | {"provider_calls": len(dag_client.calls), "high_model_tokens": 0, "cheap_worker_tokens": dag.tokens}
        runs.append(value)
    return StrategyComparison(tuple(runs), datetime.now(timezone.utc).isoformat())


def write_strategy_comparison(path: pathlib.Path, comparison: StrategyComparison) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
