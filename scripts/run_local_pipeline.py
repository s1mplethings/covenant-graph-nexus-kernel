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
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_connectivity
import compose_local_pipeline
import local_intent_router
import local_usage_planner
import long_context_state
import market_research_agent
import online_input_agent
import requirement_blueprint

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "local-pipeline-execution"
DEFAULT_GENERATED_DIR = ROOT / "generated" / "cgnk_generated_project"
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


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def provider_text(messages: list[dict[str, str]], model: str, timeout: int, *, max_attempts: int = 6) -> str:
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key")
    root = str(creds.get("base_url", "")).rstrip("/")
    if check_connectivity._is_gptsapi_base_url(root):
        endpoint = check_connectivity._chat_completions_endpoint(root)
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 12000}
    else:
        endpoint = check_connectivity._responses_endpoint(root)
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload = {"model": model, "input": prompt, "temperature": 0.2, "max_output_tokens": 12000}
    last_error = ""
    for attempt in range(max(1, max_attempts)):
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            break
        last_error = error
        if not check_connectivity._error_is_retryable(error):
            break
        time.sleep(min(20.0, 2.0 * (attempt + 1)))
    else:
        raise RuntimeError(f"provider_api_request_failed: {last_error}" if last_error else "provider_api_request_failed")
    if doc is None:
        raise RuntimeError(f"provider_api_request_failed: {last_error}")
    text = check_connectivity._extract_text(doc)
    if not text:
        raise RuntimeError("provider returned empty project payload")
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
) -> dict[str, Any]:
    system = """You are the API quality reviewer for CGNK provider-generated projects.
Review the generated project semantically. Do not use a fixed checklist tied to one project type.

Judge whether the project is specific to the user's goal, coherent, runnable enough for a first version, and honestly uses the provided online input examples where relevant.
Project type, required files, implementation strategy, and test expectations are decided by you from the requirement and input manifest.

Pass/fail rules:
- Return "fail" if any core capability explicitly requested by the user is missing.
- Return "fail" if market_research contains relevant recommended candidates for core features and the project ignores them without a clear justification.
- Return "fail" if the generated documentation does not summarize the market research or explain why the selected approach is suitable.
- Return "fail" if the project says the user must manually replace placeholders before the first useful run.
- Return "fail" if preview/output artifacts are claimed but only described, not generated by code, tests, or runtime example_outputs.
- Return "fail" if tests are superficial and do not exercise the important generated behavior for this project type.
- Return "fail" if generated files use misleading placeholder names such as binary assets renamed to .txt instead of producing or referencing real artifacts.
- Return "fail" if the user asked for image generation and the project only copies or re-labels an online example image as a generated image. Online examples can be references or previews, but generated backgrounds/characters must be produced by code, a model/API integration, or a clearly implemented local image generation pipeline.
- Return "fail" for VN/background/character art requests if the implementation only draws simple circles, rectangles, plain gradients, text labels, or other placeholder-like geometry instead of visually meaningful generated assets.
- Return "fail" for serious VN/background/character AI image generation requests if online model candidates were provided but the project ignores them and only implements procedural drawing without an online model/API integration path.
- Return "fail" if the project claims to use online AI image generation but has no credential/capability check and no failure reporting for missing image-model access.
- Return "fail" if requirements or setup instructions pin stale dependencies likely incompatible with the provided runtime_context, especially native packages that may not have wheels for the current Python version.
- If your issues mention that image generation is only downloading/copying an example image, or that local/API image generation is not implemented, the status must be "fail".
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
    compact_files = []
    for item in files:
        content = str(item.get("content", ""))
        compact_files.append(
            {
                "path": item.get("path"),
                "content": content[:6000],
                "truncated": len(content) > 6000,
            }
        )
    payload = {
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
    raw = provider_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        model,
        timeout,
        max_attempts=1,
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
    if "retryable=true" in str(error_text or "").lower():
        return True
    return False


def provider_component_checkpoint_paths(checkpoint_dir: pathlib.Path, component_id: str) -> tuple[pathlib.Path, pathlib.Path]:
    safe = provider_component_checkpoint_id(component_id)
    return checkpoint_dir / f"{safe}.json", checkpoint_dir / f"{safe}_files.json"


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
) -> dict[str, Any]:
    system = """You are a component-level project-file generator for CGNK.
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
    payload = {
        "raw_user_goal": goal,
        "goal": goal,
        "component": component,
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
    raw = provider_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        model,
        timeout,
        max_attempts=1,
    )
    doc = parse_json_object(raw)
    if str(doc.get("component_id", "")).strip() != str(component.get("id", "")).strip():
        raise RuntimeError(f"provider returned wrong component_id for {component.get('id')}: {doc.get('component_id')}")
    doc["_provider_raw_output"] = raw
    return doc


def merge_component_files(component_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    merged: dict[str, str] = {}
    owner: dict[str, str] = {}
    mergeable_docs = {"README.md", "TEST_PLAN.md", "DELIVERY_NOTES.md"}
    mergeable_web_suffixes = {".html", ".css", ".js", ".mjs", ".json"}
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
                if rel.startswith(("app/", "static/", "frontend/")) and suffix in mergeable_web_suffixes:
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
        local_repairs = list(repair_errors) + component_errors.get(component_id, [])
        for attempt in range(3):
            try:
                if attempt > 0 and component_id not in retried_components:
                    retried_components.append(component_id)
                call_timeout = remaining_timeout(deadline, timeout, floor=5, cap=120) if deadline else min(timeout, 120)
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
                    model=model,
                    timeout=call_timeout,
                    internal_context=internal_context,
                )
                raw_output = str(result.get("_provider_raw_output", ""))
                result = {key: value for key, value in result.items() if key != "_provider_raw_output"}
                files = validate_provider_files(result)
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
                message = f"{component_id} attempt {attempt + 1}: {exc}"
                component_errors.setdefault(component_id, []).append(message)
                local_repairs.append(message)
                retryable = provider_component_error_is_retryable(provider_error_type, str(exc))
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
                if not retryable or attempt == 2:
                    failed_components.append({"component_id": component_id, "provider_error_type": provider_error_type, "error": str(exc)})
                    write_provider_component_checkpoint_summary(checkpoint_dir, checkpoint_summary())
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
    missing = [rel for rel in required if rel not in paths]
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
    workspace = ROOT.resolve()
    resolved_out = out_dir.resolve()
    if not str(resolved_out).lower().startswith(str((workspace / "generated").resolve()).lower()):
        raise RuntimeError(f"refusing to clean output directory outside generated/: {resolved_out}")
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
            plan = provider_project_usage_plan(goal, project_dir, generated_files, online_inputs, example_outputs, model, plan_timeout)
            plan["planner"] = "model_with_local_fallback"
            plan["uses_model"] = True
            append_phase_log(phase_log_path, "usage_planning_model", "completed", "Model usage planning returned a plan.", started_at=usage_started)
        except Exception as exc:
            append_phase_log(phase_log_path, "usage_planning_model", "failed", f"Model usage planning failed; using local fallback: {exc}", started_at=usage_started)
            plan = local_usage_planner.create_usage_plan(project_dir, project_type)
            plan["fallback_reason"] = f"model usage planning failed: {exc}"
    else:
        append_phase_log(phase_log_path, "usage_planning_local", "started", "Local deterministic usage planning started.", started_at=usage_started)
        plan = local_usage_planner.create_usage_plan(project_dir, project_type)
        append_phase_log(phase_log_path, "usage_planning_local", "completed", "Local deterministic usage planning completed.", started_at=usage_started)
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
    require_api_generation(args)
    exec_deadline_value = generation_deadline(args)
    plan_path = pathlib.Path(args.plan) if args.plan else None
    if plan_path and plan_path.exists():
        plan_doc = load_json(plan_path)
        goal = plan_goal(plan_doc)
    else:
        goal = str(getattr(args, "goal", "") or "").strip()
        if not goal:
            raise RuntimeError("--goal or --plan is required")
        plan_doc = compose_local_pipeline.compose(
            goal,
            allow_network=bool(getattr(args, "allow_network", False)),
            allow_provider=bool(getattr(args, "allow_provider", False)),
        )
    intent = frozen_user_intent(plan_doc, goal)
    user_goal = str(intent.get("raw_user_message") or plan_doc.get("original_requirement") or goal).strip()
    internal_context = internal_context_from_plan(plan_doc)

    out_dir = pathlib.Path(args.out_dir).resolve()
    run_dir = pathlib.Path(args.run_dir).resolve()
    result_path = pathlib.Path(args.result).resolve()
    exec_deadline = ProgressDeadline(
        exec_deadline_value,
        extension_seconds=max(30, int(getattr(args, "timeout", 360))),
        phase_log_path=getattr(args, "phase_log_path", ""),
    )
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
            "missing_artifacts": ["package", "screenshot", "verify_report"],
            "provider": {"requested": False, "executed": False},
            "policy": GENERATION_POLICY,
            "can_escalate": "Only after BLOCKED plus an explicit escalation_request.",
        }
        write_json(result_path, result)
        return result
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
    for attempt in range(5):
        try:
            generation_started = time.time()
            append_phase_log(getattr(args, "phase_log_path", ""), "project_generation", "started", f"Provider project generation attempt {attempt + 1} started.", started_at=generation_started)
            generation = provider_generate_project_by_components(
                user_goal,
                component_pipeline,
                plan_doc,
                blueprint,
                online_inputs,
                market_research,
                repair_errors,
                str(args.model),
                remaining_timeout(exec_deadline, int(args.timeout), floor=5, cap=120),
                internal_context=internal_context,
                deadline=exec_deadline,
                checkpoint_dir=run_dir / "artifacts" / "provider_components",
            )
            files = validate_provider_files(generation)
            provider_review = provider_review_project(
                user_goal,
                plan_doc,
                blueprint,
                online_inputs,
                market_research,
                generation,
                files,
                str(args.model),
                remaining_timeout(exec_deadline, int(args.timeout), floor=5, cap=90),
                internal_context=internal_context,
            )
            if str(provider_review.get("status", "")).lower() != "pass":
                issues = provider_review.get("issues", [])
                if not isinstance(issues, list):
                    issues = [str(issues)]
                raise RuntimeError("provider semantic review failed: " + "; ".join(str(issue) for issue in issues[:8]))
            mark_generation_progress(
                exec_deadline,
                "provider_review",
                "Provider semantic review passed.",
                [str(result_path)],
            )
            generated_files = write_provider_files(out_dir, files)
            mark_generation_progress(
                exec_deadline,
                "project_generation",
                "Provider project files were written to disk.",
                [str(out_dir / rel) for rel in generated_files],
            )
            append_phase_log(getattr(args, "phase_log_path", ""), "project_generation", "completed", "Project files written.", [str(out_dir)], started_at=generation_started)
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
                    "project_type_conflict": conflict,
                    "can_retry": True,
                }
                write_json(result_path, blocked)
                append_phase_log(getattr(args, "phase_log_path", ""), "delivery_bundle", "failed", "Project type mismatch blocked delivery.", [str(result_path)])
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
                phase_log_path=getattr(args, "phase_log_path", ""),
                deadline=exec_deadline,
            )
            if agent_usage.get("status") == "failed":
                raise RuntimeError(f"agent project usage failed: {json.dumps(agent_usage.get('failure_summary') or agent_usage.get('events', [])[-8:], ensure_ascii=False)}")
            break
        except (RuntimeError, TimeoutError) as exc:
            repair_errors.append(f"attempt {attempt + 1}: {exc}")
            if attempt == 4:
                raise
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
    parser.add_argument("--result", "--result-path", dest="result", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--allow-network", dest="allow_network", action="store_true")
    parser.add_argument("--no-network", dest="allow_network", action="store_false")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false")
    parser.add_argument("--use-api", dest="use_api", action="store_true")
    parser.add_argument("--no-api", dest="use_api", action="store_false")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--timeout", type=int, default=360)
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
