from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_leaf_scope_enforcer import enforce_leaf_scope
from scripts.agent_scope_contract import create_scope_contract


def test_leaf_scope_enforcer_writes_allowed_and_blocks_forbidden(tmp_path: pathlib.Path) -> None:
    contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="SearchServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )
    result = enforce_leaf_scope(
        contract=contract,
        candidate_files={
            "app/services/search_service.py": "def search_documents(): return []\n",
            "README.md": "# forbidden\n",
        },
        project_dir=tmp_path / "project",
        out_dir=tmp_path,
    )

    assert result["ok"] is False
    assert "README.md" in result["blocked_files"]
    assert (tmp_path / "project" / "app" / "services" / "search_service.py").exists()
    assert not (tmp_path / "project" / "README.md").exists()
