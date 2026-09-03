from __future__ import annotations

import pathlib

import pytest

from scripts.full_dynamic_project_resume_runner import run_resume


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / "generated" / "full_dynamic_real_project_eval"
pytestmark = pytest.mark.e2e


def test_full_resume_runner_preserves_blocked_semantics(tmp_path: pathlib.Path) -> None:
    report = run_resume(
        previous=PREVIOUS,
        out_dir=tmp_path / "full_dynamic_real_project_resume_eval" / "run_001",
        readiness_override={"provider_ready": False},
        capture_visual=False,
    )
    final = report["final"]

    assert final["classification"] == "provider_unavailable_during_resume"
    assert final["classification_code"] == "B"
    assert final["verdict"] == "BLOCKED"
    assert final["not_proven"] is True
    assert final["control_path"] == "proven"
    assert final["full_real_project"] == "not_proven"
    assert final["reused_leaf_count"] == 9
    assert final["integration"] == "SKIPPED"
    assert final["visual_evidence"] == "SKIPPED"
    assert final["bundle_integrity"] == "SKIPPED"
    assert final["public_delivery_gate"] == "SKIPPED"
    assert final["fake_success_detected"] is False
    assert final["bundle_generated"] is False
    assert final["screenshots_generated"] is False
    assert final["sent_records"] == []
