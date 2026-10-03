from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "cgkn"
SERVER_PATH = PLUGIN / "scripts" / "cgkn_mcp_server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("cgkn_mcp_server_test", SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPClient:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER_PATH), "--cgkn-root", str(ROOT)],
            cwd=PLUGIN,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.next_id = 1

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin and self.process.stdout
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        assert line, self.process.stderr.read() if self.process.stderr else "MCP server stopped"
        response = json.loads(line)
        assert response["id"] == request_id
        return response

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        return response["result"]

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=10)
        assert self.process.returncode == 0, self.process.stderr.read() if self.process.stderr else ""


@pytest.fixture
def client():
    value = MCPClient()
    try:
        yield value
    finally:
        value.close()


def ready_draft() -> dict[str, Any]:
    return {
        "workflow_state": "ready",
        "summary": "Use the reviewed CGKN route and verify the smallest runnable vertical slice.",
        "diagnosis": ["The project needs bounded generation guidance and executable checks."],
        "provider_guidance": ["Generate only the requested vertical slice through the existing Provider route."],
        "repair_targets": ["src"],
        "acceptance_checks": ["The generated project starts and its supported test suite passes."],
        "context_requests": [],
        "tool_evidence_requests": ["Record the generated-project test result."],
        "known_limits": ["Agent guidance is advisory and does not authorize delivery PASS."],
    }


def test_plugin_manifest_and_mcp_configuration_are_local_and_bounded() -> None:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "cgkn"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["skills"] == "./skills/"
    assert mcp["mcpServers"]["cgkn"]["enabled"] is True
    env_vars = mcp["mcpServers"]["cgkn"]["env_vars"]
    assert "CGKN_OPENAI_API_KEY" in env_vars
    assert "CGKN_OPENAI_BASE_URL" in env_vars
    assert "OPENAI_API_KEY" not in env_vars
    command_text = json.dumps(mcp, ensure_ascii=False).lower()
    assert "openai_api_key" in command_text  # Environment pass-through only.
    assert "sk-" not in command_text
    assert "run_local_pipeline.py" not in command_text  # The MCP server owns the guarded call.


def test_mcp_protocol_lists_typed_tools_with_honest_annotations(client: MCPClient) -> None:
    initialized = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert initialized["result"]["serverInfo"]["name"] == "cgkn"
    tools = client.request("tools/list")["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "cgkn_doctor",
        "cgkn_init",
        "cgkn_prepare",
        "cgkn_seal_brief",
        "cgkn_plan_generation",
        "cgkn_probe_provider",
        "cgkn_generate",
        "cgkn_surrogate_status",
        "cgkn_submit_surrogate_response",
        "cgkn_diagnose_failure",
        "cgkn_test_generated",
        "cgkn_status",
    }
    for tool in tools:
        assert tool["inputSchema"]["additionalProperties"] is False
        assert tool["outputSchema"]["type"] == "object"
        assert tool["annotations"]["destructiveHint"] is False
        assert "api_key" not in json.dumps(tool["inputSchema"]).lower()
    generation = next(tool for tool in tools if tool["name"] == "cgkn_generate")
    assert generation["inputSchema"]["properties"]["usage_beta"]["default"] is False
    assert generation["annotations"]["openWorldHint"] is True
    assert generation["inputSchema"]["properties"]["confirmation"]["const"] == "RUN_REVIEWED_PROVIDER"
    probe = next(tool for tool in tools if tool["name"] == "cgkn_probe_provider")
    assert probe["annotations"]["readOnlyHint"] is True
    assert probe["annotations"]["idempotentHint"] is False
    assert probe["annotations"]["openWorldHint"] is True
    assert probe["inputSchema"]["properties"]["confirmation"]["const"] == "RUN_PROVIDER_PROBE"
    diagnosis = next(tool for tool in tools if tool["name"] == "cgkn_diagnose_failure")
    assert diagnosis["annotations"]["readOnlyHint"] is True
    assert diagnosis["annotations"]["openWorldHint"] is False
    assert "retry" in diagnosis["description"].lower()


def test_mcp_end_to_end_init_prepare_seal_plan_and_status(client: MCPClient, tmp_path: pathlib.Path) -> None:
    project = tmp_path / "sample"
    project.mkdir()
    (project / "README.md").write_text("# Sample\nA bounded project fixture.\n", encoding="utf-8")

    initialized = client.tool("cgkn_init", {"project_root": str(project)})
    assert initialized["structuredContent"]["ok"] is True
    assert (project / ".cgkn" / "agent-kit.json").is_file()

    prepared = client.tool(
        "cgkn_prepare",
        {
            "project_root": str(project),
            "goal": "Create a small tested sample project",
            "gap": "The implementation plan and executable checks are missing",
            "category": "planning_gap",
        },
    )
    assert prepared["structuredContent"]["request"]["authority"]["advisory_only"] is True

    sealed = client.tool("cgkn_seal_brief", {"project_root": str(project), "draft": ready_draft()})
    brief = sealed["structuredContent"]["brief"]
    assert brief["workflow_state"] == "ready"
    assert brief["authority"]["formal_evidence_status"] == "NOT_EVALUATED"

    planned = client.tool(
        "cgkn_plan_generation",
        {"project_root": str(project), "goal": "Create a small tested sample project"},
    )["structuredContent"]
    assert planned["executed"] is False
    assert planned["secrets_in_argv"] is False
    assert any("run_codex_conversation_generation.py" in item for item in planned["argv"])
    assert "--allow-provider" in planned["argv"]
    assert "--use-api" in planned["argv"]
    assert "--resume-run-dir" not in planned["argv"]

    run_dir = project / ".cgkn" / "agent-kit" / "runs"
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "pending_repair_plan.json").write_text(
        json.dumps(
            {
                "status": "pending",
                "stage": "component_file_generation",
                "raw_user_goal": "Create a small tested sample project",
            }
        ),
        encoding="utf-8",
    )
    resumed = client.tool(
        "cgkn_plan_generation",
        {"project_root": str(project), "goal": "Create a small tested sample project"},
    )["structuredContent"]
    resume_index = resumed["argv"].index("--resume-run-dir")
    assert resumed["argv"][resume_index + 1] == str(run_dir.resolve())

    different_goal = client.tool(
        "cgkn_plan_generation",
        {"project_root": str(project), "goal": "Create a different sample project"},
    )["structuredContent"]
    assert "--resume-run-dir" not in different_goal["argv"]

    status = client.tool("cgkn_status", {"project_root": str(project)})["structuredContent"]
    assert status["initialized"] is True
    assert status["formal_evidence_status"] == "NOT_EVALUATED"
    assert status["artifacts"]["brief"]["valid"] is True
    assert status["diagnosis"]["has_failure"] is False


def test_mcp_prepare_round_trips_chinese_utf8_without_surrogates(
    client: MCPClient,
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "unicode-project"
    project.mkdir()
    goal = "构建中国研究生计算机考研学习助手，支持 408 学习计划与错题复习。"
    gap = "需要保持中文目标原文，并正确区分主产品与番茄钟等次要功能。"

    client.tool("cgkn_init", {"project_root": str(project)})
    prepared = client.tool(
        "cgkn_prepare",
        {
            "project_root": str(project),
            "goal": goal,
            "gap": gap,
            "category": "planning_gap",
        },
    )["structuredContent"]

    assert prepared["ok"] is True
    request = prepared["request"]
    assert request["goal_summary"] == goal
    assert request["capability_gap"]["summary"] == gap
    assert "\\udc" not in json.dumps(request, ensure_ascii=True).lower()


def test_tool_arguments_reject_secrets_and_generation_requires_confirmation(
    client: MCPClient,
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "guarded"
    project.mkdir()
    secret = "sk-" + "ExampleOnlyNotARealCredential123"
    rejected = client.tool(
        "cgkn_prepare",
        {"project_root": str(project), "goal": secret, "gap": "gap"},
    )
    assert rejected["isError"] is True
    assert secret not in json.dumps(rejected)

    client.tool("cgkn_init", {"project_root": str(project)})
    missing_confirmation = client.tool(
        "cgkn_generate",
        {"project_root": str(project), "goal": "sample", "confirmation": "NO"},
    )
    assert missing_confirmation["isError"] is True
    assert "RUN_REVIEWED_PROVIDER" in missing_confirmation["structuredContent"]["error"]
    assert missing_confirmation["structuredContent"]["failure"] == {
        "category": "invalid_request_or_precondition",
        "summary": "arguments.confirmation must equal RUN_REVIEWED_PROVIDER",
        "retryable": False,
        "source": "mcp_tool",
    }

    wrong_type = client.tool(
        "cgkn_status",
        {"project_root": str(project), "unexpected": True},
    )
    assert wrong_type["isError"] is True
    assert "Unsupported arguments fields" in wrong_type["structuredContent"]["error"]


def test_generate_returns_managed_job_without_reusing_a_stale_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    module = load_server_module()
    server = module.CGKNPluginServer(ROOT)
    project = tmp_path / "stale-result"
    artifact_dir = project / ".cgkn" / "agent-kit"
    artifact_dir.mkdir(parents=True)
    result_path = artifact_dir / "generation_result.json"
    result_path.write_text('{"status":"BLOCKED"}\n', encoding="utf-8")
    brief_path = artifact_dir / "codex_capability_brief.json"
    for name in module.PROVIDER_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        server.connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "test-only-value", "api_key_source": "CGKN_OPENAI_API_KEY(User)"},
    )
    monkeypatch.setattr(server, "_project", lambda _value: project)
    monkeypatch.setattr(server, "_validated_brief", lambda _project: ({}, brief_path, ROOT))
    monkeypatch.setattr(server, "_loaded", lambda _project: (project, {}, ROOT, artifact_dir))
    monkeypatch.setattr(server.core, "generation_command", lambda *args, **kwargs: ["runner"])
    monkeypatch.setattr(
        server.core,
        "start_generation_job",
        lambda *args, **kwargs: {
            "started": True, "deduplicated": False, "run_id": "production-fresh",
            "state": "RUNNING", "job_alive": True,
        },
    )

    result = server.generate(
        {
            "project_root": str(project),
            "goal": "Generate a sample",
            "confirmation": module.GENERATION_CONFIRMATION,
        }
    )
    assert result["run_id"] == "production-fresh"
    assert result["state"] == "RUNNING"
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "BLOCKED"


def test_generate_projects_managed_start_failure_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    module = load_server_module()
    server = module.CGKNPluginServer(ROOT)
    project = tmp_path / "blocked-result"
    artifact_dir = project / ".cgkn" / "agent-kit"
    artifact_dir.mkdir(parents=True)
    result_path = artifact_dir / "generation_result.json"
    brief_path = artifact_dir / "codex_capability_brief.json"
    monkeypatch.setattr(
        server.connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "test-only-value", "api_key_source": "CGKN_OPENAI_API_KEY(User)"},
    )
    monkeypatch.setattr(server, "_project", lambda _value: project)
    monkeypatch.setattr(server, "_validated_brief", lambda _project: ({}, brief_path, ROOT))
    monkeypatch.setattr(server, "_loaded", lambda _project: (project, {}, ROOT, artifact_dir))
    monkeypatch.setattr(server.core, "generation_command", lambda *args, **kwargs: ["runner"])

    monkeypatch.setattr(
        server.core,
        "start_generation_job",
        lambda *args, **kwargs: {
            "started": True, "deduplicated": False, "run_id": "",
            "state": "FAILED", "job_alive": False, "terminal_reason": "JOB_START_FAILED",
        },
    )

    result = server.generate(
        {
            "project_root": str(project),
            "goal": "Generate a sample",
            "confirmation": module.GENERATION_CONFIRMATION,
        }
    )

    assert result["ok"] is False
    assert result["state"] == "FAILED"
    assert result["job"]["terminal_reason"] == "JOB_START_FAILED"


def test_failure_diagnosis_separates_root_cause_secondary_effects_and_unsafe_resume(
    client: MCPClient,
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "diagnosed"
    project.mkdir()
    client.tool("cgkn_init", {"project_root": str(project)})
    artifact_dir = project / ".cgkn" / "agent-kit"
    run_dir = artifact_dir / "runs"
    support_dir = run_dir / "artifacts"
    support_dir.mkdir(parents=True)
    goal = "Build a complete exam-learning project"
    (artifact_dir / "generation_result.json").write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason": "provider_fact_blocked",
                "goal": goal,
                "provider_semantic_review": {
                    "issues": "component backend generation failed: provider leaf repair exhausted for "
                    "backend:backend/stages_part_01.py: implementation depth contract mismatch: "
                    "nonblank implementation lines 4 < 10"
                },
                "fatal_fact_blockers": "canonical project plan files missing: app/main.py, README.md, TEST_PLAN.md",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (support_dir / "pending_repair_plan.json").write_text(
        json.dumps(
            {
                "status": "pending",
                "stage": "component_file_generation",
                "raw_user_goal": goal,
            }
        ),
        encoding="utf-8",
    )
    secret = "sk-ExampleOnlyNotARealCredential123"
    events = [
        {"event": "component_leaf_cache_scanned", "component": "backend", "spec_hash": "hash-one"},
        {
            "event": "component_leaf_attempt_failed",
            "stage": "component_file_generation",
            "component": "backend",
            "target_file": "backend/stages_part_01.py",
            "error_type": "PROVIDER_UNKNOWN_ERROR",
            "error_summary": "implementation depth contract mismatch: nonblank implementation lines 4 < 10",
        },
        {
            "event": "pipeline_fallback",
            "component": "backend",
            "target_file": "backend/stages_part_01.py",
            "reason": "transport_error_http_504",
        },
        {
            "event": "local_model_provider_attempt",
            "component": "backend",
            "target_file": "backend/stages_part_01.py",
            "provider": "ollama",
            "status": "ok",
        },
        {
            "event": "component_leaf_attempt_failed",
            "stage": "component_file_generation",
            "component": "backend",
            "target_file": "backend/stages_part_01.py",
            "error_type": "PROVIDER_UNKNOWN_ERROR",
            "error_summary": f"implementation depth contract mismatch; diagnostic token {secret}",
        },
        {"event": "component_leaf_cache_scanned", "component": "backend", "spec_hash": "hash-two"},
    ]
    (run_dir / "provider_phase_log.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    response = client.tool("cgkn_diagnose_failure", {"project_root": str(project)})
    diagnosis = response["structuredContent"]["diagnosis"]

    assert response["structuredContent"]["formal_evidence_status"] == "NOT_EVALUATED"
    assert diagnosis["has_failure"] is True
    assert diagnosis["primary_failure"]["category"] == "provider_output_contract"
    assert diagnosis["primary_failure"]["target_file"] == "backend/stages_part_01.py"
    contributing_categories = {item["category"] for item in diagnosis["contributing_failures"]}
    assert {"provider_transport", "local_model_output_contract", "checkpoint_identity_drift"} <= contributing_categories
    assert diagnosis["secondary_effects"][0]["category"] == "missing_required_artifacts"
    assert diagnosis["secondary_effects"][0]["count"] == 3
    assert diagnosis["resume"] == {
        "available": True,
        "safe": False,
        "reason": "checkpoint_identity_drift",
        "run_dir": str(run_dir.resolve()),
    }
    assert "fresh reviewed generation run" in diagnosis["recommended_next_action"]
    assert secret not in json.dumps(response)

    status = client.tool("cgkn_status", {"project_root": str(project)})["structuredContent"]
    assert status["diagnosis"]["primary_failure"]["category"] == "provider_output_contract"


def test_failure_diagnosis_uses_current_bound_resume_identity_over_historical_hashes(
    client: MCPClient,
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "identity-bound-resume"
    project.mkdir()
    client.tool("cgkn_init", {"project_root": str(project)})
    artifact_dir = project / ".cgkn" / "agent-kit"
    run_dir = artifact_dir / "runs"
    support_dir = run_dir / "artifacts"
    support_dir.mkdir(parents=True)
    goal = "Build a local study application"
    (artifact_dir / "generation_result.json").write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "goal": goal,
                "reason": "provider_fact_blocked",
                "provider_semantic_review": {
                    "issues": "component backend generation failed: provider leaf repair exhausted for "
                    "backend:backend/stages_part_02.py: RemoteDisconnected: remote end closed connection"
                },
            }
        ),
        encoding="utf-8",
    )
    (support_dir / "pending_repair_plan.json").write_text(
        json.dumps(
            {
                "status": "pending",
                "stage": "component_file_generation",
                "raw_user_goal": goal,
                "component": "backend",
                "target_file": "backend/stages_part_02.py",
                "resume_identity": {
                    "component_id": "backend",
                    "component_contract_sha256": "a" * 64,
                    "component_spec_sha256": "b" * 64,
                    "file_manifest_sha256": "c" * 64,
                    "leaf_work_graph_sha256": "d" * 64,
                    "target_file": "backend/stages_part_02.py",
                    "target_manifest_entry_sha256": "e" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    events = [
        {"event": "component_leaf_cache_scanned", "component": "foundation", "spec_hash": "foundation-old"},
        {"event": "component_leaf_cache_scanned", "component": "foundation", "spec_hash": "foundation-current"},
        {"event": "component_leaf_cache_scanned", "component": "backend", "spec_hash": "old"},
        {"event": "pending_component_leaf_superseded", "component": "backend"},
        {"event": "component_leaf_cache_scanned", "component": "backend", "spec_hash": "current"},
        {
            "event": "component_leaf_attempt_failed",
            "stage": "component_file_generation",
            "component": "backend",
            "target_file": "backend/stages_part_02.py",
            "error_type": "PROVIDER_API_REQUEST_FAILED",
            "error_summary": "RemoteDisconnected: remote end closed connection without response",
        },
    ]
    (run_dir / "provider_phase_log.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    diagnosis = client.tool(
        "cgkn_diagnose_failure", {"project_root": str(project)}
    )["structuredContent"]["diagnosis"]

    assert diagnosis["primary_failure"]["category"] == "provider_transport"
    assert diagnosis["resume"]["safe"] is True
    assert diagnosis["resume"]["reason"] == "matching_identity_bound_pending_plan"
    drift = next(
        item
        for item in diagnosis["contributing_failures"]
        if item["category"] == "checkpoint_identity_drift"
    )
    assert drift["components"] == ["foundation"]
    assert "resume the matching safe pending plan" in diagnosis["recommended_next_action"]
    assert "do not auto-resume" not in diagnosis["recommended_next_action"]


def test_provider_account_blocker_recommends_resolving_then_resuming_safe_identity(
    client: MCPClient,
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "provider-account-safe-resume"
    project.mkdir()
    client.tool("cgkn_init", {"project_root": str(project)})
    artifact_dir = project / ".cgkn" / "agent-kit"
    run_dir = artifact_dir / "runs"
    support_dir = run_dir / "artifacts"
    support_dir.mkdir(parents=True)
    goal = "Build a local study application"
    failure = 'provider_api_request_failed: HTTP 401: {"error":"Balance is insufficient"}'
    (artifact_dir / "generation_result.json").write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "goal": goal,
                "reason": "provider_fact_blocked",
                "provider_semantic_review": {"issues": failure},
            }
        ),
        encoding="utf-8",
    )
    (support_dir / "pending_repair_plan.json").write_text(
        json.dumps(
            {
                "status": "pending",
                "stage": "component_file_generation",
                "raw_user_goal": goal,
                "component": "backend",
                "target_file": "src/service.py",
                "resume_identity": {
                    "component_id": "backend",
                    "component_contract_sha256": "a" * 64,
                    "component_spec_sha256": "b" * 64,
                    "file_manifest_sha256": "c" * 64,
                    "leaf_work_graph_sha256": "d" * 64,
                    "target_file": "src/service.py",
                    "target_manifest_entry_sha256": "e" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    events = [
        {"event": "component_leaf_cache_scanned", "component": "foundation", "spec_hash": "old"},
        {"event": "component_leaf_cache_scanned", "component": "foundation", "spec_hash": "current"},
        {
            "event": "component_leaf_attempt_failed",
            "stage": "component_file_generation",
            "component": "backend",
            "target_file": "src/service.py",
            "error_type": "PROVIDER_NON_RETRYABLE_HTTP",
            "error_summary": failure,
        },
    ]
    (run_dir / "provider_phase_log.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    diagnosis = client.tool(
        "cgkn_diagnose_failure", {"project_root": str(project)}
    )["structuredContent"]["diagnosis"]

    assert diagnosis["primary_failure"]["category"] == "provider_authentication"
    assert diagnosis["resume"]["safe"] is True
    assert diagnosis["resume"]["reason"] == "matching_identity_bound_pending_plan"
    assert diagnosis["recommended_next_action"] == (
        "Resolve Provider authentication or account availability, then resume the matching "
        "safe pending plan through the reviewed Provider route."
    )


@pytest.mark.parametrize(
    ("api_result", "diagnostic", "ok"),
    [
        (
            {
                "ok": True,
                "configured": True,
                "api_key_source": "CGKN_OPENAI_API_KEY(User)",
                "base_url": "https://api.example.test/v1",
                "base_url_source": "CGKN_OPENAI_BASE_URL(User)",
                "endpoint": "https://api.example.test/v1/responses",
                "endpoint_mode": "responses",
                "attempts": 1,
                "tls_verify": True,
                "request_id": "req-test",
                "status": "connected",
            },
            "connected",
            True,
        ),
        (
            {
                "ok": False,
                "configured": True,
                "api_key_source": "CGKN_OPENAI_API_KEY(User)",
                "base_url": "https://api.example.test/v1",
                "error": 'HTTP 401: {"error":"invalid_api_key"} [retryable=false]',
                "attempts": 1,
            },
            "authentication_failed",
            False,
        ),
        (
            {"ok": False, "configured": True, "error": "HTTP 403: Key usage limit exceeded [retryable=false]"},
            "usage_limit",
            False,
        ),
        (
            {"ok": False, "configured": True, "error": "HTTP 403: permission denied [retryable=false]"},
            "permission_denied",
            False,
        ),
        (
            {"ok": False, "configured": True, "error": "HTTP 404: model does not exist [retryable=false]"},
            "model_unavailable",
            False,
        ),
        (
            {"ok": False, "configured": True, "error": "request failed: timed out [retryable=true]"},
            "transport_failure",
            False,
        ),
        ({"ok": False, "configured": False, "error": "missing API key"}, "missing_credential", False),
    ],
)
def test_provider_probe_returns_bounded_diagnostics_without_formal_promotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    api_result: dict[str, Any],
    diagnostic: str,
    ok: bool,
) -> None:
    module = load_server_module()
    server = module.CGKNPluginServer(ROOT)
    monkeypatch.setattr(server.connectivity, "check_api", lambda *_args, **_kwargs: api_result)

    result = server.probe_provider(
        {
            "project_root": str(tmp_path),
            "confirmation": module.PROVIDER_PROBE_CONFIRMATION,
            "model": "gpt-test",
            "timeout": 5,
        }
    )

    assert result["ok"] is ok
    assert result["probe"]["diagnostic"] == diagnostic
    assert result["formal_evidence_status"] == "NOT_EVALUATED"
    if api_result.get("api_key_source") == "CGKN_OPENAI_API_KEY(User)":
        assert result["probe"]["source_scope"] == "canonical_user"
    assert "api_key_source" not in result["probe"]
    assert "test-only-value" not in json.dumps(result)
    assert "sk-" not in json.dumps(result).lower()
def test_generated_project_test_profile_runs_without_parent_secrets(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "tested"
    project.mkdir()
    monkeypatch.setenv("CGKN_TEST_SECRET", "must-not-leak")
    isolated_client = MCPClient()
    try:
        isolated_client.tool("cgkn_init", {"project_root": str(project)})
        generated = project / ".cgkn" / "agent-kit" / "generated-project"
        tests = generated / "tests"
        tests.mkdir(parents=True)
        (generated / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
        (tests / "test_environment.py").write_text(
            "import os\n\ndef test_parent_secret_is_absent():\n    assert 'CGKN_TEST_SECRET' not in os.environ\n",
            encoding="utf-8",
        )
        result = isolated_client.tool(
            "cgkn_test_generated",
            {"project_root": str(project), "confirmation": "RUN_PROJECT_TESTS", "timeout": 120},
        )["structuredContent"]
        assert result["ok"] is True
        assert result["profile"] == "python-pytest"
        assert result["returncode"] == 0
    finally:
        isolated_client.close()


def test_status_does_not_promote_uninitialized_project(tmp_path: pathlib.Path) -> None:
    module = load_server_module()
    server = module.CGKNPluginServer(ROOT)
    result = server.status({"project_root": str(tmp_path)})
    assert result["initialized"] is False
    assert result["formal_evidence_status"] == "NOT_EVALUATED"
    assert result["artifacts"]["config"]["exists"] is False
    assert result["diagnosis"]["has_failure"] is False
