from __future__ import annotations

import json
import unittest

from cgnk_modules.benchmark_summary import summarize_benchmark_report
from cgnk_modules.convergence_guard import evaluate_convergence
from cgnk_modules.diagnostics_summary import summarize_diagnostics
from cgnk_modules.provider_call_guard import evaluate_provider_call_request
from cgnk_modules.requirements_extract_contract_only import extract_requirements_contract_only
from cgnk_modules.timeout_guard import evaluate_timeout_budget


class MiddleCapabilityModulesTest(unittest.TestCase):
    def test_requirements_extraction_is_deterministic_and_provider_free(self) -> None:
        first = extract_requirements_contract_only("Add docs and avoid provider calls", context={"constraints": ["no workspace writes"]})
        second = extract_requirements_contract_only("Add docs and avoid provider calls", context={"constraints": ["no workspace writes"]})
        self.assertEqual(first, second)
        self.assertTrue(first["ok"], first["diagnostics"])
        self.assertIn("provider_call", {row["reason"] for row in first["requirements"]["unsupported_items"]})
        json.dumps(first, sort_keys=True)

    def test_diagnostics_summary_counts_stable_fields(self) -> None:
        result = summarize_diagnostics(
            [
                {"code": "A", "severity": "error", "path": "$.a", "message": "a", "involved_ref": "module.x@1"},
                {"code": "A", "severity": "warning", "path": "$.b", "message": "b", "repair_hints": [{"action": "fix"}]},
            ]
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(2, result["total"])
        self.assertEqual({"error": 1, "warning": 1}, result["by_severity"])
        self.assertEqual({"A": 2}, result["by_code"])

    def test_benchmark_summary_parses_existing_report_only(self) -> None:
        result = summarize_benchmark_report({"kind": "BenchmarkReport", "ok": True, "metrics": {"score": 0.9}, "warnings": ["slow"]})
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(0.9, result["metrics"]["metrics.score"])
        self.assertEqual(["slow"], result["warnings"])

    def test_convergence_guard_detects_stall_without_execution(self) -> None:
        result = evaluate_convergence([{"ok": False, "hash": "same"}, {"ok": False, "hash": "same"}], {"repeat_hash_limit": 2})
        self.assertTrue(result["stalled"])
        self.assertIn("same", result["repeated_hashes"])

    def test_timeout_guard_reports_budget_exceeded(self) -> None:
        result = evaluate_timeout_budget({"total_seconds": 12}, {"max_total_seconds": 10})
        self.assertFalse(result["ok"])
        self.assertTrue(result["exceeded"])

    def test_provider_guard_denies_by_policy_and_never_calls_provider(self) -> None:
        result = evaluate_provider_call_request({"provider": "example", "max_tokens": 10}, policy={"allow_provider_call": False}, budget={"max_tokens": 100})
        self.assertFalse(result["allowed"])
        self.assertEqual(["policy_denies_provider_call"], result["denied_reasons"])


if __name__ == "__main__":
    unittest.main()
