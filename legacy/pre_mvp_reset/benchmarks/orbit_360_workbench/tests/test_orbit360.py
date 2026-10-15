from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from orbit360.contracts import OrbitError, add_hash, read_json, write_json
from orbit360.planner import build_plan, downstream_closure, validate_plan
from orbit360.repair import repair_unit
from orbit360.runner import run_workspace, workspace_status
from orbit360.workspace import load_workspace, materialize


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


class Orbit360Tests(unittest.TestCase):
    def test_default_plan_matches_acfv_reference_scale(self) -> None:
        plan = build_plan()
        validate_plan(plan)
        self.assertEqual(plan["unit_count"], 360)
        self.assertEqual(plan["width"], 35)
        self.assertEqual(plan["layer_count"], 11)
        self.assertEqual(plan["units"][35]["dependencies"], ["unit_000"])
        self.assertEqual(plan["units"][359]["dependencies"], ["unit_324"])

    def test_downstream_closure_is_exact(self) -> None:
        plan = build_plan()
        self.assertEqual(
            downstream_closure(plan, {"unit_008"}),
            ["unit_008", "unit_043", "unit_078", "unit_113", "unit_148", "unit_183", "unit_218", "unit_253", "unit_288", "unit_323", "unit_358"],
        )

    def test_materialize_run_resume_and_repair_360_units(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = pathlib.Path(temporary) / "workspace"
            materialized = materialize(build_plan(), workspace)
            self.assertEqual(materialized["unit_count"], 360)
            self.assertEqual(len(list((workspace / "units").glob("*.json"))), 360)
            self.assertEqual(len(list((workspace / "receipts").glob("*.json"))), 360)

            started = time.perf_counter()
            first = run_workspace(workspace, workers=8)
            elapsed = time.perf_counter() - started
            self.assertEqual(first["executed_count"], 360)
            self.assertEqual(first["reused_count"], 0)
            self.assertLess(elapsed, 30)

            second = run_workspace(workspace, workers=8)
            self.assertEqual(second["executed_count"], 0)
            self.assertEqual(second["reused_count"], 360)

            repair = repair_unit(workspace, "unit_008", 1)
            self.assertEqual(repair["affected_count"], 11)
            self.assertEqual(repair["invalidated_checkpoint_count"], 11)
            third = run_workspace(workspace, workers=8)
            self.assertEqual(third["executed_count"], 11)
            self.assertEqual(third["reused_count"], 349)
            self.assertNotEqual(first["results_sha256"], third["results_sha256"])
            self.assertEqual(third["formal_evidence_status"], "NOT_EVALUATED")

    def test_tampered_descriptor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = pathlib.Path(temporary) / "workspace"
            materialize(build_plan(12, 4), workspace)
            path = workspace / "units" / "unit_003.json"
            descriptor = read_json(path)
            descriptor["weight"] += 1
            write_json(path, descriptor)
            with self.assertRaisesRegex(OrbitError, "hash mismatch"):
                load_workspace(workspace)

    def test_tampered_boundary_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = pathlib.Path(temporary) / "workspace"
            materialize(build_plan(12, 4), workspace)
            path = workspace / "receipts" / "unit_003.json"
            receipt = read_json(path)
            receipt["validation"] = "unchecked"
            write_json(path, receipt)
            with self.assertRaisesRegex(OrbitError, "Boundary receipt is invalid"):
                load_workspace(workspace)

    def test_semantically_tampered_checkpoint_result_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = pathlib.Path(temporary) / "workspace"
            materialize(build_plan(12, 4), workspace)
            run_workspace(workspace)
            checkpoint_path = workspace / "checkpoint.json"
            checkpoint = read_json(checkpoint_path)
            corrupted = dict(checkpoint["results"]["unit_000"])
            corrupted.pop("result_sha256")
            corrupted["value"] += 1
            checkpoint["results"]["unit_000"] = add_hash(corrupted, "result_sha256")
            write_json(checkpoint_path, checkpoint)

            repaired = run_workspace(workspace)

            self.assertEqual(repaired["executed_units"], ["unit_000"])
            self.assertEqual(repaired["reused_count"], 11)

    def test_status_counts_valid_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = pathlib.Path(temporary) / "workspace"
            materialize(build_plan(40, 8), workspace)
            run_workspace(workspace, workers=4)
            status = workspace_status(workspace)
            self.assertEqual(status["valid_checkpoint_results"], 40)
            self.assertEqual(status["formal_evidence_status"], "NOT_EVALUATED")

    def test_cli_plan_run_repair_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = pathlib.Path(temporary) / "cli-workspace"

            def call(*arguments: str) -> dict:
                completed = subprocess.run(
                    [sys.executable, "-m", "orbit360", *arguments],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                return json.loads(completed.stdout)

            self.assertEqual(call("plan", "--workspace", str(workspace), "--units", "40", "--width", "8")["unit_count"], 40)
            self.assertEqual(call("run", "--workspace", str(workspace), "--workers", "4")["executed_count"], 40)
            self.assertEqual(call("repair", "--workspace", str(workspace), "--target", "unit_000")["affected_count"], 5)
            self.assertEqual(call("run", "--workspace", str(workspace), "--workers", "4")["executed_count"], 5)
            self.assertEqual(call("status", "--workspace", str(workspace))["valid_checkpoint_results"], 40)


if __name__ == "__main__":
    unittest.main()
