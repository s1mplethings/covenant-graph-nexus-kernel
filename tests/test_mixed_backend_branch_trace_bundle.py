from __future__ import annotations

import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_contracts import write_json
from scripts.run_mixed_backend_branch_phase import create_mixed_backend_trace_bundle


def test_mixed_backend_trace_bundle_contains_required_evidence(tmp_path: pathlib.Path) -> None:
    write_json(tmp_path / "provider_readiness.json", {"provider_ready": True})
    phase = tmp_path / "phase1_search_real"
    write_json(phase / "registry.json", {"agents": []})
    (phase / "spawn_actions.jsonl").write_text("{}", encoding="utf-8")
    write_json(phase / "scope_contracts" / "search_service_leaf.json", {"allowed_files": []})
    write_json(phase / "leaves" / "search_service_leaf" / "provider_output_files.json", {"files": []})
    write_json(phase / "checkpoints" / "search_service_leaf.json", {"blocked_files": [], "verdict": "PASS"})
    write_json(phase / "merge_results" / "backend_branch_agent.json", {"merge_verdict": "PASS"})
    write_json(phase / "backend_branch_test_execution.json", {"exit_code": 0})
    write_json(tmp_path / "failure_injection_scope_violation" / "final_verdict.json", {"verdict": "PASS"})
    final = {"verdict": "PASS", "classification": "mixed_backend_search_real_pass"}
    write_json(tmp_path / "final_verdict.json", final)

    bundle = create_mixed_backend_trace_bundle(out_dir=tmp_path, final_verdict=final)

    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
    assert "00_INDEX.md" in names
    assert "provider_readiness.json" in names
    assert "phase1_search_real/registry.json" in names
    assert "phase1_search_real/checkpoints/search_service_leaf.json" in names
    assert "phase1_search_real/merge_results/backend_branch_agent.json" in names
    assert "phase1_search_real/backend_branch_test_execution.json" in names
    assert "failure_injection_scope_violation/final_verdict.json" in names
    assert "final_verdict.json" in names
