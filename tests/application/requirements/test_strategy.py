from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from cgkn.application.requirements import DirectAgentService, ExecutionStrategy, compare_csv_strategies, decide_execution_strategy
from cgkn.providers import ModelRoleConfig, ProviderCompletion

from .test_work_unit_dag import CORE, MAIN, TESTS
from .test_work_unit_dag import FakeObligationProvider


class FakeDirectProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: Any) -> ProviderCompletion:
        payload = json.loads(user); self.calls.append(payload)
        actions = [
            {"action": "write_file", "path": "csv_cleaner/__init__.py", "content": "from .core import clean_csv\n__all__ = ['clean_csv']\n"},
            {"action": "write_file", "path": "csv_cleaner/__main__.py", "content": MAIN},
            {"action": "write_file", "path": "csv_cleaner/core.py", "content": CORE},
            {"action": "write_file", "path": "tests/test_csv_cleaner.py", "content": TESTS},
            {"action": "write_file", "path": "README.md", "content": "# CSV Cleaner\n\nUse `python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]`.\n"},
        ]
        value = {"schema_version": "1.0", "node_id": "DIRECT-AGENT", "summary": "complete bounded project", "actions": actions, "expected_outputs": ["gates decide"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(value), config.model, "direct-1", {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40})


class CombinedProvider:
    def __init__(self) -> None:
        self.direct = FakeDirectProvider(); self.dag = FakeObligationProvider()

    def complete(self, **kwargs):
        target = self.direct if kwargs["schema_name"] == "cgkn_direct_agent_execute" else self.dag
        return target.complete(**kwargs)


def test_routing_is_decided_before_execution_and_is_not_failure_fallback() -> None:
    small = decide_execution_strategy(source_files=5, work_units=3, long_lived_state=False, parallel_opportunity=False, high_risk_effects=False)
    complex_case = decide_execution_strategy(source_files=8, work_units=5, long_lived_state=True, parallel_opportunity=True, high_risk_effects=False)
    assert small.strategy is ExecutionStrategy.DIRECT_AGENT and small.decided_before_execution
    assert complex_case.strategy is ExecutionStrategy.COMPOSED_DAG and complex_case.decided_before_execution


def test_direct_agent_uses_same_obligations_and_cannot_bypass_hidden_acceptance(tmp_path) -> None:
    provider = FakeDirectProvider()
    result = DirectAgentService(pathlib.Path.cwd(), provider, ModelRoleConfig("agent", "fake-high")).run_csv(tmp_path / "direct", tmp_path / "receipt")
    assert result.status == "PASS" and result.hidden_acceptance == "PASS"
    assert result.provider_calls == 1 and result.manual_edits == result.whole_replans == 0
    assert provider.calls[0]["obligations"]["obligations"]
    assert (tmp_path / "receipt" / "obligation_preflight.json").is_file()


def test_direct_and_dag_comparison_uses_independent_workspaces_and_fixed_routes(tmp_path) -> None:
    result = compare_csv_strategies(
        pathlib.Path.cwd(), tmp_path, CombinedProvider(),
        ModelRoleConfig("agent", "fake-high"), ModelRoleConfig("worker", "fake-cheap"), 1,
    ).as_dict()
    assert result["direct"]["successes"] == result["dag"]["successes"] == 1
    assert result["direct"]["provider_calls"] == 1 and result["dag"]["provider_calls"] == 3
    assert result["runs"][0]["workspace"] != result["runs"][1]["workspace"]
