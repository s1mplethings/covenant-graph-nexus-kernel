from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cgnk_core import ContractIndex, ReferenceCompiler, validate_bundle


class BaselineValidateBundleTest(unittest.TestCase):
    def test_project_generation_and_refactor_compile_ok(self) -> None:
        result = validate_bundle(ROOT, schema=False)
        by_ref = {row["flow_ref"]: row for row in result["results"]}

        self.assertTrue(by_ref["flow.project_generation@1"]["ok"])
        self.assertTrue(by_ref["flow.project_refactor@1"]["ok"])
        self.assertEqual([], by_ref["flow.project_generation@1"]["diagnostics"])
        self.assertEqual([], by_ref["flow.project_refactor@1"]["diagnostics"])

    def test_project_refactor_uses_contract_only_planning_under_safe_policy(self) -> None:
        idx = ContractIndex(ROOT)
        flow = idx.flows["flow.project_refactor@1"]
        self.assertEqual("policy.safe_project_refactor@1", flow["policy_ref"])
        self.assertIn({"id": "n_plan", "uses": "module.plan.generate.contract_only@1"}, flow["nodes"])

        compiler = ReferenceCompiler(idx)
        result = compiler.compile("flow.project_refactor@1")
        self.assertTrue(result["ok"])

        plan_module = idx.modules["module.plan.generate.contract_only@1"]
        self.assertFalse(plan_module["effects"]["provider_call"])
        self.assertFalse(plan_module["effects"]["network"])

    def test_thin_cli_wrapper_runs_default_and_schema_modes(self) -> None:
        default = subprocess.run(
            [sys.executable, "scripts/validate_bundle.py"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(default.returncode, 0, default.stdout + default.stderr)
        self.assertIn("flow.project_generation@1: OK", default.stdout)
        self.assertIn("flow.project_refactor@1: OK", default.stdout)

        schema = subprocess.run(
            [sys.executable, "scripts/validate_bundle.py", "--schema"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(schema.returncode, 0, schema.stdout + schema.stderr)


if __name__ == "__main__":
    unittest.main()
