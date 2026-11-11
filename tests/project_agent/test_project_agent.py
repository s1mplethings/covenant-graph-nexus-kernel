from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from cgkn.agent.project_agent import (AdmissionPolicy, ExternalFileProjectAgent,
                                      EmbeddedProjectAgent, ProjectProposal, admit_proposal)
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.orchestration.tree_edits import TreeEdit


def catalog() -> dict:
    contract = build_leaf_contract(
        goal="write one demo file", kind="IMPLEMENTATION", scope=["out.txt"],
        acceptance=["demo.files"], checker="demo.check", output_identity="demo.write",
        effect_domains=["filesystem"], executor="local.file@1", dependencies=[],
        expected_delta="out.txt exists")
    return {
        "demo.write@1": {
            "executor_ref": "local.file@1",
            "config": {"executor_ref": "local.file@1", "action": "write_file",
                       "path": "out.txt", "content": "ok", "leaf_contract": contract},
        }
    }


def add_operation(capability="demo.write@1", node="demo.write", depends_on=()):
    return {"operation": "add_node", "node_id": node, "capability_ref": capability,
            "parent_id": "", "depends_on": list(depends_on), "config": {}}


def proposal(operations, base=1):
    return ProjectProposal(
        proposal_id="p-1", project_id="demo", base_tree_version=base,
        goal_reference="demo goal", observed_evidence_refs=["evidence/env.json"],
        proposed_operations=tuple(operations), repair_strategy="add one frontier",
        resource_preference="deterministic", expected_progress="one node",
        reason_summary="the current frontier needs one capability")


class ProjectAgentAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tree = CapabilityTree("demo goal", ())
        self.catalog = catalog()
        self.known = {"demo.write@1"}

    def policy(self, **kwargs):
        values = dict(incremental_mode=True, max_new_nodes=1,
                      allowed_effect_domains=frozenset({"filesystem", "measurement", "demo"}))
        values.update(kwargs)
        return AdmissionPolicy(**values)

    def test_external_proposal_admitted(self):
        result = admit_proposal(self.tree, 1, proposal([add_operation()]),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertTrue(result.valid, result.as_dict())
        self.assertEqual(result.code, "ADMITTED")
        self.assertEqual(len(result.preview.nodes), 1)

    def test_external_file_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "project_agent_proposal.json"
            path.write_text(json.dumps(proposal([add_operation()]).as_dict()), encoding="utf-8")
            loaded = ExternalFileProjectAgent(path).propose({"project_id": "demo"})
            result = admit_proposal(self.tree, 1, loaded, known_capabilities=self.known,
                                    catalog=self.catalog, policy=self.policy())
            self.assertTrue(result.valid, result.as_dict())

    def test_stale_base_version_rejected(self):
        result = admit_proposal(self.tree, 2, proposal([add_operation()], base=1),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertFalse(result.valid)
        self.assertEqual(result.code, "STALE_BASE_TREE_VERSION")

    def test_unknown_capability_rejected_with_canonical_hint(self):
        result = admit_proposal(self.tree, 1, proposal([add_operation("demo.unknown@1")]),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertFalse(result.valid)
        self.assertEqual(result.code, "UNKNOWN_CAPABILITY")
        self.assertIn("requested", result.details)

    def test_invalid_dependency_rejected(self):
        result = admit_proposal(self.tree, 1, proposal([add_operation(depends_on=["missing"])]),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertFalse(result.valid)
        self.assertIn(result.code, {"INVALID_DEPENDENCY", "INVALID_TREE_EDIT"})

    def test_incremental_mode_rejects_upfront_tree(self):
        operations = [add_operation(node="demo.write"),
                      add_operation(node="demo.write.two")]
        result = admit_proposal(self.tree, 1, proposal(operations),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertFalse(result.valid)
        self.assertEqual(result.code, "INCREMENTAL_LIMIT")

    def test_admission_does_not_mutate_authoritative_tree(self):
        before = self.tree.as_dict()
        result = admit_proposal(self.tree, 1, proposal([add_operation()]),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertTrue(result.valid)
        self.assertEqual(self.tree.as_dict(), before)
        self.assertEqual(len(result.preview.nodes), 1)

    def test_budget_blocks_model_resource(self):
        operation = add_operation()
        operation["config"] = {"executor_ref": "llm.cheap@1"}
        result = admit_proposal(self.tree, 1, proposal([operation]),
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy(budget_state="BLOCKED"))
        self.assertFalse(result.valid)
        self.assertEqual(result.code, "BUDGET_BLOCKED")

    def test_embedded_planner_uses_same_admission(self):
        edit = TreeEdit("e1", "add_node", "demo.write",
                        {"capability_ref": "demo.write@1", "parent_id": "",
                         "depends_on": [], "config": {}},
                        {"reason": "test"})

        class Decision:
            decision_id = "d1"
            summary = "add the frontier"
            reason = "needed now"
            edits = (edit,)

        class Composer:
            def decide(self, context):
                return Decision()

        class Context:
            project_id = "demo"
            goal = "demo goal"
            project_intent = {"tree_version": 1}
            failure_details = {}

        proposal_from_embedded = EmbeddedProjectAgent(Composer()).propose(Context())
        result = admit_proposal(self.tree, 1, proposal_from_embedded,
                                known_capabilities=self.known, catalog=self.catalog,
                                policy=self.policy())
        self.assertTrue(result.valid, result.as_dict())


if __name__ == "__main__":
    unittest.main()
