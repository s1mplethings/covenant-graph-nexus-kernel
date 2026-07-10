from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_real_provider_frontend_branch_phase import FRONTEND_LEAF_ORDER, controlled_frontend_output, run_frontend_branch_phase


def test_frontend_real_provider_scope_violation_blocks_cross_leaf_template(tmp_path: pathlib.Path) -> None:
    overrides = {leaf: controlled_frontend_output(leaf) for leaf in FRONTEND_LEAF_ORDER}
    overrides["dashboard_page_leaf"] = json.dumps({"files": [{"path": "app/templates/search.html", "content": "<html>forbidden cross leaf</html>"}]})

    result = run_frontend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
        provider_output_overrides=overrides,
    )

    assert result["classification"] == "frontend_merge_failed"
    checkpoint = json.loads((tmp_path / "checkpoints" / "dashboard_page_leaf.json").read_text(encoding="utf-8"))
    assert checkpoint["verdict"] == "FAIL"
    assert "app/templates/search.html" in checkpoint["blocked_files"]
    search_html = tmp_path / "project" / "app" / "templates" / "search.html"
    assert search_html.exists()
    assert not search_html.read_text(encoding="utf-8").startswith("forbidden")
