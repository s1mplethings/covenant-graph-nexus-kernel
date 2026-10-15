from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.e2e

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_full_dynamic_real_project_eval import controlled_full_project_outputs, run_failure_injections


def test_full_dynamic_failure_injections_block_scope_violations(tmp_path: pathlib.Path) -> None:
    summary = run_failure_injections(tmp_path)

    assert summary["case_frontend_leaf_writes_backend"]["verdict"] == "PASS"
    assert summary["case_test_leaf_writes_delivery_artifact"]["verdict"] == "PASS"

    dashboard = json.loads((tmp_path / "failure_injection" / "case_frontend_leaf_writes_backend" / "checkpoints" / "dashboard_page_leaf.json").read_text(encoding="utf-8"))
    assert dashboard["verdict"] == "FAIL"
    assert "app/services/search_service.py" in dashboard["blocked_files"]
    assert not (tmp_path / "failure_injection" / "case_frontend_leaf_writes_backend" / "merge_results" / "integration_agent.json").read_text(encoding="utf-8").count('"verdict": "PASS"')

    smoke = json.loads((tmp_path / "failure_injection" / "case_test_leaf_writes_delivery_artifact" / "checkpoints" / "smoke_test_leaf.json").read_text(encoding="utf-8"))
    assert smoke["verdict"] == "FAIL"
    assert "final_project_bundle.zip" in smoke["blocked_files"]
    assert not (tmp_path / "failure_injection" / "case_test_leaf_writes_delivery_artifact" / "final_project_bundle.zip").exists()


def test_failure_overrides_remain_leaf_scoped(tmp_path: pathlib.Path) -> None:
    outputs = controlled_full_project_outputs()
    outputs["smoke_test_leaf"] = json.dumps({"files": [{"path": "../escape.py", "content": "bad"}]})
    from scripts.run_full_dynamic_real_project_eval import run_full_dynamic_real_project_eval

    result = run_full_dynamic_real_project_eval(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
        provider_output_overrides=outputs,
        capture_visual=False,
    )

    assert result["classification"] == "test_branch_failed"
    assert not (tmp_path.parent / "escape.py").exists()
