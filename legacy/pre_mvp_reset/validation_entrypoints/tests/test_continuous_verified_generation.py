from __future__ import annotations

import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import continuous_generation_ledger


def test_iteration_ledger_record_contains_required_fields(tmp_path: pathlib.Path) -> None:
    ledger = tmp_path / "iterations.jsonl"
    record = continuous_generation_ledger.append_iteration(
        {
            "selected_gap": "cgkn_naming_consistency_guard",
            "layer": "naming_consistency",
            "reason_for_priority": "naming guard is required",
            "micro_plan": ["inspect", "verify"],
            "acceptance_criteria": ["ledger is written"],
            "commands_run": ["python scripts/check_cgkn_naming_consistency.py"],
            "test_results": [{"status": "PASS"}],
            "benchmark_results": [],
            "known_gaps_after_iteration": ["implementation_status:FAIL"],
            "next_recommended_action": "continue contract checks",
            "status": "PASS",
        },
        ledger,
    )
    loaded = continuous_generation_ledger.load_iterations(ledger)
    assert loaded == [record]
    for key in (
        "selected_gap",
        "reason_for_priority",
        "micro_plan",
        "acceptance_criteria",
        "commands_run",
        "test_results",
        "benchmark_results",
        "known_gaps_after_iteration",
        "next_recommended_action",
    ):
        assert key in record


def test_continuous_runner_writes_iteration_ledger() -> None:
    before = continuous_generation_ledger.load_iterations()
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/run_continuous_verified_generation.py",
            "--max-iterations",
            "1",
            "--focus",
            "naming",
            "--benchmark",
            "requirement_decision",
            "--no-provider",
            "--write-plan-only",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0
    after = continuous_generation_ledger.load_iterations()
    assert len(after) >= len(before) + 1
    latest = after[-1]
    assert latest["selected_gap"]
    assert latest["acceptance_criteria"]
    assert latest["next_recommended_action"]
