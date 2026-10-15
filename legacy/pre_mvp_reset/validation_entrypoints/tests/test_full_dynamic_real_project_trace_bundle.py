from __future__ import annotations

import json
import pathlib
import sys
import zipfile

import pytest

pytestmark = pytest.mark.e2e

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_full_dynamic_real_project_eval import create_trace_bundle


def test_full_dynamic_trace_bundle_contains_required_sections(tmp_path: pathlib.Path) -> None:
    run = tmp_path / "run_001"
    for rel in (
        "provider_readiness.json",
        "shared_context.json",
        "goal_alignment.json",
        "agent_tree_registry.json",
        "spawn_actions.jsonl",
        "scope_contracts/example.json",
        "leaves/example/provider_prompt.md",
        "checkpoints/example.json",
        "merge_results/backend_branch_agent.json",
        "integration/integration_checkpoint.json",
        "test_execution.json",
        "generated_project/TEST_REPORT.md",
        "visual_evidence.json",
        "screenshots/dashboard.png",
        "bundle_integrity_check.json",
        "public_delivery_gate.json",
        "final_verdict.json",
    ):
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "x", encoding="utf-8")
    failure = tmp_path / "failure_injection"
    failure.mkdir()
    (failure / "failure_injection_summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    bundle = create_trace_bundle(tmp_path, run)

    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
    assert "00_INDEX.md" in names
    assert "provider_readiness.json" in names
    assert "scope_contracts/example.json" in names
    assert "generated_project/TEST_REPORT.md" in names
    assert "failure_injection/failure_injection_summary.json" in names
