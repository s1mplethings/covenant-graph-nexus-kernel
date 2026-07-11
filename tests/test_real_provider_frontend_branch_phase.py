from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_real_provider_frontend_branch_phase import FRONTEND_LEAF_ORDER, controlled_frontend_output, run_frontend_branch_phase


def test_frontend_branch_all_real_provider_leaves_merge_with_static_validation(tmp_path: pathlib.Path) -> None:
    overrides = {leaf: controlled_frontend_output(leaf) for leaf in FRONTEND_LEAF_ORDER}

    result = run_frontend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
        provider_output_overrides=overrides,
    )

    assert result["classification"] == "frontend_branch_all_real_provider_pass"
    assert result["verdict"] == "PASS"
    merge = json.loads((tmp_path / "merge_results" / "frontend_branch_agent.json").read_text(encoding="utf-8"))
    assert merge["merge_verdict"] == "PASS"
    static = json.loads((tmp_path / "frontend_branch_static_validation.json").read_text(encoding="utf-8"))
    assert static["exit_code"] == 0
    for leaf in FRONTEND_LEAF_ORDER:
        checkpoint = json.loads((tmp_path / "checkpoints" / f"{leaf}.json").read_text(encoding="utf-8"))
        assert checkpoint["provider_mode"] == "real_provider"
        assert checkpoint["verdict"] == "PASS"
        assert checkpoint["blocked_files"] == []


def test_frontend_branch_blocks_when_provider_unavailable(tmp_path: pathlib.Path) -> None:
    result = run_frontend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": False},
    )

    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"
    assert not (tmp_path / "project" / "app" / "templates").exists()
