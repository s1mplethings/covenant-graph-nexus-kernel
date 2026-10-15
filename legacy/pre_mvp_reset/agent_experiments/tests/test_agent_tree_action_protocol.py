from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_tree_action_protocol import AgentActionRecorder, validate_action_log, validate_agent_action
from scripts.agent_tree_contracts import read_jsonl


def test_agent_action_protocol_requires_structured_actions(tmp_path: pathlib.Path) -> None:
    recorder = AgentActionRecorder(tmp_path)
    action = recorder.record(
        agent_id="backend_leaf",
        agent_role="LeafBuilder",
        stage="backend_services",
        action="create_files",
        target_files=["app/services/document_service.py"],
        reason="Required by backend_services stage in build DAG",
        input_context_id="backend_leaf_context_v1",
        expected_verification=["service_files_exist", "python_import_smoke"],
        claimed_complete=True,
    )

    assert not validate_agent_action(action)
    validation = validate_action_log(tmp_path / "agent_actions.jsonl")
    assert validation["verdict"] == "PASS"
    written = read_jsonl(tmp_path / "agent_actions.jsonl")[0]
    assert written["action_id"]
    assert written["agent_id"] == "backend_leaf"
    assert written["stage"] == "backend_services"
    assert written["target_files"]
    assert written["expected_verification"]
    assert "delivery_pass" not in written
