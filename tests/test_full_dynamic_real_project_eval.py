from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.e2e

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import runtime_visual_evidence
from scripts.run_full_dynamic_real_project_eval import controlled_full_project_outputs, run_full_dynamic_real_project_eval


def _fake_visual(out: pathlib.Path) -> dict:
    screenshots = []
    for page in ("dashboard", "documents", "search", "settings"):
        run_path = out / "screenshots" / f"{page}.png"
        project_path = out / "generated_project" / "screenshots" / f"{page}.png"
        runtime_visual_evidence.write_runtime_preview_png(run_path, title=page)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_path.write_bytes(run_path.read_bytes())
        screenshots.append(f"screenshots/{page}.png")
    result = {"verdict": "FAIL", "screenshots": [], "placeholder_screenshots": screenshots, "source": "unit_test_runtime_visual_stub", "reason": "synthetic visual fixture is not formal screenshot evidence"}
    (out / "visual_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "generated_project" / "visual_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def test_full_dynamic_real_project_control_path_blocks_synthetic_visual_fixture(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr("scripts.run_full_dynamic_real_project_eval.capture_runtime_visual_evidence", _fake_visual)

    result = run_full_dynamic_real_project_eval(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True, "smoke_status": "pass"},
        provider_output_overrides=controlled_full_project_outputs(),
    )

    assert result["classification"] == "visual_evidence_failed"
    assert result["verdict"] == "NEEDS_REWORK"
    assert result["provider_output_overrides_used"] is True
    assert result["telegram_mainline"] == "telegram_mainline_not_connected"
    assert (tmp_path / "final_project_bundle.zip").exists()
    assert (tmp_path / "public_delivery_gate.json").exists()
    registry = json.loads((tmp_path / "agent_tree_registry.json").read_text(encoding="utf-8"))
    assert registry["agents"][0]["agent_id"] == "main_agent"
    assert {agent["agent_id"] for agent in registry["agents"]} >= {
        "backend_branch_agent",
        "frontend_branch_agent",
        "test_branch_agent",
        "integration_agent",
        "qa_agent",
        "delivery_agent",
    }


def test_full_dynamic_real_project_blocks_when_provider_unavailable(tmp_path: pathlib.Path) -> None:
    result = run_full_dynamic_real_project_eval(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": False, "smoke_status": "fail", "public_safe_error": "quota"},
    )

    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"
    assert not (tmp_path / "final_project_bundle.zip").exists()
    assert not (tmp_path / "screenshots").exists()
