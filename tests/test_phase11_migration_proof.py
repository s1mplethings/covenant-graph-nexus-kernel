from __future__ import annotations

from copy import deepcopy
import pathlib
import tempfile
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry, SchemaLoader, build_agent_contract_pack, compile_flow
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.migration import build_migration_proof, check_migration_spec


class Phase11MigrationProofTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)
        self.spec = load_json(ROOT / "examples" / "migrations" / "project_generation.migration.json")

    def make_ctcp_fixture(self, include_entrypoint: bool = True, missing_file: str | None = None) -> tempfile.TemporaryDirectory:
        td = tempfile.TemporaryDirectory()
        root = pathlib.Path(td.name)
        for rel in self.spec["legacy"]["files"]:
            if rel == missing_file:
                continue
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            text = "fixture\n"
            if include_entrypoint and rel.endswith("run_concrete_project_benchmark.py"):
                text += "def run_concrete_project_benchmark():\n    pass\n"
            path.write_text(text, encoding="utf-8")
        return td

    def test_valid_migration_proof_with_temp_ctcp_fixture(self) -> None:
        with self.make_ctcp_fixture() as td:
            proof = build_migration_proof(self.spec, self.registry, pathlib.Path(td))
        self.assertTrue(proof["ok"], proof["diagnostics"])
        self.assertEqual("MigrationProof", proof["kind"])
        self.assertEqual("migration.project_generation@1", proof["migration_ref"])
        self.assertEqual("flow.project_generation@1", proof["target_flow"])
        self.assertEqual([], SchemaLoader(ROOT).validate(proof, "migration_proof.schema.json"))

    def test_missing_legacy_file_diagnostic(self) -> None:
        missing = self.spec["legacy"]["files"][0]
        with self.make_ctcp_fixture(missing_file=missing) as td:
            proof = build_migration_proof(self.spec, self.registry, pathlib.Path(td))
        self.assertFalse(proof["ok"])
        self.assertIn("CGNK_MIGRATION_LEGACY_FILE_MISSING", codes(proof))

    def test_missing_entrypoint_diagnostic(self) -> None:
        with self.make_ctcp_fixture(include_entrypoint=False) as td:
            proof = build_migration_proof(self.spec, self.registry, pathlib.Path(td))
        self.assertFalse(proof["ok"])
        self.assertIn("CGNK_MIGRATION_ENTRYPOINT_MISSING", codes(proof))

    def test_missing_target_flow_module_artifact_diagnostics(self) -> None:
        spec = deepcopy(self.spec)
        spec["target"]["flow"] = "flow.missing@1"
        spec["target"]["modules"] = ["module.missing@1"]
        spec["target"]["artifacts"] = ["artifact.missing@1"]
        with self.make_ctcp_fixture() as td:
            proof = build_migration_proof(spec, self.registry, pathlib.Path(td))
        found = codes(proof)
        self.assertIn("CGNK_MIGRATION_TARGET_FLOW_MISSING", found)
        self.assertIn("CGNK_MIGRATION_TARGET_MODULE_MISSING", found)
        self.assertIn("CGNK_MIGRATION_TARGET_ARTIFACT_MISSING", found)

    def test_missing_required_proof_evidence_diagnostics(self) -> None:
        spec = deepcopy(self.spec)
        spec["proof"]["required_tests"] = []
        spec["proof"]["required_artifacts"] = []
        spec["proof"]["required_schemas"] = []
        with self.make_ctcp_fixture() as td:
            proof = build_migration_proof(spec, self.registry, pathlib.Path(td))
        found = codes(proof)
        self.assertIn("CGNK_MIGRATION_REQUIRED_TEST_MISSING", found)
        self.assertIn("CGNK_MIGRATION_REQUIRED_ARTIFACT_MISSING", found)
        self.assertIn("CGNK_MIGRATION_REQUIRED_SCHEMA_MISSING", found)

    def test_migration_report_contains_machine_readable_proof(self) -> None:
        with self.make_ctcp_fixture() as td:
            report = check_migration_spec(self.spec, self.registry, pathlib.Path(td))
        self.assertTrue(report["ok"], report["diagnostics"])
        self.assertEqual("MigrationProof", report["migration_proof"]["kind"])

    def test_migration_agent_pack_declares_migration_proof_output(self) -> None:
        result = compile_flow("flow.project_refactor@1", self.registry)
        flow = self.registry.resolve_flow("flow.project_refactor@1")
        policy = self.registry.resolve_policy(result["policy_ref"])
        pack = build_agent_contract_pack(result, flow, policy, list(self.registry.modules.values()), list(self.registry.artifacts.values()), "migration")
        self.assertEqual("MigrationProof", pack["agent_output_contract"]["required_output_kind"])


if __name__ == "__main__":
    unittest.main()
