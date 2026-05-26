from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import ROOT
from cgnk_core import ContractRegistry, SchemaLoader, build_agent_contract_pack, compile_flow


class Phase10AgentContractPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)

    def build_pack(self) -> dict:
        result = compile_flow("flow.project_refactor@1", self.registry)
        self.assertTrue(result["ok"], result["diagnostics"])
        flow = self.registry.resolve_flow("flow.project_refactor@1")
        policy = self.registry.resolve_policy(result["policy_ref"])
        return build_agent_contract_pack(
            result,
            flow,
            policy,
            list(self.registry.modules.values()),
            list(self.registry.artifacts.values()),
            "refactor",
        )

    def test_pack_generation_for_project_refactor(self) -> None:
        pack = self.build_pack()
        self.assertEqual("AgentContractPack", pack["kind"])
        self.assertEqual("flow.project_refactor@1", pack["target_flow"])
        self.assertEqual("refactor", pack["task"]["kind"])
        self.assertEqual("flow.project_refactor@1", pack["compiled_flow"]["flow_ref"])

    def test_pack_includes_only_relevant_contracts(self) -> None:
        pack = self.build_pack()
        module_refs = {f"{m['id']}@{m['version']}" for m in pack["module_contracts"]}
        artifact_refs = {f"{a['id']}@{a['version']}" for a in pack["artifact_specs"]}
        policy_refs = {f"{p['id']}@{p['version']}" for p in pack["policies"]}

        self.assertEqual(
            {
                "module.project.snapshot@1",
                "module.project.build_graph@1",
                "module.plan.generate.contract_only@1",
                "module.patch.emit@1",
                "module.patch.validate@1",
            },
            module_refs,
        )
        self.assertNotIn("module.plan.generate.provider@1", module_refs)
        self.assertNotIn("module.support.reply.orchestrate@1", module_refs)
        self.assertEqual({"policy.safe_project_refactor@1"}, policy_refs)
        self.assertIn("artifact.goal@1", artifact_refs)
        self.assertIn("artifact.validation_report@1", artifact_refs)
        self.assertNotIn("artifact.support_reply@1", artifact_refs)

    def test_pack_hashes_and_graph_edits(self) -> None:
        pack = self.build_pack()
        for key in ("surface_hash", "policy_hash", "graph_hash"):
            self.assertEqual(64, len(pack[key]))
            self.assertEqual(pack[key], pack["hashes"][key])
        self.assertIn("replace_node", pack["allowed_graph_edits"])
        self.assertIn("remove_gate", pack["denied_graph_edits"])
        self.assertTrue(pack["agent_output_contract"]["must_submit_graph_changes_as"] == "GraphEditProposal")

    def test_pack_validates_against_schema_and_diagnostics_are_structured(self) -> None:
        pack = self.build_pack()
        diagnostics = SchemaLoader(ROOT).validate(pack, "agent_contract_pack.schema.json")
        self.assertEqual([], [d.as_dict() for d in diagnostics])
        self.assertIsInstance(pack["diagnostics"], list)
        for diag in pack["diagnostics"]:
            self.assertIn("code", diag)
            self.assertIn("severity", diag)
            self.assertIn("path", diag)

    def test_pack_cli_writes_temp_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = f"{td}/agent_contract_pack.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/cgnk_pack.py",
                    "--flow",
                    "flow.project_refactor@1",
                    "--task",
                    "refactor",
                    "--output",
                    output,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            with open(output, "r", encoding="utf-8") as handle:
                pack = json.load(handle)
            self.assertEqual("AgentContractPack", pack["kind"])
            self.assertEqual("flow.project_refactor@1", pack["target_flow"])


if __name__ == "__main__":
    unittest.main()
