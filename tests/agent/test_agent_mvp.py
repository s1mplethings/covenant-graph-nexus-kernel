from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from cgkn.agent import AgentComposer, AgentProjectLoop
from cgkn.executors import ExecutorRegistry, FileExecutor, LLMExecutor, PythonTestExecutor
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "agent_mvp_bugfix"


class FakeClient:
    def __init__(self, *, agent: list[dict[str, Any]], worker: list[dict[str, Any]]):
        self.responses = {"agent": list(agent), "worker": list(worker)}

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        del system, user, schema_name, schema
        return ProviderCompletion(json.dumps(self.responses[config.role].pop(0)), f"fake-{config.role}", f"req-{config.role}", {"total_tokens": 1})


def edit(edit_id: str, operation: str, node_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(payload or {})
    if operation == "add_node":
        value.setdefault("parent_id", "")
        value.setdefault("depends_on", [])
    return {"edit_id": edit_id, "operation": operation, "node_id": node_id, "payload": value, "provenance": {"source": "fake-agent"}}


def decision(number: int, edits: list[dict[str, Any]] = [], *, run: bool = False, finish: bool = False) -> dict[str, Any]:
    return {"schema_version": "1.0", "decision_id": f"decision-{number}", "summary": "bounded decision", "reason": "observable result", "edits": edits, "request_run": run, "finish": finish, "needs_escalation": False, "escalation_reason": ""}


def initial_decision() -> dict[str, Any]:
    return decision(1, [
        edit("e1", "add_node", "inspect", {"capability_ref": "repo.inspect@1", "config": {"executor_ref": "local.file@1", "action": "read_file", "path": "math_utils.py"}}),
        edit("e2", "add_node", "fix", {"capability_ref": "code.modify@1", "depends_on": ["inspect"], "config": {"executor_ref": "llm.cheap@1", "goal": "Correct add so it returns the sum", "acceptance": ["pytest passes"]}}),
        edit("e3", "add_node", "test", {"capability_ref": "test.python@1", "depends_on": ["fix"], "config": {"executor_ref": "local.python-test@1", "pytest_args": ["-q"]}}),
    ], run=True)


def worker_patch(find: str = "return a - b", replace: str = "return a + b") -> dict[str, Any]:
    return {"schema_version": "1.0", "node_id": "fix", "summary": "repair add", "actions": [{"action": "patch_file", "path": "math_utils.py", "find": find, "replace": replace}], "expected_outputs": ["math_utils.py updated"], "confidence": 0.95, "needs_escalation": False, "escalation_reason": ""}


def worker_escalation() -> dict[str, Any]:
    return {"schema_version": "1.0", "node_id": "fix", "summary": "need bounded clarification", "actions": [], "expected_outputs": [], "confidence": 0.2, "needs_escalation": True, "escalation_reason": "dependency context is ambiguous"}


def build_loop(project: Path, runs: Path, client: FakeClient) -> AgentProjectLoop:
    registry = ExecutorRegistry()
    registry.register(FileExecutor(project))
    registry.register(LLMExecutor(project, client, ModelRoleConfig("worker", "fake-cheap")))
    registry.register(PythonTestExecutor(project))
    store = FileRunStore(runs)
    return AgentProjectLoop(AgentComposer(client, ModelRoleConfig("agent", "fake-high")), DAGRunner(registry, store), store, known_capabilities={"repo.inspect@1", "code.modify@1", "test.python@1"}, worker_model="fake-cheap")


def copy_fixture(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project)
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    failed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=project, capture_output=True, text=True, env=environment)
    assert failed.returncode != 0
    return project


def test_fake_provider_vertical_slice_edits_file_and_passes_real_pytest(tmp_path: Path) -> None:
    project = copy_fixture(tmp_path)
    client = FakeClient(agent=[initial_decision(), decision(2, finish=True)], worker=[worker_patch()])
    result = build_loop(project, tmp_path / "runs", client).run(project_id="demo", run_id="success", goal="repair the broken add function")
    assert result.status == "SUCCEEDED" and result.agent_calls == 2 and result.worker_calls == 1
    assert "return a + b" in (project / "math_utils.py").read_text(encoding="utf-8")


def test_failed_test_triggers_affected_only_retry(tmp_path: Path) -> None:
    project = copy_fixture(tmp_path)
    repair = decision(2, [edit("e4", "update_config", "fix", {"config": {"goal": "Repair the failed arithmetic test"}}), edit("e5", "retry_node", "fix")], run=True)
    client = FakeClient(agent=[initial_decision(), repair, decision(3, finish=True)], worker=[worker_patch(replace="return a * b"), worker_patch(find="return a * b")])
    result = build_loop(project, tmp_path / "runs", client).run(project_id="demo", run_id="repair", goal="repair the broken add function")
    assert result.status == "SUCCEEDED" and result.worker_calls == 2
    assert result.run_summary and "inspect" in result.run_summary.reused_nodes and result.run_summary.retry_attempts == 2


def test_worker_escalation_returns_to_agent_then_recovers(tmp_path: Path) -> None:
    project = copy_fixture(tmp_path)
    retry = decision(2, [edit("e4", "update_config", "fix", {"config": {"goal": "Use inspect output to fix addition"}}), edit("e5", "retry_node", "fix")], run=True)
    client = FakeClient(agent=[initial_decision(), retry, decision(3, finish=True)], worker=[worker_escalation(), worker_patch()])
    result = build_loop(project, tmp_path / "runs", client).run(project_id="demo", run_id="escalate", goal="repair the broken add function")
    assert result.status == "SUCCEEDED" and result.decision_count == 3 and result.worker_calls == 2


def test_worker_rejects_shell_and_path_escape(tmp_path: Path) -> None:
    project = copy_fixture(tmp_path)
    bad = worker_patch()
    bad["actions"] = [{"action": "run_command", "command": ["pytest"]}]
    client = FakeClient(agent=[initial_decision(), decision(2, finish=True)], worker=[bad])
    result = build_loop(project, tmp_path / "runs", client).run(project_id="demo", run_id="bad", goal="repair")
    assert result.run_summary and result.run_summary.failed_nodes == ("fix",)
