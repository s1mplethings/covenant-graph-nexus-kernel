from __future__ import annotations

import json
import pathlib

import pytest

from cgkn.application.software_project.contracts import ProjectResultStatus
from cgkn.application.software_project.service import SoftwareProjectGenerationService
from cgkn.providers import ProviderCompletion


ROOT = pathlib.Path(__file__).resolve().parents[3]


class FakeClient:
    def __init__(self): self.agent_calls = 0; self.worker_calls = 0
    def complete(self, *, system, user, schema_name, schema, config):
        if config.role == "worker":
            self.worker_calls += 1
            value = {"schema_version": "1.0", "node_id": "patch", "summary": "repair add", "actions": [{"action": "patch_file", "path": "math_utils.py", "find": "return a - b", "replace": "return a + b"}], "expected_outputs": ["pytest passes"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
            return ProviderCompletion(json.dumps(value), config.model, f"worker-{self.worker_calls}", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20})
        self.agent_calls += 1
        if self.agent_calls == 1:
            def add(node, capability, config_value, deps=()):
                return {"edit_id": f"e-{node}", "operation": "add_node", "node_id": node, "payload": {"parent_id": "", "capability_ref": capability, "depends_on": list(deps), "config": config_value}, "provenance": {"provider": "fake"}}
            edits = [
                add("inspect", "workspace.inspect@1", {"executor_ref": "local.file@1", "action": "list_files", "path": ".", "goal": "inspect"}),
                add("patch", "project.file.patch@1", {"executor_ref": "llm.cheap@1", "goal": "repair add", "target_paths": ["math_utils.py"], "allowed_paths": ["math_utils.py"], "file_purpose": "arithmetic", "interfaces": {}, "acceptance": ["pytest passes"], "allowed_effects": ["filesystem.write"], "max_actions": 2, "max_write_files": 1, "max_total_output_bytes": 1000, "allow_create": False, "allow_patch": True, "allow_delete": False, "protected_paths": [".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"]}, ("inspect",)),
                add("pytest", "project.python.pytest@1", {"executor_ref": "local.python-test@1", "pytest_args": ["-q"], "goal": "test"}, ("patch",)),
                add("snapshot", "project.snapshot@1", {"executor_ref": "project.snapshot@1", "entrypoints": ["math_utils.py"], "test_commands": ["python -m pytest -q"], "runtime_commands": ["python -m pytest -q"], "goal": "snapshot"}, ("pytest",)),
                add("accept", "project.acceptance.external@1", {"executor_ref": "project.acceptance@1", "case_id": "seeded_repair", "goal": "accept"}, ("snapshot",)),
            ]
            value = {"schema_version": "1.0", "decision_id": "d1", "summary": "compose repair", "reason": "bounded repair", "edits": edits, "request_run": True, "finish": False, "needs_escalation": False, "escalation_reason": ""}
        else:
            value = {"schema_version": "1.0", "decision_id": "d2", "summary": "finish", "reason": "acceptance passed", "edits": [], "request_run": False, "finish": True, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(value), config.model, f"agent-{self.agent_calls}", {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20})


@pytest.mark.happy_path
@pytest.mark.local_functional
@pytest.mark.generation
def test_fake_provider_repair_uses_tree_dag_scoped_worker_real_pytest_and_hidden_acceptance(tmp_path):
    client = FakeClient()
    result = SoftwareProjectGenerationService(ROOT, tmp_path / "artifacts", client=client).run_case("seeded_repair", max_repair_rounds=0)
    assert result.status is ProjectResultStatus.PASS
    assert result.receipt["initial_test"]["returncode"] != 0
    assert result.receipt["internal_test_result"] == "PASS"
    assert result.receipt["hidden_acceptance_result"] == "PASS"
    assert result.receipt["functional_success"] is True
    assert result.receipt["agent_input_tokens"] == 20
    assert result.receipt["worker_output_tokens"] == 10
    assert (result.run_dir / "provider_usage.json").is_file()
    assert result.receipt["manual_intervention"] == 0
    assert client.agent_calls == 2 and client.worker_calls == 1
