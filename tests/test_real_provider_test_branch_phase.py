from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_full_dynamic_real_project_eval import controlled_full_project_outputs, run_full_dynamic_real_project_eval


def test_test_branch_real_provider_leaves_defer_pytest_until_integration(tmp_path: pathlib.Path) -> None:
    result = run_full_dynamic_real_project_eval(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
        provider_output_overrides=controlled_full_project_outputs(),
        capture_visual=False,
    )

    assert result["classification"] == "visual_evidence_failed"
    for leaf in ("smoke_test_leaf", "backend_tests_leaf", "ui_route_tests_leaf"):
        leaf_result = json.loads((tmp_path / "leaves" / leaf / "test_execution_result.json").read_text(encoding="utf-8"))
        assert leaf_result["deferred"] is True
        checkpoint = json.loads((tmp_path / "checkpoints" / f"{leaf}.json").read_text(encoding="utf-8"))
        assert checkpoint["verdict"] == "PASS"
    full = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    assert full["verdict"] == "PASS"
