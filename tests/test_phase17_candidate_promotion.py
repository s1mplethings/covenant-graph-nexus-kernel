from __future__ import annotations

from copy import deepcopy
import unittest

from tests.helpers import ROOT, codes
from cgnk_core import ContractRegistry, SchemaLoader
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.candidate_promotion import validate_candidate_promotion


class Phase17CandidatePromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ContractRegistry(ROOT, validate_schema=True)
        self.loader = SchemaLoader(ROOT)
        self.inventory = load_json(ROOT / "examples" / "ctcp" / "ctcp_module_inventory.curated.json")
        self.transfer = load_json(ROOT / "examples" / "ctcp" / "ctcp_transfer_plan.curated.json")

    def test_curated_inventory_and_transfer_plan_validate(self) -> None:
        self.assertEqual([], self.loader.validate(self.inventory, "ctcp_module_inventory.schema.json"))
        self.assertEqual([], self.loader.validate(self.transfer, "ctcp_transfer_plan.schema.json"))

    def test_promoted_candidate_contracts_validate(self) -> None:
        report = validate_candidate_promotion(self.inventory, self.transfer, self.registry)
        self.assertTrue(report["ok"], report["diagnostics"])
        promoted = set(report["promoted_modules"])
        self.assertIn("module.project.snapshot@1", promoted)
        self.assertIn("module.project.build_graph@1", promoted)
        self.assertIn("module.plan.generate.contract_only@1", promoted)
        self.assertIn("module.patch.emit@1", promoted)
        self.assertIn("module.patch.validate@1", promoted)
        self.assertIn("module.migration.proof@1", promoted)
        self.assertIn("module.repair.plan@1", promoted)

    def test_promoted_modules_include_source_trace_without_code(self) -> None:
        for row in self.transfer["modules"]:
            module = self.registry.resolve_module(row["target_module"])
            self.assertIsNotNone(module)
            trace = module["source_trace"]
            self.assertEqual(row["candidate"], trace["candidate"])
            self.assertTrue(trace["legacy_files"])
            self.assertTrue(trace["legacy_symbols"])
            self.assertTrue(trace["evidence_keywords"])
            flattened = "\n".join([trace["candidate"], *trace["legacy_files"], *trace["legacy_symbols"], *trace["evidence_keywords"]])
            self.assertNotIn("def ", flattened)
            self.assertNotIn("class ", flattened)
            self.assertNotIn("import ", flattened)

    def test_fixed_pipeline_glue_is_rejected_by_checker(self) -> None:
        inventory = deepcopy(self.inventory)
        transfer = deepcopy(self.transfer)
        inventory["candidates"].append(
            {
                "id": "candidate.legacy_glue",
                "source": {
                    "files": ["legacy/orchestrator.py"],
                    "symbols": ["old_orchestrator_runner"],
                    "evidence": ["orchestrator"]
                },
                "classification": {
                    "category": "legacy_glue",
                    "role": "fixed_pipeline_glue",
                    "migration_value": "reject"
                },
                "contract_guess": {
                    "module_ref": "module.project.snapshot@1",
                    "inputs": ["artifact.goal@1"],
                    "outputs": ["artifact.project_snapshot@1"]
                },
                "effects": {
                    "fs_read": True,
                    "fs_write": True,
                    "network": False,
                    "provider_call": False
                },
                "transfer": {
                    "recommended": False,
                    "strategy": "discard",
                    "notes": []
                }
            }
        )
        transfer["modules"].append(
            {
                "candidate": "candidate.legacy_glue",
                "target_module": "module.project.snapshot@1",
                "priority": "reject",
                "action": "discard",
                "copy_old_code": False,
                "notes": []
            }
        )
        report = validate_candidate_promotion(inventory, transfer, self.registry)
        self.assertFalse(report["ok"])
        self.assertIn("CGNK_CTCP_CANDIDATE_NOT_REUSABLE", codes(report))

    def test_missing_source_trace_is_reported(self) -> None:
        registry = ContractRegistry(ROOT, validate_schema=True)
        module = deepcopy(registry.modules["module.project.snapshot@1"])
        module.pop("source_trace", None)
        registry.modules["module.project.snapshot@1"] = module
        report = validate_candidate_promotion(self.inventory, self.transfer, registry)
        self.assertFalse(report["ok"])
        self.assertIn("CGNK_CTCP_CONTRACT_SOURCE_TRACE_MISSING", codes(report))


if __name__ == "__main__":
    unittest.main()
