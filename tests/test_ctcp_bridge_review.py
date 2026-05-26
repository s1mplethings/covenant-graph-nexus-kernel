from __future__ import annotations

from copy import deepcopy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from cgnk_core import SchemaLoader
from cgnk_core.schema_loader import load_json
from cgnk_ctcp.bridge_review import review_ctcp_bridge
from tests.helpers import ROOT, codes


class CTCPBridgeReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = SchemaLoader(ROOT)
        self.proposal = load_json(ROOT / "examples" / "ctcp_bridge_proposals" / "project_generation_bridge.proposal.json")
        self.patch_manifest = load_json(ROOT / "examples" / "patch_manifests" / "project_generation_contract_bridge.patch_manifest.json")

    def test_valid_bridge_proposal_is_approvable(self) -> None:
        review = review_ctcp_bridge(self.proposal, self.patch_manifest, schema_loader=self.loader)
        self.assertTrue(review["ok"], review["diagnostics"])
        self.assertEqual("CTCPBridgeReview", review["kind"])
        self.assertEqual("approvable", review["approval_status"])
        self.assertEqual("feature.project_generation", review["target_feature"])
        self.assertEqual(["existing project generation CLI", "existing provider selection behavior"], review["preserved_entrypoints"])
        self.assertEqual([], review["violations"])
        self.assertEqual([], self.loader.validate(review, "ctcp_bridge_review.schema.json"))

    def test_forbidden_effects_block_review(self) -> None:
        proposal = deepcopy(self.proposal)
        patch_manifest = deepcopy(self.patch_manifest)
        proposal["patch_apply"] = True
        patch_manifest["workspace_write"] = True
        review = review_ctcp_bridge(proposal, patch_manifest)
        self.assertFalse(review["ok"])
        self.assertEqual("blocked", review["approval_status"])
        self.assertIn("CGNK_CTCP_BRIDGE_FORBIDDEN_EFFECT", codes(review))

    def test_forbidden_files_block_review(self) -> None:
        proposal = deepcopy(self.proposal)
        patch_manifest = deepcopy(self.patch_manifest)
        proposal["proposed_files"].append({"path": "final_output/project_output.zip", "purpose": "bad output", "change_type": "create"})
        patch_manifest["file_changes"].append({"action": "create", "path": "final_output/project_output.zip", "reason": "bad output"})
        review = review_ctcp_bridge(proposal, patch_manifest)
        self.assertFalse(review["ok"])
        found = codes(review)
        self.assertIn("CGNK_CTCP_BRIDGE_FORBIDDEN_FILE", found)

    def test_missing_tests_and_rollback_block_review(self) -> None:
        proposal = deepcopy(self.proposal)
        proposal["required_tests"] = []
        proposal["rollback_plan"] = ""
        review = review_ctcp_bridge(proposal, self.patch_manifest)
        self.assertFalse(review["ok"])
        found = codes(review)
        self.assertIn("CGNK_CTCP_BRIDGE_TESTS_MISSING", found)
        self.assertIn("CGNK_CTCP_BRIDGE_ROLLBACK_MISSING", found)

    def test_default_behavior_and_provider_semantics_are_required(self) -> None:
        proposal = deepcopy(self.proposal)
        proposal["default_behavior_unchanged"] = False
        proposal["provider_semantics_unchanged"] = False
        proposal["optional_new_entrypoints"] = []
        review = review_ctcp_bridge(proposal, self.patch_manifest)
        self.assertFalse(review["ok"])
        found = codes(review)
        self.assertIn("CGNK_CTCP_BRIDGE_DEFAULT_BEHAVIOR_RISK", found)
        self.assertIn("CGNK_CTCP_BRIDGE_PROVIDER_SEMANTICS_RISK", found)

    def test_cli_writes_review_to_temp_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = pathlib.Path(td) / "ctcp_bridge_review.json"
            run = subprocess.run(
                [
                    sys.executable,
                    "scripts/cgnk_review_ctcp_bridge.py",
                    "--proposal",
                    "examples/ctcp_bridge_proposals/project_generation_bridge.proposal.json",
                    "--patch-manifest",
                    "examples/patch_manifests/project_generation_contract_bridge.patch_manifest.json",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            review = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(review["ok"], review["diagnostics"])
        self.assertEqual("approvable", review["approval_status"])


if __name__ == "__main__":
    unittest.main()
