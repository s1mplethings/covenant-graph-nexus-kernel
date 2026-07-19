from __future__ import annotations

import json
import pathlib

import pytest

from scripts import final_internal_acceptance


@pytest.mark.e2e
def test_internal_acceptance_executes_real_internal_gates(tmp_path: pathlib.Path) -> None:
    result = final_internal_acceptance.build_internal_acceptance(tmp_path / "acceptance-run")

    assert result["status"] == "PASS"
    for name in (
        "internal_leaf_sessions.json",
        "internal_workspace_inventory.json",
        "internal_collaboration_evidence.json",
        "internal_replan_evidence.json",
        "internal_recovery_evidence.json",
        "internal_startup_profile.json",
    ):
        document = json.loads((tmp_path / "acceptance-run" / name).read_text(encoding="utf-8"))
        assert document["status"] == "PASS", name
    deterministic = json.loads(
        (tmp_path / "acceptance-run" / "internal_deterministic_e2e.json").read_text(encoding="utf-8")
    )
    assert deterministic["status"] == "BLOCKED"
    assert deterministic["blocker_code"] == "BLOCKED_TELEGRAM_TEST_CHAT"

