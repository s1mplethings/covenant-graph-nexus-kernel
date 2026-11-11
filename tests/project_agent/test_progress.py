from __future__ import annotations

import unittest
from types import SimpleNamespace

from cgkn.agent.progress import (BUDGET_BLOCKED, INFRA_BLOCKED, NO_PROGRESS,
                                 PROGRESS, PROJECT_REPLAN, PROTOCOL_REPAIRABLE,
                                 QUARANTINE_STRATEGY, REGRESSION, STOP_BUDGET,
                                 STOP_INFRA, SUCCESS, ExecutionProgressController,
                                 LOCAL_PROTOCOL_REPAIR, observe_result)
from cgkn.execution import (BlockExecutionResult, BlockStatus, ExecutionError,
                            ExecutionErrorCode)


def node(kind="IMPLEMENTATION"):
    return SimpleNamespace(config={
        "executor_ref": "llm.cheap@1",
        "leaf_contract": {"leaf_goal": "repair", "task_kind": kind,
                          "target_scope": ["a.txt"], "acceptance": ["files"],
                          "checker_ref": "c", "output_identity": "n",
                          "effect_domains": ["filesystem"], "executor_ref": "llm.cheap@1",
                          "dependencies": []},
    })


def result(status=BlockStatus.FAILED, details=None, message="failed",
           subjects=None, delta=None, evidence=None):
    kwargs = {}
    if status not in {BlockStatus.SUCCEEDED, BlockStatus.SKIPPED}:
        kwargs["error"] = ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, message, details or {})
    return BlockExecutionResult(
        project_id="p", run_id="r", attempt_id="a", node_id="n",
        executor_ref="llm.cheap@1", status=status, outputs={},
        started_at="t0", ended_at="t1", duration_ms=1,
        metadata={"deliverable_check": {
            "subjects": subjects or {}, "artifact_delta": delta or {},
            "evidence_refs": evidence or [], "verdict": "FAILED",
        }}, **kwargs)


class ProgressClassificationTests(unittest.TestCase):
    def test_changed_artifact_is_progress(self):
        observation = observe_result(
            result(subjects={"a.txt": "new"}, delta={"a.txt": {"before": "old", "after": "new"}}),
            node(), artifact_before="old", deliverable_verdict="SUCCEEDED")
        self.assertIn(observation.progress_class, {PROGRESS, SUCCESS})
        self.assertTrue(observation.artifact_changed)

    def test_new_evidence_is_progress(self):
        observation = observe_result(
            result(evidence=[{"path": "a.txt", "sha256": "new"}]),
            node(), evidence_before=("a.txt:old",))
        self.assertEqual(observation.progress_class, PROGRESS)

    def test_regression(self):
        observation = observe_result(
            result(subjects={"a.txt": "new"}, delta={"a.txt": {"before": "old", "after": "new"}}),
            node(), artifact_before="old", deliverable_verdict="FAILED")
        self.assertEqual(observation.progress_class, REGRESSION)

    def test_budget_is_not_a_business_failure(self):
        observation = observe_result(
            result(details={"failure_domain": "BUDGET", "budget_blocked": True},
                   message="PROVIDER_BUDGET_EXHAUSTED: max_api_calls"),
            node())
        self.assertEqual(observation.progress_class, BUDGET_BLOCKED)
        self.assertEqual(observation.budget_status, "BLOCKED")
        controller = ExecutionProgressController()
        self.assertEqual(controller.observe(observation), STOP_BUDGET)

    def test_protocol_schema_failure_is_repairable(self):
        observation = observe_result(
            result(details={"failure_domain": "MODEL_OUTPUT", "failure_class": "schema"},
                   message="schema_validation_failed"),
            node())
        self.assertEqual(observation.progress_class, PROTOCOL_REPAIRABLE)
        controller = ExecutionProgressController(max_protocol_repairs=1)
        self.assertEqual(controller.observe(observation), LOCAL_PROTOCOL_REPAIR)
        second = observe_result(
            result(details={"failure_domain": "MODEL_OUTPUT", "failure_class": "schema"},
                   message="schema_validation_failed"),
            node())
        self.assertEqual(controller.observe(second), PROJECT_REPLAN)

    def test_infra_is_separate_and_stops_after_repeat(self):
        observation = observe_result(
            result(details={"failure_domain": "TRANSPORT"}, message="NetworkUnavailable"),
            node())
        self.assertEqual(observation.progress_class, INFRA_BLOCKED)
        self.assertEqual(observation.business_status, "UNKNOWN")
        controller = ExecutionProgressController(max_same_failure=2)
        self.assertNotEqual(controller.observe(observation), STOP_INFRA)
        second = observe_result(
            result(details={"failure_domain": "TRANSPORT"}, message="NetworkUnavailable"),
            node())
        self.assertEqual(controller.observe(second), STOP_INFRA)

    def test_same_failure_same_strategy_no_artifact_quarantines(self):
        controller = ExecutionProgressController(max_same_failure=2)
        first = observe_result(result(message="same failure"), node(), artifact_before="x")
        second = observe_result(result(message="same failure"), node(), artifact_before="x")
        self.assertNotEqual(controller.observe(first), QUARANTINE_STRATEGY)
        self.assertEqual(controller.observe(second), QUARANTINE_STRATEGY)

    def test_success(self):
        observation = observe_result(result(status=BlockStatus.SUCCEEDED), node())
        self.assertEqual(observation.progress_class, SUCCESS)


if __name__ == "__main__":
    unittest.main()
