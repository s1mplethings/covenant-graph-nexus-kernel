from __future__ import annotations

import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_contracts import write_json
from scripts.run_real_provider_frontend_branch_phase import create_frontend_trace_bundle


def test_frontend_trace_bundle_contains_required_evidence(tmp_path: pathlib.Path) -> None:
    write_json(tmp_path / "registry.json", {"agents": []})
    write_json(tmp_path / "merge_results" / "frontend_branch_agent.json", {"merge_verdict": "PASS"})
    write_json(tmp_path / "frontend_branch_static_validation.json", {"exit_code": 0})
    write_json(tmp_path / "checkpoints" / "dashboard_page_leaf.json", {"verdict": "PASS"})
    write_json(tmp_path / "leaves" / "dashboard_page_leaf" / "provider_output_files.json", {"files": []})
    final = {"verdict": "PASS", "classification": "frontend_branch_all_real_provider_pass"}
    write_json(tmp_path / "final_verdict.json", final)

    bundle = create_frontend_trace_bundle(out_dir=tmp_path, final_verdict=final)

    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
    assert "00_INDEX.md" in names
    assert "registry.json" in names
    assert "merge_results/frontend_branch_agent.json" in names
    assert "frontend_branch_static_validation.json" in names
    assert "checkpoints/dashboard_page_leaf.json" in names
    assert "leaves/dashboard_page_leaf/provider_output_files.json" in names
