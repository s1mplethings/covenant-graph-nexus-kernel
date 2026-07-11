from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_long_run_evaluator import phase2_real_leaf, phase3_mixed_branch
from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
from scripts.agent_scope_contract import create_scope_contract, save_scope_contract


def test_provider_unavailable_is_blocked_not_pass_or_fail(tmp_path: pathlib.Path) -> None:
    phase2 = phase2_real_leaf(tmp_path, {"provider_ready": False})
    phase3 = phase3_mixed_branch(tmp_path, phase2, {"provider_ready": False})

    assert phase2["classification"] == "provider_unavailable"
    assert phase2["verdict"] == "BLOCKED"
    assert phase3["classification"] == "provider_unavailable"
    assert phase3["verdict"] == "BLOCKED"
    assert phase3["backend_merge"] == "not_run"


def test_real_provider_leaf_builder_unavailable_does_not_write_fake_leaf_files(tmp_path: pathlib.Path) -> None:
    contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="SearchServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )
    save_scope_contract(contract, tmp_path)

    result = run_real_provider_leaf(
        agent_id="search_service_leaf",
        out_dir=tmp_path,
        project_dir=tmp_path / "project",
        user_goal="Local AI Knowledge Studio",
        readiness={"provider_ready": False},
    )

    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"
    assert not (tmp_path / "project" / "app" / "services" / "search_service.py").exists()
    assert not (tmp_path / "provider_output_raw_redacted.txt").exists()
