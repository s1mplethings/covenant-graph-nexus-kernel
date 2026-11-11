from __future__ import annotations

from tests.executor_authority_support import invoke_bound_executor
import json
import pathlib
import tempfile
import unittest

from cgkn.execution import BlockExecutionRequest, BlockStatus, TaskContext
from cgkn.executors.llm import LLMExecutor, repair_worker_envelope, validate_worker_proposal
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.providers import ModelRoleConfig, ProviderCompletion


def contract():
    return build_leaf_contract(
        goal="write out.txt", kind="IMPLEMENTATION", scope=["out.txt"],
        acceptance=["out.files"], checker="out.check", output_identity="out.write",
        effect_domains=["filesystem"], executor="llm.cheap@1", dependencies=[],
        expected_delta="out.txt exists")


def request(root: pathlib.Path, node_id="out.write"):
    return BlockExecutionRequest(
        project_id="p", run_id="r", attempt_id="a", node_id=node_id,
        component_ref="out.write@1", executor_ref="llm.cheap@1",
        task_context=TaskContext(node_goal="write out.txt",
                                 node_config={"leaf_contract": contract(),
                                              "executor_ref": "llm.cheap@1"},
                                 dependency_results={}),
        timeout_seconds=30)


def proposal(actions, summary="do it"):
    return json.dumps({
        "schema_version": "1.0", "node_id": "out.write", "summary": summary,
        "actions": actions, "expected_outputs": ["out.txt"], "confidence": 0.8,
        "needs_escalation": False, "escalation_reason": "",
    })


class FakeClient:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def complete(self, **kwargs):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return ProviderCompletion(text, "deepseek-flash", f"req-{self.calls}",
                                  {"input_tokens": 10, "output_tokens": 10}, 1)


class RaisingClient:
    def __init__(self, exc):
        self.exc = exc

    def complete(self, **kwargs):
        raise self.exc


class WorkerProtocolRepairTests(unittest.TestCase):
    def test_single_missing_field_is_filled_and_business_actions_preserved(self):
        value = {
            "schema_version": "1.0", "node_id": "out.write", "summary": "s",
            "actions": [{"action": "write_file", "path": "out.txt", "content": "ok"}],
            "confidence": 0.7, "needs_escalation": False, "escalation_reason": "",
        }
        repaired, filled = repair_worker_envelope(value, "out.write")
        self.assertEqual(filled, ["expected_outputs"])
        self.assertEqual(repaired["actions"], value["actions"])
        self.assertEqual(validate_worker_proposal(repaired, "out.write")["actions"], value["actions"])

    def test_multiple_missing_fields_are_filled(self):
        value = {
            "schema_version": "1.0", "node_id": "out.write", "summary": "s",
            "actions": [{"action": "write_file", "path": "out.txt", "content": "ok"}],
        }
        repaired, filled = repair_worker_envelope(value, "out.write")
        self.assertEqual(set(filled), {"expected_outputs", "confidence",
                                       "needs_escalation", "escalation_reason"})
        self.assertEqual(repaired["expected_outputs"], ["out.txt"])
        validate_worker_proposal(repaired, "out.write")

    def test_missing_actions_is_not_repairable(self):
        repaired, filled = repair_worker_envelope(
            {"schema_version": "1.0", "node_id": "out.write", "summary": "s"}, "out.write")
        self.assertIn("actions", filled)
        with self.assertRaises(Exception):
            validate_worker_proposal(repaired, "out.write")


class WorkerLoopTests(unittest.TestCase):
    def test_read_then_write_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "out.txt").write_text("old", encoding="utf-8")
            client = FakeClient([
                proposal([{"action": "read_file", "path": "out.txt"}]),
                proposal([{"action": "write_file", "path": "out.txt", "content": "new"}]),
            ])
            executor = LLMExecutor(root, client, ModelRoleConfig(
                "worker", "deepseek", 30, 500, 0.0, "none", "deepseek-flash"), max_rounds=4)
            result = invoke_bound_executor(executor, request(root))
            self.assertEqual(result.status, BlockStatus.SUCCEEDED)
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "new")
            self.assertEqual(client.calls, 2)

    def test_repeated_read_only_stops_without_artifact_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "out.txt").write_text("old", encoding="utf-8")
            client = FakeClient([proposal([{"action": "read_file", "path": "out.txt"}])])
            executor = LLMExecutor(root, client, ModelRoleConfig(
                "worker", "deepseek", 30, 500, 0.0, "none", "deepseek-flash"), max_rounds=4)
            result = invoke_bound_executor(executor, request(root))
            self.assertEqual(result.status, BlockStatus.BLOCKED)
            self.assertIn("NO_LOCAL_PROGRESS", result.error.message)
            self.assertLessEqual(client.calls, 4)

    def test_budget_denial_is_not_a_business_failure(self):
        from scripts.provider_api_budget import ProviderBudgetExhausted
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "out.txt").write_text("old", encoding="utf-8")
            executor = LLMExecutor(root, RaisingClient(
                ProviderBudgetExhausted("PROVIDER_BUDGET_EXHAUSTED: max_api_calls")),
                ModelRoleConfig("worker", "deepseek", 30, 500, 0.0, "none", "deepseek-flash"))
            result = invoke_bound_executor(executor, request(root))
            self.assertEqual(result.status, BlockStatus.BLOCKED)
            self.assertEqual(result.error.details.get("failure_domain"), "BUDGET")
            self.assertTrue(result.error.details.get("budget_blocked"))

    def test_transport_failure_is_infra_not_model(self):
        from cgkn.providers.gateway_client import GatewayCompletionError
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "out.txt").write_text("old", encoding="utf-8")
            executor = LLMExecutor(root, RaisingClient(
                GatewayCompletionError("network_unavailable_before_send", "boom",
                                       outcome_unknown=False)),
                ModelRoleConfig("worker", "deepseek", 30, 500, 0.0, "none", "deepseek-flash"))
            result = invoke_bound_executor(executor, request(root))
            self.assertEqual(result.status, BlockStatus.BLOCKED)
            self.assertEqual(result.error.details.get("failure_domain"), "TRANSPORT")


if __name__ == "__main__":
    unittest.main()
