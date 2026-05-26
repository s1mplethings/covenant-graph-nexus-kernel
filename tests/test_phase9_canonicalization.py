from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy

from tests.helpers import ROOT, cloned_flow, codes
from cgnk_core import ContractRegistry, apply_graph_edit_proposal, compile_flow, diff_compile_results


class Phase9CanonicalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def test_stable_topological_order(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        scrambled = deepcopy(flow)
        scrambled["nodes"] = list(reversed(scrambled["nodes"]))
        scrambled["edges"] = list(reversed(scrambled["edges"]))

        baseline = compile_flow("flow.project_refactor@1", self.registry, flow_doc=flow)
        result = compile_flow("flow.project_refactor@1", self.registry, flow_doc=scrambled)

        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(
            ["n_snapshot", "n_build_graph", "n_plan", "n_emit_patch", "n_validate_patch"],
            result["symbol_table"]["topological_order"],
        )
        self.assertEqual(baseline["graph_hash"], result["graph_hash"])

    def test_stable_edge_ids_do_not_depend_on_array_index(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        reversed_flow = deepcopy(flow)
        reversed_flow["edges"] = list(reversed(reversed_flow["edges"]))

        first = compile_flow("flow.project_refactor@1", self.registry, flow_doc=flow)
        second = compile_flow("flow.project_refactor@1", self.registry, flow_doc=reversed_flow)
        first_edges = [edge["edge_id"] for edge in first["compiled_flow"]["edges"]]
        second_edges = [edge["edge_id"] for edge in second["compiled_flow"]["edges"]]

        self.assertEqual(first_edges, second_edges)
        self.assertTrue(all(edge_id.startswith("edge.") for edge_id in first_edges))
        self.assertFalse(any(edge_id in {"e0", "e1"} for edge_id in first_edges))

    def test_graph_hash_stability_and_policy_hash(self) -> None:
        one = compile_flow("flow.project_refactor@1", self.registry)
        two = compile_flow("flow.project_refactor@1", self.registry)
        self.assertEqual(one["surface_hash"], two["surface_hash"])
        self.assertEqual(one["policy_hash"], two["policy_hash"])
        self.assertEqual(one["graph_hash"], two["graph_hash"])
        self.assertEqual(64, len(one["graph_hash"]))

    def test_cycle_diagnostic_has_cycle_path(self) -> None:
        flow = cloned_flow(self.registry, "flow.project_refactor@1")
        flow["edges"].append(
            {
                "from": {"node": "n_validate_patch", "port": "patch_manifest"},
                "to": {"node": "n_emit_patch", "port": "plan"},
            }
        )
        result = compile_flow("flow.project_refactor@1", self.registry, flow_doc=flow)
        self.assertIn("CGNK_GRAPH_CYCLE", codes(result))
        cycle = next(d for d in result["diagnostics"] if d["code"] == "CGNK_GRAPH_CYCLE")
        self.assertEqual("CGNK_GRAPH_CYCLE", cycle["code"])
        self.assertIn("involved_ref", cycle)
        self.assertIsInstance(cycle["actual"], list)
        self.assertGreaterEqual(len(cycle["actual"]), 2)

    def test_diff_output_and_cli(self) -> None:
        before = compile_flow("flow.project_generation@1", self.registry)
        proposal = {
            "kind": "GraphEditProposal",
            "id": "proposal.phase9_replace_plan",
            "target_flow": "flow.project_generation@1",
            "edits": [
                {
                    "op": "replace_node",
                    "target_node": "n_plan",
                    "replacement": {"id": "n_plan", "uses": "module.plan.generate.contract_only@1"},
                }
            ],
        }
        preview = apply_graph_edit_proposal(proposal, self.registry)
        after = preview["compile_result"]
        diff = diff_compile_results(before, after)
        self.assertFalse(diff["ok"])
        self.assertEqual(
            [{"node_id": "n_plan", "before": "module.plan.generate.provider@1", "after": "module.plan.generate.contract_only@1"}],
            diff["module_changed"],
        )
        self.assertFalse(diff["risk_increased"])

        synthetic_after = deepcopy(after)
        synthetic_after["effect_summary"]["max_risk"] = before["effect_summary"]["max_risk"] + 1
        self.assertTrue(diff_compile_results(before, synthetic_after)["risk_increased"])

        with tempfile.TemporaryDirectory() as td:
            before_path = f"{td}/before.json"
            after_path = f"{td}/after.json"
            with open(before_path, "w", encoding="utf-8") as handle:
                json.dump(before, handle)
            with open(after_path, "w", encoding="utf-8") as handle:
                json.dump(after, handle)
            proc = subprocess.run(
                [sys.executable, "scripts/cgnk_diff.py", before_path, after_path],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            cli_diff = json.loads(proc.stdout)
            self.assertEqual(diff["module_changed"], cli_diff["module_changed"])

    def test_proposal_preview_hash_changes(self) -> None:
        before = compile_flow("flow.project_generation@1", self.registry)
        proposal = {
            "kind": "GraphEditProposal",
            "id": "proposal.phase9_hash_change",
            "target_flow": "flow.project_generation@1",
            "edits": [
                {
                    "op": "replace_node",
                    "target_node": "n_plan",
                    "replacement": {"id": "n_plan", "uses": "module.plan.generate.contract_only@1"},
                }
            ],
        }
        preview = apply_graph_edit_proposal(proposal, self.registry)
        self.assertTrue(preview["ok"], preview["diagnostics"])
        self.assertNotEqual(before["graph_hash"], preview["compile_result"]["graph_hash"])


if __name__ == "__main__":
    unittest.main()
