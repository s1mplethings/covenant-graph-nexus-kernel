from __future__ import annotations

import pathlib
import tempfile
import unittest
from dataclasses import asdict
from cgkn.agent.project_agent import AdmissionPolicy
from cgkn.executors import ExecutorRegistry
from cgkn.runtime import DAGRunner
from veriarbor.capability import CapabilityContract

from cgkn.agent.composer import AgentDecision
from cgkn.agent.project_loop import ProjectSession
from cgkn.execution import (BlockExecutionResult, BlockStatus, ExecutionError,
                            ExecutionErrorCode)
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.orchestration.tree_edits import TreeEdit
from cgkn.runtime import RunSummary
from cgkn.state import FileRunStore


class _Registry:
    def list(self):
        return []


class _Runner(DAGRunner):
    def __init__(self, store):
        super().__init__(ExecutorRegistry(),store)
        self.calls = 0

    def run(self, *, project_id, run_id, tree, dag, **kwargs):
        self.calls += 1
        result = BlockExecutionResult(
            project_id=project_id, run_id=run_id, attempt_id="attempt-0001",
            node_id="demo.write", executor_ref="llm.cheap@1",
            status=BlockStatus.BLOCKED, outputs={},
            error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                                 "PROVIDER_BUDGET_EXHAUSTED: max_api_calls",
                                 {"failure_domain": "BUDGET", "budget_blocked": True}),
            started_at="t0", ended_at="t1", duration_ms=1)
        self.store.save_result(result)
        return RunSummary(project_id, run_id, "FAILED", 1, ("demo.write",), (),
                          ("demo.write",), (), 0)


class _Composer:
    def __init__(self):
        self.calls = 0

    def decide(self, context):
        self.calls += 1
        contract = build_leaf_contract(
            goal="write", kind="IMPLEMENTATION", scope=["out.txt"],
            acceptance=["files"], checker="c", output_identity="demo.write",
            effect_domains=["filesystem"], executor="llm.cheap@1", dependencies=[],
            expected_delta="out.txt")
        edit = TreeEdit("e1", "add_node", "demo.write",
                        {"capability_ref": "demo.write@1", "parent_id": "",
                         "depends_on": [],
                         "config": {"executor_ref": "llm.cheap@1",
                                    "leaf_contract": contract}},
                        {"reason": "test"})
        return AgentDecision("d1", "add", "test", (edit,), True, False, False, "",
                             {}, "", 0,decision_audit={'capability_claim':{
                                 'target_capability_id':'demo.write@1','strategy_capabilities':['demo.write@1'],
                                 'exploration_reason':'Budget-stop calibration','exploration_budget':1,
                                 'exploration_measure':'No second planning call after denial'}})


class ProjectSessionBudgetTests(unittest.TestCase):
    def test_budget_block_stops_without_another_planner_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRunStore(pathlib.Path(tmp) / "state")
            composer = _Composer()
            runner = _Runner(store)
            session = ProjectSession(composer, runner, store,
                                     known_capabilities={"demo.write@1"},
                                     worker_model="deepseek", max_decisions=4,
                                     admission_policy=AdmissionPolicy(project_id='p',execution_budget={'calls':0},
                                         capability_contracts={'demo.write@1':asdict(CapabilityContract('demo.write@1',
                                             'Budget denial fixture',critical=False,positive_controls=('budget stop',)))}))
            result = session.run(project_id="p", run_id="r", goal="demo")
            self.assertEqual(result.status, "BLOCKED")
            self.assertIn("BUDGET_BLOCKED", result.escalation_reason)
            self.assertEqual(composer.calls, 1)
            self.assertEqual(runner.calls, 1)


if __name__ == "__main__":
    unittest.main()
