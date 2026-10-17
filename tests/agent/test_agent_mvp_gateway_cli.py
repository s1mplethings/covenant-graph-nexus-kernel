from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import pathlib
import subprocess
import sys
import threading

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class AgentMVPGateway(BaseHTTPRequestHandler):
    models: list[str] = []
    agent_calls = 0

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = payload["model"]
        type(self).models.append(model)
        schema_name = payload["text"]["format"]["name"]
        if schema_name == "cgkn_worker_proposal":
            value = {"schema_version": "1.0", "node_id": "fix", "summary": "repair", "actions": [{"action": "patch_file", "path": "math_utils.py", "find": "return a - b", "replace": "return a + b"}], "expected_outputs": ["pytest passes"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        else:
            type(self).agent_calls += 1
            if self.agent_calls == 1:
                def add(edit_id, node, capability, config, deps=()):
                    return {"edit_id": edit_id, "operation": "add_node", "node_id": node, "payload": {"parent_id": "", "capability_ref": capability, "depends_on": list(deps), "config": config}, "provenance": {"provider": "gateway-mock"}}
                edits = [
                    add("e1", "inspect", "repo.inspect@1", {"executor_ref": "local.file@1", "action": "read_file", "path": "math_utils.py"}),
                    add("e2", "fix", "code.modify@1", {"executor_ref": "llm.cheap@1", "goal": "Correct add so it returns the sum", "acceptance": ["pytest passes"]}, ("inspect",)),
                    add("e3", "test", "test.python@1", {"executor_ref": "local.python-test@1", "pytest_args": ["-q"]}, ("fix",)),
                ]
                value = {"schema_version": "1.0", "decision_id": "d1", "summary": "compose", "reason": "bounded", "edits": edits, "request_run": True, "finish": False, "needs_escalation": False, "escalation_reason": ""}
            else:
                value = {"schema_version": "1.0", "decision_id": "d2", "summary": "finish", "reason": "pytest passed", "edits": [], "request_run": False, "finish": True, "needs_escalation": False, "escalation_reason": ""}
        body = json.dumps({"id": f"request-{len(self.models)}", "status": "completed", "model": model, "output_text": json.dumps(value), "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.happy_path
@pytest.mark.local_functional
def test_agent_mvp_cli_uses_gateway_routing_snapshot_and_budget(tmp_path: pathlib.Path) -> None:
    AgentMVPGateway.models = []
    AgentMVPGateway.agent_calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), AgentMVPGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    run_root = tmp_path / "run"
    env = os.environ.copy()
    env.update({
        "CGKN_PROVIDER_GATEWAY_ENABLED": "1",
        "CGKN_PROVIDER_GATEWAY_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "CGKN_PROVIDER_GATEWAY_TOKEN": "ephemeral-test-token",
        "CGKN_PROVIDER_BUDGET_LEDGER": str(run_root / "provider_budget.json"),
        "CGKN_PROVIDER_MAX_API_CALLS": "4",
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": "100000",
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": "30000",
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "100",
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": "1",
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/run_agent_mvp.py", "--run-root", str(run_root), "--json"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=90,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads((run_root / "agent_mvp_result.json").read_text(encoding="utf-8"))
    snapshot = json.loads((run_root / "model_routing_snapshot.json").read_text(encoding="utf-8"))
    ledger = json.loads((run_root / "provider_budget.json").read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert AgentMVPGateway.models == ["qwen", "deepseek", "qwen"]
    assert snapshot["roles"] == {"agent": "qwen", "worker": "deepseek"}
    assert ledger["totals"]["confirmed_calls"] == 3
    assert {row["provider"] for row in ledger["calls"]} == {"qwen", "deepseek"}
    assert "ephemeral-test-token" not in json.dumps(result) + json.dumps(snapshot) + json.dumps(ledger)
