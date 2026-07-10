#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_connectivity
import candidate_materializer
import candidate_sanitizer
import check_test_environment
import compose_local_pipeline
import discovery_selection_lane
import final_delivery_truth
import formal_model_contract
import local_intent_router
import local_usage_planner
import local_model_router
import long_context_state
import market_research_agent
import post_build_repair
import post_build_finalize
import online_input_agent
import requirement_blueprint
import requirement_decision_lane

from post_build_repair import (
    apply_deterministic_post_build_repair,
    classify_post_build_failures,
    compile_post_build_repair_plan,
    default_post_build_targets,
    existing_candidate_files,
    extract_post_build_target_files,
    missing_vitest_error,
    post_build_failure_log,
    post_build_repair_attempts,
    provider_post_build_file_repair,
    repair_windows_esm_path_import_file,
    repair_missing_vitest_with_node_runner,
    rewrite_windows_esm_dynamic_imports,
    run_candidate_post_build_repair_loop,
    validate_post_build_repair_files,
    windows_esm_path_import_error,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
def generated_root() -> pathlib.Path:
    override = str(os.environ.get("CGNK_TEST_GENERATED_ROOT", "")).strip()
    return pathlib.Path(override).resolve() if override else (ROOT / "generated").resolve()


DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "local-pipeline-execution"
DEFAULT_GENERATED_DIR = generated_root() / "cgnk_generated_project"
DEFAULT_CANDIDATE_DIR = generated_root() / "cgnk_generated_project_candidate"
DEFAULT_RESULT_PATH = ROOT / "examples" / "test_results" / "local_pipeline_execution_result.json"

FORBIDDEN_PROJECT_NAMES = {"template", "fallback", "generic"}
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov", ".pdf", ".zip"}
GENERATION_POLICY = {
    "project_files_authority": "api_provider_for_delivery_simulator_for_preflight_only",
    "local_allowed_scope": [
        "pipeline_composition",
        "requirement_blueprint",
        "online_input_discovery",
        "feature_market_research",
        "example_input_download",
        "example_based_test_artifact_generation",
        "audit_artifact_writing",
        "local_simulator_execution",
    ],
    "local_forbidden_scope": [
        "template_project_generation",
        "fallback_project_generation",
        "static_project_shell",
        "synthetic_project_code",
        "post_generation_architecture_rewrite",
    ],
    "failure_rule": "Simulator mode is allowed to stop at BLOCKED. Telegram delivery mode must use API/provider or fail fast with a clear configuration error.",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def append_phase_log(path_value: Any, phase: str, status: str, message: str, artifacts_written: list[str] | None = None, started_at: float | None = None) -> None:
    raw = str(path_value or "").strip()
    if not raw:
        return
    path = pathlib.Path(raw)
    elapsed = 0.0 if started_at is None else round(time.time() - started_at, 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": now(),
                    "phase": phase,
                    "status": status,
                    "message": message,
                    "artifacts_written": artifacts_written or [],
                    "elapsed_seconds": elapsed,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def append_provider_event_log(path_value: Any, event: dict[str, Any]) -> None:
    raw = str(path_value or "").strip()
    if not raw:
        return
    safe = {key: value for key, value in event.items() if key not in {"api_key", "prompt", "messages"}}
    safe.setdefault("ts", now())
    path = pathlib.Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(safe, ensure_ascii=False, default=str) + "\n")


def last_provider_request_event(path_value: Any) -> dict[str, Any]:
    raw = str(path_value or "").strip()
    if not raw:
        return {}
    path = pathlib.Path(raw)
    if not path.exists():
        return {}
    last: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}
    for line in lines:
        try:
            event = json.loads(line)
        except Exception:
            continue
        if isinstance(event, dict) and event.get("event") == "provider_request":
            last = event
    return last


def run_dir_from_phase_log(path_value: Any) -> pathlib.Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = pathlib.Path(raw)
    if path.name == "provider_phase_log.jsonl":
        return path.parent
    return path.parent


def record_model_call_from_phase_log(
    phase_log_path: pathlib.Path | str | None,
    *,
    stage: str,
    provider: str,
    model: str,
    requested: bool,
    executed: bool,
    status: str,
    input_value: Any = "",
    output_value: Any = "",
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> pathlib.Path | None:
    run_dir = run_dir_from_phase_log(phase_log_path)
    if run_dir is None:
        return None
    return formal_model_contract.append_model_call(
        run_dir,
        stage=stage,
        provider=provider,
        model=model,
        requested=requested,
        executed=executed,
        status=status,
        used_in_formal_chain=formal_model_contract.normalize_stage(stage) in formal_model_contract.FORMAL_CHAIN_STAGES,
        input_value=input_value,
        output_value=output_value,
        error=error,
        metadata=metadata,
    )


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_read_text(path: pathlib.Path) -> str:
    try:
        return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", str(text or "").strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:80] or "provider-generated-project"


def plan_goal(plan_doc: dict[str, Any]) -> str:
    for path in (
        ("goal", "payload", "text"),
        ("pipeline_plan", "payload", "goal"),
        ("pipeline_plan", "payload", "requirement"),
        ("project_understanding", "payload", "summary", "goal"),
    ):
        current: Any = plan_doc
        for key in path:
            if not isinstance(current, dict):
                current = ""
                break
            current = current.get(key)
        if isinstance(current, str) and current.strip():
            return current.strip()
    return "Generate a custom project from the supplied requirement."


def frozen_user_intent(plan_doc: dict[str, Any], fallback_goal: str) -> dict[str, Any]:
    if not isinstance(plan_doc, dict):
        return local_intent_router.classify_project_type(fallback_goal)
    intent = plan_doc.get("customer_intent")
    if isinstance(intent, dict) and str(intent.get("raw_user_message", "")).strip():
        return intent
    original = str(plan_doc.get("original_requirement", "")).strip()
    if original:
        return local_intent_router.classify_project_type(original)
    return local_intent_router.classify_project_type(fallback_goal)


def internal_context_from_plan(plan_doc: dict[str, Any]) -> str:
    if not isinstance(plan_doc, dict):
        return ""
    return str(plan_doc.get("internal_context_prompt") or "").strip()


def generation_deadline(args: argparse.Namespace) -> float:
    raw = getattr(args, "generation_deadline", 0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if value > time.time():
        return value
    return time.time() + max(30, int(getattr(args, "timeout", 360)))


class ProgressDeadline:
    def __init__(
        self,
        deadline: float,
        *,
        extension_seconds: int,
        phase_log_path: pathlib.Path | str | None = None,
    ) -> None:
        self.deadline = float(deadline)
        self.extension_seconds = max(30, int(extension_seconds))
        self.phase_log_path = phase_log_path
        self.progress_events: list[dict[str, Any]] = []

    def mark_progress(self, phase: str, message: str, artifacts_written: list[str] | None = None) -> None:
        previous_deadline = self.deadline
        self.deadline = max(self.deadline, time.time() + self.extension_seconds)
        extended_by = round(self.deadline - previous_deadline, 3)
        event = {
            "phase": phase,
            "message": message,
            "deadline_extended_by_seconds": max(0.0, extended_by),
            "new_deadline_epoch": round(self.deadline, 3),
        }
        if artifacts_written:
            event["artifacts_written"] = artifacts_written[:20]
        self.progress_events.append(event)
        if extended_by > 0:
            append_phase_log(
                self.phase_log_path,
                phase,
                "progress_deadline_extended",
                message,
                artifacts_written,
            )


def deadline_timestamp(deadline: float | ProgressDeadline) -> float:
    if isinstance(deadline, ProgressDeadline):
        return deadline.deadline
    return float(deadline)


def mark_generation_progress(deadline: float | ProgressDeadline | None, phase: str, message: str, artifacts_written: list[str] | None = None) -> None:
    if isinstance(deadline, ProgressDeadline):
        deadline.mark_progress(phase, message, artifacts_written)


def remaining_timeout(deadline: float | ProgressDeadline, requested: int, *, floor: int = 1, cap: int | None = None) -> int:
    remaining = int(deadline_timestamp(deadline) - time.time())
    if remaining < floor:
        raise TimeoutError("generation deadline exhausted before starting next step")
    value = min(int(requested), remaining)
    if cap is not None:
        value = min(value, int(cap))
    return max(floor, value)


def require_api_generation(args: argparse.Namespace) -> None:
    if bool(getattr(args, "use_api", False)) and not (
        bool(getattr(args, "allow_network", False)) and bool(getattr(args, "allow_provider", False))
    ):
        raise RuntimeError("Provider/API escalation requires allow_network and allow_provider.")


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on", "enabled"}:
        return True
    if value in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class ProviderModelRoutingPolicy:
    small_model: str = "gpt-5.4-nano"
    large_model: str = "gpt-5.5"
    small_payload_chars: int = 20000
    large_payload_chars: int = 40000
    enable_model_routing: bool = True
    upgrade_on_transport_error: bool = True
    downgrade_for_connectivity: bool = True


class ProviderModelRoute(dict):
    @property
    def selected_model(self) -> str:
        return str(self.get("selected_model", ""))

    @property
    def model_routing_reason(self) -> str:
        return str(self.get("model_routing_reason", ""))

    @property
    def requested_model(self) -> str:
        return str(self.get("requested_model", ""))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.selected_model == other
        return dict.__eq__(self, other)


def provider_model_routing_policy_from_args(args: argparse.Namespace | None = None) -> ProviderModelRoutingPolicy:
    policy = ProviderModelRoutingPolicy(
        small_model=str(os.environ.get("CGNK_PROVIDER_SMALL_MODEL") or ProviderModelRoutingPolicy.small_model),
        large_model=str(os.environ.get("CGNK_PROVIDER_LARGE_MODEL") or ProviderModelRoutingPolicy.large_model),
        small_payload_chars=env_int("CGNK_PROVIDER_SMALL_PAYLOAD_CHARS", ProviderModelRoutingPolicy.small_payload_chars),
        large_payload_chars=env_int("CGNK_PROVIDER_LARGE_PAYLOAD_CHARS", ProviderModelRoutingPolicy.large_payload_chars),
        enable_model_routing=env_bool("CGNK_PROVIDER_MODEL_ROUTING", ProviderModelRoutingPolicy.enable_model_routing),
    )
    if args is not None:
        small_model = str(getattr(args, "small_model", "") or "").strip()
        large_model = str(getattr(args, "large_model", "") or "").strip()
        if small_model:
            policy.small_model = small_model
        if large_model:
            policy.large_model = large_model
        if bool(getattr(args, "disable_model_routing", False)):
            policy.enable_model_routing = False
    return policy


def provider_transport_model_route_reason(last_error: Any) -> str:
    text = str(last_error or "")
    lowered = text.lower()
    if "sslv3_alert_bad_record_mac" in lowered or "bad record mac" in lowered:
        return "transport_error_ssl_bad_record_mac"
    if "tlsv1_alert_protocol_version" in lowered or "protocol version" in lowered:
        return "transport_error_tls_protocol_version"
    if "http 503" in lowered:
        return "transport_error_http_503"
    if "http 504" in lowered:
        return "transport_error_http_504"
    if "http 522" in lowered:
        return "transport_error_http_522"
    if "timeout" in lowered:
        return "transport_error_timeout"
    error_type = check_connectivity._provider_error_type(text)
    if error_type == "PROVIDER_RETRYABLE_HTTP":
        return "transport_error_retryable_http"
    if error_type == "PROVIDER_TRANSPORT_UNSTABLE":
        return "transport_error_unstable"
    return ""


def choose_provider_model(
    stage: str,
    prompt_chars: int,
    requested_model: str,
    routing_policy: ProviderModelRoutingPolicy | None,
    last_error: Any = None,
) -> dict[str, Any]:
    policy = routing_policy or ProviderModelRoutingPolicy()
    requested = str(requested_model or "").strip() or policy.small_model
    if not policy.enable_model_routing:
        return ProviderModelRoute({"selected_model": requested, "model_routing_reason": "routing_disabled", "requested_model": requested})

    transport_reason = provider_transport_model_route_reason(last_error)
    if transport_reason and policy.upgrade_on_transport_error:
        return ProviderModelRoute({"selected_model": policy.large_model, "model_routing_reason": transport_reason, "requested_model": requested})

    normalized_stage = str(stage or "").strip().lower()
    if policy.downgrade_for_connectivity and normalized_stage in {"connectivity", "ping", "lightweight_summary", "lightweight summary"}:
        return ProviderModelRoute({"selected_model": policy.small_model, "model_routing_reason": "connectivity_small_model", "requested_model": requested})

    if int(prompt_chars or 0) <= int(policy.small_payload_chars):
        return ProviderModelRoute({"selected_model": policy.small_model, "model_routing_reason": "small_payload", "requested_model": requested})

    heavy_stages = {"component_generation", "semantic_repair", "file_repair", "semantic_review", "provider_semantic_review"}
    if int(prompt_chars or 0) > int(policy.large_payload_chars) or normalized_stage in heavy_stages:
        return ProviderModelRoute({"selected_model": policy.large_model, "model_routing_reason": "large_payload", "requested_model": requested})

    return ProviderModelRoute({"selected_model": requested, "model_routing_reason": "requested_model_default", "requested_model": requested})


def parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    candidates = [raw]
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        candidates.append(raw[first : last + 1])
    for candidate in candidates:
        try:
            doc = json.loads(candidate)
        except Exception:
            continue
        if isinstance(doc, dict):
            return doc
    raise RuntimeError("provider returned non-json project payload")


def provider_plan_doc(plan_doc: dict[str, Any]) -> dict[str, Any]:
    doc = json.loads(json.dumps(plan_doc, ensure_ascii=False)) if isinstance(plan_doc, dict) else {}
    doc.pop("internal_context_prompt", None)
    return doc


def provider_internal_context(text: str) -> dict[str, Any]:
    if not str(text or "").strip():
        return {}
    return {
        "role": "supporting_cgnk_context_only",
        "warning": "This context describes internal planning artifacts. It is not the product to build and must not override raw_user_goal.",
        "text": str(text)[:12000],
    }


def provider_blueprint_context(blueprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "supporting_requirement_analysis_only",
        "warning": "This blueprint is an internal analysis artifact. Build the raw_user_goal product, not a blueprint generator.",
        "doc": blueprint,
    }


def provider_text(
    messages: list[dict[str, str]],
    model: str,
    timeout: int,
    *,
    max_attempts: int = 6,
    stage: str = "provider_text",
    component: str = "",
    max_tokens: int = 12000,
    payload_mode: str = "full",
    target_file: str = "",
    phase_log_path: pathlib.Path | str | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
    last_error: Any = None,
) -> str:
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key")
    root = str(creds.get("base_url", "")).rstrip("/")
    endpoint = check_connectivity._openai_compatible_endpoint(root, model=model)
    prompt_chars = sum(len(str(message.get("content", ""))) for message in messages if isinstance(message, dict))
    last_error_text = str(last_error or "")
    selected_model = str(model or "").strip()
    final_status = "failed"
    for attempt in range(max(1, max_attempts)):
        route = choose_provider_model(stage, prompt_chars, model, routing_policy, last_error=last_error_text)
        selected_model = str(route.get("selected_model") or model)
        if attempt > 0 and selected_model != str(model or "").strip():
            append_provider_event_log(
                phase_log_path,
                {
                    "event": "provider_retry_model_route",
                    "stage": stage,
                    "component": component,
                    "target_file": target_file,
                    "previous_model": model,
                    "next_model": selected_model,
                    "reason": route.get("model_routing_reason", ""),
                },
            )
        append_provider_event_log(
            phase_log_path,
            {
                "event": "provider_request",
                "stage": stage,
                "component": component,
                "target_file": target_file,
                "prompt_chars": prompt_chars,
                "requested_model": route.get("requested_model") or model,
                "selected_model": selected_model,
                "model_routing_reason": route.get("model_routing_reason", ""),
                "max_tokens": max_tokens,
                "payload_mode": payload_mode,
            },
        )
        payload = check_connectivity._build_openai_compatible_payload(
            root,
            {"model": selected_model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens},
        )
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            final_status = "ok"
            break
        last_error_text = error
        final_status = "timeout" if check_connectivity._error_is_retryable(error) else "failed"
        if not check_connectivity._error_is_retryable(error):
            break
        time.sleep(min(20.0, 2.0 * (attempt + 1)))
    else:
        record_model_call_from_phase_log(
            phase_log_path,
            stage=stage,
            provider="api_agent",
            model=selected_model,
            requested=True,
            executed=True,
            status=final_status,
            input_value=messages,
            error=last_error_text or "provider_api_request_failed",
            metadata={"component": component, "payload_mode": payload_mode, "target_file": target_file},
        )
        raise RuntimeError(f"provider_api_request_failed: {last_error_text}" if last_error_text else "provider_api_request_failed")
    if doc is None:
        record_model_call_from_phase_log(
            phase_log_path,
            stage=stage,
            provider="api_agent",
            model=selected_model,
            requested=True,
            executed=True,
            status=final_status,
            input_value=messages,
            error=last_error_text or "provider_api_request_failed",
            metadata={"component": component, "payload_mode": payload_mode, "target_file": target_file},
        )
        raise RuntimeError(f"provider_api_request_failed: {last_error_text}")
    text = check_connectivity._extract_text(doc)
    if not text:
        record_model_call_from_phase_log(
            phase_log_path,
            stage=stage,
            provider="api_agent",
            model=selected_model,
            requested=True,
            executed=True,
            status="failed",
            input_value=messages,
            output_value=doc,
            error="provider returned empty project payload",
            metadata={"component": component, "payload_mode": payload_mode, "target_file": target_file},
        )
        raise RuntimeError("provider returned empty project payload")
    record_model_call_from_phase_log(
        phase_log_path,
        stage=stage,
        provider="api_agent",
        model=selected_model,
        requested=True,
        executed=True,
        status="ok",
        input_value=messages,
        output_value=text,
        metadata={"component": component, "payload_mode": payload_mode, "target_file": target_file},
    )
    return text


def provider_generate_project(
    goal: str,
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    repair_errors: list[str],
    model: str,
    timeout: int,
    *,
    internal_context: str = "",
    phase_log_path: pathlib.Path | str | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    system = """You are the sole project-file generator for CGNK.
Return a complete, runnable project as strict JSON. Do not return markdown outside JSON.

Hard rules:
- Do not use a generic template, starter shell, placeholder app, or fallback project.
- Generate project-specific files that directly implement the user's request.
- Include realistic README and TEST_PLAN.
- Include a browser preview surface when it is appropriate for the project, and include non-browser runnable entry points when that better fits the request.
- If media preview is part of the request, include UI elements and sample data that visibly show preview frames/timeline/output status when appropriate.
- Use provided online_input_examples as realistic test fixtures in the generated project files, documentation, tests, and preview UI when relevant. The manifest includes project_type, input_spec, routing attempts, and source metadata. Do not claim example-based testing unless the examples are represented in project files.
- Use provided market_research findings to choose libraries, models, APIs, and product features. For each core feature, prefer the recommended candidate unless you explicitly justify a better choice in project docs/code comments.
- Include a concise market-research summary in the generated project documentation so the user can see why the selected stack/features were chosen.
- If a backend/CLI/library is appropriate, include runnable source files and tests.
- Do not emit empty files, .gitkeep files, .keep files, or directory placeholder files. Every file in files[] must contain meaningful runnable code, configuration, tests, or documentation.
- Dependency choices must match the provided runtime_context. Prefer unpinned or current compatible package ranges over stale exact pins. Avoid heavy native dependencies such as opencv-python unless the requested project truly needs them and the version supports the current Python runtime.
- For browser workflow demos, the external usage agent records the actual UI flow. The generated project should still create its requested artifacts, but it does not need a fragile in-app video encoder just to prove the UI was used.
- Web app entry points must be automation-friendly: bind to 127.0.0.1 on the planned port, and disable debug reloaders or child-process reloaders (for example Flask app.run(..., debug=False, use_reloader=False)).
- Do not put binary files such as PNG, JPG, MP4, PDF, ZIP into files[]. JSON text cannot carry those project files directly. If binary artifacts are needed, generate source code/scripts that create them or reference the runtime online_input_examples/example_outputs artifacts.
- If the user asks for self-generated images, do not satisfy it with copied examples, solid-color placeholders, or text-only placeholder art. Implement a real local generation path appropriate for a first version: procedural layered art, local model/API integration, or another concrete image-generation algorithm that creates distinct background and character outputs from user input.
- For VN/background/character art requests, simple circles/rectangles, plain gradients, text labels, or clip-art placeholders are not enough. The generated project must create visually meaningful assets with multiple scene/character-specific layers and recognizable composition, or integrate a real image-generation API/local model path.
- If online_input_examples.image_generation_models contains candidates and the user asks for serious AI-generated background/character art, prefer an online AI image generation provider/model integration over procedural drawing. The project should expose provider configuration, run a capability check, generate images from prompts, and clearly report if required image credentials are missing.
- Do not present procedural PIL/canvas drawing as the ideal solution for serious VN立绘/背景 image generation. Procedural drawing may be an explicit offline fallback only, and the UI/report must label it as fallback.
- If the user asks for an agent/demo workflow, include a local UI or CLI flow that an agent can actually run end-to-end: input data, trigger generation, observe outputs, and verify generated artifacts.
- If validation_errors are provided, regenerate the full project and fix every error. Do not explain; return only corrected JSON.
- Treat project_goal_constraints as mandatory acceptance criteria. If they conflict with a component label, satisfy the user-facing product behavior first.
- Requirement Decision First: you are not free to invent a different product. Implement selected_requirement, obey mvp_scope, respect non_goals, and satisfy acceptance_contract.
- Do not reintroduce rejected requirements. Do not shrink the project into a static preview, README-only delivery, or fake PASS.
- If complexity_project_contract is present, treat it as a hard downstream contract. First generate product_brief.md, technical_plan.md, interaction_design.md, and acceptance_matrix.md; each must cite complexity_project_contract.json.
- If complexity_project_contract is present, include orchestrator.py, stages.py, CLI, GUI, shared GUI/CLI core, required pipeline stages, required stage artifacts with required fields, honest degraded mode, README.md, TEST_REPORT.md, DELIVERY_NOTES.md, run_dir evidence hooks, screenshot-ready GUI, and final bundle instructions.
- If complexity_project_contract is present, do not use forbidden_shortcuts such as single_file_demo, static_preview_only, readme_only_delivery, fake_pass, separate GUI/CLI logic, or artifact-name-only schemas.
- Do not turn the requested app into a meta-tool that only collects requirements, emits blueprints, or documents how it could be built.
- Keep file paths relative. Never use absolute paths. Never write outside the project root.

JSON shape:
{
  "project_type": "specific short type",
  "summary": "what was built",
  "files": [
    {"path": "README.md", "content": "..."},
    {"path": "TEST_PLAN.md", "content": "..."}
  ],
  "manual_checks": ["specific checks"],
  "self_test": {"status": "pass", "checks": ["..."]},
  "quality_gate": {"status": "pass", "reasons": ["..."]}
}
"""
    user = {
        "raw_user_goal": goal,
        "goal": goal,
        "selected_requirement": plan_doc.get("selected_requirement", {}),
        "mvp_scope": plan_doc.get("mvp_scope", {}),
        "non_goals": plan_doc.get("non_goals", {}),
        "acceptance_contract": plan_doc.get("acceptance_contract", {}),
        "selected_project_direction": plan_doc.get("selected_project_direction", {}),
        "complexity_project_contract": plan_doc.get("complexity_project_contract", {}),
        "internal_context": provider_internal_context(internal_context),
        "pipeline_plan": provider_plan_doc(plan_doc),
        "requirement_blueprint": provider_blueprint_context(blueprint),
        "online_input_examples": online_inputs,
        "market_research": market_research,
        "runtime_context": {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": sys.platform,
            "ffmpeg_available": bool(shutil.which("ffmpeg")),
        },
        "validation_errors_to_repair": repair_errors,
        "generation_policy": GENERATION_POLICY,
    }
    raw = provider_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
        ],
        model,
        timeout,
        stage="project_generation",
        max_tokens=12000,
        payload_mode="full_project",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    return parse_json_object(raw)


def infer_project_goal_constraints(goal: str) -> list[str]:
    lowered = str(goal or "").lower()
    constraints: list[str] = []
    if any(token in lowered for token in ("vn", "visual novel", "视觉小说")):
        constraints.extend(
            [
                "Build the actual VN project assistant application, not a requirement-blueprint generator or project-planning tool.",
                "Include a story timeline editor surface with nodes/branches/sequence data that a user can edit and inspect.",
            ]
        )
    if any(token in lowered for token in ("时间线", "timeline", "流程图", "节点", "flowchart")):
        constraints.append("Implement timeline/flowchart editing behavior in UI or CLI, with persisted story nodes and branch relationships.")
    if any(token in lowered for token in ("背景", "立绘", "character", "sprite", "background")):
        constraints.append("Provide separate background-generation and character/sprite-generation entry points; do not merge them into one generic image form.")
    if any(token in lowered for token in ("stable diffusion", "本地部署", "local model", "本地的图片生成模型")):
        constraints.append("Expose local image model configuration/capability checks and clear missing-model reporting; do not silently fall back as if the local model succeeded.")
    if any(token in lowered for token in ("图片", "image", "生成图", "ai 生成", "ai生成")):
        constraints.append("Generated image outputs must be previewable and exportable as local PNG/JPG artifacts, with tests or runtime examples exercising the flow.")
    if not constraints:
        constraints.append("Implement the user's requested product as a runnable first version, not just documentation, analysis, or requirement artifacts.")
    return constraints


def semantic_review_system_prompt() -> str:
    return """You are the API quality reviewer for CGNK provider-generated projects.
Review the generated project semantically. Do not use a fixed checklist tied to one project type.

Judge whether the project is specific to the user's goal, coherent, runnable enough for a first version, and honestly uses the provided online input examples where relevant.
Project type, required files, implementation strategy, and test expectations are decided by you from the requirement and input manifest.

Pass/fail rules:
- Return "fail" if any core capability explicitly requested by the user is missing.
- Return "fail" if market_research contains relevant recommended candidates for core features and the project ignores them without a clear justification.
- Return "fail" if the generated documentation does not summarize the market research or explain why the selected approach is suitable.
- Return "fail" if the project says the user must manually replace placeholders before the first useful run.
- Return "fail" if preview/output artifacts are claimed as already present but only described, not generated by code, tests, runtime example_outputs, or post-build finalize.
- Do not fail solely because binary screenshots/videos/zip files are absent from provider JSON files. Provider JSON cannot carry binaries. Pass this part when the project includes honest runnable capture/package commands or scripts and does not claim missing binaries are already generated; post-build finalize is responsible for executing those commands or writing video_blocked.
- Return "fail" if tests are superficial and do not exercise the important generated behavior for this project type.
- Return "fail" if generated files use misleading placeholder names such as binary assets renamed to .txt instead of producing or referencing real artifacts.
- Return "fail" if the user asked for image generation and the project only copies or re-labels an online example image as a generated image. Online examples can be references or previews, but generated backgrounds/characters must be produced by code, a model/API integration, or a clearly implemented local image generation pipeline.
- Return "fail" if requirements or setup instructions pin stale dependencies likely incompatible with the provided runtime_context.
- Return "pass" only when remaining issues are minor follow-up improvements, not blockers for the requested first version.

Return strict JSON only:
{
  "status": "pass" or "fail",
  "issues": ["actionable issue 1"],
  "strengths": ["specific strength 1"],
  "expected_artifacts": ["what the project should produce"],
  "review_summary": "brief explanation"
}
"""


def semantic_review_full_payload(
    goal: str,
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    generation: dict[str, Any],
    files: list[dict[str, str]],
    *,
    internal_context: str = "",
) -> dict[str, Any]:
    compact_files = []
    for item in files:
        content = str(item.get("content", ""))
        compact_files.append({"path": item.get("path"), "content": content[:6000], "truncated": len(content) > 6000})
    return {
        "raw_user_goal": goal,
        "goal": goal,
        "internal_context": provider_internal_context(internal_context),
        "pipeline_plan": provider_plan_doc(plan_doc),
        "requirement_blueprint": provider_blueprint_context(blueprint),
        "online_input_examples": online_inputs,
        "market_research": market_research,
        "runtime_context": {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": sys.platform,
            "ffmpeg_available": bool(shutil.which("ffmpeg")),
        },
        "generation_metadata": {key: value for key, value in generation.items() if key != "files"},
        "files": compact_files,
    }


def semantic_review_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": semantic_review_system_prompt()},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def semantic_review_prompt_chars(payload: dict[str, Any]) -> int:
    return sum(len(str(message.get("content", ""))) for message in semantic_review_messages(payload))


def text_summary(text: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def component_for_file(path: str, component_ids: list[str]) -> str:
    rel = str(path or "").replace("\\", "/").strip()
    owner = legal_owner_for_path(rel, component_ids)
    return owner or "docs"


def files_by_component(files: list[dict[str, str]], component_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {component_id: [] for component_id in component_ids}
    for item in files:
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        component_id = component_for_file(rel, component_ids)
        out.setdefault(component_id, []).append(item)
    return out


def high_risk_component_files(component_id: str, files: list[dict[str, str]], max_files: int) -> list[dict[str, str]]:
    priorities = {
        "foundation": ("package.json", "pyproject.toml", "requirements.txt", "scripts/start", "scripts/build"),
        "backend": ("server", "backend", "api", "contracts", "data"),
        "frontend": ("index.html", "app/index.html", "src/app", "src/main", "frontend"),
        "tests": ("tests/", "TEST_PLAN.md", "TEST_REPORT.md", "scripts/run-tests"),
        "docs": ("README.md", "TEST_REPORT.md", "TEST_PLAN.md", "DELIVERY", "docs/"),
        "media": ("scripts/capture", "scripts/record", "scripts/final", "bundle", "media", "screenshots"),
    }
    tokens = priorities.get(component_id, ())
    scored = []
    for idx, item in enumerate(files):
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        score = 0 if any(token.lower() in rel.lower() for token in tokens) else 10
        scored.append((score, idx, item))
    return [item for _score, _idx, item in sorted(scored)[:max_files]]


def semantic_component_review_payload(
    *,
    goal: str,
    component_id: str,
    component_files: list[dict[str, str]],
    component_pipeline: dict[str, Any],
) -> dict[str, Any]:
    budget = semantic_review_budget_config()
    selected = high_risk_component_files(component_id, component_files, int(budget["max_files_per_component_review"]))
    payload = {
        "raw_user_goal": goal,
        "component": component_id,
        "file_manifest": [str(item.get("path", "")).replace("\\", "/").strip() for item in component_files],
        "file_summaries": [
            {"path": str(item.get("path", "")).replace("\\", "/").strip(), "chars": len(str(item.get("content", ""))), "summary": text_summary(item.get("content", ""), 700)}
            for item in component_files
        ],
        "selected_file_contents": [
            {
                "path": str(item.get("path", "")).replace("\\", "/").strip(),
                "content": str(item.get("content", ""))[: int(budget["max_file_content_chars_per_review"])],
                "truncated": len(str(item.get("content", ""))) > int(budget["max_file_content_chars_per_review"]),
            }
            for item in selected
        ],
        "component_ownership": component_ownership_table().get(component_id, {}),
        "component_contract": next((row for row in component_pipeline.get("components", []) if isinstance(row, dict) and str(row.get("id", "")) == component_id), {}),
        "semantic_review_budget_applied": len(selected) < len(component_files) or any(len(str(item.get("content", ""))) > int(budget["max_file_content_chars_per_review"]) for item in selected),
        "required_output_shape": {
            "component": component_id,
            "verdict": "pass|fail",
            "blockers": [{"kind": "missing_entry_html|frontend_backend_mismatch|placeholder_claim|module_mismatch|broken_runtime|weak_tests|fake_artifact_claim|generic", "severity": "hard|warning", "files": ["path"], "message": "...", "repair_hint": "..."}],
            "summary": "...",
        },
    }
    soft = int(budget["soft_prompt_chars"])
    if len(json.dumps(payload, ensure_ascii=False)) > soft:
        payload["selected_file_contents"] = [
            {**item, "content": str(item.get("content", ""))[:3000], "truncated": True}
            for item in payload["selected_file_contents"][:3]
        ]
    if len(json.dumps(payload, ensure_ascii=False)) > soft:
        payload["selected_file_contents"] = payload["selected_file_contents"][:2]
    if len(json.dumps(payload, ensure_ascii=False)) > soft:
        payload["file_summaries"] = [
            {**item, "summary": str(item.get("summary", ""))[:250]}
            for item in payload["file_summaries"]
        ]
    return payload


def normalize_review_blockers(raw_blockers: Any, *, default_component: str = "") -> list[dict[str, Any]]:
    if not isinstance(raw_blockers, list):
        raw_blockers = [raw_blockers] if str(raw_blockers or "").strip() else []
    out: list[dict[str, Any]] = []
    for item in raw_blockers:
        if isinstance(item, dict):
            blocker = {
                "kind": str(item.get("kind", "generic") or "generic"),
                "severity": str(item.get("severity", "hard") or "hard"),
                "component": str(item.get("component", "") or default_component),
                "files": [str(path).replace("\\", "/").strip() for path in item.get("files", []) if str(path).strip()] if isinstance(item.get("files", []), list) else [],
                "message": str(item.get("message", "") or item.get("summary", "") or item),
                "repair_hint": str(item.get("repair_hint", "") or item.get("hint", "")),
            }
        else:
            blocker = {"kind": "generic", "severity": "hard", "component": default_component, "files": [], "message": str(item), "repair_hint": ""}
        out.append(blocker)
    return out


def provider_semantic_component_review(
    *,
    goal: str,
    component_id: str,
    component_files: list[dict[str, str]],
    component_pipeline: dict[str, Any],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
) -> dict[str, Any]:
    system = """Review one CGNK component. Return strict JSON only with component, verdict, blockers, summary.
Use structured blockers with kind, severity, files, message, and repair_hint. Do not request binary artifacts from provider output."""
    payload = semantic_component_review_payload(goal=goal, component_id=component_id, component_files=component_files, component_pipeline=component_pipeline)
    raw = provider_text(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
        model,
        timeout,
        max_attempts=1,
        stage="semantic_component_review",
        component=component_id,
        max_tokens=3500,
        payload_mode="review_component",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    doc = parse_json_object(raw)
    doc["component"] = str(doc.get("component") or component_id)
    doc["verdict"] = str(doc.get("verdict") or doc.get("status") or "fail").lower()
    doc["blockers"] = normalize_review_blockers(doc.get("blockers", []), default_component=component_id)
    doc["semantic_review_budget_applied"] = bool(payload.get("semantic_review_budget_applied"))
    return doc


def extract_named_file(files: list[dict[str, str]], name: str) -> str:
    for item in files:
        if str(item.get("path", "")).replace("\\", "/").strip() == name:
            return str(item.get("content", ""))
    return ""


def semantic_cross_review_payload(
    *,
    goal: str,
    files: list[dict[str, str]],
    component_reviews: list[dict[str, Any]],
    component_pipeline: dict[str, Any],
) -> dict[str, Any]:
    manifest = [str(item.get("path", "")).replace("\\", "/").strip() for item in files]
    package_json = extract_named_file(files, "package.json")
    docs_claims = "\n".join(text_summary(extract_named_file(files, name), 1200) for name in ("README.md", "TEST_REPORT.md", "TEST_PLAN.md", "DELIVERY_NOTES.md") if extract_named_file(files, name))
    frontend_summary = "\n".join(text_summary(item.get("content", ""), 700) for item in files if str(item.get("path", "")).replace("\\", "/").strip().startswith(("src/", "app/", "frontend/")))[:2500]
    backend_summary = "\n".join(text_summary(item.get("content", ""), 700) for item in files if str(item.get("path", "")).replace("\\", "/").strip().startswith(("server/", "backend/", "api/")))[:2500]
    tests_summary = "\n".join(text_summary(item.get("content", ""), 700) for item in files if str(item.get("path", "")).replace("\\", "/").strip().startswith("tests/") or str(item.get("path", "")).endswith((".test.js", ".test.mjs", "_test.py")))[:2500]
    scripts_summary = "\n".join(f"{item.get('path')}: {text_summary(item.get('content', ''), 500)}" for item in files if str(item.get("path", "")).replace("\\", "/").strip().startswith("scripts/"))[:3000]
    return {
        "raw_user_goal": goal,
        "component_review_summaries": [
            {"component": item.get("component"), "verdict": item.get("verdict"), "summary": item.get("summary", ""), "blockers": item.get("blockers", [])}
            for item in component_reviews
        ],
        "file_manifest": manifest,
        "runtime_contract_summary": {
            "package_json_excerpt": package_json[:3000],
            "entry_candidates": [path for path in manifest if pathlib.PurePosixPath(path).name in {"index.html", "app.py", "main.py", "server.py"} or path.startswith(("server/", "scripts/start"))],
            "component_pipeline": component_pipeline,
        },
        "frontend_api_usage_summary": frontend_summary,
        "backend_api_endpoints_summary": backend_summary,
        "test_command_summary": tests_summary,
        "docs_claims_summary": docs_claims[:3000],
        "media_final_bundle_claims_summary": scripts_summary,
        "semantic_review_budget_applied": True,
        "required_output_shape": {"component": "cross_component", "verdict": "pass|fail", "blockers": [], "integration_failures": [], "repair_targets": []},
    }


def provider_semantic_cross_component_review(
    *,
    goal: str,
    files: list[dict[str, str]],
    component_reviews: list[dict[str, Any]],
    component_pipeline: dict[str, Any],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
) -> dict[str, Any]:
    system = """Review cross-component CGNK runtime contracts. Return strict JSON only.
Check module/script consistency, frontend/backend API alignment, JSON persistence, test coverage, docs claims, media/final bundle honesty, and entrypoint presence."""
    payload = semantic_cross_review_payload(goal=goal, files=files, component_reviews=component_reviews, component_pipeline=component_pipeline)
    raw = provider_text(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
        model,
        timeout,
        max_attempts=1,
        stage="semantic_cross_component_review",
        component="cross_component",
        max_tokens=5000,
        payload_mode="review_cross_component",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    doc = parse_json_object(raw)
    doc["component"] = "cross_component"
    doc["verdict"] = str(doc.get("verdict") or doc.get("status") or "fail").lower()
    blockers = normalize_review_blockers(doc.get("blockers", []), default_component="")
    blockers.extend(normalize_review_blockers(doc.get("integration_failures", []), default_component=""))
    doc["blockers"] = blockers
    return doc


def provider_semantic_final_reducer(
    *,
    component_reviews: list[dict[str, Any]],
    cross_review: dict[str, Any],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
) -> dict[str, Any]:
    system = """Reduce structured semantic review JSON into a final CGNK verdict. Return strict JSON only.
Do not ask for full source code. Use only the supplied review JSON."""
    payload = {
        "component_reviews": component_reviews,
        "cross_component_review": cross_review,
        "required_output_shape": {"verdict": "pass|fail", "blockers": [], "affected_components": [], "affected_files": [], "repair_priority": []},
    }
    raw = provider_text(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
        model,
        timeout,
        max_attempts=1,
        stage="semantic_final_reducer",
        component="semantic_reducer",
        max_tokens=3000,
        payload_mode="review_reducer",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    doc = parse_json_object(raw)
    doc["verdict"] = str(doc.get("verdict") or doc.get("status") or "fail").lower()
    doc["blockers"] = normalize_review_blockers(doc.get("blockers", []), default_component="")
    return doc


def split_semantic_review_pipeline(
    *,
    goal: str,
    component_pipeline: dict[str, Any],
    files: list[dict[str, str]],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
    original_prompt_chars: int,
) -> dict[str, Any]:
    append_provider_event_log(
        phase_log_path,
        {"event": "semantic_review_split_started", "original_prompt_chars": original_prompt_chars, "reason": "prompt_exceeds_hard_limit"},
    )
    component_ids = [str(row.get("id", "")).strip() for row in component_pipeline.get("components", []) if isinstance(row, dict) and str(row.get("id", "")).strip()]
    if not component_ids:
        component_ids = ["foundation", "backend", "frontend", "media", "tests", "docs"]
    grouped = files_by_component(files, component_ids)
    component_reviews = [
        provider_semantic_component_review(
            goal=goal,
            component_id=component_id,
            component_files=grouped.get(component_id, []),
            component_pipeline=component_pipeline,
            model=model,
            timeout=timeout,
            phase_log_path=phase_log_path,
            routing_policy=routing_policy,
        )
        for component_id in component_ids
    ]
    cross_review = provider_semantic_cross_component_review(
        goal=goal,
        files=files,
        component_reviews=component_reviews,
        component_pipeline=component_pipeline,
        model=model,
        timeout=timeout,
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    reducer = provider_semantic_final_reducer(
        component_reviews=component_reviews,
        cross_review=cross_review,
        model=model,
        timeout=timeout,
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    blockers = []
    for review in component_reviews:
        blockers.extend(review.get("blockers", []))
    blockers.extend(cross_review.get("blockers", []))
    blockers.extend(reducer.get("blockers", []))
    affected_components = sorted({str(item.get("component", "")).strip() for item in blockers if str(item.get("component", "")).strip()})
    affected_files = sorted({path for item in blockers for path in item.get("files", []) if str(path).strip()})
    append_provider_event_log(
        phase_log_path,
        {"event": "semantic_review_reduced", "blocker_count": len(blockers), "affected_components": affected_components},
    )
    status = "pass" if str(reducer.get("verdict", "")).lower() == "pass" and not [b for b in blockers if str(b.get("severity", "hard")) == "hard"] else "fail"
    return {
        "status": status,
        "issues": [str(item.get("message", item)) for item in blockers],
        "structured_blockers": blockers,
        "affected_components": affected_components,
        "affected_files": affected_files,
        "repair_priority": reducer.get("repair_priority", affected_components),
        "component_reviews": component_reviews,
        "cross_component_review": cross_review,
        "review_summary": "Split semantic review reduced component and cross-component findings.",
        "semantic_review_budget_applied": True,
    }


def provider_review_project(
    goal: str,
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    generation: dict[str, Any],
    files: list[dict[str, str]],
    model: str,
    timeout: int,
    *,
    internal_context: str = "",
    phase_log_path: pathlib.Path | str | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    payload = semantic_review_full_payload(
        goal,
        plan_doc,
        blueprint,
        online_inputs,
        market_research,
        generation,
        files,
        internal_context=internal_context,
    )
    original_prompt_chars = semantic_review_prompt_chars(payload)
    if original_prompt_chars > int(semantic_review_budget_config()["hard_prompt_chars"]):
        return split_semantic_review_pipeline(
            goal=goal,
            component_pipeline=generation.get("component_pipeline", {}) if isinstance(generation.get("component_pipeline"), dict) else {},
            files=files,
            model=model,
            timeout=timeout,
            phase_log_path=phase_log_path,
            routing_policy=routing_policy,
            original_prompt_chars=original_prompt_chars,
        )
    raw = provider_text(
        semantic_review_messages(payload),
        model,
        timeout,
        max_attempts=1,
        stage="semantic_review",
        max_tokens=12000,
        payload_mode="review_compact_files",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    doc = parse_json_object(raw)
    status = str(doc.get("status", "")).strip().lower()
    if status not in {"pass", "fail"}:
        raise RuntimeError(f"provider review returned invalid status: {status!r}")
    issues = doc.get("issues", [])
    if not isinstance(issues, list):
        doc["issues"] = [str(issues)]
    return doc


def validate_provider_files(doc: dict[str, Any]) -> list[dict[str, str]]:
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("provider project payload missing files[]")
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("provider files[] contains non-object entry")
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        content = item.get("content")
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            raise RuntimeError(f"provider emitted unsafe path: {rel!r}")
        if pathlib.PurePosixPath(rel).name.lower() in {".gitkeep", ".keep"}:
            continue
        if pathlib.PurePosixPath(rel).name.lower() in FORBIDDEN_PROJECT_NAMES:
            raise RuntimeError(f"provider emitted forbidden generic path name: {rel}")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"provider emitted empty file: {rel}")
        suffix = pathlib.PurePosixPath(rel).suffix.lower()
        if suffix in BINARY_EXTENSIONS:
            raise RuntimeError(
                f"provider emitted binary artifact as text file: {rel}. "
                "Generate binary artifacts through runtime/example outputs or provide source files that create them."
            )
        if str(content).lstrip().startswith("<<BINARY"):
            raise RuntimeError(f"provider emitted placeholder binary marker: {rel}")
        seen.add(rel)
        cleaned.append({"path": rel, "content": content})
    if not cleaned:
        raise RuntimeError("provider project payload only contained ignored placeholder files")
    return cleaned


def provider_component_checkpoint_id(component_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(component_id or "").strip())
    return value.strip("._") or "component"


def compact_for_repair_budget(value: Any, max_chars: int) -> Any:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(raw) <= max_chars:
        return value
    if isinstance(value, dict):
        return {
            "summary_only": True,
            "keys": sorted(str(key) for key in value.keys())[:50],
            "truncated_chars": len(raw),
        }
    if isinstance(value, list):
        return {
            "summary_only": True,
            "items": len(value),
            "truncated_chars": len(raw),
        }
    return str(value)[:max_chars]


def apply_repair_prompt_budget(
    payload: dict[str, Any],
    *,
    component_id: str,
    repair_actions: list[dict[str, Any]],
    component_files: list[dict[str, str]],
) -> dict[str, Any]:
    budget = repair_prompt_budget_config()
    target_files = concrete_repair_target_files(repair_actions)
    max_files = budget["max_files_per_repair"]
    relevant_paths = set(target_files[:max_files])
    if not relevant_paths:
        relevant_paths.update(str(item.get("path", "")) for item in component_files[:max_files] if isinstance(item, dict))
    relevant_files: list[dict[str, Any]] = []
    omitted_files: list[str] = []
    for item in component_files:
        path = str(item.get("path", "")).replace("\\", "/").strip()
        if path in relevant_paths and len(relevant_files) < max_files:
            content = str(item.get("content", ""))
            relevant_files.append({"path": path, "content": content[:4000], "truncated": len(content) > 4000})
        elif path:
            omitted_files.append(path)
    payload["repair_scope"] = {
        "mode": "file_level" if target_files else "component_level",
        "component": component_id,
        "target_files": target_files,
        "max_output_files_per_repair": min(budget["max_output_files_per_repair"], max(1, len(target_files) or budget["max_output_files_per_repair"])),
        "relevant_existing_files": relevant_files,
        "omitted_existing_files": omitted_files[:100],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if len(raw) <= budget["max_context_chars_per_repair"]:
        payload["repair_prompt_budget"] = budget
        payload["repair_prompt_budget_applied"] = False
        return payload
    compact_payload = dict(payload)
    per_section = max(1000, budget["max_context_chars_per_repair"] // 6)
    for key in ("pipeline_plan", "requirement_blueprint", "online_input_examples", "market_research"):
        compact_payload[key] = compact_for_repair_budget(compact_payload.get(key), per_section)
    compact_payload["repair_prompt_budget"] = budget
    compact_payload["repair_prompt_budget_applied"] = True
    compact_payload["repair_budget_original_context_chars"] = len(raw)
    return compact_payload


def provider_component_spec_hash(goal: str, component_pipeline: dict[str, Any], component: dict[str, Any]) -> str:
    payload = {
        "goal": goal,
        "component": component,
        "component_pipeline_contract": {
            "merge_policy": component_pipeline.get("merge_policy", {}),
            "component_ids": [str(row.get("id", "")).strip() for row in component_pipeline.get("components", []) if isinstance(row, dict)],
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def provider_component_semantic_review(result: dict[str, Any], files: list[dict[str, str]]) -> dict[str, Any]:
    quality_gate = result.get("quality_gate", {}) if isinstance(result, dict) else {}
    self_test = result.get("self_test", {}) if isinstance(result, dict) else {}
    blockers: list[str] = []
    for label, doc in (("quality_gate", quality_gate), ("self_test", self_test)):
        if isinstance(doc, dict) and str(doc.get("status", "")).strip().lower() == "fail":
            blockers.append(f"{label}_failed")
    if not files:
        blockers.append("no_valid_files")
    return {
        "status": "pass" if not blockers else "fail",
        "reviewer": "local_component_semantic_contract",
        "checks": ["valid_files", "component_quality_gate_not_failed", "component_self_test_not_failed"],
        "blockers": blockers,
    }


def provider_component_error_is_retryable(error_type: str, error_text: str) -> bool:
    if error_type in {"PROVIDER_TRANSPORT_UNSTABLE", "PROVIDER_RETRYABLE_HTTP"}:
        return True
    lowered = str(error_text or "").lower()
    if any(
        marker in lowered
        for marker in (
            "provider project payload missing files[]",
            "provider returned wrong component_id",
            "provider files[] contains non-object",
            "provider emitted empty file",
            "provider emitted unsafe path",
            "provider emitted binary artifact",
            "component semantic review failed",
        )
    ):
        return True
    if "retryable=true" in lowered:
        return True
    return False


def provider_component_checkpoint_paths(checkpoint_dir: pathlib.Path, component_id: str) -> tuple[pathlib.Path, pathlib.Path]:
    safe = provider_component_checkpoint_id(component_id)
    return checkpoint_dir / f"{safe}.json", checkpoint_dir / f"{safe}_files.json"


def remove_provider_component_checkpoints(checkpoint_dir: pathlib.Path | None, component_ids: list[str] | set[str]) -> list[str]:
    if checkpoint_dir is None:
        return []
    removed: list[str] = []
    for component_id in sorted({str(item).strip() for item in component_ids if str(item).strip()}):
        for path in provider_component_checkpoint_paths(checkpoint_dir, component_id):
            if path.exists():
                path.unlink()
                removed.append(str(path))
    return removed


def write_provider_component_checkpoint(
    checkpoint_dir: pathlib.Path | None,
    *,
    component_id: str,
    spec_hash: str,
    status: str,
    raw_output: str,
    parsed_result: dict[str, Any],
    files: list[dict[str, str]],
    semantic_review: dict[str, Any],
    error: str = "",
    provider_error_type: str = "",
) -> None:
    if checkpoint_dir is None:
        return
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path, files_path = provider_component_checkpoint_paths(checkpoint_dir, component_id)
    base_doc = {
        "kind": "ProviderComponentCheckpoint",
        "created_at": now(),
        "component_id": component_id,
        "project_spec_hash": spec_hash,
        "status": status,
        "semantic_review": semantic_review,
        "provider_error_type": provider_error_type,
        "error": error,
        "raw_output": raw_output,
        "parsed_result": parsed_result,
        "file_count": len(files),
        "usage": parsed_result.get("usage", {}) if isinstance(parsed_result, dict) else {},
        "evidence": parsed_result.get("evidence", {}) if isinstance(parsed_result, dict) else {},
    }
    files_doc = {
        "kind": "ProviderComponentFilesCheckpoint",
        "created_at": base_doc["created_at"],
        "component_id": component_id,
        "project_spec_hash": spec_hash,
        "status": status,
        "semantic_review": semantic_review,
        "files": files,
    }
    write_json(checkpoint_path, base_doc)
    write_json(files_path, files_doc)


def write_provider_component_checkpoint_summary(checkpoint_dir: pathlib.Path | None, summary: dict[str, Any]) -> None:
    if checkpoint_dir is None:
        return
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    doc = {"kind": "ProviderComponentCheckpointSummary", "updated_at": now(), **summary}
    write_json(checkpoint_dir / "component_checkpoint_summary.json", doc)


def update_provider_component_checkpoint_summary(checkpoint_dir: pathlib.Path | None, updates: dict[str, Any]) -> None:
    if checkpoint_dir is None:
        return
    path = checkpoint_dir / "component_checkpoint_summary.json"
    if path.exists():
        try:
            doc = load_json(path)
        except Exception:
            doc = {"kind": "ProviderComponentCheckpointSummary"}
    else:
        doc = {"kind": "ProviderComponentCheckpointSummary"}
    doc.update(updates)
    doc["updated_at"] = now()
    write_json(path, doc)


def load_provider_component_checkpoint(
    checkpoint_dir: pathlib.Path | None,
    *,
    component_id: str,
    spec_hash: str,
) -> tuple[dict[str, Any], list[dict[str, str]]] | None:
    if checkpoint_dir is None:
        return None
    checkpoint_path, files_path = provider_component_checkpoint_paths(checkpoint_dir, component_id)
    if not checkpoint_path.exists() or not files_path.exists():
        return None
    try:
        checkpoint = load_json(checkpoint_path)
        files_doc = load_json(files_path)
    except Exception:
        return None
    semantic = checkpoint.get("semantic_review", {}) if isinstance(checkpoint, dict) else {}
    if checkpoint.get("project_spec_hash") != spec_hash or files_doc.get("project_spec_hash") != spec_hash:
        return None
    if str(checkpoint.get("status", "")).lower() != "pass":
        return None
    if str(semantic.get("status", "")).lower() != "pass":
        return None
    parsed = checkpoint.get("parsed_result", {})
    if not isinstance(parsed, dict):
        return None
    try:
        files = validate_provider_files({"files": files_doc.get("files", [])})
    except Exception:
        return None
    return parsed, files


def component_pipeline_from_plan(goal: str, plan_doc: dict[str, Any]) -> dict[str, Any]:
    payload = plan_doc.get("pipeline_plan", {}).get("payload", {}) if isinstance(plan_doc, dict) else {}
    component_pipeline = payload.get("component_pipeline", {})
    if isinstance(component_pipeline, dict) and isinstance(component_pipeline.get("components"), list) and component_pipeline.get("components"):
        return component_pipeline
    return compose_local_pipeline.build_component_pipeline(goal)


COMPONENT_GENERATION_SYSTEM = """You are a component-level project-file generator for CGNK.
Return strict JSON only. Generate only the files owned by the requested component.

Hard rules:
- Do not generate a whole project unless this component explicitly owns every file.
- Do not use generic templates, placeholders, or empty files.
- Respect prior_manifest: do not duplicate an existing path unless your content is byte-identical and necessary.
- Generate component-specific runnable files that integrate with prior components through documented contracts.
- Keep file paths relative. Never use absolute paths. Never write outside the project root.
- Do not emit binary assets as JSON text. Generate source/scripts that create them or reference runtime artifacts.
- Include component-specific checks. If the component is docs, include README/TEST_PLAN updates only when assigned.

JSON shape:
{
  "component_id": "same id as requested",
  "summary": "what this component contributes",
  "files": [
    {"path": "relative/path", "content": "..."}
  ],
  "public_contract": {"exports": ["interfaces, commands, routes, or files other components can rely on"]},
  "manual_checks": ["component-specific checks"],
  "self_test": {"status": "pass", "checks": ["..."]},
  "quality_gate": {"status": "pass", "reasons": ["..."]}
}
"""


def provider_component_payload(
    *,
    goal: str,
    component: dict[str, Any],
    component_pipeline: dict[str, Any],
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    prior_manifest: list[str],
    repair_errors: list[str],
    internal_context: str = "",
    repair_actions: list[dict[str, Any]] | None = None,
    existing_component_files: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload = {
        "raw_user_goal": goal,
        "goal": goal,
        "selected_requirement": plan_doc.get("selected_requirement", {}),
        "mvp_scope": plan_doc.get("mvp_scope", {}),
        "non_goals": plan_doc.get("non_goals", {}),
        "acceptance_contract": plan_doc.get("acceptance_contract", {}),
        "selected_project_direction": plan_doc.get("selected_project_direction", {}),
        "complexity_project_contract": plan_doc.get("complexity_project_contract", {}),
        "component": component,
        "component_ownership": component_ownership_table().get(str(component.get("id", "")).strip(), {}),
        "component_pipeline": component_pipeline,
        "prior_manifest": prior_manifest,
        "internal_context": provider_internal_context(internal_context),
        "pipeline_plan": provider_plan_doc(plan_doc),
        "requirement_blueprint": provider_blueprint_context(blueprint),
        "online_input_examples": online_inputs,
        "market_research": market_research,
        "project_goal_constraints": infer_project_goal_constraints(goal),
        "runtime_context": {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": sys.platform,
            "ffmpeg_available": bool(shutil.which("ffmpeg")),
        },
        "validation_errors_to_repair": repair_errors,
        "generation_policy": GENERATION_POLICY,
    }
    if repair_errors or repair_actions:
        payload = apply_repair_prompt_budget(
            payload,
            component_id=str(component.get("id", "")).strip(),
            repair_actions=repair_actions or [],
            component_files=existing_component_files or [],
        )
    return payload


def provider_component_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": COMPONENT_GENERATION_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def provider_component_prompt_chars(payload: dict[str, Any]) -> int:
    return sum(len(str(message.get("content", ""))) for message in provider_component_messages(payload))


def should_split_component_generation(component_id: str, prompt_chars: int, *, repair_actions: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
    policy = provider_component_prompt_policy()
    if repair_actions:
        return False, ""
    if int(prompt_chars or 0) > int(policy["max_prompt_chars_hard"]):
        return True, "prompt_exceeds_hard_limit"
    if str(component_id).strip() == "frontend" and bool(policy["split_frontend_component"]):
        return True, "frontend_default_split"
    return False, ""


def provider_generate_project_component(
    *,
    goal: str,
    component: dict[str, Any],
    component_pipeline: dict[str, Any],
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    prior_manifest: list[str],
    repair_errors: list[str],
    model: str,
    timeout: int,
    internal_context: str = "",
    repair_actions: list[dict[str, Any]] | None = None,
    existing_component_files: list[dict[str, str]] | None = None,
    phase_log_path: pathlib.Path | str | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
    last_transport_error: Any = None,
) -> dict[str, Any]:
    payload = provider_component_payload(
        goal=goal,
        component=component,
        component_pipeline=component_pipeline,
        plan_doc=plan_doc,
        blueprint=blueprint,
        online_inputs=online_inputs,
        market_research=market_research,
        prior_manifest=prior_manifest,
        repair_errors=repair_errors,
        internal_context=internal_context,
        repair_actions=repair_actions,
        existing_component_files=existing_component_files,
    )
    raw = provider_text(
        provider_component_messages(payload),
        model,
        timeout,
        max_attempts=1,
        stage="file_repair" if repair_actions else "component_generation",
        component=str(component.get("id", "")).strip(),
        max_tokens=12000,
        payload_mode="split_file" if repair_actions else "component",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
        last_error=last_transport_error,
    )
    doc = parse_json_object(raw)
    if str(doc.get("component_id", "")).strip() != str(component.get("id", "")).strip():
        raise RuntimeError(f"provider returned wrong component_id for {component.get('id')}: {doc.get('component_id')}")
    doc["_provider_raw_output"] = raw
    return doc


def split_file_checkpoint_path(checkpoint_dir: pathlib.Path | None, component_id: str, path: str) -> pathlib.Path | None:
    if checkpoint_dir is None:
        return None
    safe_component = provider_component_checkpoint_id(component_id)
    safe_path = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(path or "").replace("\\", "/").strip()).strip("._") or "file"
    return checkpoint_dir / "split_files" / safe_component / f"{safe_path}.json"


def write_split_file_checkpoint(
    checkpoint_dir: pathlib.Path | None,
    *,
    component_id: str,
    spec_hash: str,
    file_item: dict[str, str],
    manifest_entry: dict[str, Any],
) -> None:
    path = split_file_checkpoint_path(checkpoint_dir, component_id, file_item.get("path", ""))
    if path is None:
        return
    write_json(
        path,
        {
            "kind": "ProviderSplitFileCheckpoint",
            "created_at": now(),
            "component_id": component_id,
            "project_spec_hash": spec_hash,
            "path": file_item.get("path", ""),
            "file": file_item,
            "manifest_entry": manifest_entry,
            "status": "pass",
        },
    )


def load_split_file_checkpoint(
    checkpoint_dir: pathlib.Path | None,
    *,
    component_id: str,
    spec_hash: str,
    path_value: str,
) -> dict[str, str] | None:
    path = split_file_checkpoint_path(checkpoint_dir, component_id, path_value)
    if path is None or not path.exists():
        return None
    try:
        doc = load_json(path)
    except Exception:
        return None
    if doc.get("project_spec_hash") != spec_hash or str(doc.get("status", "")).lower() != "pass":
        return None
    item = doc.get("file")
    if not isinstance(item, dict):
        return None
    try:
        files = validate_provider_files({"files": [item]})
    except Exception:
        return None
    return files[0] if files else None


def summarize_component_context_for_split(
    *,
    goal: str,
    component: dict[str, Any],
    component_pipeline: dict[str, Any],
    prior_manifest: list[str],
    repair_errors: list[str],
) -> dict[str, Any]:
    component_id = str(component.get("id", "")).strip()
    return {
        "raw_user_goal": goal,
        "component": {
            "id": component_id,
            "goal": str(component.get("goal", ""))[:1200],
            "acceptance": component.get("acceptance", [])[:12] if isinstance(component.get("acceptance", []), list) else [],
        },
        "component_ownership": component_ownership_table().get(component_id, {}),
        "component_ids": [str(row.get("id", "")).strip() for row in component_pipeline.get("components", []) if isinstance(row, dict)],
        "merge_policy": component_pipeline.get("merge_policy", {}),
        "prior_manifest": prior_manifest[-120:],
        "project_goal_constraints": infer_project_goal_constraints(goal),
        "repair_errors_summary": [str(item)[:1000] for item in repair_errors[-8:]],
        "generation_policy": {
            "provider_generates_text_files_only": True,
            "screenshots_video_zip_created_by_post_build_finalize": True,
        },
    }


def provider_component_file_manifest(
    *,
    goal: str,
    component: dict[str, Any],
    component_pipeline: dict[str, Any],
    prior_manifest: list[str],
    repair_errors: list[str],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
    last_transport_error: Any = None,
) -> list[dict[str, Any]]:
    component_id = str(component.get("id", "")).strip()
    system = """You plan component-owned files for CGNK provider generation.
Return strict JSON only. Return a file manifest only; do not include file contents.
Provider output must be source code, scripts, tests, and docs only. Do not claim screenshots, videos, zip files, or binary artifacts already exist.
"""
    payload = summarize_component_context_for_split(
        goal=goal,
        component=component,
        component_pipeline=component_pipeline,
        prior_manifest=prior_manifest,
        repair_errors=repair_errors,
    )
    payload["required_output_shape"] = {
        "component": component_id,
        "files": [
            {
                "path": "component/owned/path.ext",
                "purpose": "why this file is needed",
                "dependencies": ["short dependency or contract summaries"],
                "estimated_complexity": "low|medium|high",
            }
        ],
    }
    payload["manifest_rules"] = [
        "List only files owned by this component.",
        "Do not list files already present in prior_manifest unless this component legally owns and must replace them.",
        "Do not include binary screenshot/video/zip outputs; include scripts that create them when this component owns media automation.",
    ]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
    prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
    soft = int(provider_component_prompt_policy()["manifest_soft_chars"])
    if prompt_chars > soft:
        payload["prior_manifest"] = prior_manifest[-40:]
        payload["repair_errors_summary"] = [str(item)[:400] for item in repair_errors[-4:]]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]
    raw = provider_text(
        messages,
        model,
        timeout,
        max_attempts=1,
        stage="component_file_manifest",
        component=component_id,
        max_tokens=2500,
        payload_mode="split_manifest",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
        last_error=last_transport_error,
    )
    doc = parse_json_object(raw)
    if str(doc.get("component", "") or doc.get("component_id", "")).strip() not in {"", component_id}:
        raise RuntimeError(f"provider manifest returned wrong component_id for {component_id}: {doc.get('component') or doc.get('component_id')}")
    files = doc.get("files", [])
    if not isinstance(files, list) or not files:
        raise RuntimeError(f"provider manifest missing files for component {component_id}")
    manifest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError(f"provider manifest contains non-object file entry for component {component_id}")
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        if not rel or rel in seen:
            raise RuntimeError(f"provider manifest contains duplicate or empty path for component {component_id}: {rel}")
        if not component_path_allowed(component_id, rel):
            owner = legal_owner_for_path(rel) or "<unknown>"
            raise RuntimeError(f"provider manifest path ownership violation: {rel} belongs to {owner}, not {component_id}")
        seen.add(rel)
        manifest.append(
            {
                "path": rel,
                "purpose": str(item.get("purpose", "")).strip()[:1000],
                "dependencies": item.get("dependencies", []) if isinstance(item.get("dependencies", []), list) else [],
                "estimated_complexity": str(item.get("estimated_complexity", "")).strip()[:80],
            }
        )
    return manifest


def validate_split_file_for_component(
    *,
    component_id: str,
    target_file: str,
    file_item: dict[str, Any],
    prior_manifest: list[str],
    completed_paths: set[str],
) -> dict[str, str]:
    files = validate_provider_files({"files": [file_item]})
    if len(files) != 1:
        raise RuntimeError("split file generation must return exactly one file")
    item = files[0]
    rel = item["path"]
    if rel != target_file:
        raise RuntimeError(f"split file generation returned wrong path: expected {target_file}, got {rel}")
    if not component_path_allowed(component_id, rel):
        owner = legal_owner_for_path(rel) or "<unknown>"
        raise RuntimeError(f"split file ownership violation: {rel} belongs to {owner}, not {component_id}")
    if rel in completed_paths:
        raise RuntimeError(f"split file duplicate path already completed: {rel}")
    if rel in set(prior_manifest):
        raise RuntimeError(f"split file duplicate path already exists in prior manifest: {rel}")
    lowered = item["content"].lower()
    if any(token in lowered for token in ("todo", "placeholder", "占位", "后续补齐")):
        raise RuntimeError(f"split file contains placeholder wording: {rel}")
    return item


def provider_generate_component_file(
    *,
    goal: str,
    component: dict[str, Any],
    component_pipeline: dict[str, Any],
    manifest_entry: dict[str, Any],
    prior_manifest: list[str],
    completed_files: list[dict[str, str]],
    repair_errors: list[str],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
    last_transport_error: Any = None,
) -> tuple[dict[str, str], str]:
    component_id = str(component.get("id", "")).strip()
    target_file = str(manifest_entry.get("path", "")).replace("\\", "/").strip()
    system = """You generate one component-owned file for CGNK.
Return strict JSON only. Generate exactly one file and no other files.
Do not emit screenshots, videos, zip files, or binary data; generate source/docs/scripts only.
"""
    payload = summarize_component_context_for_split(
        goal=goal,
        component=component,
        component_pipeline=component_pipeline,
        prior_manifest=prior_manifest,
        repair_errors=repair_errors,
    )
    payload.update(
        {
            "target_file": target_file,
            "target_file_purpose": str(manifest_entry.get("purpose", "")),
            "target_file_dependencies": manifest_entry.get("dependencies", []),
            "completed_component_files": [
                {"path": item.get("path", ""), "content_excerpt": str(item.get("content", ""))[:2500]}
                for item in completed_files[-6:]
            ],
            "strict_rules": [
                "Generate exactly one file.",
                f"The only allowed path is {target_file}.",
                "Return strict JSON: {\"path\":\"...\",\"content\":\"...\"}.",
                "Do not return a files[] array with more than one file.",
                "Do not include TODO, placeholder, future-work, or binary artifact claims.",
            ],
        }
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
    raw = provider_text(
        messages,
        model,
        timeout,
        max_attempts=1,
        stage="component_file_generation",
        component=component_id,
        target_file=target_file,
        max_tokens=int(provider_component_prompt_policy()["max_tokens_file"]),
        payload_mode="split_file",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
        last_error=last_transport_error,
    )
    doc = parse_json_object(raw)
    if "files" in doc:
        files = doc.get("files", [])
        if not isinstance(files, list) or len(files) != 1:
            raise RuntimeError(f"split file generation for {target_file} returned {len(files) if isinstance(files, list) else 'invalid'} files")
        item = files[0]
    else:
        item = {"path": doc.get("path", ""), "content": doc.get("content", "")}
    if not isinstance(item, dict):
        raise RuntimeError(f"split file generation for {target_file} returned invalid file object")
    completed_paths = {str(row.get("path", "")).replace("\\", "/").strip() for row in completed_files}
    return (
        validate_split_file_for_component(
            component_id=component_id,
            target_file=target_file,
            file_item=item,
            prior_manifest=prior_manifest,
            completed_paths=completed_paths,
        ),
        raw,
    )


def write_pending_component_file_generation(
    path: pathlib.Path,
    *,
    raw_user_goal: str,
    component_id: str,
    target_file: str,
    file_manifest: list[dict[str, Any]],
    completed_files: list[dict[str, str]],
    selected_model: str,
    next_retry_model: str,
    last_transport_error: str,
) -> None:
    completed_paths = [str(item.get("path", "")).replace("\\", "/").strip() for item in completed_files]
    remaining_files = [
        str(item.get("path", "")).replace("\\", "/").strip()
        for item in file_manifest
        if str(item.get("path", "")).replace("\\", "/").strip() not in set(completed_paths)
    ]
    write_pending_repair_context(
        path,
        {
            "status": "pending",
            "stage": "component_file_generation",
            "raw_user_goal": raw_user_goal,
            "component": component_id,
            "target_file": target_file,
            "payload_mode": "split_file",
            "file_manifest": file_manifest,
            "completed_files": completed_paths,
            "remaining_files": remaining_files,
            "selected_model": selected_model,
            "next_retry_model": next_retry_model,
            "last_transport_error": last_transport_error,
            "updated_at": now(),
        },
    )


def provider_generate_project_component_split(
    *,
    goal: str,
    component: dict[str, Any],
    component_pipeline: dict[str, Any],
    prior_manifest: list[str],
    repair_errors: list[str],
    model: str,
    timeout: int,
    deadline: float | ProgressDeadline | None,
    checkpoint_dir: pathlib.Path | None,
    run_dir: pathlib.Path | None,
    spec_hash: str,
    phase_log_path: pathlib.Path | str | None,
    routing_policy: ProviderModelRoutingPolicy | None,
    split_reason: str,
    original_prompt_chars: int,
    pending_context: dict[str, Any] | None = None,
    last_transport_error: Any = None,
) -> dict[str, Any]:
    component_id = str(component.get("id", "")).strip()
    append_provider_event_log(
        phase_log_path,
        {
            "event": "component_generation_split_started",
            "component": component_id,
            "original_prompt_chars": original_prompt_chars,
            "reason": split_reason,
        },
    )
    pending_context = pending_context or {}
    manifest = pending_context.get("file_manifest") if str(pending_context.get("stage", "")) == "component_file_generation" else None
    if not isinstance(manifest, list) or not manifest:
        manifest_timeout = remaining_timeout(deadline, timeout, floor=5, cap=90) if deadline else min(timeout, 90)
        manifest = provider_component_file_manifest(
            goal=goal,
            component=component,
            component_pipeline=component_pipeline,
            prior_manifest=prior_manifest,
            repair_errors=repair_errors,
            model=model,
            timeout=manifest_timeout,
            phase_log_path=phase_log_path,
            routing_policy=routing_policy,
            last_transport_error=last_transport_error,
        )
    completed_files: list[dict[str, str]] = []
    completed_paths: set[str] = set()
    if str(pending_context.get("stage", "")) == "component_file_generation":
        completed_paths.update(str(item).replace("\\", "/").strip() for item in pending_context.get("completed_files", []) if str(item).strip())
    for entry in manifest:
        rel = str(entry.get("path", "")).replace("\\", "/").strip()
        cached = load_split_file_checkpoint(checkpoint_dir, component_id=component_id, spec_hash=spec_hash, path_value=rel)
        if cached is not None:
            completed_files.append(cached)
            completed_paths.add(rel)
    transport_attempt_limit = provider_transport_repair_attempts()
    last_error_text = str(last_transport_error or pending_context.get("last_transport_error", "") or "")
    for entry in manifest:
        target_file = str(entry.get("path", "")).replace("\\", "/").strip()
        if target_file in completed_paths:
            continue
        previous_model = ""
        for attempt in range(transport_attempt_limit):
            route = choose_provider_model(
                "component_file_generation",
                0,
                model,
                routing_policy,
                last_error=last_error_text,
            )
            call_model = str(route.get("selected_model") or model)
            if str(pending_context.get("next_retry_model", "")).strip() and attempt == 0 and target_file == str(pending_context.get("target_file", "")).strip():
                call_model = str(pending_context.get("next_retry_model", "")).strip()
                route["selected_model"] = call_model
                route["model_routing_reason"] = "pending_next_retry_model"
            if previous_model and previous_model != call_model:
                append_provider_event_log(
                    phase_log_path,
                    {
                        "event": "provider_retry_model_route",
                        "stage": "component_file_generation",
                        "component": component_id,
                        "target_file": target_file,
                        "previous_model": previous_model,
                        "next_model": call_model,
                        "reason": route.get("model_routing_reason", ""),
                    },
                )
            previous_model = call_model
            try:
                call_timeout = remaining_timeout(deadline, timeout, floor=5, cap=90) if deadline else min(timeout, 90)
                file_item, _raw = provider_generate_component_file(
                    goal=goal,
                    component=component,
                    component_pipeline=component_pipeline,
                    manifest_entry=entry,
                    prior_manifest=prior_manifest,
                    completed_files=completed_files,
                    repair_errors=repair_errors,
                    model=call_model,
                    timeout=call_timeout,
                    phase_log_path=phase_log_path,
                    routing_policy=routing_policy,
                    last_transport_error=last_error_text,
                )
                write_split_file_checkpoint(
                    checkpoint_dir,
                    component_id=component_id,
                    spec_hash=spec_hash,
                    file_item=file_item,
                    manifest_entry=entry,
                )
                completed_files.append(file_item)
                completed_paths.add(target_file)
                mark_generation_progress(deadline, "project_generation", f"Provider split file {component_id}:{target_file} returned.", [target_file])
                break
            except (RuntimeError, TimeoutError) as exc:
                last_error_text = str(exc)
                retryable = provider_component_error_is_retryable(check_connectivity._provider_error_type(last_error_text), last_error_text)
                next_route = choose_provider_model("component_file_generation", 0, model, routing_policy, last_error=last_error_text)
                if run_dir is not None:
                    write_pending_component_file_generation(
                        run_dir / "artifacts" / "pending_repair_plan.json",
                        raw_user_goal=goal,
                        component_id=component_id,
                        target_file=target_file,
                        file_manifest=manifest,
                        completed_files=completed_files,
                        selected_model=previous_model or model,
                        next_retry_model=str(next_route.get("selected_model") or previous_model or model),
                        last_transport_error=last_error_text,
                    )
                if not retryable or attempt == transport_attempt_limit - 1:
                    raise
                if os.environ.get("CGKN_PROVIDER_RETRY_FAST") != "1":
                    time.sleep(min(20.0, 2.0 * (2**attempt)))
    result = {
        "component_id": component_id,
        "summary": f"{component_id} generated through split file requests.",
        "files": completed_files,
        "public_contract": {"exports": [item["path"] for item in completed_files]},
        "manual_checks": [],
        "self_test": {"status": "pass", "checks": ["split_file_generation_completed"]},
        "quality_gate": {"status": "pass", "reasons": ["manifest generated", "all split files validated"]},
    }
    if run_dir is not None:
        pending_path = run_dir / "artifacts" / "pending_repair_plan.json"
        try:
            pending_doc = load_json(pending_path) if pending_path.exists() else {}
        except Exception:
            pending_doc = {}
        if str(pending_doc.get("stage", "")) == "component_file_generation" and str(pending_doc.get("component", "")) == component_id:
            archive_completed_pending_repair(run_dir)
    return result


def merge_component_files(component_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    merged: dict[str, str] = {}
    owner: dict[str, str] = {}
    mergeable_docs = {"README.md", "TEST_PLAN.md", "DELIVERY_NOTES.md"}
    mergeable_web_suffixes = {".html", ".css", ".js", ".mjs", ".json"}
    mergeable_source_suffixes = {".py", ".json"}
    mergeable_entrypoints = {"app.py", "main.py"}
    for result in component_results:
        component_id = str(result.get("component_id", "<unknown>"))
        for item in validate_provider_files(result):
            rel = item["path"]
            content = item["content"]
            if rel in merged and merged[rel] != content:
                if rel in mergeable_docs or rel.startswith("docs/"):
                    merged[rel] = (
                        merged[rel].rstrip()
                        + "\n\n"
                        + f"## Component Addendum: {component_id}\n\n"
                        + content.strip()
                        + "\n"
                    )
                    owner[rel] = f"{owner[rel]},{component_id}"
                    continue
                suffix = pathlib.PurePosixPath(rel).suffix.lower()
                if rel in mergeable_entrypoints:
                    merged[rel] = content
                    owner[rel] = component_id
                    continue
                if rel.startswith(("app/", "static/", "frontend/", "templates/")) and suffix in mergeable_web_suffixes:
                    merged[rel] = content
                    owner[rel] = component_id
                    continue
                if rel.startswith("src/") and suffix in mergeable_source_suffixes and pathlib.PurePosixPath(rel).name not in mergeable_entrypoints:
                    merged[rel] = content
                    owner[rel] = component_id
                    continue
                if rel.startswith("tests/") and suffix == ".py":
                    merged[rel] = content
                    owner[rel] = component_id
                    continue
                raise RuntimeError(f"component file conflict: {rel} from {owner[rel]} and {component_id}")
            merged[rel] = content
            owner[rel] = component_id
    return [{"path": rel, "content": merged[rel]} for rel in sorted(merged)]


def provider_generate_project_by_components(
    goal: str,
    component_pipeline: dict[str, Any],
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    repair_errors: list[str],
    model: str,
    timeout: int,
    *,
    internal_context: str = "",
    deadline: float | ProgressDeadline | None = None,
    checkpoint_dir: pathlib.Path | None = None,
    force_components: set[str] | list[str] | None = None,
    component_repair_instructions: dict[str, list[str]] | None = None,
    pending_repair_plan: dict[str, Any] | None = None,
    run_dir: pathlib.Path | None = None,
    repair_attempt_number: int = 0,
    semantic_repair_attempts_used: int = 0,
    model_base_url: str = "",
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    components = [row for row in component_pipeline.get("components", []) if isinstance(row, dict)]
    if not components:
        raise RuntimeError("component pipeline has no components")
    component_results: list[dict[str, Any]] = []
    prior_manifest: list[str] = []
    component_errors: dict[str, list[str]] = {}
    completed_components: list[str] = []
    skipped_from_checkpoint: list[str] = []
    retried_components: list[str] = []
    failed_components: list[dict[str, str]] = []
    provider_error_type = ""
    forced = {str(item).strip() for item in (force_components or []) if str(item).strip()}
    repair_by_component = component_repair_instructions or {}
    plan_for_repair = pending_repair_plan or {}
    transport_attempt_limit = provider_transport_repair_attempts()
    provider_phase_log_path = run_dir / "provider_phase_log.jsonl" if run_dir is not None else (
        checkpoint_dir.parent.parent / "provider_phase_log.jsonl" if checkpoint_dir else ""
    )

    def checkpoint_summary() -> dict[str, Any]:
        return {
            "completed_components": completed_components,
            "skipped_from_checkpoint": skipped_from_checkpoint,
            "retried_components": retried_components,
            "failed_components": failed_components,
            "provider_error_type": provider_error_type,
            "checkpoint_dir": str(checkpoint_dir) if checkpoint_dir else "",
        }

    for component in components:
        component_id = str(component.get("id", "")).strip()
        if not component_id:
            raise RuntimeError("component missing id")
        spec_hash = provider_component_spec_hash(goal, component_pipeline, component)
        cached = None
        if component_id not in forced:
            cached = load_provider_component_checkpoint(checkpoint_dir, component_id=component_id, spec_hash=spec_hash)
        if cached is not None:
            result, files = cached
            prior_manifest.extend(item["path"] for item in files if item["path"] not in prior_manifest)
            component_results.append(result)
            completed_components.append(component_id)
            skipped_from_checkpoint.append(component_id)
            write_provider_component_checkpoint_summary(checkpoint_dir, checkpoint_summary())
            append_phase_log(
                checkpoint_dir.parent.parent / "provider_phase_log.jsonl" if checkpoint_dir else "",
                "project_generation",
                "component_checkpoint_skipped",
                f"Provider component {component_id} reused from checkpoint.",
                [item["path"] for item in files],
            )
            mark_generation_progress(
                deadline,
                "project_generation",
                f"Provider component {component_id} reused from checkpoint.",
                [item["path"] for item in files],
            )
            continue
        local_repairs = list(repair_errors) + list(repair_by_component.get(component_id, [])) + component_errors.get(component_id, [])
        repair_actions = repair_actions_for_component(plan_for_repair, component_id)
        existing_component_files = component_files_from_checkpoints(checkpoint_dir).get(component_id, [])
        target_files = concrete_repair_target_files(repair_actions)
        prompt_payload = provider_component_payload(
            goal=goal,
            component=component,
            component_pipeline=component_pipeline,
            plan_doc=plan_doc,
            blueprint=blueprint,
            online_inputs=online_inputs,
            market_research=market_research,
            prior_manifest=prior_manifest,
            repair_errors=local_repairs,
            internal_context=internal_context,
            repair_actions=repair_actions,
            existing_component_files=existing_component_files,
        )
        original_prompt_chars = provider_component_prompt_chars(prompt_payload)
        split_generation, split_reason = should_split_component_generation(component_id, original_prompt_chars, repair_actions=repair_actions)
        if str(plan_for_repair.get("stage", "")) == "component_file_generation" and str(plan_for_repair.get("component", "")) == component_id:
            split_generation = True
            split_reason = "pending_component_file_generation"
        component_last_transport_error = str(plan_for_repair.get("last_transport_error", "") or "")
        previous_call_model = ""
        if component_id in forced and plan_for_repair and run_dir is not None:
            pending_route = choose_provider_model(
                "file_repair" if repair_actions else "semantic_repair",
                0,
                model,
                routing_policy,
                last_error=component_last_transport_error,
            )
            if str(plan_for_repair.get("next_retry_model", "")).strip():
                pending_route["selected_model"] = str(plan_for_repair.get("next_retry_model", "")).strip()
                pending_route["model_routing_reason"] = "pending_next_retry_model"
            prompt_path = write_repair_prompt_file(
                run_dir,
                failed_component=component_id,
                attempt=repair_attempt_number or 1,
                instructions=local_repairs,
            )
            pending_context = build_pending_repair_context(
                run_dir=run_dir,
                raw_user_goal=goal,
                model=model,
                base_url=model_base_url,
                repair_plan=plan_for_repair,
                failed_component=component_id,
                attempt=repair_attempt_number or 1,
                semantic_repair_attempts_used=semantic_repair_attempts_used,
                transport_attempt=1,
                provider_prompt_path=prompt_path,
                requested_model=model,
                selected_model=str(pending_route.get("selected_model", "")),
                model_routing_reason=str(pending_route.get("model_routing_reason", "")),
                last_transport_error=component_last_transport_error,
                next_retry_model=str(plan_for_repair.get("next_retry_model", "") or pending_route.get("selected_model", "")),
            )
            write_pending_repair_context(run_dir / "artifacts" / "pending_repair_plan.json", pending_context)
        for attempt in range(transport_attempt_limit):
            try:
                if attempt > 0 and component_id not in retried_components:
                    retried_components.append(component_id)
                route = choose_provider_model(
                    "file_repair" if repair_actions else "component_generation",
                    0,
                    model,
                    routing_policy,
                    last_error=component_last_transport_error,
                )
                call_model = str(route.get("selected_model") or model)
                if str(plan_for_repair.get("next_retry_model", "")).strip() and attempt == 0:
                    call_model = str(plan_for_repair.get("next_retry_model", "")).strip()
                    route["selected_model"] = call_model
                    route["model_routing_reason"] = "pending_next_retry_model"
                if previous_call_model and previous_call_model != call_model:
                    append_provider_event_log(
                        provider_phase_log_path,
                        {
                            "event": "provider_retry_model_route",
                            "stage": "file_repair" if repair_actions else "component_generation",
                            "component": component_id,
                            "previous_model": previous_call_model,
                            "next_model": call_model,
                            "reason": route.get("model_routing_reason", ""),
                        },
                    )
                previous_call_model = call_model
                if component_id in forced and plan_for_repair and run_dir is not None and attempt > 0:
                    pending_path = run_dir / "artifacts" / "pending_repair_plan.json"
                    try:
                        pending_context = load_json(pending_path) if pending_path.exists() else {}
                    except Exception:
                        pending_context = {}
                    if isinstance(pending_context, dict) and pending_context:
                        pending_context["transport_attempt"] = attempt + 1
                        pending_context["requested_model"] = model
                        pending_context["selected_model"] = call_model
                        pending_context["model_routing_reason"] = str(route.get("model_routing_reason", ""))
                        pending_context["last_transport_error"] = component_last_transport_error
                        pending_context["next_retry_model"] = call_model
                        pending_context["updated_at"] = now()
                        write_pending_repair_context(pending_path, pending_context)
                call_timeout = remaining_timeout(deadline, timeout, floor=5, cap=120) if deadline else min(timeout, 120)
                if split_generation:
                    result = provider_generate_project_component_split(
                        goal=goal,
                        component=component,
                        component_pipeline=component_pipeline,
                        prior_manifest=prior_manifest,
                        repair_errors=local_repairs,
                        model=call_model,
                        timeout=call_timeout,
                        deadline=deadline,
                        checkpoint_dir=checkpoint_dir,
                        run_dir=run_dir,
                        spec_hash=spec_hash,
                        phase_log_path=provider_phase_log_path,
                        routing_policy=routing_policy,
                        split_reason=split_reason,
                        original_prompt_chars=original_prompt_chars,
                        pending_context=plan_for_repair,
                        last_transport_error=component_last_transport_error,
                    )
                else:
                    result = provider_generate_project_component(
                        goal=goal,
                        component=component,
                        component_pipeline=component_pipeline,
                        plan_doc=plan_doc,
                        blueprint=blueprint,
                        online_inputs=online_inputs,
                        market_research=market_research,
                        prior_manifest=prior_manifest,
                        repair_errors=local_repairs,
                        model=call_model,
                        timeout=call_timeout,
                        internal_context=internal_context,
                        repair_actions=repair_actions,
                        existing_component_files=existing_component_files,
                        phase_log_path=provider_phase_log_path,
                        routing_policy=routing_policy,
                        last_transport_error=component_last_transport_error,
                    )
                raw_output = str(result.get("_provider_raw_output", ""))
                result = {key: value for key, value in result.items() if key != "_provider_raw_output"}
                files = validate_provider_files(result)
                if target_files and existing_component_files:
                    generated_by_path = {item["path"]: item for item in files}
                    merged_by_path = {
                        str(item.get("path", "")).replace("\\", "/").strip(): item
                        for item in existing_component_files
                        if isinstance(item, dict) and str(item.get("path", "")).strip()
                    }
                    for path, item in generated_by_path.items():
                        merged_by_path[path] = item
                    for path in target_files:
                        if path in generated_by_path:
                            merged_by_path[path] = generated_by_path[path]
                    files = [merged_by_path[path] for path in sorted(merged_by_path)]
                    result["files"] = files
                semantic_review = provider_component_semantic_review(result, files)
                if semantic_review.get("status") != "pass":
                    write_provider_component_checkpoint(
                        checkpoint_dir,
                        component_id=component_id,
                        spec_hash=spec_hash,
                        status="failed",
                        raw_output=raw_output,
                        parsed_result=result,
                        files=files,
                        semantic_review=semantic_review,
                        error="component semantic review failed",
                        provider_error_type="PROVIDER_COMPONENT_SEMANTIC_FAIL",
                    )
                    raise RuntimeError(f"component semantic review failed: {component_id}")
                write_provider_component_checkpoint(
                    checkpoint_dir,
                    component_id=component_id,
                    spec_hash=spec_hash,
                    status="pass",
                    raw_output=raw_output,
                    parsed_result=result,
                    files=files,
                    semantic_review=semantic_review,
                )
                prior_manifest.extend(item["path"] for item in files if item["path"] not in prior_manifest)
                component_results.append(result)
                completed_components.append(component_id)
                write_provider_component_checkpoint_summary(checkpoint_dir, checkpoint_summary())
                mark_generation_progress(
                    deadline,
                    "project_generation",
                    f"Provider component {component_id} returned validated files.",
                    [item["path"] for item in files],
                )
                break
            except (RuntimeError, TimeoutError) as exc:
                provider_error_type = check_connectivity._provider_error_type(str(exc))
                component_last_transport_error = str(exc)
                message = f"{component_id} attempt {attempt + 1}: {exc}"
                component_errors.setdefault(component_id, []).append(message)
                local_repairs.append(message)
                retryable = provider_component_error_is_retryable(provider_error_type, str(exc))
                retry_route = choose_provider_model(
                    "file_repair" if repair_actions else "component_generation",
                    0,
                    model,
                    routing_policy,
                    last_error=component_last_transport_error,
                )
                next_retry_model = str(retry_route.get("selected_model") or model)
                if run_dir is not None:
                    pending_path = run_dir / "artifacts" / "pending_repair_plan.json"
                    try:
                        pending_context = load_json(pending_path) if pending_path.exists() else {}
                    except Exception:
                        pending_context = {}
                    if isinstance(pending_context, dict) and pending_context:
                        pending_context["requested_model"] = model
                        pending_context["selected_model"] = previous_call_model or model
                        pending_context["model_routing_reason"] = str(retry_route.get("model_routing_reason", ""))
                        pending_context["last_transport_error"] = component_last_transport_error
                        pending_context["next_retry_model"] = next_retry_model
                        pending_context["updated_at"] = now()
                        write_pending_repair_context(pending_path, pending_context)
                write_provider_component_checkpoint(
                    checkpoint_dir,
                    component_id=component_id,
                    spec_hash=spec_hash,
                    status="failed",
                    raw_output="",
                    parsed_result={"component_id": component_id},
                    files=[],
                    semantic_review={"status": "fail", "reviewer": "local_component_semantic_contract", "blockers": ["provider_exception"]},
                    error=str(exc),
                    provider_error_type=provider_error_type,
                )
                if not retryable or attempt == transport_attempt_limit - 1:
                    failed_components.append({"component_id": component_id, "provider_error_type": provider_error_type, "error": str(exc)})
                    write_provider_component_checkpoint_summary(checkpoint_dir, checkpoint_summary())
                    if retryable and provider_error_type in {"PROVIDER_TRANSPORT_UNSTABLE", "PROVIDER_RETRYABLE_HTTP"}:
                        raise RuntimeError(f"component {component_id} provider_api_request_failed after transport attempts: {attempt + 1}: {exc}") from exc
                    raise
                sleep_for = min(20.0, 2.0 * (2**attempt))
                append_phase_log(
                    checkpoint_dir.parent.parent / "provider_phase_log.jsonl" if checkpoint_dir else "",
                    "project_generation",
                    "component_retry",
                    f"Retrying provider component {component_id} after {provider_error_type}.",
                    [],
                )
                write_provider_component_checkpoint_summary(checkpoint_dir, checkpoint_summary())
                if os.environ.get("CGKN_PROVIDER_RETRY_FAST") != "1":
                    time.sleep(sleep_for)
    files = merge_component_files(component_results)
    paths = {item["path"] for item in files if isinstance(item, dict)}
    if "TEST_PLAN.md" not in paths:
        test_paths = sorted(path for path in paths if path.startswith("tests/") and path.endswith(".py"))
        if test_paths:
            files.append(
                {
                    "path": "TEST_PLAN.md",
                    "content": "\n".join(
                        [
                            "# Test Plan",
                            "",
                            "commands_run:",
                            "- python -m pytest tests",
                            "",
                            "test_files:",
                            *[f"- {path}" for path in test_paths],
                            "",
                            "status:",
                            "- planned; post-build finalize must execute these tests and write TEST_REPORT.md",
                        ]
                    )
                    + "\n",
                }
            )
            paths.add("TEST_PLAN.md")
    required = component_pipeline.get("merge_policy", {}).get("required_final_files", ["README.md", "TEST_PLAN.md"])
    missing = []
    for rel in required:
        if rel == "TEST_PLAN.md" and "TEST_REPORT.md" in paths:
            continue
        if rel not in paths:
            missing.append(rel)
    if missing:
        raise RuntimeError("merged component output missing required files: " + ", ".join(missing))
    mark_generation_progress(
        deadline,
        "project_generation",
        "Provider components merged into a project file set.",
        [item["path"] for item in files],
    )
    return {
        "project_type": "component_assembled_provider_project",
        "summary": "Project assembled from component-scoped provider generations.",
        "files": files,
        "components": [
            {
                "id": result.get("component_id", ""),
                "summary": result.get("summary", ""),
                "file_count": len(result.get("files", [])) if isinstance(result.get("files"), list) else 0,
                "public_contract": result.get("public_contract", {}),
                "quality_gate": result.get("quality_gate", {}),
            }
            for result in component_results
        ],
        "component_pipeline": component_pipeline,
        "component_errors": component_errors,
        "component_checkpoint_summary": checkpoint_summary(),
        "manual_checks": [
            check
            for result in component_results
            for check in result.get("manual_checks", [])
            if isinstance(check, str)
        ],
        "self_test": {
            "status": "pass",
            "checks": [
                f"{result.get('component_id', '<component>')}: {check}"
                for result in component_results
                for check in (result.get("self_test", {}) if isinstance(result.get("self_test"), dict) else {}).get("checks", [])
                if isinstance(check, str)
            ],
        },
        "quality_gate": {
            "status": "pass",
            "reasons": [
                "components generated with scoped context",
                "file merge completed without conflicts",
                "required final files are present",
            ],
        },
    }


def write_provider_files(out_dir: pathlib.Path, files: list[dict[str, str]]) -> list[str]:
    written: list[str] = []
    resolved_out = out_dir.resolve()
    allowed_generated_root = generated_root().resolve()
    if not str(resolved_out).lower().startswith(str(allowed_generated_root).lower()):
        raise RuntimeError(f"refusing to clean output directory outside generated root: {resolved_out}")
    if resolved_out.exists():
        shutil.rmtree(resolved_out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in files:
        rel = item["path"]
        target = (out_dir / rel).resolve()
        if not str(target).lower().startswith(str(out_dir.resolve()).lower()):
            raise RuntimeError(f"refusing to write outside project root: {rel}")
        write_text(target, item["content"])
        written.append(rel)
    return written


def candidate_project_dir_for(out_dir: pathlib.Path) -> pathlib.Path:
    resolved = pathlib.Path(out_dir).resolve()
    current_generated_root = generated_root()
    default_generated_dir = current_generated_root / "cgnk_generated_project"
    default_candidate_dir = current_generated_root / "cgnk_generated_project_candidate"
    if resolved == default_generated_dir.resolve():
        return default_candidate_dir
    if not str(resolved).lower().startswith(str(current_generated_root).lower()):
        if resolved.name.endswith("_candidate"):
            return resolved
        return resolved.with_name(f"{resolved.name}_candidate")
    if resolved.name.endswith("_candidate"):
        return resolved
    return resolved.with_name(f"{resolved.name}_candidate")


def issue_text(issue: Any) -> str:
    if isinstance(issue, dict):
        parts = [
            str(issue.get("kind", "")),
            str(issue.get("message", "")),
            str(issue.get("raw", "")),
            " ".join(str(item) for item in issue.get("files", []) if isinstance(issue.get("files", []), list)),
        ]
        return " ".join(part for part in parts if part).strip()
    return str(issue or "").strip()


def classify_semantic_blockers(provider_review: dict[str, Any] | list[Any] | None) -> dict[str, list[Any]]:
    issues = provider_review_issues(provider_review) if isinstance(provider_review, dict) else list(provider_review or [])
    classes: dict[str, list[Any]] = {
        "fatal_fact_blocker": [],
        "repairable_fact_blocker": [],
        "hard_fact_blocker": [],
        "runtime_blocker": [],
        "quality_blocker": [],
        "warning": [],
    }
    for issue in issues:
        text = issue_text(issue)
        lowered = text.lower()
        kind = str(issue.get("kind", "") if isinstance(issue, dict) else "").lower()
        if kind in {"component_file_conflict"} or any(
            token in lowered
            for token in (
                "unsafe path",
                "path traversal",
                "no files returned",
                "missing files[]",
                "malformed provider",
                "placeholder binary",
                "rejected preview",
            )
        ):
            classes["fatal_fact_blocker"].append(issue)
            classes["hard_fact_blocker"].append(issue)
        elif kind in {"fake_artifact_claim", "fake_zip_behavior", "placeholder_claim", "inaccurate_test_report_claims"} or any(
            token in lowered
            for token in (
                "fake zip",
                "not a real zip",
                "json manifest to a .zip",
                "pass_final",
                "final_project_bundle.zip",
                "delivery_manifest",
                "fake artifact",
                "placeholder artifact",
                "claims all tests passed",
                "test_report",
            )
        ):
            classes["repairable_fact_blocker"].append(issue)
            classes["hard_fact_blocker"].append(issue)
        elif kind in {"missing_entry_html", "missing_backend_deps", "broken_runtime", "broken_tests", "module_mismatch"} or any(
            token in lowered
            for token in (
                "missing entry",
                "index.html",
                "module",
                "dependency",
                "dependencies",
                "express",
                "dotenv",
                "broken tests",
                "tests are broken",
                "not runnable",
                "start command",
                "runtime",
            )
        ):
            classes["runtime_blocker"].append(issue)
        elif kind in {"frontend_backend_mismatch", "frontend_backend_integration_missing", "weak_tests", "inaccurate_test_report_claims"} or any(
            token in lowered
            for token in (
                "localstorage",
                "frontend",
                "backend",
                "status values",
                "weak tests",
                "incomplete readme",
                "market research",
                "test_report",
                "claims all tests passed",
                "documentation",
            )
        ):
            classes["quality_blocker"].append(issue)
        else:
            classes["warning"].append(issue)
    return classes


def detect_provider_hard_fact_blockers(files: list[dict[str, str]]) -> list[str]:
    blockers: list[str] = []
    if not files:
        return ["provider returned no writable files"]
    seen: set[str] = set()
    for item in files:
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        content = str(item.get("content", ""))
        lowered = content.lower()
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            blockers.append(f"unsafe path: {rel!r}")
        if rel in seen:
            blockers.append(f"duplicate provider path: {rel}")
        seen.add(rel)
        if not content.strip():
            blockers.append(f"empty or corrupt file: {rel}")
        if pathlib.PurePosixPath(rel).suffix.lower() in BINARY_EXTENSIONS:
            blockers.append(f"provider emitted binary artifact as text: {rel}")
        if content.lstrip().startswith("<<BINARY"):
            blockers.append(f"placeholder binary marker: {rel}")
    return sorted(set(blockers))


def detect_provider_repairable_fact_blockers(files: list[dict[str, str]]) -> list[str]:
    blockers: list[str] = []
    for item in files:
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        content = str(item.get("content", ""))
        lowered = content.lower()
        if "final_project_bundle.zip" in lowered and any(token in lowered for token in ("placeholder", "fake", "not a real zip", "json manifest", "dummy")):
            blockers.append(f"fake final zip behavior claimed in {rel}")
        if "delivery_manifest.json" in lowered and any(token in lowered for token in ("placeholder", "fake", "manual", "dummy", "provider generated")):
            blockers.append(f"fake delivery manifest behavior claimed in {rel}")
        if any(name in lowered for name in ("screenshot", "video", ".zip")) and any(
            token in lowered for token in ("placeholder artifact", "mock artifact", "fake artifact")
        ):
            blockers.append(f"placeholder artifact claim in {rel}")
    return sorted(set(blockers))


def fake_delivery_claim_present(path: str, content: str) -> bool:
    rel = str(path or "").lower()
    lowered = str(content or "").lower()
    return (
        "final_project_bundle.zip" in lowered
        or "delivery_manifest.json" in lowered and any(token in lowered for token in ("fake", "placeholder", "manual", "provider generated"))
        or any(token in lowered for token in ("fake zip", "not a real zip", "placeholder artifact", "mock artifact"))
        or pathlib.PurePosixPath(rel).name in {"bundle.js", "bundle.mjs", "final-bundle.js", "final_bundle.py"}
        and "zip" in lowered
    )


def sanitize_candidate_files_before_materialization(files: list[dict[str, str]], blockers: list[Any]) -> dict[str, Any]:
    sanitized_files: list[dict[str, str]] = []
    changed_paths: list[str] = []
    sanitized_fact_blockers: set[str] = set()
    blocker_text = "\n".join(issue_text(item) for item in blockers)
    for item in files:
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        content = str(item.get("content", ""))
        suffix = pathlib.PurePosixPath(rel).suffix.lower()
        if fake_delivery_claim_present(rel, content):
            sanitized_fact_blockers.add("fake_final_bundle_script")
            changed_paths.append(rel)
            if suffix in {".js", ".mjs", ".cjs", ".py", ".sh", ".ps1"}:
                if suffix == ".py":
                    content = (
                        '"""Candidate diagnostic helper only. Final delivery zip is produced exclusively by local_packager after post-build validation."""\n'
                        "from pathlib import Path\n"
                        "Path('candidate_delivery_note.json').write_text('{\"candidate_only\": true, \"final_zip\": \"local_packager_only\"}\\n', encoding='utf-8')\n"
                    )
                else:
                    content = (
                        "// Candidate diagnostic helper only. Final delivery zip is produced exclusively by local_packager after post-build validation.\n"
                        "import { writeFileSync } from 'node:fs';\n"
                        "writeFileSync('candidate_delivery_note.json', JSON.stringify({ candidate_only: true, final_zip: 'local_packager_only' }, null, 2) + '\\n');\n"
                    )
            else:
                content = re.sub(
                    r"final_project_bundle\.zip",
                    "candidate_diagnostic_bundle.zip (final zip is produced only by local_packager after post-build validation)",
                    content,
                    flags=re.I,
                )
                content = re.sub(
                    r"delivery_manifest\.json",
                    "delivery_manifest.json (created only by local_packager/public delivery gate after final validation)",
                    content,
                    flags=re.I,
                )
        sanitized_files.append({"path": rel, "content": content})
    if blockers or sanitized_fact_blockers:
        known_limits = {
            "candidate_only": True,
            "sanitized_fake_delivery_claim": bool(sanitized_fact_blockers),
            "sanitized_fact_blockers": sorted(sanitized_fact_blockers),
            "source_blockers": [issue_text(item) for item in blockers if issue_text(item)],
            "final_delivery_blocked_until": [
                "post_build_finalize_pass",
                "local_packager_created_final_project_bundle",
                "delivery_manifest_created_by_packager",
            ],
        }
        repair_plan = {
            "candidate_only": True,
            "root_causes": sorted(sanitized_fact_blockers) or ["repairable_fact_blocker"],
            "deterministic_actions": [{"action": "sanitize_fake_delivery_claims", "paths": changed_paths}],
            "provider_actions": [],
            "validation_checks": ["final_zip_created_only_by_local_packager", "candidate_not_public_delivered"],
            "source_blockers": blocker_text,
        }
        existing = {item["path"] for item in sanitized_files}
        if "known_limits.json" not in existing:
            sanitized_files.append({"path": "known_limits.json", "content": json.dumps(known_limits, ensure_ascii=False, indent=2) + "\n"})
        if "repair_plan.json" not in existing:
            sanitized_files.append({"path": "repair_plan.json", "content": json.dumps(repair_plan, ensure_ascii=False, indent=2) + "\n"})
    post_blockers = detect_provider_hard_fact_blockers(sanitized_files)
    if post_blockers:
        return {"status": "failed", "files": sanitized_files, "fatal_fact_blockers": post_blockers, "sanitized_fact_blockers": sorted(sanitized_fact_blockers), "changed_paths": changed_paths}
    return {"status": "pass", "files": sanitized_files, "fatal_fact_blockers": [], "sanitized_fact_blockers": sorted(sanitized_fact_blockers), "changed_paths": changed_paths}


def recover_candidate_files_from_checkpoints(run_dir: pathlib.Path, existing_files: list[dict[str, str]]) -> list[dict[str, str]]:
    if existing_files:
        return existing_files
    checkpoint_dir = run_dir / "artifacts" / "provider_components"
    component_map = component_files_from_checkpoints(checkpoint_dir)
    recovered: list[dict[str, str]] = []
    seen: set[str] = set()
    for component_id in sorted(component_map):
        for item in component_map.get(component_id, []):
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path", "")).replace("\\", "/").strip()
            content = item.get("content")
            if not rel or rel in seen or not isinstance(content, str):
                continue
            seen.add(rel)
            recovered.append({"path": rel, "content": content})
    return recovered


def write_candidate_marker(
    project_dir: pathlib.Path,
    semantic_status: str,
    classifications: dict[str, list[Any]],
    sanitize_result: dict[str, Any] | None = None,
) -> pathlib.Path:
    marker = project_dir / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json"
    sanitize_result = sanitize_result or {}
    write_json(
        marker,
        {
            "candidate_only": True,
            "not_final_delivery": True,
            "semantic_review_status": semantic_status,
            "fatal_fact_blockers": classifications.get("fatal_fact_blocker", []),
            "repairable_fact_blockers": classifications.get("repairable_fact_blocker", []),
            "hard_fact_blockers": classifications.get("hard_fact_blocker", []),
            "sanitized_fact_blockers": sanitize_result.get("sanitized_fact_blockers", []),
            "sanitized_fake_delivery_claim": "fake_final_bundle_script" in set(sanitize_result.get("sanitized_fact_blockers", [])),
            "final_delivery_blocked_until": [
                "post_build_finalize_pass",
                "local_packager_created_final_project_bundle",
                "delivery_manifest_created_by_packager",
            ],
            "runtime_blockers": classifications.get("runtime_blocker", []),
            "quality_blockers": classifications.get("quality_blocker", []),
            "warnings": classifications.get("warning", []),
            "created_at": now(),
        },
    )
    return marker


def create_candidate_diagnostic_package(project_dir: pathlib.Path, run_dir: pathlib.Path) -> pathlib.Path:
    package_path = run_dir / "artifacts" / "candidate_diagnostic_bundle.zip"
    tmp = package_path.with_suffix(f".{int(time.time() * 1000)}.tmp")
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name in {"final_project_bundle.zip", "delivery_manifest.json"}:
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and not real_image_file(path):
                continue
            zf.write(path, path.relative_to(project_dir))
        for path in sorted((run_dir / "artifacts").glob("*.json")):
            if path.resolve() == package_path.resolve() or not path.is_file():
                continue
            zf.write(path, pathlib.PurePosixPath("_run_artifacts") / path.name)
        phase_log = run_dir / "provider_phase_log.jsonl"
        if phase_log.exists() and phase_log.is_file():
            zf.write(phase_log, pathlib.PurePosixPath("_run_artifacts") / phase_log.name)
    tmp.replace(package_path)
    return package_path


def candidate_startup_candidates(project_dir: pathlib.Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            package_doc = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            package_doc = {}
        scripts = package_doc.get("scripts", {}) if isinstance(package_doc, dict) else {}
        if isinstance(scripts, dict):
            for name in ("preview", "start", "dev"):
                if scripts.get(name):
                    candidates.append({"mode": "node_script", "script": name, "argv": ["npm", "run", name] if name != "start" else ["npm", "start"]})
    if (project_dir / "index.html").exists():
        candidates.append({"mode": "static_html", "path": "index.html"})
    if (project_dir / "dist" / "index.html").exists():
        candidates.append({"mode": "static_html", "path": "dist/index.html"})
    for name in ("app.py", "main.py"):
        if (project_dir / name).exists():
            candidates.append({"mode": "python_app", "path": name, "argv": [sys.executable, name]})
    return candidates


def screenshot_environment_diagnostics() -> dict[str, str]:
    tools = ("node", "npm", "npx", "chrome", "msedge", "ffmpeg")
    env = {tool: shutil.which(tool) or "" for tool in tools}
    try:
        import playwright  # type: ignore

        env["playwright"] = str(getattr(playwright, "__version__", "")) or "available"
    except Exception as exc:
        env["playwright"] = f"unavailable: {exc}"
    return env


def real_image_file(path: pathlib.Path) -> bool:
    if not path.exists() or not path.is_file() or path.stat().st_size < 100:
        return False
    try:
        head = path.read_bytes()[:16]
    except Exception:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        diag = png_image_metrics(path)
        return bool(
            not diag.get("is_blank_or_invalid", True)
            and int(diag.get("image_width", 0) or 0) >= 640
            and int(diag.get("image_height", 0) or 0) >= 360
        )
    return head.startswith(b"\xff\xd8\xff") or head.startswith(b"RIFF")


def png_image_metrics(path: pathlib.Path) -> dict[str, Any]:
    import struct
    import zlib

    result: dict[str, Any] = {
        "image_width": 0,
        "image_height": 0,
        "blank_score": 0.0,
        "is_blank_or_invalid": True,
    }
    try:
        data = path.read_bytes()
    except Exception:
        return result
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return result
    offset = 8
    width = height = bit_depth = color_type = 0
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data[:13])
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    result["image_width"] = int(width or 0)
    result["image_height"] = int(height or 0)
    if width <= 0 or height <= 0 or bit_depth != 8 or color_type not in {2, 6} or not idat:
        return result
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except Exception:
        return result
    previous = bytearray(stride)
    sampled = 0
    blankish = 0
    non_white = 0
    varied = 0
    pos = 0
    for _row in range(height):
        if pos >= len(raw):
            return result
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos : pos + stride])
        pos += stride
        if len(row) != stride:
            return result
        for idx in range(stride):
            left = row[idx - channels] if idx >= channels else 0
            up = previous[idx]
            upper_left = previous[idx - channels] if idx >= channels else 0
            if filter_type == 1:
                row[idx] = (row[idx] + left) & 0xFF
            elif filter_type == 2:
                row[idx] = (row[idx] + up) & 0xFF
            elif filter_type == 3:
                row[idx] = (row[idx] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - upper_left
                pa = abs(estimate - left)
                pb = abs(estimate - up)
                pc = abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
                row[idx] = (row[idx] + predictor) & 0xFF
            elif filter_type != 0:
                return result
        for idx in range(0, stride, channels):
            r, g, b = row[idx], row[idx + 1], row[idx + 2]
            alpha = row[idx + 3] if channels == 4 else 255
            if alpha == 0:
                continue
            sampled += 1
            if min(r, g, b) >= 245 and max(r, g, b) - min(r, g, b) <= 8:
                blankish += 1
            if min(r, g, b) < 245:
                non_white += 1
            if max(r, g, b) - min(r, g, b) > 8:
                varied += 1
        previous = row
    if sampled <= 0:
        return result
    blank_score = blankish / sampled
    threshold = max(25, min(width * height, int(width * height * 0.001)))
    result["blank_score"] = round(float(blank_score), 6)
    result["is_blank_or_invalid"] = not (non_white >= threshold or varied >= threshold)
    return result


def image_file_diagnostics(path: pathlib.Path) -> dict[str, Any]:
    result = {
        "screenshot_path": str(path) if path else "",
        "screenshot_size_bytes": path.stat().st_size if path and path.exists() and path.is_file() else 0,
        "image_width": 0,
        "image_height": 0,
        "blank_score": 0.0,
        "is_blank_or_invalid": True,
    }
    if not path or not path.exists() or not path.is_file():
        return result
    try:
        head = path.read_bytes()[:16]
    except Exception:
        return result
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        result.update(png_image_metrics(path))
    elif head.startswith(b"\xff\xd8\xff") or head.startswith(b"RIFF"):
        result["is_blank_or_invalid"] = not real_image_file(path)
    return result


def candidate_ui_smoke(details: dict[str, Any], keywords: list[str] | None = None) -> dict[str, Any]:
    keywords = keywords or ["Task Board", "Add Task", "Todo", "Doing", "Done"]
    text = str(details.get("body_text_sample", "") or "")
    found = [keyword for keyword in keywords if keyword in text]
    issues: list[str] = []
    if not str(details.get("page_title", "")).strip():
        issues.append("missing_page_title")
    if int(details.get("body_text_length") or 0) <= 50:
        issues.append("body_text_too_short")
    if len(found) < min(3, len(keywords)):
        issues.append("domain_keywords_missing")
    if details.get("console_errors"):
        issues.append("console_errors")
    if details.get("network_errors"):
        issues.append("network_errors")
    return {
        "status": "pass" if not issues else "fail",
        "body_text_length": int(details.get("body_text_length") or 0),
        "keywords_found": found,
        "issues": issues,
    }


def write_screenshot_metadata(path: pathlib.Path, details: dict[str, Any]) -> str:
    diag = image_file_diagnostics(path)
    meta = path.with_suffix(path.suffix + ".meta.json")
    write_json(
        meta,
        {
            "path": str(path),
            "width": int(diag.get("image_width", 0) or 0),
            "height": int(diag.get("image_height", 0) or 0),
            "size_bytes": int(diag.get("screenshot_size_bytes", 0) or 0),
            "blank_score": float(diag.get("blank_score", 0.0) or 0.0),
            "opened_url": str(details.get("opened_url", "")),
            "page_title": str(details.get("page_title", "")),
            "body_text_length": int(details.get("body_text_length", 0) or 0),
            "body_text_sample": str(details.get("body_text_sample", ""))[:500],
            "captured_by": "playwright",
            "timestamp": now(),
        },
    )
    return str(meta)


def write_video_blocked(project_dir: pathlib.Path, reason: str, *, failure_reason: str = "unknown", environment: dict[str, str] | None = None, browser_used: str = "") -> str:
    environment = environment or screenshot_environment_diagnostics()
    path = project_dir / "video_blocked.json"
    write_json(
        path,
        {
            "status": "blocked",
            "failure_reason": failure_reason,
            "reason": reason,
            "ffmpeg_path": str(environment.get("ffmpeg", "")),
            "playwright_available": not str(environment.get("playwright", "")).startswith("unavailable"),
            "browser_used": browser_used,
            "next_repair_hint": "Install ffmpeg/browser recording support or add a real demo video capture flow." if failure_reason != "not_requested" else "",
            "created_at": now(),
            "candidate_only": True,
        },
    )
    return str(path)


def validate_candidate_review_artifacts(candidate_dir: pathlib.Path, run_dir: pathlib.Path) -> dict[str, Any]:
    issues: list[str] = []
    project = pathlib.Path(candidate_dir)
    bundle = pathlib.Path(run_dir) / "artifacts" / "candidate_diagnostic_bundle.zip"
    required = ["candidate_review_summary.json", "TEST_REPORT.md", "DELIVERY_NOTES.md", "known_limits.json", "repair_plan.json"]
    for name in required:
        if not (project / name).exists():
            issues.append(f"missing {name}")
    screenshot_ok = any((project / "artifacts" / "screenshots").glob("*.png")) if (project / "artifacts" / "screenshots").exists() else False
    if not screenshot_ok and not (project / "screenshot_blocked.json").exists():
        issues.append("missing screenshot or screenshot_blocked")
    video_ok = any(path.suffix.lower() in {".mp4", ".webm"} for path in project.rglob("*")) if project.exists() else False
    if not video_ok and not (project / "video_blocked.json").exists():
        issues.append("missing video or video_blocked")
    if not bundle.exists() or bundle.stat().st_size <= 0:
        issues.append("missing candidate_diagnostic_bundle.zip")
    else:
        try:
            with zipfile.ZipFile(bundle) as zf:
                names = zf.namelist()
                lowered = "\n".join(names).lower()
                if any(pathlib.PurePosixPath(name).name == "final_project_bundle.zip" for name in names):
                    issues.append("bundle contains final_project_bundle.zip")
                if any(pathlib.PurePosixPath(name).name == "delivery_manifest.json" for name in names):
                    issues.append("bundle contains delivery_manifest.json")
                for name in names:
                    if pathlib.PurePosixPath(name).suffix.lower() in {".json", ".md", ".txt", ".jsonl"}:
                        try:
                            text = zf.read(name).decode("utf-8", errors="replace")
                        except Exception:
                            continue
                        if "PASS_FINAL" in text:
                            issues.append("bundle contains fake PASS_FINAL")
                            break
                if "pass_final" in lowered:
                    issues.append("bundle path mentions PASS_FINAL")
        except Exception as exc:
            issues.append(f"bundle unreadable: {exc}")
    if (project / "final_project_bundle.zip").exists():
        issues.append("candidate contains final_project_bundle.zip")
    if (project / "delivery_manifest.json").exists():
        issues.append("candidate contains delivery_manifest.json")
    return {
        "status": "pass" if not issues else "fail",
        "candidate_dir": str(project),
        "diagnostic_bundle": str(bundle),
        "issues": issues,
    }


def png_has_visual_content(path: pathlib.Path) -> bool:
    import struct
    import zlib

    try:
        data = path.read_bytes()
    except Exception:
        return False
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    width = height = bit_depth = color_type = 0
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data[:13])
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if width <= 0 or height <= 0 or bit_depth != 8 or color_type not in {2, 6} or not idat:
        return False
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except Exception:
        return False
    previous = bytearray(stride)
    non_white = 0
    varied = 0
    sampled = 0
    pos = 0
    threshold = max(25, min(width * height, int(width * height * 0.001)))
    for _row in range(height):
        if pos >= len(raw):
            return False
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos : pos + stride])
        pos += stride
        if len(row) != stride:
            return False
        for idx in range(stride):
            left = row[idx - channels] if idx >= channels else 0
            up = previous[idx]
            upper_left = previous[idx - channels] if idx >= channels else 0
            if filter_type == 1:
                row[idx] = (row[idx] + left) & 0xFF
            elif filter_type == 2:
                row[idx] = (row[idx] + up) & 0xFF
            elif filter_type == 3:
                row[idx] = (row[idx] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - upper_left
                pa = abs(estimate - left)
                pb = abs(estimate - up)
                pc = abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
                row[idx] = (row[idx] + predictor) & 0xFF
            elif filter_type != 0:
                return False
        for idx in range(0, stride, channels):
            r, g, b = row[idx], row[idx + 1], row[idx + 2]
            alpha = row[idx + 3] if channels == 4 else 255
            if alpha == 0:
                continue
            sampled += 1
            if max(r, g, b) - min(r, g, b) > 8:
                varied += 1
            if min(r, g, b) < 245:
                non_white += 1
                if non_white >= threshold or varied >= threshold:
                    return True
        previous = row
    return sampled > 0 and (non_white >= threshold or varied >= threshold)


def find_free_local_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def screenshot_failure_reason(raw: str, *, failure_type: str = "", body_text_length: int = 0, image_diag: dict[str, Any] | None = None) -> str:
    text = str(raw or "").lower()
    kind = str(failure_type or "").lower()
    image_diag = image_diag or {}
    if "browser_unavailable" in kind or "playwright unavailable" in text or "playwright install" in text or "executable doesn't exist" in text:
        return "browser_unavailable"
    if "entrypoint" in kind or "no candidate startup mode" in text:
        return "entrypoint_missing"
    if "startup" in kind or "startup url did not become ready" in text or "start_failed" in text:
        return "startup_failed"
    if "timeout" in text:
        return "page_load_timeout"
    if image_diag.get("screenshot_size_bytes", 0) and image_diag.get("is_blank_or_invalid", True):
        return "page_blank" if body_text_length <= 20 else "invalid_screenshot"
    if "blank" in text:
        return "page_blank"
    if "invalid" in text or "missing" in text:
        return "invalid_screenshot"
    return "unknown"


def write_screenshot_blocked(project_dir: pathlib.Path, reason: str, *, failure_type: str = "screenshot_failure", details: dict[str, Any] | None = None) -> str:
    path = project_dir / "screenshot_blocked.json"
    details = details or {}
    image_diag = details.get("image_diagnostics") if isinstance(details.get("image_diagnostics"), dict) else None
    if image_diag is None:
        image_diag = image_file_diagnostics(pathlib.Path(str(details.get("screenshot_path", "")))) if details.get("screenshot_path") else {
        "screenshot_path": "",
        "screenshot_size_bytes": 0,
        "image_width": 0,
        "image_height": 0,
        "blank_score": 0.0,
        "is_blank_or_invalid": True,
        }
    body_text = str(details.get("body_text_sample", "") or "")
    body_text_length = int(details.get("body_text_length") or len(body_text))
    failure_reason = str(details.get("failure_reason") or screenshot_failure_reason(reason, failure_type=failure_type, body_text_length=body_text_length, image_diag=image_diag))
    write_json(
        path,
        {
            "status": "blocked",
            "failure_type": failure_type,
            "failure_reason": failure_reason,
            "reason": reason,
            "detected_entrypoint": str(details.get("detected_entrypoint", "")),
            "startup_command": str(details.get("startup_command", "")),
            "opened_url": str(details.get("opened_url", "")),
            "browser_used": str(details.get("browser_used", "")),
            "browser_available": bool(details.get("browser_available", failure_reason != "browser_unavailable")),
            "page_title": str(details.get("page_title", "")),
            "body_text_length": body_text_length,
            "body_text_sample": body_text[:500],
            "console_errors": list(details.get("console_errors", []) or [])[:20],
            "network_errors": list(details.get("network_errors", []) or [])[:20],
            "screenshot_attempted": bool(details.get("screenshot_attempted", True)),
            "screenshot_path": str(image_diag.get("screenshot_path", "")),
            "screenshot_size_bytes": int(image_diag.get("screenshot_size_bytes", 0) or 0),
            "image_width": int(image_diag.get("image_width", 0) or 0),
            "image_height": int(image_diag.get("image_height", 0) or 0),
            "blank_score": float(image_diag.get("blank_score", 0.0) or 0.0),
            "is_blank_or_invalid": bool(image_diag.get("is_blank_or_invalid", True)),
            "environment": details.get("environment") if isinstance(details.get("environment"), dict) else screenshot_environment_diagnostics(),
            "next_repair_hint": str(details.get("next_repair_hint", "")),
            "details": details,
            "created_at": now(),
            "candidate_only": True,
        },
    )
    return str(path)


def screenshot_attempt_base_details(
    candidate: dict[str, Any] | None = None,
    *,
    environment: dict[str, str] | None = None,
    opened_url: str = "",
    startup_command: list[str] | None = None,
    browser_available: bool = True,
    failure_reason: str = "",
) -> dict[str, Any]:
    candidate = candidate or {}
    entrypoint = str(candidate.get("path") or candidate.get("script") or candidate.get("mode") or "")
    return {
        "detected_entrypoint": entrypoint,
        "startup_command": " ".join(startup_command or [str(item) for item in candidate.get("argv", []) if str(item).strip()]),
        "opened_url": opened_url,
        "browser_used": "chromium" if browser_available else "",
        "browser_available": browser_available,
        "page_title": "",
        "body_text_length": 0,
        "body_text_sample": "",
        "console_errors": [],
        "network_errors": [],
        "screenshot_attempted": False,
        "screenshot_path": "",
        "environment": environment or screenshot_environment_diagnostics(),
        "failure_reason": failure_reason,
        "next_repair_hint": "",
    }


def capture_candidate_screenshot(project_dir: pathlib.Path, run_dir: pathlib.Path, timeout: int = 60) -> dict[str, Any]:
    out_dir = project_dir / "artifacts" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "candidate_home.png"
    attempts: list[dict[str, Any]] = []
    environment = screenshot_environment_diagnostics()
    candidates = candidate_startup_candidates(project_dir)
    if not candidates:
        details = screenshot_attempt_base_details(environment=environment, browser_available=True, failure_reason="entrypoint_missing")
        details["next_repair_hint"] = "Add a runnable entrypoint such as package.json start script, index.html, app.py, or main.py."
        blocked = write_screenshot_blocked(project_dir, "no candidate startup mode detected", failure_type="entrypoint_missing", details=details)
        return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": attempts}

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        details = screenshot_attempt_base_details(candidates[0] if candidates else {}, environment=environment, browser_available=False, failure_reason="browser_unavailable")
        details["next_repair_hint"] = "Install or repair browser automation runtime; do not repair project code for this environment-only failure."
        blocked = write_screenshot_blocked(project_dir, f"playwright unavailable: {exc}", failure_type="browser_unavailable", details=details)
        return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": attempts}

    last_error = ""
    last_details: dict[str, Any] = screenshot_attempt_base_details(candidates[0] if candidates else {}, environment=environment)
    for candidate in candidates:
        proc: subprocess.Popen[str] | None = None
        browser = None
        url_value = ""
        env = os.environ.copy()
        startup_argv: list[str] = []
        details = screenshot_attempt_base_details(candidate, environment=environment)
        try:
            mode = str(candidate.get("mode", ""))
            if mode == "static_html":
                port = find_free_local_port()
                rel_path = str(candidate.get("path", "index.html")).replace("\\", "/").lstrip("/")
                url_value = f"http://127.0.0.1:{port}/{rel_path}"
                startup_argv = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
                details.update(screenshot_attempt_base_details(candidate, environment=environment, opened_url=url_value, startup_command=startup_argv))
                proc = subprocess.Popen(startup_argv, cwd=str(project_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                if not wait_for_url(url_value, timeout=min(timeout, 25)):
                    last_error = "startup URL did not become ready"
                    details["failure_reason"] = "startup_failed"
                    details["next_repair_hint"] = "Static entrypoint exists but did not become reachable over the local HTTP server."
                    attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "url": url_value, "diagnostics": details})
                    last_details = details
                    continue
            else:
                port = find_free_local_port()
                url_value = f"http://127.0.0.1:{port}"
                env["PORT"] = str(port)
                env["HOST"] = "127.0.0.1"
                argv = [str(item) for item in candidate.get("argv", [])]
                startup_argv = normalize_allowed_argv(argv) if argv_is_allowed(argv) else argv
                details.update(screenshot_attempt_base_details(candidate, environment=environment, opened_url=url_value, startup_command=startup_argv))
                if not argv_is_allowed(argv):
                    details["failure_reason"] = "startup_failed"
                    details["next_repair_hint"] = "Startup command is not in the allowed command list."
                    attempts.append({"candidate": candidate, "ok": False, "reason": "startup command not allowed"})
                    last_details = details
                    continue
                proc = subprocess.Popen(startup_argv, cwd=str(project_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                if not wait_for_url(url_value, timeout=min(timeout, 25)):
                    last_error = "startup URL did not become ready"
                    details["failure_reason"] = "startup_failed"
                    details["next_repair_hint"] = "The app start command did not expose a reachable local HTTP URL."
                    attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "url": url_value, "diagnostics": details})
                    last_details = details
                    continue
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
                console_errors: list[str] = []
                network_errors: list[str] = []
                try:
                    page.on("console", lambda msg: console_errors.append(str(msg.text)) if str(getattr(msg, "type", "")).lower() == "error" else None)
                    page.on("requestfailed", lambda req: network_errors.append(str(req.url)))
                except Exception:
                    pass
                page.goto(url_value, wait_until="domcontentloaded", timeout=min(timeout, 30) * 1000)
                page.wait_for_timeout(500)
                try:
                    details["page_title"] = str(page.title())
                except Exception:
                    details["page_title"] = ""
                try:
                    body_text = str(page.evaluate("() => document.body ? document.body.innerText : ''") or "")
                except Exception:
                    body_text = ""
                details["body_text_length"] = len(body_text)
                details["body_text_sample"] = body_text[:500]
                details["console_errors"] = console_errors[:20]
                details["network_errors"] = network_errors[:20]
                details["screenshot_attempted"] = True
                details["screenshot_path"] = str(out)
                page.screenshot(path=str(out), full_page=True)
                details["image_diagnostics"] = image_file_diagnostics(out)
                details.update(details["image_diagnostics"])
                browser.close()
                browser = None
            body_text_for_smoke = str(details.get("body_text_sample", "") or "")
            ui_smoke_ok = int(details.get("body_text_length") or 0) > 50 and any(token in body_text_for_smoke for token in ("Task", "Todo", "Doing", "Done"))
            if real_image_file(out) and ui_smoke_ok:
                attempts.append({"candidate": candidate, "ok": True, "url": url_value, "screenshot": str(out), "diagnostics": details})
                return {"status": "pass", "screenshots": [str(out)], "screenshot_blocked": "", "attempts": attempts, "startup": candidate}
            last_error = "captured screenshot was missing or invalid" if real_image_file(out) else "captured screenshot was blank or invalid"
            details["failure_reason"] = screenshot_failure_reason(last_error, failure_type="screenshot_failure", body_text_length=int(details.get("body_text_length") or 0), image_diag=details.get("image_diagnostics") if isinstance(details.get("image_diagnostics"), dict) else {})
            if real_image_file(out) and not ui_smoke_ok:
                details["failure_reason"] = "page_blank"
            details["next_repair_hint"] = "Page loaded but produced an empty or invalid screenshot; inspect body text, console errors, and entrypoint wiring."
            try:
                out.unlink(missing_ok=True)
            except Exception:
                pass
            attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "url": url_value, "diagnostics": details})
            last_details = details
        except Exception as exc:
            last_error = str(exc)
            failure_type = "browser_unavailable" if "Executable doesn't exist" in last_error or "playwright install" in last_error.lower() else ("page_load_timeout" if "timeout" in last_error.lower() else "screenshot_failure")
            details["failure_reason"] = screenshot_failure_reason(last_error, failure_type=failure_type, body_text_length=int(details.get("body_text_length") or 0), image_diag=details.get("image_diagnostics") if isinstance(details.get("image_diagnostics"), dict) else {})
            details["next_repair_hint"] = "Browser automation failed while opening or capturing the candidate page."
            try:
                out.unlink(missing_ok=True)
            except Exception:
                pass
            attempts.append({"candidate": candidate, "ok": False, "reason": last_error, "failure_type": failure_type, "diagnostics": details})
            last_details = details
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if proc is not None:
                try:
                    proc.terminate()
                    proc.communicate(timeout=5)
                except Exception:
                    if sys.platform.startswith("win"):
                        kill_windows_process_tree(proc.pid)
                    else:
                        proc.kill()
    final_reason_text = last_error or "candidate screenshot capture failed"
    preferred_details = last_details
    for preferred_reason in ("page_blank", "invalid_screenshot", "page_load_timeout", "startup_failed", "entrypoint_missing", "browser_unavailable", "unknown"):
        for attempt in attempts:
            diag = attempt.get("diagnostics") if isinstance(attempt, dict) else {}
            if isinstance(diag, dict) and str(diag.get("failure_reason", "")) == preferred_reason:
                preferred_details = dict(diag)
                final_reason_text = str(attempt.get("reason", final_reason_text))
                break
        if preferred_details is not last_details or str(preferred_details.get("failure_reason", "")) == preferred_reason:
            break
    failure_type = "browser_unavailable" if str(preferred_details.get("failure_reason", "")).lower() == "browser_unavailable" else "screenshot_failure"
    preferred_details["attempts"] = [{key: value for key, value in attempt.items() if key != "diagnostics"} for attempt in attempts]
    if not preferred_details.get("failure_reason"):
        preferred_details["failure_reason"] = screenshot_failure_reason(final_reason_text, failure_type=failure_type, body_text_length=int(preferred_details.get("body_text_length") or 0), image_diag=preferred_details.get("image_diagnostics") if isinstance(preferred_details.get("image_diagnostics"), dict) else {})
    blocked = write_screenshot_blocked(project_dir, final_reason_text, failure_type=failure_type, details=preferred_details)
    return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": attempts}


def write_candidate_review_summary(
    project_dir: pathlib.Path,
    *,
    verdict: str,
    test_status: str,
    screenshots: list[str],
    video_blocked: str,
    known_limits: list[str],
) -> str:
    path = project_dir / "candidate_review_summary.json"
    warnings = list(known_limits)
    if not (project_dir / "final_project_bundle.zip").exists():
        warnings.append("final_project_bundle.zip not generated")
    if not (project_dir / "delivery_manifest.json").exists():
        warnings.append("delivery_manifest.json not generated")
    if video_blocked:
        warnings.append("video blocked")
    write_json(
        path,
        {
            "verdict": verdict,
            "candidate_project_dir": str(project_dir),
            "test_status": test_status,
            "screenshot_paths": screenshots,
            "video_status": "blocked" if video_blocked else "available",
            "video_blocked": video_blocked,
            "final_delivery": False,
            "warnings": sorted(set(warnings)),
            "created_at": now(),
        },
    )
    return str(path)


def run_candidate_post_build_finalize(
    *,
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    user_goal: str,
    generated_files: list[str],
    online_inputs: dict[str, Any],
    example_outputs: dict[str, Any],
    model: str,
    timeout: int,
    phase_log_path: pathlib.Path | str,
    deadline: ProgressDeadline,
    classifications: dict[str, list[Any]],
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    started = time.time()
    append_phase_log(phase_log_path, "post_build_finalize", "started", "Candidate post-build finalize started.", [str(project_dir)], started_at=started)
    test_environment = check_test_environment.check_environment(project_dir)
    write_json(run_dir / "artifacts" / "test_environment_report.json", test_environment)
    test_result: dict[str, Any] = {"status": "skipped", "reason": "no recognized test command"}
    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            package_doc = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            package_doc = {}
        scripts = package_doc.get("scripts", {}) if isinstance(package_doc, dict) else {}
        if isinstance(scripts, dict) and scripts.get("test"):
            test_result = run_allowed_command(["npm", "test"], project_dir, timeout=min(timeout, 180))
    elif (project_dir / "tests").exists():
        test_result = run_allowed_command([sys.executable, "-m", "pytest", "-q"], project_dir, timeout=min(timeout, 180))

    try:
        agent_usage = run_project_usage_agent(
            user_goal,
            project_dir,
            run_dir,
            generated_files,
            online_inputs,
            example_outputs,
            model,
            min(timeout, 180),
            allow_model_usage_planning=False,
            phase_log_path=phase_log_path,
            deadline=deadline,
            routing_policy=routing_policy,
        )
    except Exception as exc:
        agent_usage = {"status": "failed", "events": [{"type": "candidate_usage_failed", "error": str(exc)}], "screenshots": [], "workflow_video": ""}

    screenshots = [
        str(path)
        for path in agent_usage.get("screenshots", [])
        if str(path).strip() and real_image_file(pathlib.Path(str(path)))
    ]
    screenshot_blocked = ""
    screenshot_capture: dict[str, Any] = {"status": "skipped", "reason": "existing screenshot evidence present" if screenshots else "tests did not pass yet"}
    environment_failures = set(test_environment.get("failures", []) if isinstance(test_environment.get("failures"), list) else [])
    if any("node unavailable" in item or "npm unavailable" in item for item in environment_failures):
        test_result = {"status": "environment_failure", "reason": "node/npm unavailable", "environment": test_environment}

    if not screenshots and str(test_result.get("status", "")).lower() == "pass":
        screenshot_capture = capture_candidate_screenshot(project_dir, run_dir, timeout=min(timeout, 90))
        screenshots = [
            str(path)
            for path in screenshot_capture.get("screenshots", [])
            if str(path).strip() and real_image_file(pathlib.Path(str(path)))
        ]
        screenshot_blocked = str(screenshot_capture.get("screenshot_blocked", "") or "")
    if screenshots:
        stale_blocked = project_dir / "screenshot_blocked.json"
        if stale_blocked.exists():
            try:
                stale_blocked.unlink()
            except Exception:
                pass
        screenshot_blocked = ""
    screenshot_metadata = ""
    screenshot_ui_smoke: dict[str, Any] = {"status": "skipped"}
    success_attempt = next((attempt for attempt in screenshot_capture.get("attempts", []) if isinstance(attempt, dict) and attempt.get("ok")), {})
    success_details = success_attempt.get("diagnostics", {}) if isinstance(success_attempt, dict) and isinstance(success_attempt.get("diagnostics"), dict) else {}
    if screenshots and success_details:
        screenshot_ui_smoke = candidate_ui_smoke(success_details)
        screenshot_metadata = write_screenshot_metadata(pathlib.Path(screenshots[0]), success_details)
    video = str(agent_usage.get("workflow_video", "") or "")
    video_blocked = ""
    if not video:
        env = screenshot_environment_diagnostics()
        reason = "ffmpeg_unavailable" if not env.get("ffmpeg") else "not_requested"
        video_blocked = write_video_blocked(project_dir, "candidate post-build did not produce a demo video", failure_reason=reason, environment=env, browser_used=str(success_details.get("browser_used", "")))

    known_limits = [
        str(issue_text(item))
        for key in ("runtime_blocker", "quality_blocker", "warning")
        for item in classifications.get(key, [])
        if issue_text(item)
    ]
    if str(test_result.get("status", "")).lower() != "pass":
        known_limits.append("tests did not pass during candidate post-build finalize")
    if not screenshots:
        known_limits.append("screenshot evidence was not produced during candidate post-build finalize")
        if screenshot_blocked:
            known_limits.append("screenshot_blocked: candidate screenshot could not be captured in this environment")
    if video_blocked:
        known_limits.append("video_blocked: demo video was not produced during candidate post-build finalize")

    repair_plan = compile_repair_plan(
        classifications.get("runtime_blocker", []) + classifications.get("quality_blocker", []),
        {},
    )
    test_report = project_dir / "TEST_REPORT.md"
    write_text(
        test_report,
        "\n".join(
            [
                "# TEST_REPORT",
                "",
                "candidate_only: true",
                f"test_status: {test_result.get('status', 'unknown')}",
                f"agent_usage_status: {agent_usage.get('status', 'unknown')}",
                "",
                "commands_run:",
                f"- {json.dumps(test_result.get('argv', []), ensure_ascii=False)}" if test_result.get("argv") else "- no recognized test command",
                "",
                "known_limits:",
                *[f"- {item}" for item in known_limits[:30]],
            ]
        )
        + "\n",
    )
    write_text(
        project_dir / "DELIVERY_NOTES.md",
        "\n".join(
            [
                "# DELIVERY_NOTES",
                "",
                "candidate_only: true",
                "not_final_delivery: true",
                "This candidate is available for local review only. It is not a public delivery artifact.",
            ]
        )
        + "\n",
    )
    write_json(project_dir / "known_limits.json", {"candidate_only": True, "known_limits": known_limits, "created_at": now()})
    write_json(project_dir / "repair_plan.json", repair_plan)
    status = "pass" if str(test_result.get("status", "")).lower() == "pass" and screenshots else "needs_rework"
    candidate_review_ready = str(test_result.get("status", "")).lower() == "pass" and (bool(screenshots) or bool(screenshot_blocked))
    candidate_review_summary = ""
    if candidate_review_ready:
        candidate_review_summary = write_candidate_review_summary(
            project_dir,
            verdict="ASK_USER_REVIEW",
            test_status=str(test_result.get("status", "unknown")),
            screenshots=screenshots,
            video_blocked=video_blocked,
            known_limits=known_limits,
        )
    diagnostic_package = create_candidate_diagnostic_package(project_dir, run_dir)
    artifact_integrity = validate_candidate_review_artifacts(project_dir, run_dir)
    result = {
        "status": status,
        "candidate_only": True,
        "test_result": test_result,
        "agent_usage": agent_usage,
        "screenshots": screenshots,
        "screenshot_capture": screenshot_capture,
        "screenshot_blocked": screenshot_blocked,
        "screenshot_metadata": screenshot_metadata,
        "ui_smoke": screenshot_ui_smoke,
        "video": video,
        "video_blocked": video_blocked,
        "known_limits": known_limits,
        "repair_plan": repair_plan,
        "candidate_review_ready": candidate_review_ready,
        "candidate_review_summary": candidate_review_summary,
        "diagnostic_package": str(diagnostic_package),
        "test_environment": test_environment,
        "artifact_integrity": artifact_integrity,
    }
    write_json(run_dir / "artifacts" / "candidate_post_build_finalize.json", result)
    append_phase_log(phase_log_path, "post_build_finalize", status, "Candidate post-build finalize completed.", [str(test_report), str(diagnostic_package)], started_at=started)
    return result


def decide_adaptive_final_verdict(
    *,
    candidate_materialized: bool,
    hard_fact_blockers: list[Any],
    runtime_blockers: list[Any],
    quality_blockers: list[Any],
    warnings: list[Any],
    post_build: dict[str, Any],
    final_delivery_allowed: bool,
    final_bundle_exists: bool,
    delivery_manifest_exists: bool,
) -> str:
    if hard_fact_blockers or not candidate_materialized:
        return "FACT_BLOCKED"
    if final_delivery_allowed and final_bundle_exists and delivery_manifest_exists:
        return "DELIVER_WITH_WARNINGS" if (quality_blockers or warnings) else "PASS_FINAL"
    if runtime_blockers or str(post_build.get("status", "")).lower() == "needs_rework":
        if not runtime_blockers and bool(post_build.get("candidate_review_ready")):
            return "ASK_USER_REVIEW"
        return "NEEDS_REWORK"
    return "ASK_USER_REVIEW"



def provider_semantic_repair_attempts(args: argparse.Namespace | None = None) -> int:
    raw = os.environ.get("CGNK_PROVIDER_SEMANTIC_REPAIR_ATTEMPTS", "")
    if args is not None and getattr(args, "provider_semantic_repair_attempts", None) is not None:
        raw = str(getattr(args, "provider_semantic_repair_attempts"))
    try:
        return max(0, min(5, int(raw)))
    except (TypeError, ValueError):
        return 2


def provider_transport_repair_attempts() -> int:
    raw = os.environ.get("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS", "")
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return 3


def provider_component_prompt_policy() -> dict[str, int | bool]:
    return {
        "max_prompt_chars_hard": env_int("CGNK_PROVIDER_COMPONENT_MAX_PROMPT_CHARS_HARD", 40000),
        "frontend_target_chars": env_int("CGNK_PROVIDER_FRONTEND_TARGET_PROMPT_CHARS", 20000),
        "manifest_soft_chars": env_int("CGNK_PROVIDER_COMPONENT_MANIFEST_SOFT_CHARS", 20000),
        "max_tokens_file": env_int("CGNK_PROVIDER_COMPONENT_FILE_MAX_TOKENS", 8000),
        "split_frontend_component": env_bool("CGNK_SPLIT_FRONTEND_COMPONENT", True),
    }


def semantic_review_budget_config() -> dict[str, int]:
    return {
        "soft_prompt_chars": env_int("CGNK_SEMANTIC_REVIEW_SOFT_PROMPT_CHARS", 20000),
        "hard_prompt_chars": env_int("CGNK_SEMANTIC_REVIEW_HARD_PROMPT_CHARS", 40000),
        "max_files_per_component_review": env_int("CGNK_SEMANTIC_REVIEW_MAX_FILES_PER_COMPONENT", 3),
        "max_file_content_chars_per_review": env_int("CGNK_SEMANTIC_REVIEW_MAX_FILE_CONTENT_CHARS", 6000),
    }


def provider_base_url_for_diagnostics() -> str:
    try:
        return str(check_connectivity._resolve_api_credentials().get("base_url", "")).strip()
    except Exception:
        return ""


def write_run_context(
    run_dir: pathlib.Path,
    *,
    raw_user_goal: str,
    model: str,
    base_url: str,
    generation_mode: str,
    requested_project_dir: pathlib.Path,
) -> pathlib.Path:
    path = run_dir / "artifacts" / "run_context.json"
    write_json(
        path,
        {
            "raw_user_goal": raw_user_goal,
            "model": model,
            "base_url": base_url,
            "generation_mode": generation_mode,
            "requested_project_dir": str(requested_project_dir.resolve()),
            "created_at": now(),
        },
    )
    return path


def load_run_context(run_dir: pathlib.Path | str) -> dict[str, Any]:
    path = pathlib.Path(run_dir).resolve() / "artifacts" / "run_context.json"
    if not path.exists():
        return {}
    try:
        doc = load_json(path)
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def repair_prompt_budget_config() -> dict[str, int]:
    def read_int(name: str, default: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(os.environ.get(name, default))))
        except (TypeError, ValueError):
            return default

    return {
        "max_context_chars_per_repair": read_int("CGNK_MAX_CONTEXT_CHARS_PER_REPAIR", 16000, 4000, 60000),
        "max_files_per_repair": read_int("CGNK_MAX_FILES_PER_REPAIR", 3, 1, 20),
        "max_output_files_per_repair": read_int("CGNK_MAX_OUTPUT_FILES_PER_REPAIR", 2, 1, 10),
    }


def provider_review_issues(provider_review: dict[str, Any]) -> list[Any]:
    structured = provider_review.get("structured_blockers", []) if isinstance(provider_review, dict) else []
    if isinstance(structured, list) and structured:
        return [item for item in structured if item]
    issues = provider_review.get("issues", []) if isinstance(provider_review, dict) else []
    if isinstance(issues, list):
        return [item if isinstance(item, dict) else str(item) for item in issues if str(item).strip()]
    if str(issues).strip():
        return [str(issues)]
    return []


def component_ownership_table() -> dict[str, dict[str, list[str]]]:
    return {
        "foundation": {
            "allowed": ["package.json", "package-lock.json", "pyproject.toml", "requirements.txt", "vite.config.*", "tsconfig.json", ".gitignore"],
            "forbidden": ["src/app.js", "src/main.js", "src/App.*", "app.py", "main.py", "server.py", "routes/**", "tests/**", "README.md", "TEST_PLAN.md", "TEST_REPORT.md"],
        },
        "frontend": {
            "allowed": ["src/**", "public/**", "index.html", "frontend/**", "app/**"],
            "owns": ["src/app.js", "src/main.js", "src/App.*"],
        },
        "backend": {
            "allowed": ["app.py", "main.py", "server.py", "backend/**", "api/**", "data/**"],
            "owns": ["backend/**", "api/**", "data/**", "app.py", "main.py", "server.py"],
        },
        "tests": {
            "allowed": ["tests/**", "test_*.py", "*.spec.*", "*.test.*"],
            "owns": ["tests/**", "test_*.py", "*.spec.*", "*.test.*"],
        },
        "docs": {
            "allowed": ["README.md", "TEST_PLAN.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "docs/**"],
            "owns": ["README.md", "TEST_PLAN.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"],
        },
        "media": {
            "allowed": ["scripts/capture*", "screenshots/**", "media/**", "demo/**", "assets/demo/**", "assets/screenshots/**"],
            "owns": ["scripts/capture*", "screenshots/**", "media/**", "demo/**", "assets/demo/**", "assets/screenshots/**"],
        },
    }


def path_matches_pattern(path: str, pattern: str) -> bool:
    rel = str(path or "").replace("\\", "/").strip()
    pat = str(pattern or "").replace("\\", "/").strip()
    if not rel or not pat:
        return False
    if pat.endswith("/**"):
        return rel == pat[:-3].rstrip("/") or rel.startswith(pat[:-3].rstrip("/") + "/")
    if "*" in pat:
        return pathlib.PurePosixPath(rel).match(pat)
    return rel == pat


def legal_owner_for_path(path: str, components: list[str] | None = None, ownership_table: dict[str, dict[str, list[str]]] | None = None) -> str:
    table = ownership_table or component_ownership_table()
    component_filter = {str(item).strip() for item in (components or []) if str(item).strip()}
    for component_id, rules in table.items():
        if component_filter and component_id not in component_filter:
            continue
        for pattern in rules.get("owns", []):
            if path_matches_pattern(path, pattern):
                return component_id
    for component_id, rules in table.items():
        if component_filter and component_id not in component_filter:
            continue
        for pattern in rules.get("allowed", []):
            if path_matches_pattern(path, pattern):
                return component_id
    return component_filter.pop() if len(component_filter) == 1 else ""


def component_path_allowed(component_id: str, path: str, ownership_table: dict[str, dict[str, list[str]]] | None = None) -> bool:
    table = ownership_table or component_ownership_table()
    rules = table.get(str(component_id or "").strip(), {})
    return any(path_matches_pattern(path, pattern) for pattern in list(rules.get("owns", [])) + list(rules.get("allowed", [])))


def parse_review_blocker(blocker: Any, component_pipeline: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(blocker, dict):
        kind = str(blocker.get("kind", "generic") or "generic")
        files = [str(path).replace("\\", "/").strip() for path in blocker.get("files", []) if str(path).strip()] if isinstance(blocker.get("files", []), list) else []
        component = str(blocker.get("component", "") or "").strip()
        components = [component] if component else []
        message = str(blocker.get("message", "") or blocker)
        if kind in {"missing_entry_html", "missing_entrypoint"}:
            return {"kind": "missing_entry_html", "raw": message, "components": components or ["frontend"], "files_hint": files or ["index.html"], "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
        if kind in {"frontend_backend_mismatch", "status_mismatch", "api_contract_mismatch"}:
            return {"kind": "frontend_backend_integration_missing", "raw": message, "components": components or ["frontend", "backend"], "files_hint": files or ["src/app.js", "backend/**"], "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
        if kind in {"missing_backend_deps", "module_mismatch", "broken_runtime"}:
            return {"kind": kind, "raw": message, "components": components or ["foundation", "backend"], "files_hint": files or ["package.json"], "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
        if kind in {"broken_tests", "weak_tests"}:
            return {"kind": "broken_tests", "raw": message, "components": components or ["tests"], "files_hint": files or ["tests/**"], "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
        if kind in {"fake_artifact_claim", "fake_zip_behavior", "placeholder_claim"}:
            return {"kind": "fake_artifact_claim", "raw": message, "components": components or ["docs", "media"], "files_hint": files or ["TEST_REPORT.md", "README.md", "scripts/**"], "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
        if kind in {"inaccurate_test_report_claims", "inaccurate_test_report"}:
            return {"kind": "inaccurate_test_report_claims", "raw": message, "components": components or ["docs"], "files_hint": files or ["TEST_REPORT.md"], "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
        return {"kind": "generic_semantic_blocker", "raw": message, "components": components, "files_hint": files, "severity": blocker.get("severity", "hard"), "repair_hint": blocker.get("repair_hint", "")}
    text = str(blocker or "").strip()
    lowered = text.lower()
    components = [str(row.get("id", "")).strip() for row in (component_pipeline or {}).get("components", []) if isinstance(row, dict)]
    conflict = re.search(r"component file conflict:\s*([^\s]+)\s+from\s+([A-Za-z0-9_.-]+)\s+and\s+([A-Za-z0-9_.-]+)", text, flags=re.I)
    if conflict:
        path = conflict.group(1).strip()
        owners = [conflict.group(2).strip(), conflict.group(3).strip()]
        legal = legal_owner_for_path(path, owners) or legal_owner_for_path(path, components)
        return {
            "kind": "component_file_conflict",
            "raw": text,
            "path": path,
            "components": owners,
            "legal_owner": legal,
            "illegal_owners": [item for item in owners if legal and item != legal],
            "severity": "hard",
        }
    if any(token in lowered for token in ("localstorage", "local storage")) and any(token in lowered for token in ("api", "backend", "后端")):
        return {
            "kind": "frontend_backend_integration_missing",
            "raw": text,
            "components": [item for item in ("frontend", "backend") if not components or item in components],
            "files_hint": ["src/app.js", "app.py", "server.py"],
            "severity": "hard",
        }
    if any(token in lowered for token in ("commonjs", "require")) and any(token in lowered for token in ("esm", "type=module", "module")):
        return {
            "kind": "module_system_mismatch",
            "raw": text,
            "components": [item for item in ("foundation", "tests", "frontend") if not components or item in components],
            "files_hint": ["package.json", "tests/**", "src/**"],
            "severity": "hard",
        }
    return {
        "kind": "generic_semantic_blocker",
        "raw": text,
        "components": route_semantic_review_blockers([text], component_pipeline or {"components": [{"id": item} for item in components]}) if components else [],
        "severity": "hard",
    }


def component_files_from_checkpoints(checkpoint_dir: pathlib.Path | None) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    if checkpoint_dir is None or not checkpoint_dir.exists():
        return out
    for path in checkpoint_dir.glob("*_files.json"):
        try:
            doc = load_json(path)
        except Exception:
            continue
        component_id = str(doc.get("component_id", "")).strip()
        if not component_id:
            continue
        files = doc.get("files", [])
        if isinstance(files, list):
            out[component_id] = [item for item in files if isinstance(item, dict)]
    return out


def concrete_repair_target_files(actions: list[dict[str, Any]]) -> list[str]:
    files: list[str] = []
    for action in actions:
        path = str(action.get("path", "")).replace("\\", "/").strip()
        if path and "*" not in path and not path.endswith("/"):
            files.append(path)
    return sorted(set(files))


def repair_actions_for_component(repair_plan: dict[str, Any], component_id: str) -> list[dict[str, Any]]:
    return [
        action
        for action in repair_plan.get("provider_actions", [])
        if isinstance(action, dict) and str(action.get("component", "")).strip() == component_id
    ]


def repair_plan_file_level_components(repair_plan: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for component_id in repair_plan_provider_components(repair_plan):
        actions = repair_actions_for_component(repair_plan, component_id)
        if concrete_repair_target_files(actions):
            out.add(component_id)
    return out


def build_component_repair_prompt(component_id: str, plan: dict[str, Any]) -> str:
    target_files = [
        str(action.get("path", ""))
        for action in plan.get("provider_actions", [])
        if str(action.get("component", "")) == component_id and str(action.get("path", "")).strip()
    ]
    concrete_targets = concrete_repair_target_files(
        [action for action in plan.get("provider_actions", []) if isinstance(action, dict) and str(action.get("component", "")) == component_id]
    )
    budget = repair_prompt_budget_config()
    owner_lines = [f"You are regenerating {component_id}_files only.", f"Do not modify files owned by other components."]
    if target_files:
        owner_lines.append("Target files: " + ", ".join(sorted(set(target_files))))
    if concrete_targets:
        plural = "file" if len(concrete_targets) == 1 else "files"
        owner_lines.extend(
            [
                "File-level repair mode.",
                f"Regenerate only {', '.join(concrete_targets)}.",
                f"Keep every other {component_id} file unchanged.",
                f"Return exactly {len(concrete_targets)} {plural} unless explicitly required by these blockers.",
            ]
        )
    if component_id == "frontend":
        owner_lines.extend(
            [
                "You own src/app.js when it is part of this project.",
                "The frontend must use fetch to call backend API endpoints for create/update/delete/status/filter actions.",
                "Do not use localStorage as the primary persistence layer.",
            ]
        )
    owner_lines.extend(
        [
            "Do not add TODO, placeholder, or future-work claims.",
            "Return only files belonging to this component.",
            "Repair prompt budget: "
            + json.dumps(
                {
                    "max_context_chars_per_repair": budget["max_context_chars_per_repair"],
                    "max_files_per_repair": budget["max_files_per_repair"],
                    "max_output_files_per_repair": min(budget["max_output_files_per_repair"], max(1, len(concrete_targets) or budget["max_output_files_per_repair"])),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            "Old blockers that must disappear: " + "; ".join(str(item) for item in plan.get("must_disappear_blockers", [])),
            "Validation checks: " + "; ".join(str(item) for item in plan.get("validation_checks", [])),
        ]
    )
    return "\n".join(line for line in owner_lines if line.strip())


def compile_repair_plan(
    blockers: list[str],
    component_files: dict[str, list[dict[str, str]]] | None,
    ownership_table: dict[str, dict[str, list[str]]] | None = None,
    component_pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    table = ownership_table or component_ownership_table()
    parsed = [parse_review_blocker(item, component_pipeline) for item in blockers]
    root_causes: list[str] = []
    deterministic_actions: list[dict[str, Any]] = []
    provider_actions: list[dict[str, Any]] = []
    validation_checks: list[str] = []
    affected_components: set[str] = set()
    affected_files: set[str] = set()
    must_disappear: list[str] = []

    for item in parsed:
        kind = str(item.get("kind", "generic_semantic_blocker"))
        must_disappear.append(str(item.get("raw", "")))
        if kind == "component_file_conflict":
            root_causes.append("component_ownership_violation")
            path = str(item.get("path", ""))
            legal = str(item.get("legal_owner", ""))
            affected_files.add(path)
            for component_id in item.get("components", []):
                affected_components.add(str(component_id))
            for owner in item.get("illegal_owners", []):
                deterministic_actions.append({"action": "remove_file_from_component", "component": owner, "path": path})
            if legal:
                provider_actions.append(
                    {
                        "component": legal,
                        "path": path,
                        "instruction": f"{legal}_files owns {path}; implement this file here and do not duplicate it from other components.",
                    }
                )
                affected_components.add(legal)
            validation_checks.extend(["no_duplicate_paths", f"{path}_owned_by_{legal}" if legal else f"{path}_single_owner"])
            if path.startswith("src/"):
                validation_checks.append("foundation_has_no_business_source")
        elif kind == "frontend_backend_integration_missing":
            root_causes.append("frontend_backend_integration_missing")
            affected_components.update(str(component) for component in item.get("components", []))
            affected_files.update(str(path) for path in item.get("files_hint", []))
            hinted = [str(path) for path in item.get("files_hint", []) if str(path).strip()]
            if hinted:
                for path in hinted:
                    owner = legal_owner_for_path(path, ["frontend", "backend"]) or ("frontend" if path.startswith(("src/", "app/", "frontend/")) else "backend")
                    provider_actions.append(
                        {
                            "component": owner,
                            "path": path,
                            "instruction": str(item.get("repair_hint", "") or "Align frontend API usage and backend routes/status enum/persistence contract."),
                        }
                    )
            else:
                provider_actions.extend(
                    [
                        {
                            "component": "frontend",
                            "path": "src/app.js",
                            "instruction": "Frontend must call backend API endpoints for create/update/delete/status/filter actions and must not use localStorage as primary persistence.",
                        },
                        {
                            "component": "backend",
                            "path": "backend/**",
                            "instruction": "Backend must expose API routes and local JSON file persistence used by the frontend.",
                        },
                    ]
                )
            validation_checks.extend(["frontend_uses_fetch_api", "backend_json_persistence"])
        elif kind == "module_system_mismatch":
            root_causes.append("module_system_mismatch")
            affected_components.update(str(component) for component in item.get("components", []))
            affected_files.update(str(path) for path in item.get("files_hint", []))
            deterministic_actions.append({"action": "normalize_module_system"})
            provider_actions.append({"component": "tests", "path": "tests/**", "instruction": "Use module syntax that matches package.json and source files."})
            validation_checks.append("module_system_consistent")
        elif kind in {"missing_entry_html", "broken_runtime", "missing_backend_deps", "broken_tests", "fake_artifact_claim", "inaccurate_test_report_claims", "module_mismatch"}:
            root_causes.append(kind)
            files_hint = [str(path) for path in item.get("files_hint", []) if str(path).strip()]
            for path in files_hint:
                affected_files.add(path)
            components_for_item = [str(component) for component in item.get("components", []) if str(component).strip()]
            if not components_for_item:
                components_for_item = route_semantic_review_blockers([str(item.get("raw", ""))], component_pipeline or {})
            for component_id in components_for_item:
                affected_components.add(component_id)
                target_paths = files_hint or [""]
                for path in target_paths:
                    provider_actions.append(
                        {
                            "component": component_id,
                            "path": path,
                            "instruction": str(item.get("repair_hint", "") or item.get("raw", "") or f"Repair {kind}."),
                        }
                    )
            if kind == "missing_entry_html":
                validation_checks.append("frontend_entry_html_exists")
            elif kind in {"missing_backend_deps", "module_mismatch", "broken_runtime"}:
                validation_checks.append("runtime_dependencies_and_module_system_consistent")
            elif kind == "broken_tests":
                validation_checks.append("tests_match_actual_runtime_contract")
            elif kind == "fake_artifact_claim":
                validation_checks.append("no_fake_zip_or_media_claims_provider_side")
            elif kind == "inaccurate_test_report_claims":
                validation_checks.append("test_report_contains_only_executed_evidence")
        else:
            root_causes.append("semantic_review_blocker")
            for component_id in item.get("components", []):
                affected_components.add(str(component_id))
                provider_actions.append({"component": str(component_id), "path": "", "instruction": str(item.get("raw", ""))})

    for action in provider_actions:
        component_id = str(action.get("component", ""))
        if component_id:
            action["repair_prompt"] = build_component_repair_prompt(component_id, {
                "provider_actions": provider_actions,
                "validation_checks": validation_checks,
                "must_disappear_blockers": must_disappear,
            })
    return {
        "root_causes": sorted(set(root_causes)),
        "parsed_blockers": parsed,
        "deterministic_actions": deterministic_actions,
        "provider_actions": provider_actions,
        "validation_checks": sorted(set(validation_checks)),
        "affected_components": sorted(affected_components),
        "affected_files": sorted(affected_files),
        "must_disappear_blockers": [item for item in must_disappear if item],
        "ownership_table": table,
    }


def rewrite_component_checkpoint_files(checkpoint_dir: pathlib.Path | None, component_id: str, files: list[dict[str, str]]) -> None:
    if checkpoint_dir is None:
        return
    checkpoint_path, files_path = provider_component_checkpoint_paths(checkpoint_dir, component_id)
    if files_path.exists():
        files_doc = load_json(files_path)
        files_doc["files"] = files
        files_doc["updated_at"] = now()
        write_json(files_path, files_doc)
    if checkpoint_path.exists():
        checkpoint = load_json(checkpoint_path)
        parsed = checkpoint.get("parsed_result", {})
        if isinstance(parsed, dict):
            parsed["files"] = files
            checkpoint["parsed_result"] = parsed
        checkpoint["file_count"] = len(files)
        checkpoint["updated_at"] = now()
        write_json(checkpoint_path, checkpoint)


def apply_deterministic_repair_actions(
    component_files: dict[str, list[dict[str, str]]],
    repair_plan: dict[str, Any],
    *,
    checkpoint_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    changed: list[dict[str, Any]] = []
    mark_for_regeneration: set[str] = set()
    invalidated: list[str] = []
    for action in repair_plan.get("deterministic_actions", []):
        if not isinstance(action, dict):
            continue
        kind = str(action.get("action", ""))
        component_id = str(action.get("component", "")).strip()
        path = str(action.get("path", "")).replace("\\", "/").strip()
        if kind == "remove_file_from_component" and component_id and path:
            before = component_files.get(component_id, [])
            after = [item for item in before if str(item.get("path", "")).replace("\\", "/") != path]
            if len(after) != len(before):
                component_files[component_id] = after
                rewrite_component_checkpoint_files(checkpoint_dir, component_id, after)
                changed.append({"action": kind, "component": component_id, "path": path})
        elif kind == "move_file_to_component" and component_id and path:
            target = str(action.get("target_component", "")).strip()
            if target:
                source_files = component_files.get(component_id, [])
                moving = [item for item in source_files if str(item.get("path", "")).replace("\\", "/") == path]
                component_files[component_id] = [item for item in source_files if str(item.get("path", "")).replace("\\", "/") != path]
                existing = {str(item.get("path", "")).replace("\\", "/") for item in component_files.get(target, [])}
                component_files.setdefault(target, []).extend(item for item in moving if str(item.get("path", "")).replace("\\", "/") not in existing)
                rewrite_component_checkpoint_files(checkpoint_dir, component_id, component_files.get(component_id, []))
                rewrite_component_checkpoint_files(checkpoint_dir, target, component_files.get(target, []))
                changed.append({"action": kind, "component": component_id, "target_component": target, "path": path})
        elif kind == "delete_placeholder_doc_lines" and component_id:
            filtered: list[dict[str, str]] = []
            for item in component_files.get(component_id, []):
                content = str(item.get("content", ""))
                lines = [
                    line
                    for line in content.splitlines()
                    if not any(token in line.lower() for token in ("todo", "placeholder", "占位", "后续补齐"))
                ]
                filtered.append({**item, "content": "\n".join(lines) + ("\n" if content.endswith("\n") else "")})
            component_files[component_id] = filtered
            rewrite_component_checkpoint_files(checkpoint_dir, component_id, filtered)
            changed.append({"action": kind, "component": component_id})
        elif kind == "normalize_module_system":
            changed.append({"action": kind, "status": "planned"})
        elif kind == "invalidate_component_checkpoint" and component_id:
            invalidated.extend(remove_provider_component_checkpoints(checkpoint_dir, [component_id]))
            changed.append({"action": kind, "component": component_id})
        elif kind == "mark_component_for_regeneration" and component_id:
            mark_for_regeneration.add(component_id)
            changed.append({"action": kind, "component": component_id})
    return {
        "changed": changed,
        "invalidated_checkpoints": invalidated,
        "mark_for_regeneration": sorted(mark_for_regeneration),
        "component_files": component_files,
    }


def repeated_repair_blocker(issues: list[str], attempted_repairs: list[dict[str, Any]]) -> str:
    issue_text = "\n".join(str(item) for item in issues)
    for repair in attempted_repairs:
        plan = repair.get("repair_plan", {}) if isinstance(repair, dict) else {}
        for blocker in plan.get("must_disappear_blockers", []):
            if str(blocker).strip() and str(blocker).strip() in issue_text:
                return str(blocker)
    return ""


def write_repair_invariant_failure(
    run_dir: pathlib.Path,
    blocker: str,
    attempted_repairs: list[dict[str, Any]],
    checkpoint_dir: pathlib.Path | None,
) -> dict[str, Any]:
    diagnostics = {
        "status": "blocked",
        "stage": "repair_invariant_check",
        "reason": "repair did not remove original blocker",
        "repeated_blocker": blocker,
        "attempts": len(attempted_repairs),
        "attempted_repairs": attempted_repairs,
        "checkpoint_files": list_checkpoint_files(checkpoint_dir),
        "materialized": False,
        "project_dir": None,
    }
    write_json(run_dir / "artifacts" / "provider_semantic_review_failure.json", diagnostics)
    return diagnostics


def provider_transport_error_info(error_text: str) -> dict[str, Any]:
    text = str(error_text or "")
    error_type = check_connectivity._provider_error_type(text)
    retryable = provider_component_error_is_retryable(error_type, text)
    if error_type in {"PROVIDER_TRANSPORT_UNSTABLE", "PROVIDER_RETRYABLE_HTTP"} or "http 522" in text.lower() or "timeout" in text.lower():
        match = re.search(r"component\s+([A-Za-z0-9_.-]+)", text)
        attempts = re.search(r"transport attempts:\s*(\d+)", text, flags=re.I) or re.search(r"transport_attempts=(\d+)", text, flags=re.I)
        return {
            "is_transport": True,
            "provider_error_type": error_type,
            "retryable": retryable,
            "failed_component": match.group(1) if match else "",
            "transport_attempts": int(attempts.group(1)) if attempts else 0,
            "provider_headers": extract_provider_error_headers(text),
        }
    return {"is_transport": False, "provider_error_type": error_type, "retryable": retryable, "failed_component": ""}


def extract_provider_error_headers(error_text: str) -> dict[str, str]:
    match = re.search(r"provider_headers=(\{.*?\})(?:\]|,|\s*$)", str(error_text or ""))
    if not match:
        return {}
    try:
        doc = json.loads(match.group(1))
    except Exception:
        return {}
    allowed = {"cf-ray", "x-trace-id", "x-request-id", "request-id", "date", "server"}
    return {str(key).lower(): str(value) for key, value in doc.items() if str(key).lower() in allowed}


def write_repair_prompt_file(
    run_dir: pathlib.Path,
    *,
    failed_component: str,
    attempt: int,
    instructions: list[str],
) -> str:
    prompt_dir = run_dir / "artifacts" / "provider_components" / "repair_prompts"
    path = prompt_dir / f"{provider_component_checkpoint_id(failed_component)}_repair_attempt_{attempt}.txt"
    write_text(path, "\n\n".join(str(item).strip() for item in instructions if str(item).strip()) + "\n")
    return str(path.resolve())


def build_pending_repair_context(
    *,
    run_dir: pathlib.Path,
    raw_user_goal: str,
    model: str,
    base_url: str,
    repair_plan: dict[str, Any],
    failed_component: str,
    attempt: int,
    semantic_repair_attempts_used: int,
    transport_attempt: int,
    provider_prompt_path: str,
    requested_model: str = "",
    selected_model: str = "",
    model_routing_reason: str = "",
    last_transport_error: str = "",
    next_retry_model: str = "",
) -> dict[str, Any]:
    if not repair_plan:
        diagnostic = {
            "status": "pending_repair_plan_unavailable",
            "stage": "provider_semantic_repair",
            "raw_user_goal": raw_user_goal,
            "model": model,
            "requested_model": requested_model or model,
            "selected_model": selected_model or model,
            "model_routing_reason": model_routing_reason,
            "last_transport_error": last_transport_error,
            "next_retry_model": next_retry_model or selected_model or model,
            "base_url": base_url,
            "reason": "repair_plan_empty",
            "created_at": now(),
        }
        write_json(run_dir / "artifacts" / "pending_repair_plan_unavailable.json", diagnostic)
        return diagnostic
    actions = repair_actions_for_component(repair_plan, failed_component) if failed_component else []
    return {
        "status": "pending",
        "stage": "provider_semantic_repair",
        "raw_user_goal": raw_user_goal,
        "model": model,
        "requested_model": requested_model or model,
        "selected_model": selected_model or model,
        "model_routing_reason": model_routing_reason,
        "last_transport_error": last_transport_error,
        "next_retry_model": next_retry_model or selected_model or model,
        "base_url": base_url,
        "failed_component": failed_component,
        "affected_components": repair_plan.get("affected_components", []),
        "affected_files": repair_plan.get("affected_files", []),
        "blockers": repair_plan.get("must_disappear_blockers", []),
        "repair_plan": repair_plan,
        "provider_actions": repair_plan.get("provider_actions", []),
        "target_files": concrete_repair_target_files(actions),
        "repair_level": "file" if concrete_repair_target_files(actions) else "component",
        "provider_prompt_path": provider_prompt_path,
        "checkpoint_summary_path": str((run_dir / "artifacts" / "provider_components" / "component_checkpoint_summary.json").resolve()),
        "attempt": attempt,
        "semantic_repair_attempts_used": semantic_repair_attempts_used,
        "transport_attempt": transport_attempt,
        "created_at": now(),
    }


def write_pending_repair_context(path: pathlib.Path, context: dict[str, Any]) -> None:
    if not context or context == {}:
        write_json(
            path.parent / "pending_repair_plan_unavailable.json",
            {"status": "pending_repair_plan_unavailable", "stage": "provider_semantic_repair", "reason": "empty_context", "created_at": now()},
        )
        return
    write_json(path, context)


def archive_completed_pending_repair(run_dir: pathlib.Path) -> None:
    path = run_dir / "artifacts" / "pending_repair_plan.json"
    if not path.exists():
        return
    try:
        doc = load_json(path)
    except Exception:
        return
    doc["status"] = "completed"
    doc["completed_at"] = now()
    write_json(run_dir / "artifacts" / "pending_repair_plan.completed.json", doc)
    path.unlink()


def write_provider_transport_blocked_failure(
    run_dir: pathlib.Path,
    requested_project_dir: pathlib.Path,
    error_text: str,
    pending_repair_plan: dict[str, Any],
    attempted_repairs: list[dict[str, Any]],
    checkpoint_dir: pathlib.Path | None,
    *,
    failed_component: str = "",
) -> dict[str, Any]:
    info = provider_transport_error_info(error_text)
    pending_path = run_dir / "artifacts" / "pending_repair_plan.json"
    transport_attempts = int(info.get("transport_attempts") or 0)
    effective_pending = pending_repair_plan
    if not effective_pending:
        effective_pending = {
            "status": "pending_repair_plan_unavailable",
            "stage": "provider_semantic_repair",
            "reason": "transport_failed_before_repair_plan_available",
            "provider_error_type": info.get("provider_error_type", ""),
            "retryable": bool(info.get("retryable")),
            "failed_component": failed_component or str(info.get("failed_component", "")),
            "transport_attempts": transport_attempts,
            "created_at": now(),
        }
    formal_model_contract.append_model_call(
        run_dir,
        stage="repair",
        provider="api_agent",
        model=str(effective_pending.get("selected_model") or effective_pending.get("model") or ""),
        requested=True,
        executed=True,
        status="timeout" if "504" in str(error_text) or "timeout" in str(error_text).lower() else "failed",
        used_in_formal_chain=True,
        input_value=effective_pending,
        output_value="",
        error=error_text,
        metadata={"failed_component": failed_component or str(info.get("failed_component", ""))},
    )
    fallback_evidence = attempt_formal_local_model_fallback(
        run_dir=run_dir,
        failed_stage="repair",
        error_text=error_text,
        failed_component=failed_component or str(info.get("failed_component", "")),
        pending_repair_plan=effective_pending,
    )
    diagnostics = {
        "status": "blocked",
        "stage": "provider_semantic_repair",
        "block_reason": "provider_transport_failed",
        "provider_error": error_text,
        "provider_error_type": info.get("provider_error_type", ""),
        "retryable": bool(info.get("retryable")),
        "failed_component": failed_component or str(info.get("failed_component", "")),
        "provider_headers": info.get("provider_headers", {}),
        "pending_repair_plan_path": str(pending_path.resolve()) if pending_path.exists() else "",
        "transport_attempts": transport_attempts,
        "pending_repair_plan": effective_pending,
        "provider_fallback_evidence": fallback_evidence,
        "attempted_repairs": attempted_repairs,
        "semantic_repair_attempts": len(attempted_repairs),
        "checkpoint_files": list_checkpoint_files(checkpoint_dir),
        "materialized": False,
        "project_dir": None,
        "requested_project_dir": str(requested_project_dir.resolve()),
    }
    artifacts = run_dir / "artifacts"
    write_json(artifacts / "provider_semantic_review_failure.json", diagnostics)
    write_json(artifacts / "provider_fallback_evidence.json", fallback_evidence)
    write_pending_repair_context(artifacts / "pending_repair_plan.json", effective_pending)
    return diagnostics


def attempt_formal_local_model_fallback(
    *,
    run_dir: pathlib.Path,
    failed_stage: str,
    error_text: str,
    failed_component: str,
    pending_repair_plan: dict[str, Any],
) -> dict[str, Any]:
    compact_plan = {
        "root_causes": pending_repair_plan.get("root_causes", []),
        "parsed_blockers": pending_repair_plan.get("parsed_blockers", [])[:5] if isinstance(pending_repair_plan.get("parsed_blockers", []), list) else [],
        "affected_components": pending_repair_plan.get("affected_components", []),
        "affected_files": pending_repair_plan.get("affected_files", []),
        "must_disappear_blockers": pending_repair_plan.get("must_disappear_blockers", [])[:8] if isinstance(pending_repair_plan.get("must_disappear_blockers", []), list) else [],
        "raw_user_goal": str(pending_repair_plan.get("raw_user_goal", ""))[:1200],
    }
    prompt = json.dumps(
        {
            "task": "formal_provider_transport_fallback",
            "failed_stage": failed_stage,
            "failed_component": failed_component,
            "provider_error": str(error_text)[:2000],
            "pending_repair_plan": compact_plan,
            "required_output": "Return concise JSON repair or planning guidance for continuing the formal chain.",
        },
        ensure_ascii=False,
        indent=2,
    )
    requested_model = str(os.environ.get("CGNK_OLLAMA_MODEL", "") or "local_model_router").strip()
    fallback_timeout = int(str(os.environ.get("CGNK_LOCAL_MODEL_FALLBACK_TIMEOUT", "180") or "180"))
    try:
        result = local_model_router.call_text_task(
            "pipeline_planner",
            "You are a formal CGKN fallback planner. Return concise JSON only.",
            prompt,
            timeout=fallback_timeout,
        )
    except Exception as exc:
        result = {"ok": False, "provider": "local_model_router", "model": requested_model, "error": str(exc)}
    ok = bool(result.get("ok"))
    provider = str(result.get("provider") or "local_model_router")
    model = str(result.get("model") or requested_model)
    text = str(result.get("text") or "")
    status = "ok" if ok else "failed"
    formal_model_contract.append_model_call(
        run_dir,
        stage=failed_stage,
        provider="local_model_router" if provider == "ollama" else provider,
        model=model,
        requested=True,
        executed=True,
        status=status,
        used_in_formal_chain=True,
        input_value=prompt,
        output_value=text,
        error=None if ok else str(result.get("error", "local_model_fallback_failed")),
        metadata={"fallback_for": "api_agent", "failed_component": failed_component},
    )
    return {
        "primary_provider": "api_agent",
        "primary_status": "failed_504" if "504" in str(error_text) else "failed_transport",
        "fallback_provider": "local_model_router",
        "fallback_model": model,
        "fallback_status": status,
        "formal_chain_continued": ok,
        "requires_reverify": True,
        "delivery_pass_allowed_without_reverify": False,
        "error": "" if ok else str(result.get("error", "local_model_fallback_failed")),
        "output_preview": text[:500] if ok else "",
    }


def load_pending_repair_plan(run_dir: pathlib.Path | str) -> dict[str, Any]:
    path = pathlib.Path(run_dir).resolve() / "artifacts" / "pending_repair_plan.json"
    if not path.exists():
        return {}
    try:
        doc = load_json(path)
    except Exception:
        return {}
    if not isinstance(doc, dict):
        return {}
    nested = doc.get("repair_plan")
    if isinstance(nested, dict):
        merged = dict(nested)
        merged.update({key: value for key, value in doc.items() if key not in {"repair_plan"}})
        if "provider_actions" not in merged and isinstance(nested.get("provider_actions"), list):
            merged["provider_actions"] = nested["provider_actions"]
        return merged
    return doc


def repair_plan_component_instructions(repair_plan: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for action in repair_plan.get("provider_actions", []):
        if not isinstance(action, dict):
            continue
        component_id = str(action.get("component", "")).strip()
        if not component_id:
            continue
        prompt = str(action.get("repair_prompt") or action.get("instruction") or "").strip()
        if prompt:
            out.setdefault(component_id, []).append(prompt)
    return out


def repair_plan_provider_components(repair_plan: dict[str, Any]) -> list[str]:
    components = {
        str(action.get("component", "")).strip()
        for action in repair_plan.get("provider_actions", [])
        if isinstance(action, dict) and str(action.get("component", "")).strip()
    }
    if str(repair_plan.get("stage", "")) == "component_file_generation" and str(repair_plan.get("component", "")).strip():
        components.add(str(repair_plan.get("component", "")).strip())
    return sorted(components)


def route_semantic_review_blockers(issues: list[str], component_pipeline: dict[str, Any]) -> list[str]:
    components = [str(row.get("id", "")).strip() for row in component_pipeline.get("components", []) if isinstance(row, dict)]
    available = {item for item in components if item}
    if not available:
        return []
    affected: set[str] = set()
    text = "\n".join(issues).lower()

    def add_if_available(*ids: str) -> None:
        for component_id in ids:
            if component_id in available:
                affected.add(component_id)

    for component_id in available:
        if component_id.lower() in text:
            affected.add(component_id)
    if any(token in text for token in ("localstorage", "local storage", "fetch", "api", "前端", "ui", "browser", "浏览器")):
        add_if_available("frontend")
    if any(token in text for token in ("backend", "后端", "json", "persist", "persistence", "data/tasks", "文件落盘", "持久化")):
        add_if_available("backend")
    if any(token in text for token in ("test", "coverage", "crud", "filter", "筛选", "自动化测试", "测试")):
        add_if_available("tests")
    if any(token in text for token in ("readme", "docs", "documentation", "placeholder", "todo", "占位", "后续", "补齐", "文档")):
        add_if_available("docs")
    if any(token in text for token in ("commonjs", "esm", "module", "require", "import", "package.json", "type=module")):
        add_if_available("foundation", "frontend", "backend", "tests")
    if any(token in text for token in ("screenshot", "video", "mp4", "webm", "截图", "视频", "media")):
        # Provider should provide honest capture commands/scripts. Real binary capture belongs to post-build finalize.
        add_if_available("media", "docs")
    if not affected:
        affected.update(available)
    return [component_id for component_id in components if component_id in affected]


def repair_instructions_for_components(issues: list[str], affected_components: list[str], attempt_number: int) -> dict[str, list[str]]:
    blocker_text = "\n".join(f"- {issue}" for issue in issues) or "- semantic review failed without detailed issues"
    common = [
        f"Semantic review repair attempt {attempt_number}. Fix these blockers without reducing scope:\n{blocker_text}",
        "Do not claim screenshots, videos, zip files, or test results already exist unless the project creates them during post-build/runtime commands.",
        "README, TEST_PLAN, and TEST_REPORT content must be concrete and must not contain placeholder/TODO/后续补齐/占位 wording.",
    ]
    by_component: dict[str, list[str]] = {}
    for component_id in affected_components:
        rules = list(common)
        if component_id == "frontend":
            rules.extend(
                [
                    "Frontend must call backend APIs with fetch for task CRUD, status changes, filtering, and JSON-backed persistence; do not implement the main persistence only with localStorage.",
                    "Expose stable selectors or routes that screenshot/video capture can exercise after the app starts locally.",
                ]
            )
        elif component_id == "backend":
            rules.extend(
                [
                    "Backend must provide local JSON file persistence and API endpoints used by the frontend.",
                    "Keep module syntax consistent with package.json and the tests.",
                ]
            )
        elif component_id == "tests":
            rules.extend(
                [
                    "Tests must execute real CRUD, status filtering, and JSON persistence/API behavior.",
                    "Use commands that can run in the generated project without external network access after dependencies are prepared.",
                ]
            )
        elif component_id == "docs":
            rules.extend(
                [
                    "Docs must document the actual startup/test/capture/package commands and must not describe required artifacts as future/manual placeholders.",
                    "Document that real screenshots/video are generated by post-build finalize or capture commands, not by provider JSON text.",
                ]
            )
        elif component_id == "foundation":
            rules.extend(
                [
                    "package.json module settings must match the generated JavaScript source and tests.",
                    "Provide runnable scripts for start, test, screenshot/video capture when applicable, and final bundle preparation without claiming a zip already exists.",
                ]
            )
        elif component_id == "media":
            rules.extend(
                [
                    "Provide honest screenshot/video capture scripts or commands only; do not claim binary artifacts already exist in provider output.",
                    "If video capture requires ffmpeg or browser tooling, expose a command and a clear blocked/warning path for post-build finalize.",
                ]
            )
        by_component[component_id] = rules
    return by_component


def write_rejected_project_preview(preview_dir: pathlib.Path, files: list[dict[str, str]]) -> list[str]:
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for item in files:
        rel = str(item.get("path", "")).replace("\\", "/").strip()
        if not rel:
            continue
        target = (preview_dir / rel).resolve()
        if not str(target).lower().startswith(str(preview_dir.resolve()).lower()):
            continue
        write_text(target, str(item.get("content", "")))
        written.append(str(target))
    write_json(
        preview_dir / "_CGNK_REJECTED_PREVIEW_DO_NOT_DELIVER.json",
        {
            "status": "rejected_preview_only",
            "delivery_artifact": False,
            "packager_input": False,
            "reason": "provider_semantic_review_failed",
        },
    )
    return written


def list_checkpoint_files(checkpoint_dir: pathlib.Path | None) -> list[str]:
    if checkpoint_dir is None or not checkpoint_dir.exists():
        return []
    return [str(path.resolve()) for path in sorted(checkpoint_dir.glob("*.json")) if path.is_file()]


def write_provider_semantic_review_failure(
    run_dir: pathlib.Path,
    requested_project_dir: pathlib.Path,
    provider_review: dict[str, Any],
    attempted_repairs: list[dict[str, Any]],
    checkpoint_dir: pathlib.Path | None,
    files: list[dict[str, str]],
    *,
    provider_status: str = "blocked",
) -> dict[str, Any]:
    artifacts_dir = run_dir / "artifacts"
    preview_dir = artifacts_dir / "rejected_project_preview"
    preview_files = write_rejected_project_preview(preview_dir, files) if files else []
    remaining_blockers = provider_review_issues(provider_review)
    diagnostics = {
        "status": "blocked",
        "stage": "provider_semantic_review",
        "provider_status": provider_status,
        "semantic_review_status": str(provider_review.get("status", "unknown")) if isinstance(provider_review, dict) else "unknown",
        "attempts": 1 + len(attempted_repairs),
        "blockers": remaining_blockers,
        "attempted_repairs": attempted_repairs,
        "remaining_blockers": remaining_blockers,
        "checkpoint_files": list_checkpoint_files(checkpoint_dir),
        "materialized": False,
        "project_dir": None,
        "requested_project_dir": str(requested_project_dir.resolve()),
        "rejected_project_preview": str(preview_dir.resolve()) if preview_files else "",
        "rejected_project_preview_files": preview_files,
        "why_project_dir_was_not_materialized": "Provider semantic review still failed after configured repair attempts; rejected preview is debug-only and cannot be packaged or delivered.",
    }
    write_json(artifacts_dir / "provider_semantic_review_failure.json", diagnostics)
    return diagnostics


def run_provider_semantic_review_with_repair(
    *,
    user_goal: str,
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    component_pipeline: dict[str, Any],
    repair_errors: list[str],
    model: str,
    timeout: int,
    internal_context: str,
    deadline: float | ProgressDeadline,
    run_dir: pathlib.Path,
    out_dir: pathlib.Path,
    result_path: pathlib.Path,
    max_repair_attempts: int,
    phase_log_path: pathlib.Path | str,
    initial_repair_plan: dict[str, Any] | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    checkpoint_dir = run_dir / "artifacts" / "provider_components"
    attempted_repairs: list[dict[str, Any]] = []
    component_repair_instructions: dict[str, list[str]] = {}
    force_components: set[str] = set()
    last_generation: dict[str, Any] = {}
    last_files: list[dict[str, str]] = []
    last_review: dict[str, Any] = {}
    pending_repair_plan = initial_repair_plan or {}
    pending_repair_record: dict[str, Any] | None = None
    if pending_repair_plan:
        component_repair_instructions = repair_plan_component_instructions(pending_repair_plan)
        force_components = set(repair_plan_provider_components(pending_repair_plan))

    for semantic_attempt in range(max_repair_attempts + 1):
        generation_started = time.time()
        append_phase_log(
            phase_log_path,
            "project_generation",
            "started",
            f"Provider project generation semantic attempt {semantic_attempt + 1} started.",
            started_at=generation_started,
        )
        try:
            generation = provider_generate_project_by_components(
                user_goal,
                component_pipeline,
                plan_doc,
                blueprint,
                online_inputs,
                market_research,
                repair_errors,
                model,
                remaining_timeout(deadline, timeout, floor=5, cap=120),
                internal_context=internal_context,
                deadline=deadline,
                checkpoint_dir=checkpoint_dir,
                force_components=force_components,
                component_repair_instructions=component_repair_instructions,
                pending_repair_plan=pending_repair_plan,
                run_dir=run_dir,
                repair_attempt_number=semantic_attempt + 1,
                semantic_repair_attempts_used=len(attempted_repairs),
                model_base_url=provider_base_url_for_diagnostics(),
                routing_policy=routing_policy,
            )
        except (RuntimeError, TimeoutError) as exc:
            issues = [str(exc)]
            transport = provider_transport_error_info(str(exc))
            if transport.get("is_transport"):
                diagnostics = write_provider_transport_blocked_failure(
                    run_dir,
                    out_dir,
                    str(exc),
                    pending_repair_plan,
                    attempted_repairs,
                    checkpoint_dir,
                    failed_component=str(transport.get("failed_component", "")) or (sorted(force_components)[0] if len(force_components) == 1 else ""),
                )
                update_provider_component_checkpoint_summary(
                    checkpoint_dir,
                    {
                        "semantic_review_status": "provider_transport_blocked",
                        "semantic_review_attempts": semantic_attempt + 1,
                        "attempted_repairs": attempted_repairs,
                        "pending_repair_plan": pending_repair_plan,
                        "failure_diagnostics": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
                    },
                )
                return {
                    "status": "blocked",
                    "generation": last_generation,
                    "files": last_files,
                    "provider_review": {
                        "status": "fail",
                        "issues": issues,
                        "review_summary": "Provider transport failed during semantic repair; pending repair plan was preserved for resume.",
                    },
                    "attempted_repairs": attempted_repairs,
                    "diagnostics": diagnostics,
                }
            if semantic_attempt < max_repair_attempts:
                repeated = repeated_repair_blocker(issues, attempted_repairs)
                if repeated:
                    diagnostics = write_repair_invariant_failure(run_dir, repeated, attempted_repairs, checkpoint_dir)
                    return {
                        "status": "blocked",
                        "generation": last_generation,
                        "files": last_files,
                        "provider_review": {"status": "fail", "issues": ["REPAIR_INVARIANT_FAILED", repeated], "review_summary": "Repair invariant failed."},
                        "attempted_repairs": attempted_repairs,
                        "diagnostics": diagnostics,
                    }
                repair_plan = compile_repair_plan(issues, component_files_from_checkpoints(checkpoint_dir), component_pipeline=component_pipeline)
                deterministic_result = apply_deterministic_repair_actions(
                    component_files_from_checkpoints(checkpoint_dir),
                    repair_plan,
                    checkpoint_dir=checkpoint_dir,
                )
                pending_repair_plan = repair_plan
                pending_repair_plan.setdefault("raw_user_goal", user_goal)
                pending_repair_plan.setdefault("component_pipeline", component_pipeline)
                component_repair_instructions = repair_plan_component_instructions(repair_plan)
                force_components = set(repair_plan_provider_components(repair_plan))
                file_level_components = repair_plan_file_level_components(repair_plan)
                to_remove = [item for item in deterministic_result.get("mark_for_regeneration", []) if item not in file_level_components]
                removed = remove_provider_component_checkpoints(checkpoint_dir, to_remove)
                repair_record = {
                    "attempt_number": semantic_attempt + 1,
                    "blockers": issues,
                    "affected_components": sorted(force_components),
                    "regenerated_files": [],
                    "removed_checkpoints": removed,
                    "review_verdict": "component_generation_failed",
                    "repair_instructions": component_repair_instructions,
                    "repair_plan": repair_plan,
                    "deterministic_actions_result": deterministic_result,
                }
                pending_repair_record = repair_record
                repair_errors.append(
                    "provider component generation repair "
                    + json.dumps(
                        {
                            "attempt_number": semantic_attempt + 1,
                            "blockers": issues,
                            "affected_components": sorted(force_components),
                        },
                        ensure_ascii=False,
                    )
                )
                update_provider_component_checkpoint_summary(
                    checkpoint_dir,
                    {
                        "semantic_review_status": "repairing",
                        "semantic_review_attempts": semantic_attempt + 1,
                        "attempted_repairs": attempted_repairs,
                        "pending_repair": repair_record,
                    },
                )
                append_phase_log(
                    phase_log_path,
                    "project_generation",
                    "component_generation_repair_retry",
                    f"Retrying provider components after generation blocker: {', '.join(sorted(force_components)) or 'all'}",
                    sorted(force_components),
                    started_at=generation_started,
                )
                continue
            provider_review = {
                "status": "fail",
                "issues": issues,
                "review_summary": "Provider component generation failed before project-level semantic review could complete.",
            }
            diagnostics = write_provider_semantic_review_failure(
                run_dir,
                out_dir,
                provider_review,
                attempted_repairs,
                checkpoint_dir,
                last_files,
                provider_status="component_generation_failed",
            )
            update_provider_component_checkpoint_summary(
                checkpoint_dir,
                {
                    "semantic_review_status": "blocked",
                    "semantic_review_attempts": semantic_attempt + 1,
                    "attempted_repairs": attempted_repairs,
                    "remaining_blockers": [str(exc)],
                    "failure_diagnostics": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
                },
            )
            append_phase_log(
                phase_log_path,
                "project_generation",
                "blocked",
                f"Provider component generation failed before materialization: {exc}",
                [str(run_dir / "artifacts" / "provider_semantic_review_failure.json")],
                started_at=generation_started,
            )
            return {
                "status": "blocked",
                "generation": last_generation,
                "files": last_files,
                "provider_review": provider_review,
                "attempted_repairs": attempted_repairs,
                "diagnostics": diagnostics,
            }
        if pending_repair_record is not None:
            attempted_repairs.append(pending_repair_record)
            pending_repair_record = None
        if attempted_repairs and force_components:
            regenerated: list[str] = []
            for component_id in sorted(force_components):
                _, files_path = provider_component_checkpoint_paths(checkpoint_dir, component_id)
                if files_path.exists():
                    try:
                        files_doc = load_json(files_path)
                        regenerated.extend(
                            str(item.get("path", ""))
                            for item in files_doc.get("files", [])
                            if isinstance(item, dict) and str(item.get("path", "")).strip()
                        )
                    except Exception:
                        continue
            attempted_repairs[-1]["regenerated_files"] = sorted(set(regenerated))
        files = validate_provider_files(generation)
        try:
            provider_review = provider_review_project(
                user_goal,
                plan_doc,
                blueprint,
                online_inputs,
                market_research,
                generation,
                files,
                model,
                remaining_timeout(deadline, timeout, floor=5, cap=90),
                internal_context=internal_context,
                phase_log_path=phase_log_path,
                routing_policy=routing_policy,
            )
        except Exception as exc:
            transport = provider_transport_error_info(str(exc))
            if not transport.get("is_transport"):
                last_request = last_provider_request_event(phase_log_path)
                request_stage = str(last_request.get("stage", "provider_semantic_review") or "provider_semantic_review")
                failed_component = str(last_request.get("component", "") or "")
                issue = {
                    "kind": "provider_review_format_error",
                    "severity": "warning",
                    "component": failed_component,
                    "files": [],
                    "message": f"provider semantic review failed before returning strict JSON: {exc}",
                    "repair_hint": "Do not treat provider review formatting failure as a generated-project fact blocker; materialize candidate only after static fact checks pass.",
                }
                provider_review = {
                    "status": "fail",
                    "issues": [issue],
                    "structured_blockers": [issue],
                    "review_summary": "Provider semantic review returned an unusable response; generated files are preserved for candidate review.",
                }
                diagnostics = write_provider_semantic_review_failure(
                    run_dir,
                    out_dir,
                    provider_review,
                    attempted_repairs,
                    checkpoint_dir,
                    files,
                    provider_status="provider_semantic_review_failed",
                )
                update_provider_component_checkpoint_summary(
                    checkpoint_dir,
                    {
                        "semantic_review_status": "blocked",
                        "semantic_review_attempts": semantic_attempt + 1,
                        "attempted_repairs": attempted_repairs,
                        "remaining_blockers": [issue],
                        "failure_diagnostics": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
                    },
                )
                append_phase_log(
                    phase_log_path,
                    "provider_semantic_review",
                    "provider_review_failed",
                    f"Provider semantic review failed during {request_stage}: {exc}",
                    [str(run_dir / "artifacts" / "provider_semantic_review_failure.json")],
                    started_at=generation_started,
                )
                return {
                    "status": "blocked",
                    "generation": generation,
                    "files": files,
                    "provider_review": provider_review,
                    "attempted_repairs": attempted_repairs,
                    "diagnostics": diagnostics,
                }
            last_request = last_provider_request_event(phase_log_path)
            request_stage = str(last_request.get("stage", "provider_semantic_review") or "provider_semantic_review")
            request_prompt_chars = int(last_request.get("prompt_chars") or 0)
            requested_model = str(last_request.get("requested_model") or model)
            selected_model = str(last_request.get("selected_model") or model)
            next_route = choose_provider_model(
                request_stage,
                request_prompt_chars,
                requested_model,
                routing_policy,
                last_error=str(exc),
            )
            pending_context = dict(pending_repair_plan or {})
            pending_context.update(
                {
                    "status": "pending",
                    "stage": request_stage,
                    "reason": "provider_transport_failed_during_semantic_review",
                    "raw_user_goal": user_goal,
                    "component_pipeline": component_pipeline,
                    "requested_model": requested_model,
                    "selected_model": selected_model,
                    "model_routing_reason": str(last_request.get("model_routing_reason", "")),
                    "last_transport_error": str(exc),
                    "next_retry_model": str(next_route.get("selected_model") or selected_model),
                    "payload_mode": str(last_request.get("payload_mode", "")),
                    "prompt_chars": request_prompt_chars,
                    "failed_component": str(last_request.get("component", "") or transport.get("failed_component", "")),
                    "provider_error_type": str(transport.get("provider_error_type", "")),
                    "retryable": bool(transport.get("retryable")),
                    "updated_at": now(),
                }
            )
            pending_context.setdefault("created_at", now())
            diagnostics = write_provider_transport_blocked_failure(
                run_dir,
                out_dir,
                str(exc),
                pending_context,
                attempted_repairs,
                checkpoint_dir,
                failed_component=str(pending_context.get("failed_component", "")),
            )
            update_provider_component_checkpoint_summary(
                checkpoint_dir,
                {
                    "semantic_review_status": "provider_transport_blocked",
                    "semantic_review_attempts": semantic_attempt + 1,
                    "attempted_repairs": attempted_repairs,
                    "pending_repair_plan": pending_context,
                    "failure_diagnostics": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
                },
            )
            append_phase_log(
                phase_log_path,
                "provider_semantic_review",
                "provider_transport_blocked",
                f"Provider semantic review transport failed: {transport.get('provider_error_type', '')}",
                [str(run_dir / "artifacts" / "provider_semantic_review_failure.json")],
                started_at=generation_started,
            )
            return {
                "status": "blocked",
                "generation": generation,
                "files": files,
                "provider_review": {"status": "blocked", "issues": ["PROVIDER_TRANSPORT_BLOCKED"], "review_summary": str(exc)},
                "attempted_repairs": attempted_repairs,
                "diagnostics": diagnostics,
            }
        last_generation = generation
        last_files = files
        last_review = provider_review
        issues = provider_review_issues(provider_review)
        append_phase_log(
            phase_log_path,
            "provider_semantic_review",
            str(provider_review.get("status", "unknown")),
            f"Provider semantic review attempt {semantic_attempt + 1}: {str(provider_review.get('review_summary', ''))[:500]}",
            issues[:20],
            started_at=generation_started,
        )
        if str(provider_review.get("status", "")).lower() == "pass":
            if pending_repair_plan:
                archive_completed_pending_repair(run_dir)
            update_provider_component_checkpoint_summary(
                checkpoint_dir,
                {
                    "semantic_review_status": "pass",
                    "semantic_review_attempts": semantic_attempt + 1,
                    "attempted_repairs": attempted_repairs,
                },
            )
            mark_generation_progress(deadline, "provider_review", "Provider semantic review passed.", [str(result_path)])
            return {
                "status": "pass",
                "generation": generation,
                "files": files,
                "provider_review": provider_review,
                "attempted_repairs": attempted_repairs,
            }
        if semantic_attempt >= max_repair_attempts:
            diagnostics = write_provider_semantic_review_failure(
                run_dir,
                out_dir,
                provider_review,
                attempted_repairs,
                checkpoint_dir,
                files,
            )
            update_provider_component_checkpoint_summary(
                checkpoint_dir,
                {
                    "semantic_review_status": "blocked",
                    "semantic_review_attempts": semantic_attempt + 1,
                    "attempted_repairs": attempted_repairs,
                    "remaining_blockers": issues,
                    "failure_diagnostics": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
                },
            )
            append_phase_log(
                phase_log_path,
                "provider_semantic_review",
                "blocked",
                "Provider semantic review remained blocked after repair attempts.",
                [str(run_dir / "artifacts" / "provider_semantic_review_failure.json")],
            )
            return {
                "status": "blocked",
                "generation": generation,
                "files": files,
                "provider_review": provider_review,
                "attempted_repairs": attempted_repairs,
                "diagnostics": diagnostics,
            }
        repeated = repeated_repair_blocker(issues, attempted_repairs)
        if repeated:
            diagnostics = write_repair_invariant_failure(run_dir, repeated, attempted_repairs, checkpoint_dir)
            return {
                "status": "blocked",
                "generation": generation,
                "files": files,
                "provider_review": {"status": "fail", "issues": ["REPAIR_INVARIANT_FAILED", repeated], "review_summary": "Repair invariant failed."},
                "attempted_repairs": attempted_repairs,
                "diagnostics": diagnostics,
            }
        repair_plan = compile_repair_plan(issues, component_files_from_checkpoints(checkpoint_dir), component_pipeline=component_pipeline)
        deterministic_result = apply_deterministic_repair_actions(
            component_files_from_checkpoints(checkpoint_dir),
            repair_plan,
            checkpoint_dir=checkpoint_dir,
        )
        pending_repair_plan = repair_plan
        pending_repair_plan.setdefault("raw_user_goal", user_goal)
        pending_repair_plan.setdefault("component_pipeline", component_pipeline)
        component_repair_instructions = repair_plan_component_instructions(repair_plan)
        force_components = set(repair_plan_provider_components(repair_plan))
        file_level_components = repair_plan_file_level_components(repair_plan)
        to_remove = [item for item in deterministic_result.get("mark_for_regeneration", []) if item not in file_level_components]
        removed = remove_provider_component_checkpoints(checkpoint_dir, to_remove)
        repair_record = {
            "attempt_number": semantic_attempt + 1,
            "blockers": issues,
            "affected_components": sorted(force_components),
            "regenerated_files": [],
            "removed_checkpoints": removed,
            "review_verdict": str(provider_review.get("status", "unknown")),
            "repair_instructions": component_repair_instructions,
            "repair_plan": repair_plan,
            "deterministic_actions_result": deterministic_result,
        }
        pending_repair_record = repair_record
        repair_errors.append(
            "provider semantic review repair "
            + json.dumps(
                {
                    "attempt_number": semantic_attempt + 1,
                    "blockers": issues,
                    "affected_components": sorted(force_components),
                },
                ensure_ascii=False,
            )
        )
        update_provider_component_checkpoint_summary(
            checkpoint_dir,
            {
                "semantic_review_status": "repairing",
                "semantic_review_attempts": semantic_attempt + 1,
                "attempted_repairs": attempted_repairs,
                "pending_repair": repair_record,
            },
        )
        append_phase_log(
            phase_log_path,
            "provider_semantic_review",
            "semantic_repair_retry",
            f"Retrying provider components after semantic review blockers: {', '.join(sorted(force_components)) or 'all'}",
            sorted(force_components),
        )
    return {
        "status": "blocked",
        "generation": last_generation,
        "files": last_files,
        "provider_review": last_review,
        "attempted_repairs": attempted_repairs,
    }


def make_generated_image_preview(out_dir: pathlib.Path, input_path: pathlib.Path, goal: str) -> dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        return {"status": "failed", "reason": f"pillow not available: {exc}"}

    def font(size: int) -> Any:
        for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    out_dir.mkdir(parents=True, exist_ok=True)
    preview = out_dir / "example_generated_preview.png"
    canvas = Image.new("RGB", (1280, 720), (34, 38, 56))
    draw = ImageDraw.Draw(canvas)

    # Locally generated VN-style background and character layers. The online input is used
    # as a small reference swatch only; it is not copied as the output.
    for y in range(720):
        ratio = y / 720
        color = (
            int(42 + 50 * ratio),
            int(58 + 72 * ratio),
            int(105 + 80 * ratio),
        )
        draw.line((0, y, 1280, y), fill=color)
    draw.rectangle((0, 520, 1280, 720), fill=(54, 72, 84))
    draw.polygon([(0, 520), (360, 300), (700, 520)], fill=(44, 61, 92))
    draw.polygon([(430, 520), (820, 260), (1280, 520)], fill=(51, 67, 98))
    draw.ellipse((930, 80, 1100, 250), fill=(250, 210, 120))
    draw.rectangle((190, 365, 390, 640), fill=(102, 75, 86))
    draw.polygon([(190, 365), (290, 260), (390, 365)], fill=(135, 84, 91))
    draw.rectangle((230, 420, 270, 470), fill=(246, 218, 165))
    draw.rectangle((310, 420, 350, 470), fill=(246, 218, 165))

    # Character sprite layer.
    draw.ellipse((535, 175, 665, 305), fill=(245, 205, 180))
    draw.pieslice((520, 140, 680, 310), 180, 360, fill=(80, 52, 72))
    draw.rounded_rectangle((500, 305, 700, 610), radius=64, fill=(180, 74, 116))
    draw.polygon([(500, 380), (415, 520), (505, 535)], fill=(245, 205, 180))
    draw.polygon([(700, 380), (785, 520), (695, 535)], fill=(245, 205, 180))
    draw.ellipse((570, 230, 586, 246), fill=(35, 39, 50))
    draw.ellipse((620, 230, 636, 246), fill=(35, 39, 50))
    draw.arc((575, 255, 640, 285), 0, 180, fill=(120, 58, 70), width=3)

    title_font = font(42)
    body_font = font(24)
    small_font = font(18)
    draw.text((48, 42), "Generated VN Preview", fill=(255, 255, 255), font=title_font)
    draw.text((50, 100), "Agent-created background + character preview from story intent", fill=(230, 235, 245), font=body_font)
    draw.text((50, 650), "This output is generated by the runtime drawing pipeline; the online image is only a reference input.", fill=(230, 235, 245), font=small_font)

    reference_path = ""
    try:
        ref = Image.open(input_path).convert("RGB")
        ref.thumbnail((220, 160))
        draw.rounded_rectangle((1000, 450, 1240, 670), radius=14, fill=(255, 255, 255), outline=(210, 220, 235), width=2)
        canvas.paste(ref, (1010 + (220 - ref.width) // 2, 490))
        draw.text((1015, 462), "Reference input", fill=(40, 52, 75), font=small_font)
        reference_path = str(input_path)
    except Exception:
        pass

    canvas.save(preview)
    return {
        "status": "pass" if preview.exists() and preview.stat().st_size > 0 else "failed",
        "image_preview": str(preview),
        "reference_input": reference_path,
        "generation_method": "local PIL composition from story intent; not a copied input image",
    }


def make_workflow_demo_video(out_dir: pathlib.Path, image_path: pathlib.Path, goal: str) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "skipped", "reason": "ffmpeg not available"}
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        return {"status": "skipped", "reason": f"pillow not available: {exc}"}

    slide_dir = out_dir / "workflow_slides"
    slide_dir.mkdir(parents=True, exist_ok=True)
    try:
        base_image = Image.open(image_path).convert("RGB")
    except Exception as exc:
        return {"status": "failed", "reason": f"cannot open preview image: {exc}", "image": str(image_path)}

    def font(size: int) -> Any:
        for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    title_font = font(42)
    body_font = font(24)
    small_font = font(18)
    frames: list[pathlib.Path] = []
    steps = [
        ("1. Input Interface", "Story: a quiet VN opening scene\nNeed: background + character preview\nAction: prepare generation request"),
        ("2. Generate Assets", "The assistant turns the story input into image prompts,\nthen starts the image preview workflow."),
        ("3. Preview Generated Image", "A real PNG preview artifact is available for inspection.\nThis frame is generated by the local runtime, not copied from input."),
        ("4. Delivery Artifacts", "Outputs prepared for Telegram:\n- still PNG preview\n- MP4 workflow demo\n- example report with source metadata"),
    ]

    for idx, (title, body) in enumerate(steps, 1):
        canvas = Image.new("RGB", (1280, 720), (246, 248, 252))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((44, 40, 1236, 680), radius=24, fill=(255, 255, 255), outline=(214, 222, 235), width=2)
        draw.text((80, 76), title, fill=(30, 42, 64), font=title_font)
        draw.text((82, 142), body, fill=(62, 74, 96), font=body_font, spacing=8)
        draw.rounded_rectangle((80, 310, 560, 610), radius=14, fill=(243, 246, 250), outline=(210, 218, 230), width=2)
        draw.text((110, 334), "VN Assistant", fill=(39, 53, 78), font=body_font)
        draw.rounded_rectangle((110, 390, 520, 440), radius=10, fill=(255, 255, 255), outline=(180, 190, 205), width=1)
        draw.text((130, 402), "Enter story / prompt...", fill=(95, 105, 120), font=small_font)
        draw.rounded_rectangle((110, 470, 300, 522), radius=10, fill=(37, 99, 235))
        draw.text((136, 484), "Generate", fill=(255, 255, 255), font=body_font)

        preview = base_image.copy()
        preview.thumbnail((520, 360))
        px = 670 + max(0, (520 - preview.width) // 2)
        py = 240 + max(0, (360 - preview.height) // 2)
        draw.rounded_rectangle((640, 196, 1200, 628), radius=16, fill=(241, 244, 249), outline=(205, 214, 226), width=2)
        canvas.paste(preview, (px, py))
        draw.text((660, 212), "Preview Artifact", fill=(39, 53, 78), font=body_font)
        draw.text((80, 634), f"Step {idx}/4 - workflow demo, not only final result", fill=(94, 105, 122), font=small_font)
        path = slide_dir / f"workflow_step_{idx:02d}.png"
        canvas.save(path)
        frames.append(path)

    list_path = slide_dir / "workflow_frames.txt"
    lines = []
    for frame in frames:
        lines.append(f"file '{frame.as_posix()}'")
        lines.append("duration 2")
    lines.append(f"file '{frames[-1].as_posix()}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    video = out_dir / "workflow_demo.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-vf",
        "format=yuv420p",
        "-r",
        "24",
        "-an",
        "-c:v",
        "libx264",
        str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return {
        "status": "pass" if video.exists() and video.stat().st_size > 0 else "failed",
        "video": str(video) if video.exists() else "",
        "slides": [str(path) for path in frames],
        "returncode": proc.returncode,
        "stderr_tail": proc.stderr[-800:],
    }


def provider_project_usage_plan(
    goal: str,
    project_dir: pathlib.Path,
    generated_files: list[str],
    online_inputs: dict[str, Any],
    example_outputs: dict[str, Any],
    model: str,
    timeout: int,
    *,
    phase_log_path: pathlib.Path | str | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    system = """You are an agent that plans how to actually use a generated local project.
Return strict JSON only. Do not use shell strings; commands must be argv arrays.

Goal: decide how an agent should run or open the project, what input to provide, what output to produce, and what browser actions to record.
Prefer a browser flow when the project has a local web UI. If the project is CLI/API-only, plan command-line usage and artifact checks.
Do not plan destructive commands. Do not require installing large external dependencies. Use existing generated files and runtime example artifacts.
Inspect the provided source excerpts before choosing commands. The start_command must actually keep the app/server running and listen at wait_url.
For FastAPI apps without an explicit if __name__ == "__main__": uvicorn.run(...) block, use ["python", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"].
For Flask apps without app.run(...), use ["python", "-m", "flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", "5000"] or the matching module name.
Use pre_commands only for narrow setup such as ["python", "-m", "pip", "install", "-r", "requirements.txt"] when requirements.txt is present.

JSON shape:
{
  "summary": "what the agent will demonstrate",
  "pre_commands": [["python", "scripts/generate_assets.py"]],
  "start_command": ["python", "app.py"],
  "wait_url": "http://127.0.0.1:5000/",
  "browser_steps": [
    {"action": "goto", "url": "http://127.0.0.1:5000/"},
    {"action": "fill", "selector": "textarea,input[name='story']", "text": "example story"},
    {"action": "click", "selector": "button"},
    {"action": "wait", "seconds": 1}
  ],
  "artifact_expectations": ["what output should be visible or created"]
}
If there is no usable browser flow, set browser_steps to [] and explain in summary.
"""
    file_summaries = []
    for rel in generated_files[:80]:
        path = project_dir / rel
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            text = ""
        file_summaries.append({"path": rel, "content_excerpt": text})
    payload = {
        "goal": goal,
        "project_dir": str(project_dir),
        "generated_files": generated_files,
        "file_summaries": file_summaries,
        "online_input_examples": online_inputs,
        "example_outputs": example_outputs,
    }
    raw = provider_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        model,
        min(timeout, 20),
        max_attempts=2,
        stage="lightweight_summary",
        max_tokens=12000,
        payload_mode="usage_plan",
        phase_log_path=phase_log_path,
        routing_policy=routing_policy,
    )
    doc = parse_json_object(raw)
    if not isinstance(doc.get("pre_commands", []), list):
        doc["pre_commands"] = []
    if not isinstance(doc.get("browser_steps", []), list):
        doc["browser_steps"] = []
    if not isinstance(doc.get("start_command", []), list):
        doc["start_command"] = []
    return doc


def argv_is_allowed(argv: list[Any]) -> bool:
    if not argv or not all(isinstance(item, str) and item.strip() for item in argv):
        return False
    exe = pathlib.PurePath(argv[0]).name.lower()
    if exe in {"python", "python.exe", "py", "py.exe", "node", "node.exe", "npm", "npm.cmd"}:
        return True
    if exe in {"pip", "pip.exe", "pip3", "pip3.exe"}:
        return len(argv) >= 4 and argv[1:4] == ["install", "-r", "requirements.txt"]
    return False


def normalize_allowed_argv(argv: list[str]) -> list[str]:
    exe = pathlib.PurePath(argv[0]).name.lower()
    if exe in {"python", "python.exe", "py", "py.exe"}:
        return [sys.executable, *argv[1:]]
    if exe in {"pip", "pip.exe", "pip3", "pip3.exe"}:
        return [sys.executable, "-m", "pip", *argv[1:]]
    if exe in {"node", "node.exe"}:
        return [shutil.which("node") or argv[0], *argv[1:]]
    if exe in {"npm", "npm.cmd"}:
        return [shutil.which("npm.cmd") or shutil.which("npm") or argv[0], *argv[1:]]
    return argv


def run_allowed_command(argv: list[str], cwd: pathlib.Path, timeout: int = 120) -> dict[str, Any]:
    if not argv_is_allowed(argv):
        return {"status": "skipped", "reason": "command not allowed", "argv": argv}
    exe = pathlib.PurePath(argv[0]).name.lower()
    if exe in {"pip", "pip.exe", "pip3", "pip3.exe"} or (exe in {"python", "python.exe", "py", "py.exe"} and len(argv) >= 5 and argv[1:4] == ["-m", "pip", "install"]):
        return {
            "status": "pass",
            "skipped": True,
            "reason": "dependency install skipped to avoid mutating the shared runtime environment",
            "argv": argv,
        }
    normalized = normalize_allowed_argv(argv)
    try:
        proc = subprocess.run(normalized, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return {
            "status": "pass" if proc.returncode == 0 else "failed",
            "argv": argv,
            "executed_argv": normalized,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-1200:],
            "stderr_tail": proc.stderr[-1200:],
        }
    except Exception as exc:
        return {"status": "failed", "argv": argv, "error": str(exc)}


def normalize_usage_plan_placeholders(value: Any, project_dir: pathlib.Path, run_dir: pathlib.Path) -> Any:
    project_dir = project_dir.resolve()
    run_dir = run_dir.resolve()
    try:
        project_uri = project_dir.as_uri()
    except ValueError:
        project_uri = "file:///" + project_dir.as_posix().lstrip("/")
    replacements = {
        "file://{project_dir}": project_uri,
        "{project_dir_uri}": project_uri,
        "{project_dir}": str(project_dir),
        "{project_dir_posix}": project_dir.as_posix(),
        "{run_dir}": str(run_dir),
        "{run_dir_posix}": run_dir.as_posix(),
    }
    if isinstance(value, str):
        text = value
        for marker, replacement in replacements.items():
            text = text.replace(marker, replacement)
        return text
    if isinstance(value, list):
        return [normalize_usage_plan_placeholders(item, project_dir, run_dir) for item in value]
    if isinstance(value, dict):
        return {key: normalize_usage_plan_placeholders(item, project_dir, run_dir) for key, item in value.items()}
    return value


def wait_for_url(url: str, timeout: int = 25) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except Exception:
            time.sleep(1)
    return False


def kill_windows_process_tree(pid: int) -> None:
    script = f"""
$seen = @{{}}
function Stop-Tree([int]$Id) {{
  if ($seen.ContainsKey($Id)) {{ return }}
  $seen[$Id] = $true
  Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq $Id }} | ForEach-Object {{ Stop-Tree ([int]$_.ProcessId) }}
  Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
}}
Stop-Tree {pid}
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=15)


def detect_browser_error_text(text: str) -> str:
    lowered = text.lower()
    markers = [
        "traceback",
        "internal server error",
        "jinja2.exceptions",
        "werkzeug",
        "undefinederror",
        "debugger caught an exception",
        "500 internal",
    ]
    for marker in markers:
        if marker in lowered:
            return marker
    return ""


def run_project_usage_agent(
    goal: str,
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    generated_files: list[str],
    online_inputs: dict[str, Any],
    example_outputs: dict[str, Any],
    model: str,
    timeout: int,
    *,
    allow_model_usage_planning: bool = False,
    phase_log_path: pathlib.Path | str | None = None,
    deadline: float | ProgressDeadline | None = None,
    routing_policy: ProviderModelRoutingPolicy | None = None,
) -> dict[str, Any]:
    usage_dir = run_dir / "agent_usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    usage_started = time.time()
    append_phase_log(phase_log_path, "usage_planning", "started", "Building usage plan.", started_at=usage_started)
    project_type = str(online_inputs.get("project_type", "")) if isinstance(online_inputs, dict) else ""
    write_json(
        usage_dir / "usage_planning_diagnostics.json",
        {
            "kind": "UsagePlanningDiagnostics",
            "created_at": now(),
            "status": "started",
            "allow_model_usage_planning": allow_model_usage_planning,
            "project_type": project_type,
            "project_dir": str(project_dir),
        },
    )
    if allow_model_usage_planning:
        try:
            append_phase_log(phase_log_path, "usage_planning_model", "started", "Model usage planning started with short retry budget.", started_at=usage_started)
            plan_timeout = remaining_timeout(deadline, min(timeout, 20), floor=5, cap=20) if deadline else min(timeout, 20)
            plan = provider_project_usage_plan(
                goal,
                project_dir,
                generated_files,
                online_inputs,
                example_outputs,
                model,
                plan_timeout,
                phase_log_path=phase_log_path,
                routing_policy=routing_policy,
            )
            plan["planner"] = "model_with_local_fallback"
            plan["uses_model"] = True
            plan["requires_model"] = True
            plan["selected_provider"] = "api_agent"
            plan["selected_model"] = model
            plan["formal_chain_bound"] = True
            append_phase_log(phase_log_path, "usage_planning_model", "completed", "Model usage planning returned a plan.", started_at=usage_started)
        except Exception as exc:
            append_phase_log(phase_log_path, "usage_planning_model", "failed", f"Model usage planning failed; using local fallback: {exc}", started_at=usage_started)
            plan = local_usage_planner.create_usage_plan(project_dir, project_type)
            plan["fallback_reason"] = f"model usage planning failed: {exc}"
    else:
        append_phase_log(phase_log_path, "usage_planning_local", "started", "Local deterministic usage planning started.", started_at=usage_started)
        plan = local_usage_planner.create_usage_plan(project_dir, project_type)
        append_phase_log(phase_log_path, "usage_planning_local", "completed", "Local deterministic usage planning completed.", started_at=usage_started)
    plan.setdefault("requires_model", True)
    plan.setdefault("formal_chain_bound", bool(plan.get("uses_model")))
    formal_records = [
        row
        for row in formal_model_contract.read_ledger(run_dir)
        if formal_model_contract.formal_record(row)
    ]
    if formal_records:
        last_model_record = formal_records[-1]
        plan["uses_model"] = True
        plan["requires_model"] = True
        plan["formal_chain_bound"] = True
        plan.setdefault("model_evidence_source", "model_call_ledger")
        plan.setdefault("selected_provider", str(last_model_record.get("provider", "")))
        plan.setdefault("selected_model", str(last_model_record.get("model", "")))
    if plan.get("uses_model") and not plan.get("selected_provider"):
        plan["selected_provider"] = "api_agent"
        plan["selected_model"] = model
    plan = normalize_usage_plan_placeholders(plan, project_dir, run_dir)
    write_json(usage_dir / "usage_plan.json", plan)
    append_phase_log(phase_log_path, "usage_planning", "artifact_written", "usage_plan.json written.", [str(usage_dir / "usage_plan.json")], started_at=usage_started)
    mark_generation_progress(deadline, "usage_planning", "Usage planning artifacts written.", [str(usage_dir / "usage_plan.json")])
    runtime_check = local_usage_planner.create_runtime_check(project_dir, plan)
    visual_evidence_plan = local_usage_planner.create_visual_evidence_plan(project_dir, plan)
    write_json(usage_dir / "runtime_check.json", runtime_check)
    write_json(usage_dir / "visual_evidence_plan.json", visual_evidence_plan)
    write_json(
        usage_dir / "usage_planning_diagnostics.json",
        {
            "kind": "UsagePlanningDiagnostics",
            "created_at": now(),
            "status": "completed",
            "allow_model_usage_planning": allow_model_usage_planning,
            "project_type": project_type,
            "planner": plan.get("planner", ""),
            "uses_model": plan.get("uses_model", False),
            "requires_model": plan.get("requires_model", True),
            "formal_chain_bound": plan.get("formal_chain_bound", False),
            "run_mode": plan.get("run_mode", ""),
            "project_dir": str(project_dir),
        },
    )
    append_phase_log(
        phase_log_path,
        "usage_planning",
        "completed",
        "Usage plan written.",
        [str(usage_dir / "usage_plan.json")],
        started_at=usage_started,
    )
    append_phase_log(
        phase_log_path,
        "runtime_check",
        "completed",
        "Runtime check written.",
        [str(usage_dir / "runtime_check.json")],
    )
    append_phase_log(
        phase_log_path,
        "visual_evidence",
        "completed",
        "Visual evidence plan written.",
        [str(usage_dir / "visual_evidence_plan.json")],
    )
    mark_generation_progress(
        deadline,
        "visual_evidence",
        "Runtime and visual evidence plans written.",
        [str(usage_dir / "runtime_check.json"), str(usage_dir / "visual_evidence_plan.json")],
    )
    result: dict[str, Any] = {
        "status": "planned",
        "plan": plan,
        "runtime_check": runtime_check,
        "visual_evidence_plan": visual_evidence_plan,
        "events": [],
        "workflow_video": "",
        "screenshots": [],
    }

    for idx, command in enumerate(plan.get("pre_commands", []), 1):
        if isinstance(command, list):
            argv_pre = [str(item) for item in command]
            command_timeout = remaining_timeout(deadline, 180, floor=3, cap=180) if deadline else 180
            command_result = run_allowed_command(argv_pre, project_dir, timeout=command_timeout)
            result["events"].append({"type": "pre_command", "index": idx, **command_result})

    argv = [str(item) for item in plan.get("start_command", [])]
    proc: subprocess.Popen[str] | None = None
    if argv:
        if not argv_is_allowed(argv):
            result["events"].append({"type": "start_skipped", "reason": "command not allowed", "argv": argv})
        else:
            try:
                normalized_argv = normalize_allowed_argv(argv)
                proc = subprocess.Popen(normalized_argv, cwd=str(project_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                result["events"].append({"type": "started", "argv": argv, "executed_argv": normalized_argv, "pid": proc.pid})
            except Exception as exc:
                result["events"].append({"type": "start_failed", "argv": argv, "error": str(exc)})

    wait_url_value = str(plan.get("wait_url", "")).strip()
    wait_url_ok = True
    if wait_url_value:
        wait_timeout = remaining_timeout(deadline, 30, floor=2, cap=30) if deadline else 30
        ok = wait_for_url(wait_url_value, timeout=wait_timeout)
        wait_url_ok = ok
        result["events"].append({"type": "wait_url", "url": wait_url_value, "ok": ok})

    browser_steps = plan.get("browser_steps", [])
    if browser_steps and wait_url_value.startswith("http") and not wait_url_ok:
        result["events"].append(
            {
                "type": "browser_steps_skipped",
                "reason": "wait_url was not reachable; skipping dependent browser actions to avoid repeated selector timeouts",
                "skipped_count": len(browser_steps),
            }
        )
        browser_steps = []
    if browser_steps:
        try:
            from playwright.sync_api import sync_playwright

            video_dir = usage_dir / "browser_video"
            video_dir.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(video_dir))
                page = context.new_page()
                for idx, step in enumerate(browser_steps, 1):
                    if not isinstance(step, dict):
                        continue
                    action = str(step.get("action", "")).lower()
                    try:
                        if action == "goto":
                            step_timeout_ms = (remaining_timeout(deadline, 15, floor=2, cap=15) if deadline else 15) * 1000
                            page.goto(str(step.get("url", wait_url_value)), wait_until="domcontentloaded", timeout=step_timeout_ms)
                        elif action == "fill":
                            selector = str(step.get("selector", "")).strip()
                            if selector:
                                loc = page.locator(selector).first
                                loc.fill(str(step.get("text", "")), timeout=(remaining_timeout(deadline, 5, floor=1, cap=5) if deadline else 5) * 1000)
                        elif action == "click":
                            selector = str(step.get("selector", "")).strip()
                            if selector:
                                page.locator(selector).first.click(timeout=(remaining_timeout(deadline, 5, floor=1, cap=5) if deadline else 5) * 1000)
                        elif action in {"select", "select_option"}:
                            selector = str(step.get("selector", "")).strip()
                            option = str(step.get("option", step.get("value", ""))).strip()
                            if selector and option:
                                page.locator(selector).first.select_option(option, timeout=(remaining_timeout(deadline, 5, floor=1, cap=5) if deadline else 5) * 1000)
                        elif action == "wait":
                            page.wait_for_timeout(int(float(step.get("seconds", 1)) * 1000))
                        elif action in {"wait_for_selector", "assert_visible"}:
                            selector = str(step.get("selector", "")).strip()
                            if selector:
                                page.locator(selector).first.wait_for(state="visible", timeout=(remaining_timeout(deadline, 15, floor=2, cap=15) if deadline else 15) * 1000)
                        elif action == "screenshot":
                            pass
                        shot = usage_dir / f"step_{idx:02d}_{action or 'step'}.png"
                        page.screenshot(path=str(shot), full_page=True)
                        result["screenshots"].append(str(shot))
                        mark_generation_progress(deadline, "visual_evidence", "Browser evidence screenshot captured.", [str(shot)])
                        try:
                            body_text = page.locator("body").inner_text(timeout=1000)
                        except Exception:
                            body_text = ""
                        error_marker = detect_browser_error_text(body_text)
                        if error_marker:
                            result["events"].append(
                                {
                                    "type": "browser_page_error",
                                    "index": idx,
                                    "action": action,
                                    "ok": False,
                                    "marker": error_marker,
                                    "text_excerpt": body_text[:800],
                                    "screenshot": str(shot),
                                }
                            )
                        result["events"].append({"type": "browser_step", "index": idx, "action": action, "ok": True})
                    except Exception as exc:
                        result["events"].append({"type": "browser_step", "index": idx, "action": action, "ok": False, "error": str(exc)})
                context.close()
                browser.close()
            videos = sorted(video_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
            if videos:
                source_video = videos[0]
                mp4 = usage_dir / "agent_project_usage_demo.mp4"
                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg:
                    proc2 = subprocess.run(
                        [ffmpeg, "-y", "-i", str(source_video), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(mp4)],
                        capture_output=True,
                        text=True,
                        timeout=remaining_timeout(deadline, 120, floor=5, cap=120) if deadline else 120,
                    )
                    result["events"].append({"type": "video_convert", "returncode": proc2.returncode, "stderr_tail": proc2.stderr[-600:]})
                    if mp4.exists() and mp4.stat().st_size > 0:
                        result["workflow_video"] = str(mp4)
                if not result["workflow_video"]:
                    result["workflow_video"] = str(source_video)
        except Exception as exc:
            result["events"].append({"type": "browser_usage_failed", "error": str(exc)})

    if proc is not None:
        try:
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if sys.platform.startswith("win"):
                    kill_windows_process_tree(proc.pid)
                else:
                    proc.kill()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", "process did not exit after forced termination"
            result["events"].append({"type": "process_output", "stdout_tail": stdout[-1000:], "stderr_tail": stderr[-1000:]})
        except Exception as exc:
            result["events"].append({"type": "process_cleanup_failed", "error": str(exc)})
    failed_critical = [
        event
        for event in result["events"]
        if event.get("type") in {"wait_url", "browser_step", "browser_page_error"}
        and event.get("ok") is False
        and str(event.get("action", "goto")) in {"", "goto", "fill", "click", "wait_for_selector", "assert_visible", "screenshot"}
    ]
    failed_setup = [
        event
        for event in result["events"]
        if event.get("type") in {"pre_command", "start_skipped", "start_failed"}
        and event.get("status", "failed") != "pass"
    ]
    planned_browser = bool(browser_steps)
    if not planned_browser and plan.get("planner") == "local_deterministic":
        result["status"] = "partial"
    else:
        result["status"] = "pass" if (result.get("workflow_video") and not failed_setup and not failed_critical and (not planned_browser or result.get("screenshots"))) else "failed"
    if failed_setup or failed_critical:
        result["failure_summary"] = (failed_setup + failed_critical)[:8]
    write_json(usage_dir / "agent_usage_report.json", result)
    return result


def make_example_outputs(run_dir: pathlib.Path, online_inputs: dict[str, Any]) -> dict[str, Any]:
    examples = online_inputs.get("examples", []) if isinstance(online_inputs, dict) else []
    if not examples:
        return {"status": "skipped", "reason": "no online input examples"}
    first = examples[0]
    modality = str(first.get("modality", "")).strip().lower()
    input_path = pathlib.Path(str(first.get("local_path", "")))
    if not input_path.exists():
        if modality == "repository_metadata" and first.get("url"):
            out_dir = run_dir / "output_examples"
            out_dir.mkdir(parents=True, exist_ok=True)
            report = out_dir / "example_repository_report.json"
            write_json(
                report,
                {
                    "status": "pass",
                    "kind": "RepositoryMetadataExample",
                    "source": first.get("source"),
                    "url": first.get("url"),
                    "title": first.get("title"),
                    "language": first.get("language"),
                    "stars": first.get("stars"),
                    "description": first.get("description"),
                },
            )
            return {"status": "pass", "modality": modality, "repository_report": str(report)}
        return {"status": "failed", "reason": "online input local file missing", "input": str(input_path), "modality": modality}
    out_dir = run_dir / "output_examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    if modality in {"csv", "json", "pdf", "html_snapshot", "repository_metadata"}:
        report = out_dir / "example_input_report.json"
        payload: dict[str, Any] = {
            "status": "pass",
            "modality": modality,
            "input": str(input_path),
            "bytes": input_path.stat().st_size,
            "source": first.get("source"),
            "url": first.get("url"),
            "title": first.get("title"),
        }
        if modality == "csv":
            with input_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = []
                for idx, row in enumerate(reader):
                    rows.append(row)
                    if idx >= 9:
                        break
                payload["columns"] = reader.fieldnames or []
                payload["sample_rows"] = rows
        elif modality == "json":
            try:
                doc = json.loads(input_path.read_text(encoding="utf-8", errors="replace"))
                payload["top_level_keys"] = sorted(doc.keys())[:30] if isinstance(doc, dict) else []
            except Exception as exc:
                payload["json_parse_error"] = str(exc)
        elif modality == "html_snapshot":
            text = input_path.read_text(encoding="utf-8", errors="replace")
            payload["title"] = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S).group(1).strip() if re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S) else first.get("title")
            payload["text_excerpt"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:500]
        write_json(report, payload)
        return {"status": "pass", "modality": modality, "input": str(input_path), "example_report": str(report)}
    if modality == "image":
        generated_preview = make_generated_image_preview(out_dir, input_path, str(online_inputs.get("goal", "")))
        preview = pathlib.Path(str(generated_preview.get("image_preview", "")))
        if generated_preview.get("status") != "pass" or not preview.exists():
            return {"status": "failed", "reason": "generated image preview failed", "details": generated_preview}
        video_preview = out_dir / "example_image_preview.mp4"
        video_status: dict[str, Any] = {"status": "skipped", "reason": "ffmpeg not available"}
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            import subprocess

            cmd = [
                ffmpeg,
                "-y",
                "-loop",
                "1",
                "-i",
                str(preview),
                "-t",
                "3",
                "-vf",
                "scale=960:-2,format=yuv420p",
                "-r",
                "24",
                "-an",
                "-c:v",
                "libx264",
                str(video_preview),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            video_status = {
                "status": "pass" if video_preview.exists() and video_preview.stat().st_size > 0 else "failed",
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-600:],
            }
        report = out_dir / "example_image_report.json"
        workflow_demo = make_workflow_demo_video(out_dir, preview, str(online_inputs.get("goal", "")))
        workflow_video = pathlib.Path(str(workflow_demo.get("video", "")))
        selected_video = workflow_video if workflow_video.exists() else video_preview
        report_payload = {
            "status": "pass",
            "modality": modality,
            "input": str(input_path),
            "image_preview": str(preview),
            "video_preview": str(selected_video) if selected_video.exists() else "",
            "generated_preview": generated_preview,
            "workflow_demo": workflow_demo,
            "video_status": video_status,
            "bytes": preview.stat().st_size,
        }
        write_json(report, report_payload)
        return {
            "status": "pass",
            "modality": modality,
            "input": str(input_path),
            "image_preview": str(preview),
            "video_preview": str(selected_video) if selected_video.exists() else "",
            "generated_preview": generated_preview,
            "workflow_demo": workflow_demo,
            "example_report": str(report),
        }
    if modality == "audio":
        report = out_dir / "example_audio_report.json"
        write_json(report, {"status": "pass", "modality": modality, "input": str(input_path), "bytes": input_path.stat().st_size})
        return {"status": "pass", "modality": modality, "input": str(input_path), "example_report": str(report)}
    clip = out_dir / "example_highlight_preview.mp4"
    frame = out_dir / "example_highlight_frame.jpg"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "failed", "reason": "ffmpeg not available", "input": str(input_path)}
    import subprocess

    clip_cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-t",
        "6",
        "-vf",
        "scale=960:-2",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(clip),
    ]
    frame_cmd = [ffmpeg, "-y", "-ss", "1", "-i", str(input_path), "-vframes", "1", str(frame)]
    clip_proc = subprocess.run(clip_cmd, capture_output=True, text=True, timeout=120)
    frame_proc = subprocess.run(frame_cmd, capture_output=True, text=True, timeout=60)
    status = "pass" if clip.exists() and clip.stat().st_size > 0 else "failed"
    return {
        "status": status,
        "input": str(input_path),
        "video_preview": str(clip) if clip.exists() else "",
        "frame_preview": str(frame) if frame.exists() else "",
        "clip_returncode": clip_proc.returncode,
        "frame_returncode": frame_proc.returncode,
        "clip_stderr_tail": clip_proc.stderr[-800:],
        "frame_stderr_tail": frame_proc.stderr[-400:],
    }


def make_mermaid() -> str:
    return """flowchart TD
  Goal[Goal] --> Blueprint[Requirement Blueprint]
  Goal --> OnlineInputs[Online Input Examples]
  Blueprint --> MarketResearch[Feature Market Research]
  OnlineInputs --> MarketResearch
  MarketResearch --> Provider[API Provider Project Generation]
  Provider --> Project[Provider Generated Project Files]
  Project --> Validation[Provider Output Validation]
  Validation --> Effect[Effect Report]
"""


def write_runtime_artifacts(
    run_dir: pathlib.Path,
    goal: str,
    plan_doc: dict[str, Any],
    blueprint: dict[str, Any],
    generation: dict[str, Any],
    generated_files: list[str],
    online_inputs: dict[str, Any],
    market_research: dict[str, Any],
    example_outputs: dict[str, Any],
    agent_usage: dict[str, Any],
) -> dict[str, str]:
    artifact_dir = run_dir / "artifacts"
    requirement_blueprint_outputs_dir = artifact_dir / "requirement_blueprint_outputs"
    output_refs = requirement_blueprint.write_requirement_blueprint_outputs(requirement_blueprint_outputs_dir, blueprint)
    project_blueprint = {
        "kind": "ProjectBlueprint",
        "payload": {
            "name": slug(goal),
            "type": str(generation.get("project_type", "provider_generated_project")),
            "summary": str(generation.get("summary", "")),
            "files": generated_files,
            "generator": {"provider": "api", "policy": GENERATION_POLICY},
            "requirement_blueprint": {
                "status": blueprint.get("status", "unknown"),
                "artifact": str(artifact_dir / "requirement_blueprint.json"),
                "outputs_dir": str(requirement_blueprint_outputs_dir),
            },
        },
    }
    artifacts = {
        "pipeline_composition.json": plan_doc,
        "requirement_blueprint.json": {**blueprint, "output_refs": output_refs},
        "project_blueprint.json": project_blueprint,
        "component_pipeline.json": generation.get("component_pipeline", {}),
        "component_generation_report.json": {
            "kind": "ComponentGenerationReport",
            "payload": {
                "strategy": "component_scoped_provider_calls",
                "components": generation.get("components", []),
                "component_errors": generation.get("component_errors", {}),
                "merge_policy": generation.get("component_pipeline", {}).get("merge_policy", {}),
            },
        },
        "generation_trace.json": {
            "kind": "GenerationTrace",
            "payload": {
                "created_at": now(),
                "events": [
                    "pipeline-composed",
                    "requirement-blueprint-generated",
                    "component-pipeline-planned",
                    "market-research-generated",
                    "component-provider-project-generated",
                    "component-files-merged",
                    "provider-output-validated",
                    "provider-project-files-written",
                    "runtime-artifacts-written",
                ],
                "policy": GENERATION_POLICY,
            },
        },
        "self_test_report.json": generation.get("self_test", {"status": "unknown"}),
        "quality_report.json": generation.get("quality_gate", {"status": "unknown"}),
        "provider_semantic_review.json": generation.get("provider_semantic_review", {"status": "unknown"}),
        "online_input_examples.json": online_inputs,
        "market_research.json": market_research,
        "example_output_report.json": example_outputs,
        "agent_usage_report.json": agent_usage,
        "test_graph.json": {
            "kind": "TestGraph",
            "payload": {
                "nodes": [
                    "goal",
                    "online_input_agent",
                    "market_research_agent",
                    "requirement_blueprint",
                    "api_provider_generation",
                    "provider_output_validation",
                    "example_output_generation",
                    "agent_project_usage",
                    "project_files",
                ],
                "manual_checks": generation.get("manual_checks", []),
            },
        },
        "effect_report.json": {
            "kind": "EffectReport",
            "payload": {
                "verdict": "pass",
                "summary": "Project files were generated only by API/provider and validated before writing.",
                "fs_write": True,
                "network": "enabled",
                "provider": "executed",
                "policy": GENERATION_POLICY,
                "online_inputs": online_inputs,
                "market_research": market_research,
                "example_outputs": example_outputs,
                "agent_usage": agent_usage,
            },
        },
    }
    refs: dict[str, str] = {}
    for name, doc in artifacts.items():
        path = artifact_dir / name
        write_json(path, doc)
        refs[name] = str(path)
    write_text(artifact_dir / "test_graph.mmd", make_mermaid())
    refs["test_graph.mmd"] = str(artifact_dir / "test_graph.mmd")
    return refs


def write_provider_long_context_artifacts(
    run_dir: pathlib.Path,
    out_dir: pathlib.Path,
    goal: str,
    artifact_refs: dict[str, str],
    generated_files: list[str],
    *,
    model: str,
) -> dict[str, str]:
    artifact_args = [f"{pathlib.Path(name).stem}={path}" for name, path in sorted(artifact_refs.items()) if name.endswith(".json")]
    user_turn = long_context_state.append_turn(
        argparse.Namespace(
            run_dir=str(run_dir),
            run_id=run_dir.name,
            role="user",
            content=goal,
            turn_id="",
            artifact=[],
            metadata_json="",
        )
    )
    agent_turn = long_context_state.append_turn(
        argparse.Namespace(
            run_dir=str(run_dir),
            run_id=run_dir.name,
            role="agent",
            content=f"API/provider generation completed with model {model}; runtime artifacts, provider review, media previews, and checkpoint state were emitted.",
            turn_id="",
            artifact=artifact_args,
            metadata_json=json.dumps(
                {
                    "id": "api-provider-generation",
                    "stage": "provider_local_pipeline_execution",
                    "decision": "use configured API/provider for project file generation",
                    "rationale": "the run explicitly enabled network, provider, and use-api",
                },
                ensure_ascii=False,
            ),
        )
    )
    reduced = long_context_state.reduce_state(
        argparse.Namespace(
            run_dir=str(run_dir),
            run_id=run_dir.name,
            recent_turns=8,
            summary_turns=16,
            summary_chars=1800,
            max_items=24,
            next_action="build_context_pack",
        )
    )
    file_paths = [str((out_dir / rel).resolve()) for rel in generated_files if (out_dir / rel).exists()]
    checkpoint = long_context_state.commit_checkpoint(
        argparse.Namespace(
            run_dir=str(run_dir),
            run_id=run_dir.name,
            stage="provider_local_pipeline_execution",
            status="pass",
            checkpoint_id="checkpoint-provider-local-pipeline-execution",
            completed_step=[
                "compose_pipeline",
                "build_requirement_blueprint",
                "collect_online_inputs",
                "run_market_research",
                "api_provider_project_generation",
                "provider_semantic_review",
                "write_provider_files",
                "emit_runtime_artifacts",
                "reduce_conversation_state",
            ],
            pending_step=[],
            artifact=artifact_args
            + [
                f"conversation_turn_user={user_turn['path']}",
                f"conversation_turn_agent={agent_turn['path']}",
                f"conversation_state={reduced['state_path']}",
                f"decision_ledger={reduced['ledger_path']}",
            ],
            file=file_paths,
            resume_command=f"python scripts/run_local_pipeline.py --goal {json.dumps(goal, ensure_ascii=False)} --run-dir {json.dumps(str(run_dir))} --out-dir {json.dumps(str(out_dir))} --allow-network --allow-provider --use-api --model {json.dumps(model)}",
            failure_json="",
        )
    )
    context_pack = long_context_state.build_context_pack(
        argparse.Namespace(
            run_dir=str(run_dir),
            run_id=run_dir.name,
            active_module="module.project.generator@1",
            flow_ref="flow.modular_project_generation@1",
            recent_turns=6,
            purpose="project_generation",
            prompt_max_chars=6000,
            output=str((run_dir / "artifacts" / "context_pack.json").resolve()),
            json=False,
        )
    )
    return {
        "conversation_turn_user.json": str(user_turn["path"]),
        "conversation_turn_agent.json": str(agent_turn["path"]),
        "conversation_state.json": str(reduced["state_path"]),
        "decision_ledger.json": str(reduced["ledger_path"]),
        "generation_checkpoint.json": str(checkpoint["checkpoint_path"]),
        "context_pack.json": str(context_pack["context_pack_path"]),
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    resume_run_dir = str(getattr(args, "resume_run_dir", "") or "").strip()
    if resume_run_dir:
        args.run_dir = resume_run_dir
        args.use_api = True
        args.allow_network = True
        args.allow_provider = True
    require_api_generation(args)
    exec_deadline_value = generation_deadline(args)
    run_dir = pathlib.Path(args.run_dir).resolve()
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    out_dir = pathlib.Path(args.out_dir).resolve()
    result_path = pathlib.Path(args.result).resolve()
    plan_path = pathlib.Path(args.plan) if args.plan else None
    resume_pending_plan: dict[str, Any] = {}
    resume_run_context: dict[str, Any] = {}
    if resume_run_dir:
        resume_pending_plan = load_pending_repair_plan(resume_run_dir)
        resume_run_context = load_run_context(resume_run_dir)
    if plan_path and plan_path.exists():
        plan_doc = load_json(plan_path)
        goal = plan_goal(plan_doc)
    else:
        goal = str(
            getattr(args, "goal", "")
            or resume_pending_plan.get("raw_user_goal", "")
            or resume_run_context.get("raw_user_goal", "")
            or ""
        ).strip()
        if not goal:
            if resume_run_dir:
                raise RuntimeError("RESUME_CONTEXT_MISSING_GOAL")
            raise RuntimeError("--goal or --plan is required")
        plan_doc = compose_local_pipeline.compose(
            goal,
            allow_network=bool(getattr(args, "allow_network", False)),
            allow_provider=bool(getattr(args, "allow_provider", False)),
            use_local_model=local_model_router.local_model_requested(),
        )
        local_model_hint = (
            plan_doc.get("project_understanding", {}).get("payload", {}).get("optional_local_model", {})
            if isinstance(plan_doc, dict)
            else {}
        )
        if isinstance(local_model_hint, dict) and local_model_hint.get("ok"):
            formal_model_contract.append_model_call(
                run_dir,
                stage="planning",
                provider="local_model_router",
                model=str(local_model_hint.get("model", "")),
                requested=True,
                executed=True,
                status="ok",
                used_in_formal_chain=True,
                input_value=goal,
                output_value=local_model_hint.get("result", {}),
                metadata={"source": "compose_local_pipeline"},
            )
    intent = frozen_user_intent(plan_doc, goal)
    user_goal = str(intent.get("raw_user_message") or plan_doc.get("original_requirement") or goal).strip()
    internal_context = internal_context_from_plan(plan_doc)
    phase_log_path = str(getattr(args, "phase_log_path", "") or (run_dir / "provider_phase_log.jsonl"))
    routing_policy = provider_model_routing_policy_from_args(args)
    exec_deadline = ProgressDeadline(
        exec_deadline_value,
        extension_seconds=max(30, int(getattr(args, "timeout", 360))),
        phase_log_path=phase_log_path,
    )
    requirement_decision_result = requirement_decision_lane.run_requirement_decision(user_goal, run_dir)
    selected_requirement = (
        requirement_decision_result.get("selected_requirement", {})
        if isinstance(requirement_decision_result.get("selected_requirement"), dict)
        else {}
    )
    acceptance_contract = (
        requirement_decision_result.get("acceptance_contract", {})
        if isinstance(requirement_decision_result.get("acceptance_contract"), dict)
        else {}
    )
    requirement_paths = requirement_decision_result.get("paths", {}) if isinstance(requirement_decision_result.get("paths"), dict) else {}
    mvp_scope_doc = safe_read_text(pathlib.Path(str(requirement_paths.get("mvp_scope", "")))) if requirement_paths.get("mvp_scope") else ""
    non_goals_doc = safe_read_text(pathlib.Path(str(requirement_paths.get("non_goals", "")))) if requirement_paths.get("non_goals") else ""
    plan_doc = dict(plan_doc)
    plan_doc["requirement_decision"] = {
        "status": requirement_decision_result.get("status"),
        "paths": requirement_paths,
        "candidate_count": len((requirement_decision_result.get("candidate_requirements", {}) or {}).get("candidates", []))
        if isinstance(requirement_decision_result.get("candidate_requirements"), dict)
        else 0,
    }
    plan_doc["selected_requirement"] = selected_requirement
    plan_doc["mvp_scope"] = {"path": requirement_paths.get("mvp_scope", ""), "text": mvp_scope_doc}
    plan_doc["non_goals"] = {"path": requirement_paths.get("non_goals", ""), "text": non_goals_doc}
    plan_doc["acceptance_contract"] = acceptance_contract
    internal_context = (
        internal_context
        + "\n\nRequirement Decision Lane result:\n"
        + json.dumps(
            {
                "selected_requirement": selected_requirement,
                "mvp_scope": mvp_scope_doc[:4000],
                "non_goals": non_goals_doc[:4000],
                "acceptance_contract": acceptance_contract,
            },
            ensure_ascii=False,
            indent=2,
        )
    ).strip()
    if requirement_decision_result.get("status") != "PASS":
        blocked = {
            "kind": "RuntimeExecutionResult",
            "status": "BLOCKED",
            "reason": "requirement_decision_needs_rework",
            "generated_at": now(),
            "goal": user_goal,
            "generation_context_goal": goal,
            "project_dir": None,
            "requested_project_dir": str(out_dir),
            "run_dir": str(run_dir),
            "requirement_decision": requirement_decision_result,
            "requirement_decision_status": "FAIL",
            "implementation_status": "NOT_EVALUATED",
            "delivery_status": "NEEDS_REWORK",
            "overall_status": "NEEDS_REWORK",
            "final_delivery_allowed": False,
            "final_verdict": "NEEDS_REWORK",
            "policy": GENERATION_POLICY,
        }
        write_json(result_path, blocked)
        return blocked

    discovery_result = discovery_selection_lane.run_discovery_selection(user_goal, run_dir / "discovery")
    selected_project_direction = (
        discovery_result.get("selected_project_direction", {})
        if isinstance(discovery_result.get("selected_project_direction"), dict)
        else {}
    )
    complexity_project_contract = (
        discovery_result.get("complexity_project_contract", {})
        if isinstance(discovery_result.get("complexity_project_contract"), dict)
        else {}
    )
    plan_doc["discovery_selection"] = {
        "status": discovery_result.get("status"),
        "paths": discovery_result.get("paths", {}),
        "candidate_count": discovery_result.get("candidate_count", 0),
    }
    plan_doc["selected_project_direction"] = selected_project_direction
    plan_doc["complexity_project_contract"] = complexity_project_contract
    internal_context = (
        internal_context
        + "\n\nDiscovery & Selection Lane result:\n"
        + json.dumps(
            {
                "selected_requirement": selected_requirement,
                "mvp_scope": mvp_scope_doc[:4000],
                "non_goals": non_goals_doc[:4000],
                "acceptance_contract": acceptance_contract,
                "selected_project_direction": selected_project_direction,
                "complexity_project_contract": complexity_project_contract,
            },
            ensure_ascii=False,
            indent=2,
        )
    ).strip()
    if discovery_result.get("status") != "PASS":
        blocked = {
            "kind": "RuntimeExecutionResult",
            "status": "BLOCKED",
            "reason": "discovery_selection_needs_rework",
            "generated_at": now(),
            "goal": user_goal,
            "generation_context_goal": goal,
            "project_dir": None,
            "requested_project_dir": str(out_dir),
            "run_dir": str(run_dir),
            "discovery_selection": discovery_result,
            "requirement_decision": requirement_decision_result,
            "selected_requirement": selected_requirement,
            "acceptance_contract": acceptance_contract,
            "final_delivery_allowed": False,
            "final_verdict": "NEEDS_REWORK",
            "policy": GENERATION_POLICY,
        }
        write_json(result_path, blocked)
        return blocked
    if not bool(getattr(args, "use_api", False)):
        artifacts_dir = run_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        simulator_progress = {
            "kind": "LocalSimulatorTeamProgress",
            "created_at": now(),
            "goal": user_goal,
            "generation_context_goal": goal,
            "status": "BLOCKED",
            "reason": "delivery evidence is not complete yet",
            "provider_used": False,
            "api_used": False,
            "stages": [
                {"stage": "intake", "status": "observed"},
                {"stage": "simulator_team", "status": "running"},
                {"stage": "delivery_evidence_gate", "status": "blocked", "missing": ["package", "screenshot", "verify_report"]},
            ],
        }
        write_json(artifacts_dir / "simulator_progress.json", simulator_progress)
        result = {
            "kind": "RuntimeExecutionResult",
            "status": "BLOCKED",
            "generated_at": now(),
            "goal": user_goal,
            "generation_context_goal": goal,
            "project_dir": str(out_dir),
            "run_dir": str(run_dir),
            "reason": "provider_api_disabled_by_default",
            "message": "Local simulator advanced the middle stage, but delivery evidence is not complete.",
            "simulator_progress": str(artifacts_dir / "simulator_progress.json"),
            "requirement_decision": requirement_decision_result,
            "selected_requirement": selected_requirement,
            "acceptance_contract": acceptance_contract,
            "discovery_selection": discovery_result,
            "selected_project_direction": selected_project_direction,
            "complexity_project_contract": complexity_project_contract,
            "missing_artifacts": ["package", "screenshot", "verify_report"],
            "provider": {"requested": False, "executed": False},
            "policy": GENERATION_POLICY,
            "can_escalate": "Only after BLOCKED plus an explicit escalation_request.",
        }
        write_json(result_path, result)
        return result
    write_run_context(
        run_dir,
        raw_user_goal=user_goal,
        model=str(args.model),
        base_url=provider_base_url_for_diagnostics(),
        generation_mode=str(os.environ.get("CGNK_GENERATION_MODE", "api") or "api"),
        requested_project_dir=out_dir,
    )
    blueprint = requirement_blueprint.build_requirement_blueprint(user_goal, [], assume_defaults=False)
    online_inputs = online_input_agent.collect_online_inputs(user_goal, run_dir / "input_examples")
    if isinstance(online_inputs, dict):
        online_inputs.setdefault("project_type", str(intent.get("project_type", "")))
        online_inputs.setdefault("raw_user_message", user_goal)
    market_research = market_research_agent.run_market_research(user_goal, blueprint, online_inputs, run_dir / "market_research")
    component_pipeline = component_pipeline_from_plan(user_goal, plan_doc)
    repair_errors: list[str] = []
    generation: dict[str, Any] = {}
    files: list[dict[str, str]] = []
    provider_review: dict[str, Any] = {}
    generated_files: list[str] = []
    example_outputs: dict[str, Any] = {}
    agent_usage: dict[str, Any] = {}
    semantic_result = run_provider_semantic_review_with_repair(
        user_goal=user_goal,
        plan_doc=plan_doc,
        blueprint=blueprint,
        online_inputs=online_inputs,
        market_research=market_research,
        component_pipeline=component_pipeline,
        repair_errors=repair_errors,
        model=str(args.model),
        timeout=int(args.timeout),
        internal_context=internal_context,
        deadline=exec_deadline,
        run_dir=run_dir,
        out_dir=out_dir,
        result_path=result_path,
        max_repair_attempts=provider_semantic_repair_attempts(args),
        phase_log_path=phase_log_path,
        initial_repair_plan=resume_pending_plan,
        routing_policy=routing_policy,
    )
    generation = semantic_result.get("generation", {}) if isinstance(semantic_result.get("generation"), dict) else {}
    files = semantic_result.get("files", []) if isinstance(semantic_result.get("files"), list) else []
    provider_review = semantic_result.get("provider_review", {}) if isinstance(semantic_result.get("provider_review"), dict) else {}
    if semantic_result.get("status") != "pass":
        diagnostics = semantic_result.get("diagnostics", {})
        original_file_count = len(files)
        files = recover_candidate_files_from_checkpoints(run_dir, files)
        recovered_candidate_files = original_file_count == 0 and bool(files)
        semantic_classes = classify_semantic_blockers(provider_review)
        static_fatal_fact_blockers = detect_provider_hard_fact_blockers(files)
        static_repairable_fact_blockers = detect_provider_repairable_fact_blockers(files)
        fatal_fact_blockers = list(semantic_classes.get("fatal_fact_blocker", [])) + static_fatal_fact_blockers
        repairable_fact_blockers = list(semantic_classes.get("repairable_fact_blocker", [])) + static_repairable_fact_blockers
        sanitize_result: dict[str, Any] = {"status": "pass", "files": files, "sanitized_fact_blockers": [], "changed_paths": []}
        if files and not fatal_fact_blockers and repairable_fact_blockers:
            sanitize_result = candidate_sanitizer.run(files, repairable_fact_blockers)
            files = sanitize_result.get("files", files) if isinstance(sanitize_result.get("files"), list) else files
            fatal_fact_blockers = list(sanitize_result.get("fatal_fact_blockers", []))
        if files and not fatal_fact_blockers:
            candidate_dir = candidate_project_dir_for(out_dir)
            materialized_candidate = candidate_materializer.run(
                candidate_dir=candidate_dir,
                files=files,
                semantic_classes=semantic_classes,
                sanitize_result=sanitize_result,
            )
            generated_files = list(materialized_candidate.get("metadata", {}).get("generated_files", []))
            generation["provider_semantic_review"] = provider_review
            generation["provider_semantic_review_attempted_repairs"] = semantic_result.get("attempted_repairs", [])
            candidate_example_outputs = make_example_outputs(run_dir, online_inputs)
            post_build = post_build_finalize.run(
                project_dir=candidate_dir,
                run_dir=run_dir,
                user_goal=user_goal,
                generated_files=generated_files,
                online_inputs=online_inputs,
                example_outputs=candidate_example_outputs,
                model=str(args.model),
                timeout=int(args.timeout),
                phase_log_path=phase_log_path,
                deadline=exec_deadline,
                classifications=semantic_classes,
                routing_policy=routing_policy,
            )
            post_build = run_candidate_post_build_repair_loop(
                candidate_dir=candidate_dir,
                run_dir=run_dir,
                user_goal=user_goal,
                generated_files=generated_files,
                online_inputs=online_inputs,
                example_outputs=candidate_example_outputs,
                model=str(args.model),
                timeout=int(args.timeout),
                phase_log_path=phase_log_path,
                deadline=exec_deadline,
                classifications=semantic_classes,
                routing_policy=routing_policy,
                initial_post_build=post_build,
                max_attempts=post_build_repair_attempts(args),
            )
            final_bundle_exists = (candidate_dir / "final_project_bundle.zip").exists()
            delivery_manifest_exists = (candidate_dir / "delivery_manifest.json").exists()
            final_truth = final_delivery_truth.run_if_applicable(
                project_dir=candidate_dir,
                manifest={},
                session={"goal": user_goal},
                evidence={
                    "run_dir": str(run_dir),
                    "usage_plan": (
                        post_build.get("agent_usage", {}).get("plan", {})
                        if isinstance(post_build.get("agent_usage", {}), dict)
                        else {}
                    ),
                },
                phase="final",
            )
            final_delivery_allowed = bool(final_truth.get("metadata", {}).get("delivery_allowed"))
            model_participation = final_truth.get("metadata", {}).get("formal_model_gate", {})
            final_verdict = decide_adaptive_final_verdict(
                candidate_materialized=True,
                hard_fact_blockers=[],
                runtime_blockers=semantic_classes.get("runtime_blocker", []),
                quality_blockers=semantic_classes.get("quality_blocker", []),
                warnings=semantic_classes.get("warning", []),
                post_build=post_build,
                final_delivery_allowed=final_delivery_allowed,
                final_bundle_exists=final_bundle_exists,
                delivery_manifest_exists=delivery_manifest_exists,
            )
            candidate_result = {
                "kind": "RuntimeExecutionResult",
                "status": final_verdict,
                "reason": str(model_participation.get("reason") or "semantic_review_needs_rework_candidate_materialized")
                if isinstance(model_participation, dict) and model_participation.get("status") == "fail"
                else "semantic_review_needs_rework_candidate_materialized",
                "generated_at": now(),
                "goal": user_goal,
                "generation_context_goal": goal,
                "project_dir": None,
                "candidate_project_dir": str(candidate_dir),
                "requested_project_dir": str(out_dir),
                "run_dir": str(run_dir),
                "provider_status": "candidate_materialized",
                "semantic_review_status": "needs_rework",
                "provider_semantic_review": provider_review,
                "requirement_decision": requirement_decision_result,
                "selected_requirement": selected_requirement,
                "acceptance_contract": acceptance_contract,
                "discovery_selection": discovery_result,
                "selected_project_direction": selected_project_direction,
                "complexity_project_contract": complexity_project_contract,
                "attempted_repairs": semantic_result.get("attempted_repairs", []),
                "diagnostics": diagnostics,
                "diagnostics_path": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
                "candidate_only": True,
                "not_final_delivery": True,
                "candidate_materialized": True,
                "materialized": False,
                "generated_files": generated_files,
                "candidate_files_recovered_from_checkpoints": recovered_candidate_files,
                "fatal_fact_blockers": [],
                "repairable_fact_blockers": repairable_fact_blockers,
                "hard_fact_blockers": repairable_fact_blockers,
                "sanitized_fact_blockers": sanitize_result.get("sanitized_fact_blockers", []),
                "sanitized_files": sanitize_result.get("changed_paths", []),
                "runtime_blockers": semantic_classes.get("runtime_blocker", []),
                "quality_blockers": semantic_classes.get("quality_blocker", []),
                "warnings": semantic_classes.get("warning", []),
                "post_build_finalize_status": post_build.get("status", "unknown"),
                "post_build_finalize": post_build,
                "final_delivery_allowed": final_delivery_allowed,
                "formal_model_participation": model_participation,
                "final_verdict": final_verdict,
                "final_project_bundle": "",
                "delivery_manifest": "",
                "policy": GENERATION_POLICY,
                "provider": {"requested": True, "executed": True, "model": str(args.model)},
            }
            write_json(result_path, candidate_result)
            return candidate_result
        blocked = {
            "kind": "RuntimeExecutionResult",
            "status": "BLOCKED",
            "reason": "provider_fact_blocked" if fatal_fact_blockers else "provider_semantic_review_failed",
            "generated_at": now(),
            "goal": user_goal,
            "generation_context_goal": goal,
            "project_dir": None,
            "candidate_project_dir": str(candidate_project_dir_for(out_dir)),
            "requested_project_dir": str(out_dir),
            "run_dir": str(run_dir),
            "provider_status": "blocked",
            "semantic_review_status": str(provider_review.get("status", "unknown")),
            "provider_semantic_review": provider_review,
            "requirement_decision": requirement_decision_result,
            "selected_requirement": selected_requirement,
            "acceptance_contract": acceptance_contract,
            "discovery_selection": discovery_result,
            "selected_project_direction": selected_project_direction,
            "complexity_project_contract": complexity_project_contract,
            "attempted_repairs": semantic_result.get("attempted_repairs", []),
            "diagnostics": diagnostics,
            "diagnostics_path": str((run_dir / "artifacts" / "provider_semantic_review_failure.json").resolve()),
            "candidate_materialized": False,
            "candidate_files_recovered_from_checkpoints": recovered_candidate_files,
            "materialized": False,
            "why_project_dir_was_not_materialized": "Fatal fact blockers prevent candidate materialization." if fatal_fact_blockers else "Provider semantic review failed after repair attempts.",
            "fatal_fact_blockers": fatal_fact_blockers,
            "repairable_fact_blockers": repairable_fact_blockers,
            "hard_fact_blockers": fatal_fact_blockers + repairable_fact_blockers,
            "runtime_blockers": semantic_classes.get("runtime_blocker", []),
            "quality_blockers": semantic_classes.get("quality_blocker", []),
            "warnings": semantic_classes.get("warning", []),
            "post_build_finalize_status": "not_started",
            "final_delivery_allowed": False,
            "final_verdict": "FACT_BLOCKED" if fatal_fact_blockers else "NEEDS_REWORK",
            "policy": GENERATION_POLICY,
            "provider": {"requested": True, "executed": True, "model": str(args.model)},
        }
        write_json(result_path, blocked)
        return blocked
    generation["provider_semantic_review_attempted_repairs"] = semantic_result.get("attempted_repairs", [])
    generated_files = write_provider_files(out_dir, files)
    mark_generation_progress(
        exec_deadline,
        "project_generation",
        "Provider project files were written to disk.",
        [str(out_dir / rel) for rel in generated_files],
    )
    append_phase_log(phase_log_path, "project_generation", "completed", "Project files written.", [str(out_dir)])
    example_outputs = make_example_outputs(run_dir, online_inputs)
    if example_outputs.get("status") != "pass":
        raise RuntimeError(f"example-based output generation failed: {example_outputs}")
    mark_generation_progress(
        exec_deadline,
        "example_outputs",
        "Example output artifacts were generated.",
        [str(path) for path in example_outputs.get("files", [])] if isinstance(example_outputs.get("files"), list) else [],
    )
    expected_intent = intent
    conflict = local_intent_router.detect_project_type_conflict(expected_intent, out_dir)
    if conflict.get("conflict"):
        blocked = {
            "kind": "RuntimeExecutionResult",
            "status": "BLOCKED",
            "reason": "project_type_mismatch",
            "generated_at": now(),
            "goal": user_goal,
            "generation_context_goal": goal,
            "project_dir": str(out_dir),
            "run_dir": str(run_dir),
            "frozen_intent": intent,
            "requirement_decision": requirement_decision_result,
            "selected_requirement": selected_requirement,
            "acceptance_contract": acceptance_contract,
            "discovery_selection": discovery_result,
            "selected_project_direction": selected_project_direction,
            "complexity_project_contract": complexity_project_contract,
            "project_type_conflict": conflict,
            "can_retry": True,
        }
        write_json(result_path, blocked)
        append_phase_log(phase_log_path, "delivery_bundle", "failed", "Project type mismatch blocked delivery.", [str(result_path)])
        return blocked
    agent_usage = run_project_usage_agent(
        user_goal,
        out_dir,
        run_dir,
        generated_files,
        online_inputs,
        example_outputs,
        str(args.model),
        remaining_timeout(exec_deadline, int(args.timeout), floor=5, cap=180),
        allow_model_usage_planning=bool(getattr(args, "allow_model_usage_planning", False)),
        phase_log_path=phase_log_path,
        deadline=exec_deadline,
        routing_policy=routing_policy,
    )
    if agent_usage.get("status") == "failed":
        raise RuntimeError(f"agent project usage failed: {json.dumps(agent_usage.get('failure_summary') or agent_usage.get('events', [])[-8:], ensure_ascii=False)}")
    generation["provider_semantic_review"] = provider_review
    artifact_refs = write_runtime_artifacts(run_dir, user_goal, plan_doc, blueprint, generation, generated_files, online_inputs, market_research, example_outputs, agent_usage)
    artifact_refs.update(
        write_provider_long_context_artifacts(
            run_dir,
            out_dir,
            user_goal,
            artifact_refs,
            generated_files,
            model=str(args.model),
        )
    )

    result = {
        "kind": "RuntimeExecutionResult",
        "status": "pass",
        "generated_at": now(),
        "goal": user_goal,
        "generation_context_goal": goal,
        "project_dir": str(out_dir),
        "run_dir": str(run_dir),
        "generated_files": generated_files,
        "online_input_examples": online_inputs,
        "market_research": market_research,
        "component_pipeline": component_pipeline,
        "frozen_intent": intent,
        "component_generation": {
            "strategy": "component_scoped_provider_calls",
            "components": generation.get("components", []),
            "component_errors": generation.get("component_errors", {}),
        },
        "example_outputs": example_outputs,
        "agent_usage": agent_usage,
        "provider_semantic_review": provider_review,
        "formal_model_participation": formal_model_contract.evaluate_model_participation(
            context="formal_live_generation",
            run_dir=run_dir,
            usage_plan=agent_usage.get("plan", {}) if isinstance(agent_usage, dict) else {},
        ),
        "requirement_decision": requirement_decision_result,
        "selected_requirement": selected_requirement,
        "acceptance_contract": acceptance_contract,
        "discovery_selection": discovery_result,
        "selected_project_direction": selected_project_direction,
        "complexity_project_contract": complexity_project_contract,
        "artifact_refs": artifact_refs,
        "policy": GENERATION_POLICY,
        "provider": {"requested": True, "executed": True, "model": str(args.model)},
    }
    write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=False, allow_provider=False, use_api=False)
    parser.add_argument("--plan", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_GENERATED_DIR))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--resume-run-dir", default="")
    parser.add_argument("--result", "--result-path", dest="result", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--allow-network", dest="allow_network", action="store_true")
    parser.add_argument("--no-network", dest="allow_network", action="store_false")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false")
    parser.add_argument("--use-api", dest="use_api", action="store_true")
    parser.add_argument("--no-api", dest="use_api", action="store_false")
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--small-model", default="")
    parser.add_argument("--large-model", default="")
    parser.add_argument("--disable-model-routing", action="store_true")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--provider-semantic-repair-attempts", type=int, default=None)
    parser.add_argument("--post-build-repair-attempts", type=int, default=None)
    parser.add_argument("--allow-model-usage-planning", action="store_true", help="Opt in to model-planned usage validation; local deterministic planning is the default.")
    parser.add_argument("--phase-log-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = execute(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"LOCAL_PIPELINE_EXECUTION: {result['status'].upper()}")
        print(f"project_dir={result['project_dir']}")
        print(f"run_dir={result['run_dir']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
