from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import pathlib
import threading
from typing import Any

import pytest

from cgkn.application.software_project.contracts import ProjectResultStatus
from cgkn.application.software_project.service import SoftwareProjectGenerationService
from cgkn.providers import CGKNModelRouting, GatewayCompletionClient


ROOT = pathlib.Path(__file__).resolve().parents[3]


class ProjectGateway(BaseHTTPRequestHandler):
    models: list[str] = []
    agent_calls = 0

    def log_message(self, *_args: object) -> None:
        return

    @staticmethod
    def _add(node: str, capability: str, config: dict[str, Any], deps: tuple[str, ...] = ()) -> dict[str, Any]:
        return {"edit_id": f"e-{node}", "operation": "add_node", "node_id": node, "payload": {"parent_id": "", "capability_ref": capability, "depends_on": list(deps), "config": config}, "provenance": {"provider": "mock-gateway"}}

    def do_POST(self) -> None:  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = payload["model"]
        type(self).models.append(model)
        schema_name = payload["text"]["format"]["name"]
        if schema_name == "cgkn_scoped_project_worker":
            value = {"schema_version": "1.0", "node_id": "patch", "summary": "repair add", "actions": [{"action": "patch_file", "path": "math_utils.py", "find": "return a - b", "replace": "return a + b"}], "expected_outputs": ["pytest passes"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        else:
            type(self).agent_calls += 1
            if self.agent_calls == 1:
                protected = [".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"]
                edits = [
                    self._add("inspect", "workspace.inspect@1", {"executor_ref": "local.file@1", "action": "list_files", "path": ".", "goal": "inspect"}),
                    self._add("patch", "project.file.patch@1", {"executor_ref": "llm.cheap@1", "goal": "repair add", "target_paths": ["math_utils.py"], "allowed_paths": ["math_utils.py"], "file_purpose": "arithmetic", "interfaces": {}, "acceptance": ["pytest passes"], "allowed_effects": ["filesystem.write"], "max_actions": 2, "max_write_files": 1, "max_total_output_bytes": 1000, "allow_create": False, "allow_patch": True, "allow_delete": False, "protected_paths": protected}, ("inspect",)),
                    self._add("pytest", "project.python.pytest@1", {"executor_ref": "local.python-test@1", "pytest_args": ["-q"], "goal": "test"}, ("patch",)),
                    self._add("snapshot", "project.snapshot@1", {"executor_ref": "project.snapshot@1", "entrypoints": ["math_utils.py"], "test_commands": ["python -m pytest -q"], "runtime_commands": ["python -m pytest -q"], "goal": "snapshot"}, ("pytest",)),
                    self._add("accept", "project.acceptance.external@1", {"executor_ref": "project.acceptance@1", "case_id": "seeded_repair", "goal": "accept"}, ("snapshot",)),
                ]
                value = {"schema_version": "1.0", "decision_id": "d1", "summary": "compose", "reason": "bounded repair", "edits": edits, "request_run": True, "finish": False, "needs_escalation": False, "escalation_reason": ""}
            else:
                value = {"schema_version": "1.0", "decision_id": "d2", "summary": "finish", "reason": "acceptance passed", "edits": [], "request_run": False, "finish": True, "needs_escalation": False, "escalation_reason": ""}
        body = json.dumps({"id": f"mock-{len(self.models)}", "status": "completed", "model": model, "output_text": json.dumps(value), "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.happy_path
@pytest.mark.local_functional
@pytest.mark.generation
def test_qwen_agent_deepseek_worker_crosses_real_runtime_pytest_and_external_acceptance(tmp_path: pathlib.Path) -> None:
    ProjectGateway.models = []
    ProjectGateway.agent_calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProjectGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = GatewayCompletionClient(f"http://127.0.0.1:{server.server_port}/v1", "ephemeral-test-token", enforce_budget=False)
        routing = CGKNModelRouting.load(ROOT / "config" / "provider_profiles" / "gateway_model_routing.json")
        result = SoftwareProjectGenerationService(ROOT, tmp_path / "artifacts", client=client, routing=routing).run_case("seeded_repair", max_repair_rounds=0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.status is ProjectResultStatus.PASS
    assert ProjectGateway.models == ["qwen", "deepseek", "qwen"]
    assert result.receipt["internal_test_result"] == "PASS"
    assert result.receipt["hidden_acceptance_result"] == "PASS"
    assert result.receipt["model_routing_roles"] == {"agent": "qwen", "worker": "deepseek"}
    snapshot = json.loads((result.run_dir / "model_routing_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["fallback"] == "deny" and snapshot["contains_credentials"] is False
