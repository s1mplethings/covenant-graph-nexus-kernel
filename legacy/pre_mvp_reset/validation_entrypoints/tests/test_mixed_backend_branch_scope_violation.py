from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_mixed_backend_branch_phase import run_scope_violation_injection


def test_scope_violation_injection_blocks_forbidden_real_provider_file(tmp_path: pathlib.Path) -> None:
    result = run_scope_violation_injection(out_dir=tmp_path, project_name="Local AI Knowledge Studio")

    assert result["classification"] == "real_leaf_scope_violation_blocked"
    assert result["verdict"] == "PASS"
    assert result["forbidden_file_written"] is False
    assert not (tmp_path / "project" / "README.md").exists()
    checkpoint = json.loads((tmp_path / "checkpoints" / "search_service_leaf.json").read_text(encoding="utf-8"))
    assert checkpoint["verdict"] == "FAIL"
    assert "README.md" in checkpoint["blocked_files"]
    merge = json.loads((tmp_path / "merge_results" / "backend_branch_agent.json").read_text(encoding="utf-8"))
    assert merge["merge_verdict"] == "FAIL"
