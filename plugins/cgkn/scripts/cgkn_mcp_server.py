#!/usr/bin/env python3
"""Local MCP bridge for the reviewed Agent-assisted CGKN workflow."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any, Callable


SERVER_VERSION = "0.2.0-rc.2"
PROTOCOL_VERSION = "2025-06-18"
GENERATION_CONFIRMATION = "RUN_REVIEWED_PROVIDER"
PROVIDER_PROBE_CONFIRMATION = "RUN_PROVIDER_PROBE"
TEST_CONFIRMATION = "RUN_PROJECT_TESTS"
PROVIDER_MODES = ("live", "codex_surrogate", "deterministic_replay")
PROVIDER_KEY_ENV_NAMES = (
    "CGKN_OPENAI_API_KEY_OVERRIDE",
    "QWEN_API_KEY",
    "CGKN_OPENAI_API_KEY",
    "OPENAI_API_KEY",
)
CATEGORIES = (
    "environment_blocker",
    "generation_failure",
    "integration_failure",
    "planning_gap",
    "research_gap",
    "test_failure",
    "tool_gap",
)
SECRET_KEY = re.compile(r"(?i)(api.?key|access.?token|auth.?token|password|secret|credential)")
SECRET_VALUE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b|(?i:Bearer\s+[A-Za-z0-9._~+/=-]{12,})")
MAX_DIAGNOSTIC_LOG_BYTES = 4 * 1024 * 1024
MAX_DIAGNOSTIC_EVENTS = 2000


class ToolError(RuntimeError):
    """An error safe to return as an MCP tool result."""


def object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
INTEGER = {"type": "integer"}
JSON_OBJECT = {"type": "object"}
STRING_ARRAY = {"type": "array", "items": STRING}


def tool_definition(
    name: str,
    title: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    *,
    read_only: bool,
    open_world: bool,
    idempotent: bool | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": input_schema,
        "outputSchema": output_schema,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False,
            "idempotentHint": read_only if idempotent is None else idempotent,
            "openWorldHint": open_world,
        },
    }


PROJECT = {"project_root": {"type": "string", "description": "Absolute or working-directory-relative local project directory."}}
DRAFT_SCHEMA = object_schema(
    {
        "workflow_state": {"enum": ["ready", "needs_context", "declined"]},
        "summary": {"type": "string", "maxLength": 1200},
        "diagnosis": STRING_ARRAY,
        "provider_guidance": STRING_ARRAY,
        "repair_targets": STRING_ARRAY,
        "acceptance_checks": STRING_ARRAY,
        "context_requests": STRING_ARRAY,
        "tool_evidence_requests": STRING_ARRAY,
        "known_limits": STRING_ARRAY,
    },
    (
        "workflow_state",
        "summary",
        "diagnosis",
        "provider_guidance",
        "repair_targets",
        "acceptance_checks",
        "context_requests",
        "tool_evidence_requests",
        "known_limits",
    ),
)

TOOLS = [
    tool_definition(
        "cgkn_doctor",
        "Check CGKN readiness",
        "Check the project's CGKN configuration and the reviewed Provider mainline. Nested Codex is not required by this plugin.",
        object_schema(PROJECT, ("project_root",)),
        object_schema({"ok": BOOLEAN, "report": JSON_OBJECT}, ("ok", "report")),
        read_only=True,
        open_world=False,
    ),
    tool_definition(
        "cgkn_conversation",
        "Answer from CGKN evidence",
        "Answer one read-only query from the existing CGKN knowledge authority with localized retrieval, auditable provenance, and honest no-evidence or Provider-unavailable behavior.",
        object_schema(
            {
                **PROJECT,
                "query": {"type": "string", "minLength": 1, "maxLength": 4000},
                "thread_context_id": {"type": "string", "default": ""},
                "knowledge_path": {"type": "string", "default": ".cgkn/project_knowledge_pack.json"},
                "retrieval_constraints": {"type": "object", "additionalProperties": True},
                "provider_mode": {"enum": ["auto", "disabled"], "default": "auto"},
            },
            ("project_root", "query"),
        ),
        object_schema({"ok": BOOLEAN, "response": JSON_OBJECT, "component_ref": STRING}, ("ok", "response", "component_ref")),
        read_only=True,
        open_world=True,
        idempotent=False,
    ),
    tool_definition(
        "cgkn_init",
        "Initialize CGKN support",
        "Create project-local .cgkn Agent support state. This stores no provider secret.",
        object_schema({**PROJECT, "force": {"type": "boolean", "default": False}}, ("project_root",)),
        object_schema({"ok": BOOLEAN, "config_path": STRING, "config": JSON_OBJECT}, ("ok", "config_path", "config")),
        read_only=False,
        open_world=False,
    ),
    tool_definition(
        "cgkn_prepare",
        "Prepare bounded Agent guidance request",
        "Scan a bounded, secret-filtered project context and prepare an advisory CGKN request.",
        object_schema(
            {
                **PROJECT,
                "goal": {"type": "string", "minLength": 1, "maxLength": 2000},
                "gap": {"type": "string", "minLength": 1, "maxLength": 1600},
                "category": {"enum": list(CATEGORIES), "default": "planning_gap"},
            },
            ("project_root", "goal", "gap"),
        ),
        object_schema({"ok": BOOLEAN, "request_path": STRING, "request": JSON_OBJECT}, ("ok", "request_path", "request")),
        read_only=False,
        open_world=False,
    ),
    tool_definition(
        "cgkn_seal_brief",
        "Validate and seal Agent guidance",
        "Validate a bounded advisory draft and create the CGKN capability brief plus shared support artifacts.",
        object_schema({**PROJECT, "draft": DRAFT_SCHEMA}, ("project_root", "draft")),
        object_schema({"ok": BOOLEAN, "brief_path": STRING, "brief": JSON_OBJECT}, ("ok", "brief_path", "brief")),
        read_only=False,
        open_world=False,
    ),
    tool_definition(
        "cgkn_plan_generation",
        "Preview reviewed CGKN generation",
        "Validate the sealed advisory brief and return the exact existing Provider-mainline command without running it.",
        object_schema(
            {
                **PROJECT,
                "goal": {"type": "string", "minLength": 1, "maxLength": 2000},
                "model": {"type": "string", "default": "gpt-4.1"},
                "provider_mode": {"enum": list(PROVIDER_MODES), "default": "live"},
                "usage_beta": {"type": "boolean", "default": False},
                "replay_dir": {"type": "string", "default": ""},
                "allow_network": {"type": "boolean", "default": False},
            },
            ("project_root", "goal"),
        ),
        object_schema(
            {"ok": BOOLEAN, "executed": BOOLEAN, "argv": STRING_ARRAY, "brief_sha256": STRING, "secrets_in_argv": BOOLEAN},
            ("ok", "executed", "argv", "brief_sha256", "secrets_in_argv"),
        ),
        read_only=True,
        open_world=False,
    ),
    tool_definition(
        "cgkn_probe_provider",
        "Probe CGKN Provider connectivity",
        "Run one minimal live Provider API diagnostic without generating, packaging, or delivering a project. Uses only CGKN's resolved credential sources and requires RUN_PROVIDER_PROBE.",
        object_schema(
            {
                **PROJECT,
                "confirmation": {"const": PROVIDER_PROBE_CONFIRMATION},
                "model": {"type": "string", "default": "gpt-4.1-mini"},
                "timeout": {"type": "integer", "minimum": 5, "maximum": 60, "default": 20},
            },
            ("project_root", "confirmation"),
        ),
        object_schema(
            {"ok": BOOLEAN, "probe": JSON_OBJECT, "formal_evidence_status": STRING},
            ("ok", "probe", "formal_evidence_status"),
        ),
        read_only=True,
        open_world=True,
        idempotent=False,
    ),
    tool_definition(
        "cgkn_generate",
        "Run reviewed CGKN Provider generation",
        "Start one managed execution of the existing reviewed CGKN Provider route and return its durable run identity without waiting for generation completion. Repeated starts deduplicate a live job; observe progress with cgkn_status.",
        object_schema(
            {
                **PROJECT,
                "goal": {"type": "string", "minLength": 1, "maxLength": 2000},
                "confirmation": {"const": GENERATION_CONFIRMATION},
                "model": {"type": "string", "default": "gpt-4.1"},
                "provider_mode": {"enum": list(PROVIDER_MODES), "default": "live"},
                "usage_beta": {"type": "boolean", "default": False},
                "replay_dir": {"type": "string", "default": ""},
                "allow_network": {"type": "boolean", "default": False},
                "timeout": {"type": "integer", "minimum": 30, "maximum": 7200, "default": 1800},
            },
            ("project_root", "goal", "confirmation"),
        ),
        object_schema(
            {"ok": BOOLEAN, "started": BOOLEAN, "deduplicated": BOOLEAN, "run_id": STRING, "state": STRING, "job": JSON_OBJECT},
            ("ok", "started", "deduplicated", "run_id", "state", "job"),
        ),
        read_only=False,
        open_world=True,
    ),
    tool_definition(
        "cgkn_surrogate_status",
        "Inspect surrogate Provider handshake",
        "Read pending and consumed scheduler-created Provider requests for the latest or selected run.",
        object_schema({**PROJECT, "run_dir": {"type": "string", "default": ""}}, ("project_root",)),
        object_schema({"ok": BOOLEAN, "status": JSON_OBJECT}, ("ok", "status")),
        read_only=True,
        open_world=False,
    ),
    tool_definition(
        "cgkn_submit_surrogate_response",
        "Submit a Codex surrogate Provider response",
        "Bind one Provider text payload to a canonical scheduler request. The entry validates run, project, job, attempt, stage, hashes, schema, ownership, and duplicate/closed state before acceptance.",
        object_schema(
            {
                **PROJECT,
                "run_dir": {"type": "string", "default": ""},
                "job_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "attempt_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "payload": {"type": "string", "minLength": 1},
                "surrogate_identity": {"type": "string", "minLength": 1, "maxLength": 160, "default": "codex"},
            },
            ("project_root", "job_id", "attempt_id", "payload"),
        ),
        object_schema({"ok": BOOLEAN, "receipt": JSON_OBJECT}, ("ok", "receipt")),
        read_only=False,
        open_world=False,
        idempotent=True,
    ),
    tool_definition(
        "cgkn_diagnose_failure",
        "Diagnose the latest CGKN failure",
        "Read the latest generation result, bounded Provider phase log, and pending repair plan. Separates the primary failure from contributing failures and downstream missing artifacts, and reports whether checkpoint resume is safe. This tool is read-only, performs no retry, and cannot authorize formal evidence.",
        object_schema(PROJECT, ("project_root",)),
        object_schema(
            {"ok": BOOLEAN, "formal_evidence_status": STRING, "diagnosis": JSON_OBJECT},
            ("ok", "formal_evidence_status", "diagnosis"),
        ),
        read_only=True,
        open_world=False,
    ),
    tool_definition(
        "cgkn_test_generated",
        "Test the generated project",
        "Run the supported test profile inside CGKN's recorded generated-project directory. Arbitrary commands are not accepted. Requires RUN_PROJECT_TESTS.",
        object_schema(
            {
                **PROJECT,
                "confirmation": {"const": TEST_CONFIRMATION},
                "timeout": {"type": "integer", "minimum": 10, "maximum": 3600, "default": 600},
            },
            ("project_root", "confirmation"),
        ),
        object_schema(
            {"ok": BOOLEAN, "project_dir": STRING, "profile": STRING, "argv": STRING_ARRAY, "returncode": INTEGER, "stdout": STRING, "stderr": STRING},
            ("ok", "project_dir", "profile", "argv", "returncode", "stdout", "stderr"),
        ),
        read_only=False,
        open_world=False,
    ),
    tool_definition(
        "cgkn_status",
        "Inspect honest CGKN status",
        "Inspect project-local CGKN artifacts and validation state, including the latest compact failure diagnosis, without treating workflow completion as formal evidence PASS.",
        object_schema(PROJECT, ("project_root",)),
        object_schema(
            {
                "ok": BOOLEAN,
                "initialized": BOOLEAN,
                "formal_evidence_status": STRING,
                "note": STRING,
                "artifacts": JSON_OBJECT,
                "diagnosis": JSON_OBJECT,
            },
            ("ok", "initialized", "formal_evidence_status", "note", "artifacts", "diagnosis"),
        ),
        read_only=True,
        open_world=False,
    ),
]
TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}


class CGKNPluginServer:
    def __init__(self, cgkn_root: pathlib.Path) -> None:
        self.cgkn_root = cgkn_root.expanduser().resolve()
        if not (self.cgkn_root / "scripts" / "run_local_pipeline.py").is_file():
            raise RuntimeError(f"Not a compatible CGKN checkout: {self.cgkn_root}")
        source = self.cgkn_root / "tools" / "cgkn-agent-kit" / "src"
        sys.path.insert(0, str(source))
        sys.path.insert(0, str(self.cgkn_root / "src"))
        sys.path.insert(0, str(self.cgkn_root))
        scripts = self.cgkn_root / "scripts"
        sys.path.insert(0, str(scripts))
        from cgkn_agent_kit import core
        import check_connectivity

        self.core = core
        self.connectivity = check_connectivity
        spec = importlib.util.spec_from_file_location(
            "cgkn_codex_capability_supervisor",
            scripts / "codex_capability_supervisor.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load CGKN capability supervisor")
        self.supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.supervisor)
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "cgkn_doctor": self.doctor,
            "cgkn_conversation": self.conversation,
            "cgkn_init": self.initialize,
            "cgkn_prepare": self.prepare,
            "cgkn_seal_brief": self.seal_brief,
            "cgkn_plan_generation": self.plan_generation,
            "cgkn_probe_provider": self.probe_provider,
            "cgkn_generate": self.generate,
            "cgkn_surrogate_status": self.surrogate_status,
            "cgkn_submit_surrogate_response": self.submit_surrogate_response,
            "cgkn_diagnose_failure": self.diagnose_failure,
            "cgkn_test_generated": self.test_generated,
            "cgkn_status": self.status,
        }

    def conversation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from cgkn.application.conversation import (
            CONVERSATION_COMPONENT_SPEC, ConversationExecutor, ConversationService,
        )
        from cgkn.execution import BlockExecutionRequest, TaskContext
        from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, completion_client_from_environment

        project = self._project(arguments["project_root"])
        relative = str(arguments.get("knowledge_path") or ".cgkn/project_knowledge_pack.json")
        knowledge_path = (project / relative).resolve()
        try:
            knowledge_path.relative_to(project)
        except ValueError as exc:
            raise ToolError("knowledge_path must stay within project_root") from exc
        if not knowledge_path.is_file():
            raise ToolError(f"Knowledge pack does not exist: {knowledge_path}")
        provider_mode = str(arguments.get("provider_mode") or "auto")
        client = None
        config = None
        run_id = f"conversation-{uuid.uuid4().hex[:12]}"
        if provider_mode == "auto":
            try:
                client = completion_client_from_environment()
                routing = CGKNModelRouting.load(self.cgkn_root / "config" / "provider_profiles" / "gateway_model_routing.json")
                config = routing.worker
                if isinstance(client, GatewayCompletionClient):
                    client = client.bind_run(run_id, "conversation", budget_purpose="BENCHMARK")
            except Exception:
                client = None
                config = None
        service = ConversationService(client, config)
        executor = ConversationExecutor(service)
        request = BlockExecutionRequest(
            project.name or "conversation", run_id, "attempt-1", "conversation.answer",
            CONVERSATION_COMPONENT_SPEC.ref, executor.descriptor.executor_ref,
            TaskContext("Answer one read-only evidence-grounded Conversation query."),
            input_values={"request": {
                "query": arguments["query"],
                "thread_context_id": arguments.get("thread_context_id", ""),
                "retrieval_constraints": arguments.get("retrieval_constraints", {}),
                "knowledge_path": str(knowledge_path),
                "provider_enabled": provider_mode == "auto",
            }},
            timeout_seconds=float((config.timeout_seconds if config else 45) + 30),
            declared_effects=("provider.optional",),
            metadata={"read_only": True},
        )
        result = executor.execute(request)
        if not result.succeeded:
            raise ToolError(result.error.message if result.error else "Conversation execution failed")
        response = result.as_dict()["outputs"]["response"]
        return {"ok": response["status"] != "INVALID_REQUEST", "response": response, "component_ref": CONVERSATION_COMPONENT_SPEC.ref}

    @staticmethod
    def _project(value: Any) -> pathlib.Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("project_root must be a non-empty local path")
        path = pathlib.Path(value).expanduser().resolve()
        if not path.is_dir():
            raise ToolError(f"Project directory does not exist: {path}")
        return path

    @staticmethod
    def _check_arguments(name: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be an object")
        schema = TOOL_BY_NAME[name]["inputSchema"]
        CGKNPluginServer._validate_schema(arguments, schema, "arguments")
        CGKNPluginServer._reject_secrets(arguments)
        return arguments

    @staticmethod
    def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
        if "const" in schema and value != schema["const"]:
            raise ToolError(f"{path} must equal {schema['const']}")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolError(f"{path} is not one of the supported values")
        expected = schema.get("type")
        valid_type = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
        }.get(expected, True)
        if not valid_type:
            raise ToolError(f"{path} must be {expected}")
        if expected == "object":
            properties = schema.get("properties", {})
            extras = sorted(set(value) - set(properties)) if schema.get("additionalProperties") is False else []
            missing = sorted(set(schema.get("required", [])) - set(value))
            if extras:
                raise ToolError(f"Unsupported {path} fields: " + ", ".join(extras))
            if missing:
                raise ToolError(f"Missing required {path} fields: " + ", ".join(missing))
            for key, nested in value.items():
                if key in properties:
                    CGKNPluginServer._validate_schema(nested, properties[key], f"{path}.{key}")
        elif expected == "array":
            if "maxItems" in schema and len(value) > int(schema["maxItems"]):
                raise ToolError(f"{path} has too many items")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, nested in enumerate(value):
                    CGKNPluginServer._validate_schema(nested, item_schema, f"{path}[{index}]")
        elif expected == "string":
            if len(value) < int(schema.get("minLength", 0)):
                raise ToolError(f"{path} is too short")
            if "maxLength" in schema and len(value) > int(schema["maxLength"]):
                raise ToolError(f"{path} is too long")
        elif expected == "integer":
            if "minimum" in schema and value < int(schema["minimum"]):
                raise ToolError(f"{path} is below the minimum")
            if "maximum" in schema and value > int(schema["maximum"]):
                raise ToolError(f"{path} exceeds the maximum")

    @staticmethod
    def _reject_secrets(value: Any, key: str = "") -> None:
        if key and SECRET_KEY.search(key):
            raise ToolError(f"Secret-like tool argument is prohibited: {key}")
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                CGKNPluginServer._reject_secrets(nested, str(nested_key))
        elif isinstance(value, list):
            for nested in value:
                CGKNPluginServer._reject_secrets(nested)
        elif isinstance(value, str) and SECRET_VALUE.search(value):
            raise ToolError("Secret-like content is prohibited in CGKN tool arguments")

    def _sanitize(self, value: Any, key: str = "") -> Any:
        if key and SECRET_KEY.search(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): self._sanitize(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str):
            return self.core.redact(value)
        return value

    def _loaded(self, project: pathlib.Path) -> tuple[pathlib.Path, dict[str, Any], pathlib.Path, pathlib.Path]:
        root, config, cgkn_root = self.core.load_project(project)
        artifact_dir = (root / str(config["artifact_dir"])).resolve()
        return root, config, cgkn_root, artifact_dir

    def _validated_brief(self, project: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path, pathlib.Path]:
        _, _, cgkn_root, artifact_dir = self._loaded(project)
        brief_path = artifact_dir / "codex_capability_brief.json"
        brief = self.core.read_json(brief_path)
        errors = self.supervisor.validate_capability_brief(brief)
        if errors:
            raise ToolError("Capability brief is invalid: " + "; ".join(errors))
        if brief.get("workflow_state") != "ready":
            raise ToolError(f"Capability brief is not ready: {brief.get('workflow_state', 'unknown')}")
        return brief, brief_path, cgkn_root

    def _matching_resume_run_dir(self, project: pathlib.Path, goal: str) -> pathlib.Path | None:
        _, _, cgkn_root, artifact_dir = self._loaded(project)
        result_path = artifact_dir / "generation_result.json"
        if result_path.is_file():
            try:
                result = self.core.read_json(result_path)
            except self.core.AgentKitError:
                result = {}
            if (
                str(result.get("status", "")).upper() in {"WAITING_SURROGATE_RESPONSE", "WAITING_REQUIREMENT_REPLAN"}
                and str(result.get("goal", "")).strip() == goal
                and str(result.get("run_dir", "")).strip()
            ):
                selected = pathlib.Path(str(result["run_dir"])).resolve()
                if selected.is_dir():
                    return selected
        run_dir = (artifact_dir / "runs").resolve()
        pending_path = run_dir / "artifacts" / "pending_repair_plan.json"
        if not pending_path.is_file():
            return None
        try:
            pending = self.core.read_json(pending_path)
        except self.core.AgentKitError:
            return None
        if (
            pending.get("status") == "pending"
            and pending.get("stage") in {"component_file_generation", "provider_semantic_repair"}
            and str(pending.get("raw_user_goal", "")).strip() == goal
        ):
            return run_dir
        return None

    @staticmethod
    def _result_identity(path: pathlib.Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _bounded_text(value: Any, limit: int = 600) -> str:
        text = " ".join(str(value or "").split())
        return text[:limit]

    def _read_optional_json(self, path: pathlib.Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = self.core.read_json(path)
        except self.core.AgentKitError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_jsonl_tail(path: pathlib.Path) -> tuple[list[dict[str, Any]], bool]:
        if not path.is_file():
            return [], False
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                truncated = size > MAX_DIAGNOSTIC_LOG_BYTES
                if truncated:
                    handle.seek(size - MAX_DIAGNOSTIC_LOG_BYTES)
                raw = handle.read(MAX_DIAGNOSTIC_LOG_BYTES)
        except OSError:
            return [], False
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if truncated and lines:
            lines = lines[1:]
        events: list[dict[str, Any]] = []
        for line in lines[-MAX_DIAGNOSTIC_EVENTS:]:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events, truncated or len(lines) > MAX_DIAGNOSTIC_EVENTS

    @staticmethod
    def _text_items(value: Any) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _resume_identity_complete(pending: dict[str, Any]) -> bool:
        identity = (
            pending.get("resume_identity", {})
            if isinstance(pending.get("resume_identity", {}), dict)
            else {}
        )
        required = {
            "component_id",
            "component_contract_sha256",
            "component_spec_sha256",
            "file_manifest_sha256",
            "leaf_work_graph_sha256",
            "target_file",
            "target_manifest_entry_sha256",
        }
        return required.issubset(identity) and all(
            str(identity.get(key, "")).strip() for key in required
        )

    @staticmethod
    def _failure_category(summary: str, error_type: str = "") -> str:
        lowered = f"{error_type} {summary}".lower()
        if any(marker in lowered for marker in ("usage limit", "insufficient_quota", "quota")):
            return "provider_usage_limit"
        if any(marker in lowered for marker in ("invalid_api_key", "incorrect api key", "http 401", "authentication")):
            return "provider_authentication"
        if any(
            marker in lowered
            for marker in (
                "http 502",
                "http 503",
                "http 504",
                "timed out",
                "timeout",
                "transport_error",
                "remotedisconnected",
                "remote end closed connection",
                "connection reset",
                "connection aborted",
                "connection closed",
                "sslerror",
            )
        ):
            return "provider_transport"
        if any(marker in lowered for marker in ("non-json response", "unterminated string", "json decode", "parse")):
            return "provider_response_parse"
        if any(
            marker in lowered
            for marker in (
                "contract mismatch",
                "implementation depth",
                "missing expected",
                "placeholder",
                "syntax",
                "validation",
            )
        ):
            return "provider_output_contract"
        if "local model" in lowered or "ollama" in lowered:
            return "local_model_failure"
        if "checkpoint" in lowered or "spec hash" in lowered or "spec_hash" in lowered:
            return "checkpoint_identity_drift"
        if any(marker in lowered for marker in ("permission denied", "not found", "environment", "executable")):
            return "environment_failure"
        return "generation_internal_failure"

    def _failure_diagnosis(self, project: pathlib.Path) -> dict[str, Any]:
        config_path = project / self.core.CONFIG_PATH
        if not config_path.is_file():
            return {
                "has_failure": False,
                "observed_generation_status": "NOT_EVALUATED",
                "primary_failure": None,
                "contributing_failures": [],
                "secondary_effects": [],
                "resume": {"available": False, "safe": False, "reason": "project_not_initialized"},
                "counts": {},
                "recommended_next_action": "Initialize CGKN before diagnosing generation.",
                "sources": [],
            }

        _, _, _, artifact_dir = self._loaded(project)
        result_path = artifact_dir / "generation_result.json"
        run_dir = artifact_dir / "runs"
        phase_log_path = run_dir / "provider_phase_log.jsonl"
        pending_path = run_dir / "artifacts" / "pending_repair_plan.json"
        result = self._read_optional_json(result_path)
        pending = self._read_optional_json(pending_path)
        job_path = self.core.generation_job_path(artifact_dir)
        job_status = (
            self.core.generation_job_status(artifact_dir)
            if job_path.is_file()
            else {"state": "NOT_STARTED"}
        )
        job_state = str(job_status.get("state", "") or "").upper()
        external_wait = job_state in {"WAITING_SURROGATE_RESPONSE", "WAITING_REQUIREMENT_REPLAN"}
        surrogate_report: dict[str, Any] = {}
        if external_wait and str(job_status.get("run_dir", "") or "").strip():
            try:
                surrogate_report = self.core.surrogate_status(
                    project,
                    run_dir=pathlib.Path(str(job_status["run_dir"])),
                )
            except (self.core.AgentKitError, OSError, TypeError, ValueError):
                surrogate_report = {}
        submitted_unconsumed = [
            item
            for item in surrogate_report.get("requests", [])
            if isinstance(item, dict)
            and bool(item.get("responded"))
            and not bool(item.get("consumed"))
        ]
        events, log_truncated = self._read_jsonl_tail(phase_log_path)
        observed_status = str(result.get("status", "NOT_EVALUATED") or "NOT_EVALUATED").upper()
        has_failure = observed_status not in {"PASS", "PASS_WITH_LIMITS", "NOT_EVALUATED"}

        leaf_failures = [event for event in events if event.get("event") == "component_leaf_attempt_failed"]
        completed_leaves = [event for event in events if event.get("event") == "component_leaf_completed"]
        transport_events = [
            event
            for event in events
            if event.get("event") == "pipeline_fallback"
            and any(marker in str(event.get("reason", "")).lower() for marker in ("transport", "http_502", "http_503", "http_504", "timeout"))
        ]
        local_attempts = [event for event in events if event.get("event") == "local_model_provider_attempt"]
        parse_failures = [
            event
            for event in leaf_failures
            if self._failure_category(str(event.get("error_summary", "")), str(event.get("error_type", "")))
            == "provider_response_parse"
        ]

        semantic_review = result.get("provider_semantic_review", {})
        semantic_issues = self._text_items(semantic_review.get("issues") if isinstance(semantic_review, dict) else None)
        primary_issue = semantic_issues[0] if semantic_issues else ""
        component = ""
        target_file = ""
        issue_match = re.search(
            r"component\s+(?P<component>[^\s:]+)\s+generation failed:.*?for\s+[^:]+:(?P<target>[^:]+):\s*(?P<summary>.+)$",
            primary_issue,
            flags=re.IGNORECASE,
        )
        if issue_match:
            component = issue_match.group("component")
            target_file = issue_match.group("target")
            primary_summary = issue_match.group("summary")
        else:
            primary_summary = primary_issue

        matching_leaf = next(
            (
                event
                for event in reversed(leaf_failures)
                if not target_file or str(event.get("target_file", "")) == target_file
            ),
            None,
        )
        if matching_leaf:
            component = str(matching_leaf.get("component", component))
            target_file = str(matching_leaf.get("target_file", target_file))
            primary_summary = str(matching_leaf.get("error_summary", primary_summary))
            primary_error_type = str(matching_leaf.get("error_type", ""))
            primary_stage = str(matching_leaf.get("stage", ""))
        else:
            primary_error_type = ""
            primary_stage = ""
        if has_failure and not primary_summary:
            primary_summary = str(result.get("reason", "generation failed"))

        primary_failure: dict[str, Any] | None = None
        if has_failure:
            primary_failure = {
                "category": self._failure_category(primary_summary, primary_error_type),
                "summary": self._bounded_text(primary_summary),
                "stage": primary_stage,
                "component": component,
                "target_file": target_file,
                "error_type": primary_error_type,
                "source_artifact": str(phase_log_path if matching_leaf else result_path),
            }

        contributing: list[dict[str, Any]] = []
        if transport_events:
            contributing.append(
                {
                    "category": "provider_transport",
                    "count": len(transport_events),
                    "summary": "Provider transport failed and the reviewed fallback was attempted.",
                }
            )
        local_targets = {str(event.get("target_file", "")) for event in local_attempts}
        local_rejections = [event for event in leaf_failures if str(event.get("target_file", "")) in local_targets]
        if local_rejections:
            contributing.append(
                {
                    "category": "local_model_output_contract",
                    "count": len(local_rejections),
                    "summary": "Local fallback returned output that later failed the same leaf contract.",
                }
            )
        if parse_failures and (not primary_failure or primary_failure["category"] != "provider_response_parse"):
            contributing.append(
                {
                    "category": "provider_response_parse",
                    "count": len(parse_failures),
                    "summary": "At least one Provider response could not be parsed as the required JSON output.",
                }
            )

        hashes_by_component: dict[str, set[str]] = {}
        for event in events:
            if event.get("event") != "component_leaf_cache_scanned":
                continue
            current_component = str(event.get("component", ""))
            spec_hash = str(event.get("spec_hash", ""))
            if current_component and spec_hash:
                hashes_by_component.setdefault(current_component, set()).add(spec_hash)
        identity_bound_pending = self._resume_identity_complete(pending)
        drift_components = sorted(
            name
            for name, values in hashes_by_component.items()
            if len(values) > 1
            and not (
                identity_bound_pending
                and name
                == str(
                    (pending.get("resume_identity", {}) or {}).get(
                        "component_id", pending.get("component", "")
                    )
                )
            )
        )
        if drift_components:
            contributing.append(
                {
                    "category": "checkpoint_identity_drift",
                    "count": len(drift_components),
                    "components": drift_components[:12],
                    "summary": "Saved component plan identity changed within the recorded run.",
                }
            )

        secondary_effects: list[dict[str, Any]] = []
        fatal_blockers = self._text_items(result.get("fatal_fact_blockers"))
        for blocker in fatal_blockers:
            if blocker.lower().startswith("canonical project plan files missing"):
                missing_text = blocker.split(":", 1)[1] if ":" in blocker else ""
                missing_count = len([item for item in missing_text.split(",") if item.strip()])
                secondary_effects.append(
                    {
                        "category": "missing_required_artifacts",
                        "count": missing_count,
                        "summary": "Required project files are absent because generation stopped before materialization.",
                    }
                )
            else:
                secondary_effects.append(
                    {"category": "downstream_blocker", "summary": self._bounded_text(blocker)}
                )
        generated_dir = artifact_dir / "generated-project"
        if has_failure and not generated_dir.is_dir():
            secondary_effects.append(
                {
                    "category": "candidate_not_materialized",
                    "summary": "No complete generated project candidate was materialized.",
                }
            )
        delivery_manifest = generated_dir / "delivery_manifest.json"
        if has_failure and not delivery_manifest.is_file():
            secondary_effects.append(
                {
                    "category": "delivery_not_reached",
                    "summary": "Packaging and delivery evidence were not reached.",
                }
            )

        pending_goal = str(pending.get("raw_user_goal", "")).strip()
        result_goal = str(result.get("goal", "")).strip()
        response_ready = external_wait and bool(submitted_unconsumed)
        resume_available = response_ready or bool(
            pending.get("status") == "pending"
            and pending.get("stage") in {"component_file_generation", "provider_semantic_repair"}
            and (not result_goal or pending_goal == result_goal)
        )
        resume_safe = response_ready or (
            resume_available and (identity_bound_pending or not drift_components)
        )
        if response_ready:
            resume_reason = "submitted_unconsumed_surrogate_response"
        elif external_wait:
            resume_reason = "awaiting_identity_bound_surrogate_response"
        elif resume_available and identity_bound_pending:
            resume_reason = "matching_identity_bound_pending_plan"
        elif drift_components:
            resume_reason = "checkpoint_identity_drift"
        elif resume_available:
            resume_reason = "matching_pending_repair_plan"
        elif pending and pending_goal and result_goal and pending_goal != result_goal:
            resume_reason = "goal_mismatch"
        else:
            resume_reason = "no_matching_pending_repair_plan"
        resume = {
            "available": resume_available,
            "safe": resume_safe,
            "reason": resume_reason,
            "run_dir": (
                str(job_status.get("run_dir", "") or "")
                if response_ready
                else str(run_dir) if resume_available else ""
            ),
        }

        provider_unavailable = bool(
            primary_failure
            and primary_failure["category"]
            in {
                "provider_authentication",
                "provider_transport",
                "provider_usage_limit",
            }
        )
        if response_ready:
            action = "Resume the same production run; its identity-bound surrogate response is submitted and not yet consumed."
        elif external_wait:
            action = "Submit the identity-bound pending surrogate response, then resume the same production run."
        elif not has_failure:
            action = "No blocked generation failure is recorded."
        elif provider_unavailable and resume_safe:
            action = "Resolve Provider authentication or account availability, then resume the matching safe pending plan through the reviewed Provider route."
        elif provider_unavailable and drift_components:
            action = "Resolve Provider authentication or account availability; this checkpoint is unsafe because its plan identity changed, so start a fresh reviewed generation run."
        elif provider_unavailable:
            action = "Resolve Provider authentication or account availability before starting another reviewed generation run."
        elif resume_safe:
            action = "Repair the identified target through the reviewed Provider route and resume the matching pending plan."
        elif drift_components:
            action = "Start a fresh reviewed generation run because the saved plan identity changed; do not auto-resume this checkpoint."
        else:
            action = "Repair the primary failure through the reviewed Provider route before starting a new bounded run."

        sources = [str(path) for path in (result_path, phase_log_path, pending_path, job_path) if path.exists()]
        sources.extend(
            str(item.get("response_path", "") or item.get("request_path", ""))
            for item in submitted_unconsumed
            if str(item.get("response_path", "") or item.get("request_path", "")).strip()
        )
        return self._sanitize(
            {
                "has_failure": has_failure,
                "observed_generation_status": observed_status,
                "primary_failure": primary_failure,
                "contributing_failures": contributing[:8],
                "secondary_effects": secondary_effects[:8],
                "resume": resume,
                "external_wait": {
                    "active": external_wait,
                    "state": job_state if external_wait else "",
                    "submitted_unconsumed_responses": len(submitted_unconsumed),
                    "waiting_for": str(job_status.get("waiting_for", "") or ""),
                },
                "counts": {
                    "observed_events": len(events),
                    "leaf_failures": len(leaf_failures),
                    "completed_leaves": len(completed_leaves),
                    "provider_transport_failures": len(transport_events),
                    "local_model_attempts": len(local_attempts),
                    "provider_response_parse_failures": len(parse_failures),
                },
                "log_truncated": log_truncated,
                "recommended_next_action": action,
                "sources": sources,
            }
        )

    def doctor(self, args: dict[str, Any]) -> dict[str, Any]:
        report = self.core.doctor(self._project(args["project_root"]))
        report["plugin_mcp_ready"] = bool(report.get("provider_mainline_available") and not report.get("secrets_stored"))
        report["nested_codex_required"] = False
        return {"ok": True, "report": self._sanitize(report)}

    def initialize(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        config = self.core.initialize_project(project, self.cgkn_root, force=bool(args.get("force", False)))
        return {
            "ok": True,
            "config_path": str(project / self.core.CONFIG_PATH),
            "config": self._sanitize(config),
        }

    def prepare(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        goal = str(args["goal"]).strip()
        gap = str(args["gap"]).strip()
        if not goal or len(goal) > 2000 or not gap or len(gap) > 1600:
            raise ToolError("goal or gap is empty or exceeds the bounded request limit")
        category = str(args.get("category", "planning_gap"))
        if category not in CATEGORIES:
            raise ToolError(f"Unsupported capability-gap category: {category}")
        request_path = self.core.prepare_request(project, goal=goal, gap=gap, category=category)
        request = self.core.read_json(request_path)
        return {"ok": True, "request_path": str(request_path), "request": self._sanitize(request)}

    def seal_brief(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        draft = args["draft"]
        if not isinstance(draft, dict) or len(json.dumps(draft, ensure_ascii=False)) > 16000:
            raise ToolError("draft must be a bounded JSON object")
        _, _, _, artifact_dir = self._loaded(project)
        request_path = artifact_dir / "codex_request.json"
        if not request_path.is_file():
            raise ToolError("No prepared request exists; call cgkn_prepare first")
        draft_path = self.core.write_json(artifact_dir / "codex_draft.json", draft)
        brief_path = self.core.seal_draft(project, request_path, draft_path)
        brief = self.core.read_json(brief_path)
        errors = self.supervisor.validate_capability_brief(brief)
        if errors:
            raise ToolError("Sealed capability brief failed validation: " + "; ".join(errors))
        return {"ok": True, "brief_path": str(brief_path), "brief": self._sanitize(brief)}

    def plan_generation(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        goal = str(args["goal"]).strip()
        brief, brief_path, _ = self._validated_brief(project)
        argv = self.core.generation_command(
            project,
            goal=goal,
            brief_path=brief_path,
            model=str(args.get("model", "gpt-4.1")),
            allow_network=bool(args.get("allow_network", False)),
            resume_run_dir=self._matching_resume_run_dir(project, goal),
            provider_mode=(str(args["provider_mode"]) if "provider_mode" in args else None),
            usage_beta=bool(args.get("usage_beta", False)),
            replay_dir=pathlib.Path(str(args["replay_dir"])) if str(args.get("replay_dir", "")).strip() else None,
        )
        clean_argv = [self.core.redact(str(item)) for item in argv]
        return {
            "ok": True,
            "executed": False,
            "argv": clean_argv,
            "brief_sha256": str(brief["brief_sha256"]),
            "secrets_in_argv": any(SECRET_VALUE.search(item) for item in clean_argv),
        }

    def generate(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("confirmation") != GENERATION_CONFIRMATION:
            raise ToolError(f"Generation requires confirmation={GENERATION_CONFIRMATION}")
        provider_mode = self.core.resolve_provider_mode(
            str(args["provider_mode"]) if "provider_mode" in args else None,
            usage_beta=bool(args.get("usage_beta", False)),
        )
        if provider_mode == "live":
            credentials = self.connectivity._resolve_api_credentials()
            if not str(credentials.get("api_key", "")).strip():
                raise ToolError("CGKN provider credential is not available from the configured credential sources")
        project = self._project(args["project_root"])
        goal = str(args["goal"]).strip()
        _, brief_path, cgkn_root = self._validated_brief(project)
        _, _, _, artifact_dir = self._loaded(project)
        argv = self.core.generation_command(
            project,
            goal=goal,
            brief_path=brief_path,
            model=str(args.get("model", "gpt-4.1")),
            allow_network=bool(args.get("allow_network", False)),
            resume_run_dir=self._matching_resume_run_dir(project, goal),
            provider_mode=provider_mode,
            usage_beta=bool(args.get("usage_beta", False)),
            replay_dir=pathlib.Path(str(args["replay_dir"])) if str(args.get("replay_dir", "")).strip() else None,
        )
        try:
            job = self.core.start_generation_job(
                argv,
                cgkn_root=cgkn_root,
                artifact_dir=artifact_dir,
            )
        except self.core.AgentKitError as exc:
            raise ToolError(str(exc)) from exc
        clean_job = self._sanitize(job)
        return {
            "ok": str(job.get("state", "")).upper() not in {"FAILED", "CANCELLED"},
            "started": bool(job.get("started")),
            "deduplicated": bool(job.get("deduplicated")),
            "run_id": str(job.get("run_id", "")),
            "state": str(job.get("state", "UNKNOWN")),
            "job": clean_job,
        }

    def surrogate_status(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        run_value = str(args.get("run_dir", "") or "").strip()
        return {
            "ok": True,
            "status": self._sanitize(
                self.core.surrogate_status(
                    project,
                    run_dir=pathlib.Path(run_value) if run_value else None,
                )
            ),
        }

    def submit_surrogate_response(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        run_value = str(args.get("run_dir", "") or "").strip()
        receipt = self.core.submit_surrogate_response(
            project,
            run_dir=pathlib.Path(run_value) if run_value else None,
            job_id=str(args["job_id"]),
            attempt_id=str(args["attempt_id"]),
            payload=str(args["payload"]),
            surrogate_identity=str(args.get("surrogate_identity", "codex")),
        )
        return {"ok": bool(receipt.get("accepted")), "receipt": self._sanitize(receipt)}

    def diagnose_failure(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        return {
            "ok": True,
            "formal_evidence_status": "NOT_EVALUATED",
            "diagnosis": self._failure_diagnosis(project),
        }

    @staticmethod
    def _probe_diagnostic(result: dict[str, Any]) -> str:
        if bool(result.get("ok")):
            return "connected"
        if not bool(result.get("configured")):
            return "missing_credential"
        error = str(result.get("error", ""))
        lowered = error.lower()
        if "http 401" in lowered or "invalid_api_key" in lowered or "incorrect api key" in lowered:
            return "authentication_failed"
        if "key usage limit exceeded" in lowered or "insufficient_quota" in lowered:
            return "usage_limit"
        if "http 403" in lowered:
            return "permission_denied"
        if "model" in lowered and ("http 404" in lowered or "not found" in lowered or "does not exist" in lowered):
            return "model_unavailable"
        if "retryable=true" in lowered or any(
            marker in lowered
            for marker in ("ssl", "timeout", "timed out", "urlerror", "connection", "http 502", "http 503", "http 504")
        ):
            return "transport_failure"
        return "provider_error"

    @staticmethod
    def _credential_source_label(source: Any) -> str:
        value = str(source or "")
        if value == "CGKN_OPENAI_API_KEY_OVERRIDE":
            return "process_override"
        if value == "QWEN_API_KEY(User)":
            return "shared_qwen_user"
        if value == "QWEN_API_KEY(Machine)":
            return "shared_qwen_machine"
        if value == "QWEN_API_KEY":
            return "shared_qwen_process"
        if value == "CGKN_OPENAI_API_KEY(User)":
            return "canonical_user"
        if value == "CGKN_OPENAI_API_KEY(Machine)":
            return "canonical_machine"
        if value == "CGKN_OPENAI_API_KEY":
            return "canonical_process"
        if value:
            return "compatibility_environment"
        return ""

    def probe_provider(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("confirmation") != PROVIDER_PROBE_CONFIRMATION:
            raise ToolError(f"Provider probe requires confirmation={PROVIDER_PROBE_CONFIRMATION}")
        self._project(args["project_root"])
        model = str(args.get("model", "gpt-4.1-mini")).strip()
        result = self.connectivity.check_api(True, int(args.get("timeout", 20)), model)
        error = str(result.get("error", ""))
        conflict_sources = [
            self._credential_source_label(source)
            for source in result.get("api_key_conflict_sources", [])
        ]
        probe = {
            "diagnostic": self._probe_diagnostic(result),
            "configured": bool(result.get("configured")),
            "source_scope": self._credential_source_label(result.get("api_key_source", "")),
            "conflict_scopes": list(dict.fromkeys(source for source in conflict_sources if source)),
            "base_url": str(result.get("base_url", "")),
            "base_url_source": str(result.get("base_url_source", "")),
            "endpoint": str(result.get("endpoint", "")),
            "endpoint_mode": str(result.get("endpoint_mode", "")),
            "model": model,
            "provider_name": "qwen" if model.lower().startswith("qwen") else "openai_compatible",
            "credential_present": bool(result.get("configured")),
            "credential_env_name": str(result.get("api_key_source", "")).split("(", 1)[0],
            "base_url_host": self.connectivity._base_url_domain(str(result.get("base_url", ""))),
            "free_tier_only": False,
            "attempts": int(result.get("attempts", 0) or 0),
            "tls_verify": bool(result.get("tls_verify", True)),
            "request_id": str(result.get("request_id", "")),
            "provider_error_type": self.connectivity._provider_error_type(error) if error else "",
            "detail": error or str(result.get("status", "")),
        }
        return {
            "ok": bool(result.get("ok")),
            "probe": self._sanitize(probe),
            "formal_evidence_status": "NOT_EVALUATED",
        }

    def _recorded_generated_dir(self, project: pathlib.Path) -> pathlib.Path:
        _, _, _, artifact_dir = self._loaded(project)
        generated = (artifact_dir / "generated-project").resolve()
        if not generated.is_relative_to(artifact_dir) or not generated.is_dir():
            raise ToolError("No recorded generated-project directory exists")
        return generated

    @staticmethod
    def _test_profile(generated: pathlib.Path) -> tuple[str, list[str]]:
        has_python = any((generated / name).is_file() for name in ("pyproject.toml", "pytest.ini", "setup.cfg")) or (generated / "tests").is_dir()
        if has_python:
            return "python-pytest", [sys.executable, "-m", "pytest", "-q"]
        package = generated / "package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ToolError(f"Cannot read generated package.json: {exc}") from exc
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
                npm = shutil.which("npm.cmd") or shutil.which("npm")
                if not npm:
                    raise ToolError("npm is required by the generated project's test profile")
                argv = [npm, "test"]
                if "jest" in scripts["test"].lower():
                    argv.extend(["--", "--runInBand"])
                return "node-npm-test", argv
        raise ToolError("No supported generated-project test profile was detected")

    def test_generated(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("confirmation") != TEST_CONFIRMATION:
            raise ToolError(f"Generated-project tests require confirmation={TEST_CONFIRMATION}")
        project = self._project(args["project_root"])
        generated = self._recorded_generated_dir(project)
        profile, argv = self._test_profile(generated)
        child_env = {
            key: value
            for key, value in os.environ.items()
            if not re.search(r"(?i)(API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", key)
        }
        child_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        try:
            completed = subprocess.run(
                argv,
                cwd=generated,
                env=child_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=int(args.get("timeout", 600)),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(f"Generated-project tests could not complete: {exc}") from exc
        return {
            "ok": completed.returncode == 0,
            "project_dir": str(generated),
            "profile": profile,
            "argv": [self.core.redact(str(item)) for item in argv],
            "returncode": completed.returncode,
            "stdout": self.core.redact(completed.stdout)[-12000:],
            "stderr": self.core.redact(completed.stderr)[-12000:],
        }

    def status(self, args: dict[str, Any]) -> dict[str, Any]:
        project = self._project(args["project_root"])
        config_path = project / self.core.CONFIG_PATH
        note = "Workflow and artifact state cannot authorize formal delivery evidence."
        if not config_path.is_file():
            return {
                "ok": True,
                "initialized": False,
                "formal_evidence_status": "NOT_EVALUATED",
                "note": note,
                "artifacts": {"config": {"exists": False, "path": str(config_path)}},
                "diagnosis": self._failure_diagnosis(project),
            }
        _, _, _, artifact_dir = self._loaded(project)
        artifacts: dict[str, Any] = {}
        names = {
            "config": config_path,
            "request": artifact_dir / "codex_request.json",
            "brief": artifact_dir / "codex_capability_brief.json",
            "generation_result": artifact_dir / "generation_result.json",
            "generated_project": artifact_dir / "generated-project",
            "delivery_manifest": artifact_dir / "generated-project" / "delivery_manifest.json",
        }
        for name, path in names.items():
            summary: dict[str, Any] = {"exists": path.exists(), "path": str(path)}
            if path.is_file() and path.suffix == ".json":
                try:
                    data = self.core.read_json(path)
                    summary.update({
                        "kind": data.get("kind"),
                        "status": data.get("status"),
                        "workflow_state": data.get("workflow_state"),
                    })
                    if name == "brief":
                        errors = self.supervisor.validate_capability_brief(data)
                        summary["valid"] = not errors
                        summary["errors"] = errors
                        summary["brief_sha256"] = data.get("brief_sha256")
                except self.core.AgentKitError as exc:
                    summary["read_error"] = str(exc)
            artifacts[name] = self._sanitize(summary)
        artifacts["generation_job"] = self._sanitize(
            self.core.generation_job_status(artifact_dir)
        )
        plugin_root = pathlib.Path(__file__).resolve().parents[1]
        plugin_manifest = self.core.read_json(plugin_root / ".codex-plugin" / "plugin.json")
        repository_revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.cgkn_root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False,
        )
        artifacts["runtime_identity"] = {
            "repository_root": str(self.cgkn_root),
            "repository_revision": repository_revision.stdout.strip() if repository_revision.returncode == 0 else None,
            "plugin_root": str(plugin_root),
            "plugin_version": plugin_manifest.get("version"),
            "server_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        }
        return {
            "ok": True,
            "initialized": True,
            "formal_evidence_status": "NOT_EVALUATED",
            "note": note,
            "artifacts": artifacts,
            "diagnosis": self._failure_diagnosis(project),
        }

    def call_tool(self, name: str, arguments: Any) -> dict[str, Any]:
        if name not in self.handlers:
            raise ToolError(f"Unknown CGKN tool: {name}")
        clean = self._check_arguments(name, arguments)
        return self.handlers[name](clean)


def text_result(value: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
        "structuredContent": value,
    }
    if is_error:
        result["isError"] = True
    return result


def response(request_id: Any, *, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return message


def handle(server: CGKNPluginServer, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return response(None, error={"code": -32600, "message": "Invalid Request"})
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        params = message.get("params", {})
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        return response(
            request_id,
            result={
                "protocolVersion": requested or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "cgkn", "version": SERVER_VERSION},
                "instructions": "Use CGKN tools for bounded Agent guidance and the reviewed Provider route. Never pass secrets as arguments.",
            },
        )
    if method == "ping":
        return response(request_id, result={})
    if method == "tools/list":
        return response(request_id, result={"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params", {})
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return response(request_id, error={"code": -32602, "message": "Invalid tool call parameters"})
        try:
            value = server.call_tool(params["name"], params.get("arguments", {}))
            return response(request_id, result=text_result(value))
        except (ToolError, server.core.AgentKitError, ValueError) as exc:
            safe = server.core.redact(str(exc))[:4000]
            if isinstance(exc, ToolError):
                category = "invalid_request_or_precondition"
            elif isinstance(exc, ValueError):
                category = "invalid_internal_data"
            else:
                category = "cgkn_execution_error"
            failure = {
                "category": category,
                "summary": safe,
                "retryable": False,
                "source": "mcp_tool",
            }
            return response(
                request_id,
                result=text_result({"ok": False, "error": safe, "failure": failure}, is_error=True),
            )
        except Exception as exc:  # Preserve server availability without exposing internals.
            safe = server.core.redact(f"CGKN tool failed: {exc}")[:2000]
            failure = {
                "category": "internal_tool_error",
                "summary": safe,
                "retryable": False,
                "source": "mcp_server",
            }
            return response(
                request_id,
                result=text_result({"ok": False, "error": safe, "failure": failure}, is_error=True),
            )
    return response(request_id, error={"code": -32601, "message": "Method not found"})


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description="Serve CGKN tools over MCP stdio.")
    parser.add_argument("--cgkn-root", default=os.environ.get("CGKN_ROOT", ""))
    args = parser.parse_args()
    if not args.cgkn_root:
        print("CGKN root is required", file=sys.stderr)
        return 2
    try:
        server = CGKNPluginServer(pathlib.Path(args.cgkn_root))
    except Exception as exc:
        print(f"Cannot start CGKN MCP server: {exc}", file=sys.stderr)
        return 2
    for line in sys.stdin:
        try:
            message = json.loads(line)
            outgoing = handle(server, message)
        except ValueError as exc:
            outgoing = response(None, error={"code": -32700, "message": f"Parse error: {exc}"})
        if outgoing is not None:
            sys.stdout.write(json.dumps(outgoing, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
