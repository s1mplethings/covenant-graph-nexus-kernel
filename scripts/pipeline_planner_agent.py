#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from typing import Any

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity
import local_model_router
import pipeline_manifest


PLANNER_SYSTEM_PROMPT = """You are the CGNK CFO pipeline planner agent.
The bottom-level orchestration model is one main agent named cfo. The cfo designs the modular pipeline and coordinates specialist agents that do the work.
Your job is to generate the pipeline_manifest JSON that represents the cfo-controlled module pipeline for this project.
Use the user messages, backend dialogue events, whiteboard, generation_context_snapshot, tool results, and delivery requirements.
Do not write project code.
Do not announce delivery completion.
Output JSON only.
The pipeline must be customized around the current project.
Always include a role with id "cfo". The cfo must have an early step that writes or updates the module pipeline/assignments, and a later review step before package_project.
Use specialist roles for the actual work, such as foundation, backend, frontend, asset_pipeline, data, integration, qa, docs, or export, depending on the project.
Do not let specialist agents invent a separate formal generation route; they execute the cfo module pipeline through allowed actions.
You may freely design the roles and steps for this project, but the pipeline_manifest must cover these Product Studio stages:
- product_plan
- technical_plan
- build
- test
- evidence_review
- review
- package
Stage rules:
- Do not skip product_plan.
- Do not skip technical_plan.
- Do not skip test.
- Do not skip evidence_review.
- Do not skip review.
- Do not put package before test, evidence_review, or review.
- evidence_review must happen after test and before review.
- Do not jump directly from test to package.
- Simple projects may merge stages, but TEST_REPORT.md and DELIVERY_NOTES.md still must be generated.
- Every step must declare stage. Use either a string stage or a list of stages for merged steps.
- Every step must explain goal.
- Every agent_turn step must use allowed_actions.
- You only generate pipeline_manifest. You do not write project files and you do not announce final delivery completion.
CFO design requirements:
- The cfo owns module planning, handoff order, acceptance interpretation, evidence review, and delivery readiness.
- The first cfo step should write or update MODULE_PIPELINE.md with module map, worker assignments, evidence targets, risk/default assumptions, and handoff order.
- The product_plan stage must write PRODUCT_PLAN.md and OUTPUT_CONTRACT.md.
- The technical_plan stage must write TECHNICAL_PLAN.md and BUILD_PLAN.md.
- The cfo may use support agents before worker implementation. Prefer context_librarian for a factual CFO_CONTEXT_DB.json and risk_reviewer for CFO_RISK_REGISTER.md on non-trivial projects.
- Support agents are advisory only: they maintain context/risk artifacts for cfo and workers, but they do not own scope, final routing, file generation strategy, or delivery readiness.
- Worker steps should be scoped to assigned modules and should leave handoff artifacts.
- Worker steps should read MODULE_PIPELINE.md plus any CFO support artifacts such as CFO_CONTEXT_DB.json and CFO_RISK_REGISTER.md.
- QA/test steps must write TEST_REPORT.md, attempt at least one feasible check command when possible, and record NO TEST EXECUTED with reason when no check can run.
- The evidence_review stage must write EVIDENCE_REVIEW.md. It is not final delivery; it prepares test code, test commands, sample inputs, screenshots, videos, preview files, missing real evidence, what the user should check, and the next recommended action.
- If the project involves GUI, visual output, video, demo files, image generation, data analysis, model effects, cheat detection, labels, preview, csgo/cs2/csgo2, 鉴挂, or user-visible screenshots/videos/tests, evidence_review must prepare evidence the user can judge before final package.
- Do not allow a complete PASS without EVIDENCE_REVIEW.md.
- A later cfo review step must inspect support artifacts, worker handoffs, test evidence, preview evidence, and whiteboard acceptance criteria before package_project.
- Review steps must read TEST_REPORT.md and write DELIVERY_NOTES.md. If TEST_REPORT.md is missing, review cannot mark PASS.
- The manifest may include a cfo_contract object describing authority, planning artifact, review artifact, support artifacts, support agent rule, worker handoff rule, and evidence rule.
Do not over-split normal projects, but preserve the cfo -> module agents -> cfo review -> package shape.
Every step must operate through allowed_actions.
The manifest cannot execute arbitrary Python, modify CGNK core code, call generate_project.py, call run_local_pipeline, or use simulator.
Allowed step types: agent_turn, use_skill, run_command, package_project, update_whiteboard.
Return a JSON object with kind AgentGeneratedPipelineManifest and version 1."""


def read_agent_session(session_path: str | pathlib.Path) -> list[dict[str, Any]]:
    path = pathlib.Path(session_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except Exception:
            continue
        if isinstance(doc, dict):
            events.append(doc)
    return events


def _compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interesting = {
        "user",
        "backend_dialogue_tick",
        "generation_context_snapshot",
        "tool_result",
        "pipeline_step_result",
        "whiteboard_patch_requested",
    }
    selected: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or event.get("role") or "")
        if kind in interesting or event.get("role") == "user":
            selected.append(event)
    return selected[-80:]


def collect_generation_context(session_path: str | pathlib.Path, whiteboard: dict[str, Any] | None) -> str:
    events = read_agent_session(session_path)
    context = {
        "whiteboard": whiteboard if isinstance(whiteboard, dict) else {},
        "agent_session_events": _compact_events(events),
    }
    return json.dumps(context, ensure_ascii=False, indent=2)[-60000:]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    return local_model_router.extract_json(text)


def _call_provider(prompt: str, model: str, timeout: int) -> str:
    if str(model).startswith("gpt-test"):
        raise RuntimeError("test model does not call provider")
    local_result = local_model_router.call_json_task("pipeline_planner", PLANNER_SYSTEM_PROMPT, prompt, timeout)
    if local_result.get("ok") and isinstance(local_result.get("json"), dict):
        doc = dict(local_result["json"])
        doc.setdefault("source", "local_model_planner")
        return json.dumps(doc, ensure_ascii=False)
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for pipeline planner")
    root = str(creds.get("base_url", "")).rstrip("/")
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    if check_connectivity._is_gptsapi_base_url(root):
        endpoint = root + "/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 2200}
    else:
        endpoint = root + "/responses"
        payload = {
            "model": model,
            "input": "\n".join(f"{item['role']}: {item['content']}" for item in messages),
            "temperature": 0.1,
            "max_output_tokens": 2200,
        }
    last_error = ""
    for attempt in range(3):
        doc, error = check_connectivity._post_json(endpoint, payload, token, timeout)
        if doc is not None:
            text = check_connectivity._extract_text(doc)
            if text:
                return text
        last_error = error
        time.sleep(min(5.0, 1.2 * (attempt + 1)))
    raise RuntimeError(last_error or "empty planner response")


def plan_pipeline(
    session_path: str | pathlib.Path,
    whiteboard: dict[str, Any],
    model: str,
    timeout: int,
    api_budget: str = "low",
) -> dict[str, Any]:
    del api_budget
    try:
        context = collect_generation_context(session_path, whiteboard)
        raw = _call_provider(context, model, timeout)
        doc = _extract_json_object(raw)
        manifest = pipeline_manifest.normalize_pipeline_manifest(doc or {}, whiteboard)
        ok, errors = pipeline_manifest.validate_pipeline_manifest(manifest)
        stage_ok, missing_required_stages = pipeline_manifest.validate_required_stages(manifest)
        if not ok or not stage_ok:
            fallback = pipeline_manifest.default_minimal_pipeline_manifest(whiteboard)
            fallback["planner_fallback_reason"] = "planner manifest failed validation"
            fallback["planner_errors"] = errors
            fallback["missing_required_stages"] = missing_required_stages
            return fallback
        return manifest
    except Exception as exc:
        fallback = pipeline_manifest.default_minimal_pipeline_manifest(whiteboard)
        fallback["planner_fallback_reason"] = str(exc)
        return fallback
