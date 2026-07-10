from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_scope_contract import check_scope_write, create_scope_contract, validate_scope_contract


def test_scope_contract_blocks_leaf_delivery_claims_and_unowned_writes() -> None:
    contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="SearchServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )

    assert not validate_scope_contract(contract)
    assert "claim_delivery_pass" in contract["forbidden_actions"]
    assert "modify_unowned_file" in contract["forbidden_actions"]
    assert check_scope_write(contract, ["app/services/search_service.py"])["ok"] is True
    violation = check_scope_write(contract, ["README.md"])
    assert violation["ok"] is False
    assert "README.md" in violation["violations"]
