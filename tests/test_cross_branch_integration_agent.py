from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_full_dynamic_real_project_eval import controlled_full_project_outputs, run_full_dynamic_real_project_eval


def test_integration_agent_waits_for_all_branch_merges(tmp_path: pathlib.Path) -> None:
    outputs = controlled_full_project_outputs()
    outputs["dashboard_page_leaf"] = json.dumps({"files": [{"path": "app/services/search_service.py", "content": "bad"}]})

    result = run_full_dynamic_real_project_eval(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
        provider_output_overrides=outputs,
        capture_visual=False,
    )

    assert result["classification"] == "frontend_branch_failed"
    integration = json.loads((tmp_path / "merge_results" / "integration_agent.json").read_text(encoding="utf-8"))
    assert integration["verdict"] == "SKIPPED"
    assert not (tmp_path / "generated_project" / "app" / "main.py").exists()


def test_integration_agent_writes_only_integration_scope(tmp_path: pathlib.Path) -> None:
    result = run_full_dynamic_real_project_eval(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
        provider_output_overrides=controlled_full_project_outputs(),
        capture_visual=False,
    )

    assert result["integration"] == "PASS"
    integration = json.loads((tmp_path / "merge_results" / "integration_agent.json").read_text(encoding="utf-8"))
    assert "app/main.py" in integration["written_files"]
    assert "final_project_bundle.zip" not in integration["written_files"]
