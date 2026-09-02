#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
from typing import Any, Callable

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import agent_conversation_loop
import check_connectivity
import local_agent_actions
import local_model_router
import pipeline_manifest
import pipeline_planner_agent


AgentCallable = Callable[[list[dict[str, Any]], str, int], str | dict[str, Any]]


MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
PREVIEW_SUFFIXES = MEDIA_SUFFIXES | {".html", ".csv", ".json"}
PYTHON_ENTRYPOINTS = ("app.py", "main.py")
PYTHON_DEPENDENCY_FILES = ("requirements.txt", "pyproject.toml")
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css"}
USER_REVIEW_KEYWORDS = (
    "gui",
    "visual",
    "image",
    "video",
    "csgo",
    "cs2",
    "csgo2",
    "鉴挂",
    "视觉",
    "模型检测",
    "数据分析",
    "视觉信息",
    "截图",
)


def _looks_like_generated_image(path: pathlib.Path) -> bool:
    lowered = str(path).replace("\\", "/").lower()
    return any(
        token in lowered
        for token in (
            "generated",
            "generation",
            "output",
            "outputs",
            "asset",
            "background",
            "bg",
            "scene",
            "sprite",
            "character",
            "portrait",
            "立绘",
            "背景",
            "角色",
        )
    )


def _asset_label(path: pathlib.Path) -> str:
    return str(path).replace("\\", "/").lower()


def _looks_like_screenshot(path: pathlib.Path) -> bool:
    label = _asset_label(path)
    return any(token in label for token in ("screenshot", "screen", "ui_", "desktop", "preview", "界面", "截图"))


def _looks_like_background(path: pathlib.Path) -> bool:
    label = _asset_label(path)
    return any(token in label for token in ("background", "bg_", "bg-", "/bg/", "scene", "背景"))


def _looks_like_sprite(path: pathlib.Path) -> bool:
    label = _asset_label(path)
    return any(token in label for token in ("sprite", "character", "portrait", "standing", "立绘", "角色"))


def _project_text_for_requirements(manifest: dict[str, Any], whiteboard: dict[str, Any] | None = None) -> str:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    parts: list[str] = [str(manifest.get("project_goal", ""))]
    for key in ("project_summary", "known_facts", "acceptance_criteria", "delivery_requirements", "change_requests", "user_rules"):
        value = board.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if str(item).strip())
    return "\n".join(parts).lower()


def _visual_requirements(manifest: dict[str, Any], whiteboard: dict[str, Any] | None = None) -> dict[str, bool]:
    compact = re.sub(r"\s+", "", _project_text_for_requirements(manifest, whiteboard))
    return {
        "screenshot": any(token in compact for token in ("截图", "界面", "桌面界面", "gui", "desktop", "interface", "screenshot")),
        "generated_image": any(token in compact for token in ("图片", "图像", "生成图", "image", "picture", "photo")),
        "background": any(token in compact for token in ("背景", "背景图", "background", "sceneart")),
        "sprite": any(token in compact for token in ("立绘", "角色图", "character", "sprite", "portrait")),
        "video": any(token in compact for token in ("视频", "演示视频", "录屏", "video", "mp4", "webm")),
    }


def _role_by_id(manifest: dict[str, Any], role_id: str) -> dict[str, Any]:
    for role in manifest.get("roles", []):
        if isinstance(role, dict) and str(role.get("id", "")) == role_id:
            return role
    return {"id": role_id, "name": role_id or "Pipeline Agent", "purpose": "Execute this pipeline step."}


def _role_operating_rules(role: dict[str, Any], step: dict[str, Any], manifest: dict[str, Any]) -> str:
    role_id = str(role.get("id", "")).strip()
    stages = pipeline_manifest._stage_values(step.get("stage"))
    cfo_contract = manifest.get("cfo_contract", {}) if isinstance(manifest.get("cfo_contract"), dict) else {}
    support_artifacts = cfo_contract.get("support_artifacts", {}) if isinstance(cfo_contract.get("support_artifacts"), dict) else {}
    context_db = support_artifacts.get("context_db", "CFO_CONTEXT_DB.json")
    risk_register = support_artifacts.get("risk_register", "CFO_RISK_REGISTER.md")
    supervisor_brief = support_artifacts.get(
        "codex_capability_brief", "CODEX_CAPABILITY_BRIEF.json"
    )
    global_rules = """Product Studio operating rules:
- Do not rush to package.
- Follow the Product Studio discipline: plan, technical plan, build, test, review, package.
- Do not claim final delivery readiness unless you are in review stage.
- Missing evidence must be written as a warning, not hidden."""
    stage_rules: list[str] = []
    if "product_plan" in stages or role_id in {"product", "cfo"}:
        stage_rules.append("""Product plan rules:
- You must write PRODUCT_PLAN.md and OUTPUT_CONTRACT.md during product_plan work.
- Preserve unanswered questions as assumptions.
- Define first version scope and acceptance criteria.
- Do not implement before plan artifacts exist.""")
    if "technical_plan" in stages or role_id in {"architect"}:
        stage_rules.append("""Technical plan rules:
- You must write TECHNICAL_PLAN.md and BUILD_PLAN.md during technical_plan work.
- Include file structure, runtime plan, test plan, risks, and dependencies.""")
    if "build" in stages or role_id in {"builder", "backend", "frontend"}:
        stage_rules.append("""Build rules:
- You must read PRODUCT_PLAN.md, OUTPUT_CONTRACT.md, TECHNICAL_PLAN.md, and BUILD_PLAN.md when they exist.
- You must write README.md.
- You must create a real runnable project, not only README/planning/report files.
- You must create app.py or main.py, requirements.txt or pyproject.toml, source code, tests, and requested visual artifacts such as UI screenshots, generated backgrounds, and generated sprites/立绘.
- You must not package.""")
    if "test" in stages or role_id == "qa":
        stage_rules.append("""QA rules:
- You must create TEST_REPORT.md.
- You must run at least one relevant command against the generated project.
- If TEST_REPORT.md contains NO TEST EXECUTED, this step is not complete and must be repaired before package.
- TEST_REPORT.md must include: commands_run, results, failures, repairs, remaining_warnings.
- Do not claim PASS without evidence.""")
    if "review" in stages or role_id in {"delivery_reviewer"}:
        stage_rules.append("""Review rules:
- You must read TEST_REPORT.md.
- You must write DELIVERY_NOTES.md.
- DELIVERY_NOTES.md must include: delivery_status, tests_executed, evidence_found, evidence_missing, known_limits, revision_entry.
- If TEST_REPORT.md is missing, delivery_status cannot be PASS.
- If visual evidence is missing for GUI/visual projects, mention it as a limitation.""")

    prefix = "\n".join([global_rules] + stage_rules)
    if role_id == "cfo":
        return f"""{prefix}

CFO operating rules:
- You are the main coordinating agent, not a worker pretending to finish everything alone.
- Your first responsibility is to convert the whiteboard into a concrete module pipeline with owners, handoffs, acceptance criteria, evidence targets, risks, and fallback boundaries.
- Identify critical capabilities before assigning workers. Use capability_strategy, capability_research_targets, critical_questions, and acceptance criteria when present.
- For each critical capability, prefer a mature/high-quality method or model/library/API/workflow. If the project uses a fallback, label it as fallback and do not mark the original capability as satisfied.
- When route choices have obvious user-visible differences, preserve the question and the assumed default in MODULE_PIPELINE.md so workers and review do not silently collapse the distinction.
- Write or update {cfo_contract.get('planning_artifact', 'MODULE_PIPELINE.md')} when planning.
- Use support artifacts {context_db} and {risk_register} as your factual context database and risk register; support agents advise you but do not own route or readiness.
- During review, inspect support artifacts, worker handoffs, test evidence, preview evidence, and project files against the whiteboard before delivery readiness.
- Write or update {cfo_contract.get('review_artifact', 'DELIVERY_NOTES.md')} with pass/warning status, missing evidence, and any patched gaps.
- Do not invent a new formal generation path; coordinate only through the manifest, project files, allowed actions, and handoff artifacts."""
    if role_id == "context_librarian":
        return f"""{prefix}

CFO support operating rules:
- You are a support agent for the cfo, not a route owner.
- Maintain {context_db} as a compact factual database of user intent, rules, constraints, acceptance criteria, delivery requirements, attachments, assumptions, module dependencies, and handoff references.
- Include capability_strategy, capability_research_targets, critical_questions, and local capability discovery results as first-class facts when present.
- Prefer structured JSON with source/evidence references where available.
- Do not implement product features, do not decide delivery readiness, and do not create a new formal generation path."""
    if role_id == "codex_capability_supervisor":
        return f"""{prefix}

Codex capability-supervisor operating rules:
- You operate above the context librarian only for an explicit bounded capability escalation; you do not replace the cfo or the reviewed Provider route.
- Require a validated CGKNCodexCapabilityEscalation from agent_session or the project support artifacts before acting.
- Use the supervise-cgkn-capabilities skill and write only the validated advisory artifact {supervisor_brief}.
- You may diagnose, request narrowly missing context or tool evidence, and propose Provider guidance, relative repair targets, and executable acceptance checks.
- You must not write generated product source, claim formal PASS, decide delivery readiness, package, deliver, or create a new generation path.
- If no external Codex handoff is available, report needs_context instead of falling back to another model that impersonates this role."""
    if role_id == "risk_reviewer":
        return f"""{prefix}

CFO support operating rules:
- You are a support agent for the cfo, not a route owner.
- Maintain {risk_register} with risks, missing evidence, likely failure modes, user-visible quality concerns, checks to run, and repair priorities.
- Treat a missing core capability, ignored advanced-method candidate, or fallback presented as success as a user-visible quality risk.
- Ground every risk in the whiteboard, module plan, context database, handoffs, or project files.
- Do not implement product features unless the current step explicitly allows a small artifact update, do not decide delivery readiness, and do not create a new formal generation path."""
    return f"""{prefix}

Worker operating rules:
- Treat the cfo as the owner of scope, module boundaries, handoff order, acceptance interpretation, and delivery readiness.
- Read MODULE_PIPELINE.md, CFO_CONTEXT_DB.json, optional {supervisor_brief}, CFO_RISK_REGISTER.md, and existing handoff files before changing project files when those artifacts exist.
- Work only on the area assigned by the current step goal unless a small supporting file is required.
- Leave a concise HANDOFF_<ROLE>.md or update the step-specific handoff with files changed, checks run, gaps, and next dependencies.
- Do not claim final delivery readiness; that belongs to cfo_review and packaging."""


def _system_prompt(role: dict[str, Any], step: dict[str, Any], manifest: dict[str, Any]) -> str:
    allowed = step.get("allowed_actions", [])
    operating_rules = _role_operating_rules(role, step, manifest)
    return f"""You are {role.get('name')}.
Role id: {role.get('id')}.
Role purpose: {role.get('purpose')}.
Current step goal: {step.get('goal')}.
You must read the latest whiteboard, generation_context_snapshot, pipeline_manifest, and tool_result events in the provided session history.
{operating_rules}
You may only use these action types: {json.dumps(allowed, ensure_ascii=False)}.
Return JSON only:
{{
  "message": "short status",
  "actions": [
    {{"type": "write_file", "path": "README.md", "content": "..."}}
  ]
}}
Keep source-file actions compact enough to fit valid JSON. If a file would be long, write the most important file first and let the next repair turn add supporting files.
Do not claim delivery is complete. Do not call old CGNK paths like generate_project.py, run_local_pipeline, or simulator.
Pipeline manifest:
{json.dumps(manifest, ensure_ascii=False)[:12000]}"""


def collect_generation_context(session_path: str | pathlib.Path, whiteboard: dict[str, Any] | None = None) -> str:
    return pipeline_planner_agent.collect_generation_context(session_path, whiteboard or {})


def _history_for_step(session_path: pathlib.Path, system_prompt: str) -> list[dict[str, Any]]:
    events = agent_conversation_loop.read_session(session_path)
    return [{"kind": "step_system_prompt", "role": "system", "content": system_prompt}] + events


def _call_step_provider(events: list[dict[str, Any]], model: str, timeout: int) -> str:
    if str(model).startswith("gpt-test"):
        raise RuntimeError("test model does not call provider")
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    if not token:
        raise RuntimeError("missing OpenAI-compatible API key for dynamic pipeline runner")
    root = str(creds.get("base_url", "")).rstrip("/")
    system = str(events[0].get("content", "")) if events else ""
    history = "\n".join(f"{event.get('kind', 'event')}: {json.dumps(event, ensure_ascii=False)}" for event in events[1:])[-60000:]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": history}]
    endpoint = check_connectivity._openai_compatible_endpoint(root, model=model)
    payload = check_connectivity._build_openai_compatible_payload(
        root,
        {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 7000},
    )
    transport = check_connectivity._post_json_with_retry(
        endpoint,
        payload,
        token,
        timeout,
        max_attempts=3,
        base_delay_sec=1.2,
    )
    if transport.doc is not None:
        text = check_connectivity._extract_text(transport.doc)
        if text:
            return text
    raise RuntimeError(
        f"provider_api_request_failed: {transport.error}"
        if transport.error
        else "empty dynamic pipeline agent response"
    )


def _local_task_for_step(role: dict[str, Any], step: dict[str, Any]) -> str:
    role_id = str(role.get("id", "")).strip().lower()
    step_id = str(step.get("id", "")).strip().lower()
    if role_id == "cfo" and step_id == "cfo_pipeline":
        return "cfo_pipeline"
    if role_id == "context_librarian":
        return "context_support"
    if role_id == "risk_reviewer":
        return "risk_support"
    if role_id == "foundation":
        return "foundation"
    if role_id == "qa":
        return "qa"
    return ""


def _call_step_agent(events: list[dict[str, Any]], model: str, timeout: int, *, role: dict[str, Any], step: dict[str, Any]) -> str:
    if str(role.get("id", "")).strip().lower() == "codex_capability_supervisor":
        raise RuntimeError("codex_capability_supervisor_requires_external_codex_handoff")
    local_task = _local_task_for_step(role, step)
    if local_task:
        system = str(events[0].get("content", "")) if events else ""
        history = "\n".join(f"{event.get('kind', 'event')}: {json.dumps(event, ensure_ascii=False)}" for event in events[1:])[-60000:]
        local_result = local_model_router.call_text_task(local_task, system, history, timeout)
        if local_result.get("ok") and str(local_result.get("text", "")).strip():
            return str(local_result["text"]).strip()
    return _call_step_provider(events, model, timeout)


def _forbidden_command(command: str) -> bool:
    lowered = str(command or "").lower()
    return any(pattern in lowered for pattern in pipeline_manifest.FORBIDDEN_LEGACY_PATTERNS)


def _execute_manifest_action(
    executor: local_agent_actions.LocalAgentActionExecutor,
    action: dict[str, Any],
    allowed_actions: set[str],
) -> dict[str, Any]:
    action_type = str(action.get("type") or action.get("action") or "").strip()
    if action_type not in allowed_actions:
        return {"ok": False, "type": action_type, "error": f"action type not allowed for this step: {action_type}"}
    if action_type == "run_command" and _forbidden_command(str(action.get("command", ""))):
        return {"ok": False, "type": action_type, "error": "legacy generation command rejected"}
    if action_type == "write_file" and str(action.get("path", "")).strip().lower().endswith(".json"):
        content = str(action.get("content", ""))
        try:
            json.loads(content)
        except Exception as exc:
            return {
                "ok": False,
                "type": action_type,
                "path": str(action.get("path", "")),
                "error": f"write_file JSON content is invalid: {exc}",
            }
    return executor.execute(action)


def collect_quality_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    checks = {
        "readme": project / "README.md",
        "test_report": project / "TEST_REPORT.md",
        "delivery_notes": project / "DELIVERY_NOTES.md",
        "product_plan": project / "PRODUCT_PLAN.md",
        "output_contract": project / "OUTPUT_CONTRACT.md",
        "technical_plan": project / "TECHNICAL_PLAN.md",
        "build_plan": project / "BUILD_PLAN.md",
    }
    evidence = {
        "readme_found": checks["readme"].exists(),
        "test_report_found": checks["test_report"].exists(),
        "delivery_notes_found": checks["delivery_notes"].exists(),
        "product_plan_found": checks["product_plan"].exists(),
        "output_contract_found": checks["output_contract"].exists(),
        "technical_plan_found": checks["technical_plan"].exists(),
        "build_plan_found": checks["build_plan"].exists(),
        "preview_evidence_found": False,
        "missing": [],
    }
    preview_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".html"}
    if project.exists():
        evidence["preview_evidence_found"] = any(path.is_file() and path.suffix.lower() in preview_suffixes for path in project.rglob("*"))
    missing_keys = {
        "readme_found": "readme",
        "test_report_found": "test_report",
        "delivery_notes_found": "delivery_notes",
        "product_plan_found": "product_plan",
        "output_contract_found": "output_contract",
        "technical_plan_found": "technical_plan",
        "build_plan_found": "build_plan",
        "preview_evidence_found": "preview_evidence",
    }
    evidence["missing"] = [label for key, label in missing_keys.items() if not evidence.get(key)]
    return evidence


def _rel(project: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(project.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _find_files(project: pathlib.Path, patterns: tuple[str, ...], *, limit: int = 80) -> list[str]:
    out: list[str] = []
    if not project.exists():
        return out
    for pattern in patterns:
        for path in sorted(project.glob(pattern)):
            if path.is_file():
                rel = _rel(project, path)
                if rel not in out:
                    out.append(rel)
            if len(out) >= limit:
                return out
    return out


def _project_files(project: pathlib.Path) -> list[pathlib.Path]:
    if not project.exists():
        return []
    return [path for path in project.rglob("*") if path.is_file()]


def _has_python_entrypoint(project: pathlib.Path) -> bool:
    return any((project / name).is_file() for name in PYTHON_ENTRYPOINTS)


def _has_dependency_file(project: pathlib.Path) -> bool:
    return any((project / name).is_file() for name in PYTHON_DEPENDENCY_FILES)


def _has_source_file(project: pathlib.Path) -> bool:
    for path in _project_files(project):
        rel = _rel(project, path).lower()
        if path.suffix.lower() in SOURCE_SUFFIXES and not rel.startswith("tests/") and not pathlib.Path(rel).name.startswith("test_"):
            return True
    return False


def _has_test_file(project: pathlib.Path) -> bool:
    return bool(_find_files(project, ("tests/**/*.py", "test_*.py", "*_test.py")))


def _media_files(project: pathlib.Path) -> list[pathlib.Path]:
    return [path for path in _project_files(project) if path.suffix.lower() in MEDIA_SUFFIXES]


def _build_completion_audit(project_dir: str | pathlib.Path, manifest: dict[str, Any], whiteboard: dict[str, Any] | None = None) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    media = _media_files(project)
    visual = _visual_requirements(manifest, whiteboard)
    missing: list[str] = []
    if not _has_python_entrypoint(project):
        missing.append("app.py_or_main.py")
    if not _has_dependency_file(project):
        missing.append("requirements.txt_or_pyproject.toml")
    if not _has_source_file(project):
        missing.append("source_files")
    if not _has_test_file(project):
        missing.append("test_files")
    if not media:
        missing.append("image_or_preview_media")
    if visual["screenshot"] and not any(_looks_like_screenshot(path) for path in media):
        missing.append("ui_screenshot")
    if visual["generated_image"] and not any(_looks_like_generated_image(path) for path in media):
        missing.append("generated_images")
    if visual["background"] and not any(_looks_like_background(path) for path in media):
        missing.append("generated_background")
    if visual["sprite"] and not any(_looks_like_sprite(path) for path in media):
        missing.append("generated_sprite")
    if visual["video"] and not any(path.suffix.lower() in {".mp4", ".webm", ".gif"} for path in media):
        missing.append("demo_video")
    return {
        "ok": not missing,
        "missing": missing,
        "entrypoints": [name for name in PYTHON_ENTRYPOINTS if (project / name).is_file()],
        "dependency_files": [name for name in PYTHON_DEPENDENCY_FILES if (project / name).is_file()],
        "test_files": _find_files(project, ("tests/**/*.py", "test_*.py", "*_test.py")),
        "media_files": [_rel(project, path) for path in media[:80]],
        "visual_requirements": visual,
    }


def _extract_test_commands(test_report: pathlib.Path) -> list[str]:
    if not test_report.exists():
        return []
    text = test_report.read_text(encoding="utf-8", errors="replace")
    match = None
    for pattern in (
        r"commands_run\s*:?(.*?)(?:\n\s*(?:results|failures|repairs|remaining_warnings|#)\s*:|\Z)",
        r"test_commands\s*:?(.*?)(?:\n\s*(?:results|failures|repairs|remaining_warnings|#)\s*:|\Z)",
    ):
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            break
    section = match.group(1) if match else ""
    commands: list[str] = []
    for line in section.splitlines():
        cleaned = line.strip().strip("-*` ").strip()
        if cleaned and cleaned.lower() not in {"none", "no test executed", "未执行"}:
            commands.append(cleaned[:500])
    return commands[:20]


def _test_report_has_no_test_executed(test_report: pathlib.Path) -> bool:
    if not test_report.exists():
        return False
    text = test_report.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r"NO[\s_]+TEST[\s_]+EXECUTED", text.upper()))


def _qa_completion_audit(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    test_report = project / "TEST_REPORT.md"
    commands = _extract_test_commands(test_report)
    missing: list[str] = []
    if not test_report.exists():
        missing.append("TEST_REPORT.md")
    if _test_report_has_no_test_executed(test_report):
        missing.append("real_test_execution")
    if not commands:
        missing.append("test_commands")
    return {
        "ok": not missing,
        "missing": missing,
        "test_report_path": _rel(project, test_report) if test_report.exists() else "",
        "test_commands": commands,
        "no_test_executed": _test_report_has_no_test_executed(test_report),
    }


def collect_user_review_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    test_report = project / "TEST_REPORT.md"
    evidence_review = project / "EVIDENCE_REVIEW.md"
    test_code_files = _find_files(project, ("tests/**/*.py", "test_*.py", "*_test.py"))
    sample_inputs = _find_files(project, ("samples/**/*", "test_data/**/*", "demo/**/*"))
    screenshots = [item for item in _find_files(project, ("screenshots/**/*", "artifacts/**/*", "preview/**/*", "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp")) if pathlib.Path(item).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    generated_images = [
        item
        for item in _find_files(project, ("generated/**/*", "outputs/**/*", "output/**/*", "assets/**/*", "artifacts/**/*", "preview/**/*", "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp", "**/*.gif"))
        if pathlib.Path(item).suffix.lower() in MEDIA_SUFFIXES and _looks_like_generated_image(project / item)
    ]
    videos = [item for item in _find_files(project, ("artifacts/**/*", "preview/**/*", "**/*.mp4", "**/*.webm", "**/*.gif")) if pathlib.Path(item).suffix.lower() in {".mp4", ".webm", ".gif"}]
    preview_files = [item for item in _find_files(project, ("artifacts/**/*", "preview/**/*", "**/*.html", "**/*.csv", "**/*.json", "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp", "**/*.gif", "**/*.mp4", "**/*.webm")) if pathlib.Path(item).suffix.lower() in PREVIEW_SUFFIXES]
    missing: list[str] = []
    if not test_report.exists():
        missing.append("TEST_REPORT.md")
    if not evidence_review.exists():
        missing.append("EVIDENCE_REVIEW.md")
    if not test_code_files:
        missing.append("test_code_files")
    if not sample_inputs:
        missing.append("sample_inputs")
    if not screenshots:
        missing.append("screenshots")
    if not generated_images:
        missing.append("generated_images")
    if not videos:
        missing.append("videos")
    if not preview_files:
        missing.append("preview_files")
    return {
        "test_report_path": _rel(project, test_report) if test_report.exists() else "",
        "evidence_review_path": _rel(project, evidence_review) if evidence_review.exists() else "",
        "test_code_files": test_code_files,
        "test_commands": _extract_test_commands(test_report),
        "sample_inputs": sample_inputs,
        "screenshots": screenshots,
        "generated_images": generated_images,
        "videos": videos,
        "preview_files": preview_files,
        "missing": missing,
    }


def _evidence_blockers(evidence: dict[str, Any], manifest: dict[str, Any], whiteboard: dict[str, Any] | None = None) -> list[str]:
    visual = _visual_requirements(manifest, whiteboard)
    blockers: list[str] = []
    if not evidence.get("test_report_path"):
        blockers.append("TEST_REPORT.md")
    if not evidence.get("test_code_files"):
        blockers.append("test_code_files")
    if not evidence.get("test_commands"):
        blockers.append("test_commands")
    if visual["screenshot"] and not evidence.get("screenshots"):
        blockers.append("screenshots")
    if visual["generated_image"] and not evidence.get("generated_images"):
        blockers.append("generated_images")
    generated_images = evidence.get("generated_images", []) if isinstance(evidence.get("generated_images"), list) else []
    if visual["background"] and not any(_looks_like_background(pathlib.Path(str(item))) for item in generated_images):
        blockers.append("generated_background")
    if visual["sprite"] and not any(_looks_like_sprite(pathlib.Path(str(item))) for item in generated_images):
        blockers.append("generated_sprite")
    if visual["video"] and not evidence.get("videos"):
        blockers.append("videos")
    return blockers


def requires_user_evidence_judgement(manifest: dict[str, Any], whiteboard: dict[str, Any] | None = None) -> bool:
    board = whiteboard if isinstance(whiteboard, dict) else {}
    if board.get("requires_user_evidence_review") is True:
        return True
    parts: list[str] = []
    for value in (manifest.get("project_goal"), board.get("project_summary")):
        if isinstance(value, str):
            parts.append(value)
    for key in ("known_facts", "acceptance_criteria", "delivery_requirements", "user_rules", "change_requests"):
        values = board.get(key, [])
        if isinstance(values, list):
            parts.extend(str(item) for item in values if str(item).strip())
        elif isinstance(values, str):
            parts.append(values)
    text = "\n".join(parts).lower()
    return any(token in text for token in USER_REVIEW_KEYWORDS)


def _stage_order_index(stage: str) -> int:
    try:
        return pipeline_manifest_module.REQUIRED_STAGES.index(stage)
    except ValueError:
        return -1


def _step_earliest_stage_index(step: dict[str, Any]) -> int:
    indexes = [_stage_order_index(stage) for stage in pipeline_manifest_module._stage_values(step.get("stage"))]
    valid = [index for index in indexes if index >= 0]
    return min(valid) if valid else -1


def _should_skip_for_start_stage(step: dict[str, Any], start_stage: str) -> bool:
    if not start_stage:
        return False
    start_index = _stage_order_index(start_stage)
    if start_index < 0:
        return False
    step_index = _step_earliest_stage_index(step)
    return step_index >= 0 and step_index < start_index


def _step_has_stage(step: dict[str, Any], stage: str) -> bool:
    return stage in pipeline_manifest_module._stage_values(step.get("stage"))


def _has_later_stage_step(steps: list[Any], current_index: int, stage: str) -> bool:
    for step in steps[current_index + 1 :]:
        if isinstance(step, dict) and _step_has_stage(step, stage):
            return True
    return False


def _is_worker_build_step(step: dict[str, Any]) -> bool:
    role = str(step.get("role", "")).strip().lower()
    step_id = str(step.get("id", "")).strip().lower()
    if role in {"cfo", "context_librarian", "risk_reviewer", "qa", "delivery_reviewer"}:
        return False
    if step_id in {"cfo_pipeline", "context_support", "risk_support", "qa", "test", "evidence_review", "cfo_review", "review"}:
        return False
    return _step_has_stage(step, "build")


def _is_qa_completion_step(step: dict[str, Any]) -> bool:
    role = str(step.get("role", "")).strip().lower()
    step_id = str(step.get("id", "")).strip().lower()
    return _step_has_stage(step, "test") and (role == "qa" or step_id in {"qa", "test"})


def _pipeline_rework_blocked(
    *,
    session_file: pathlib.Path,
    project: pathlib.Path,
    pipeline_manifest: dict[str, Any],
    step_id: str,
    reason: str,
    audit: dict[str, Any],
) -> dict[str, Any]:
    agent_conversation_loop.append_event(
        session_file,
        {
            "kind": "pipeline_rework_blocked",
            "role": "system",
            "step_id": step_id,
            "reason": reason,
            "audit": audit,
        },
    )
    return {
        "status": "rework_blocked",
        "session_path": str(session_file),
        "project_dir": str(project),
        "pipeline_manifest": pipeline_manifest,
        "blocked_step_id": step_id,
        "reason": reason,
        "audit": audit,
    }


def _write_repair_test_report(project: pathlib.Path, missing: list[str]) -> None:
    report = project / "TEST_REPORT.md"
    if report.exists():
        return
    inspected = ["README.md", "PRODUCT_PLAN.md", "OUTPUT_CONTRACT.md", "TECHNICAL_PLAN.md", "BUILD_PLAN.md"]
    existing = [item for item in inspected if (project / item).exists()]
    report.write_text(
        "\n".join(
            [
                "# Test Report",
                "",
                "NO TEST EXECUTED",
                "",
                "reason: TEST_REPORT.md was missing during pre-package audit, so the runner recorded an honest repair report before packaging.",
                f"manual_files_checked: {', '.join(existing) if existing else 'none'}",
                f"missing_evidence_before_repair: {', '.join(missing) if missing else 'none'}",
                "",
                "commands_run:",
                "- none",
                "",
                "results:",
                "- No automated test evidence was available before packaging.",
                "",
                "failures:",
                "- Missing test evidence before pre-package audit repair.",
                "",
                "repairs:",
                "- Wrote this TEST_REPORT.md during pre-package audit.",
                "",
                "remaining_warnings:",
                "- Automated tests were not executed.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_repair_delivery_notes(project: pathlib.Path, evidence: dict[str, Any]) -> None:
    notes = project / "DELIVERY_NOTES.md"
    if notes.exists():
        return
    test_status = "found" if evidence.get("test_report_found") or (project / "TEST_REPORT.md").exists() else "missing"
    delivery_status = "WARNING" if test_status == "found" else "PARTIAL"
    notes.write_text(
        "\n".join(
            [
                "# Delivery Notes",
                "",
                f"delivery_status: {delivery_status}",
                f"tests_executed: {test_status}",
                f"evidence_found: {json.dumps({k: v for k, v in evidence.items() if k.endswith('_found')}, ensure_ascii=False)}",
                f"evidence_missing: {', '.join(evidence.get('missing', [])) or 'none'}",
                "known_limits:",
                "- DELIVERY_NOTES.md was missing during pre-package audit and was repaired by the runner.",
                "revision_entry:",
                "- Pre-package audit created this review note so packaging can proceed with warnings instead of hidden gaps.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def pre_package_audit(session_file: str | pathlib.Path, project_dir: str | pathlib.Path, manifest: dict[str, Any]) -> dict[str, Any]:
    del manifest
    session = pathlib.Path(session_file).resolve()
    project = pathlib.Path(project_dir).resolve()
    project.mkdir(parents=True, exist_ok=True)
    before = collect_quality_evidence(project)
    original_missing = list(before.get("missing", []))
    agent_conversation_loop.append_event(
        session,
        {
            "kind": "pre_package_audit",
            "role": "system",
            "quality_evidence": before,
            "missing": original_missing,
        },
    )

    repairs: list[str] = []
    known_limits: list[str] = []
    if not before.get("test_report_found"):
        agent_conversation_loop.append_event(
            session,
            {
                "kind": "pre_package_repair_turn",
                "role": "qa",
                "goal": "Write TEST_REPORT.md. If tests cannot run, include NO TEST EXECUTED and the reason.",
            },
        )
        _write_repair_test_report(project, original_missing)
        repairs.append("test_report")
        known_limits.append("打包前未找到 TEST_REPORT.md，已自动补齐 NO TEST EXECUTED 测试报告")
    middle = collect_quality_evidence(project)
    if not middle.get("delivery_notes_found"):
        agent_conversation_loop.append_event(
            session,
            {
                "kind": "pre_package_repair_turn",
                "role": "delivery_reviewer",
                "goal": "Write DELIVERY_NOTES.md with test status, evidence, limits, and delivery status.",
            },
        )
        _write_repair_delivery_notes(project, middle)
        repairs.append("delivery_notes")
        known_limits.append("打包前未找到 DELIVERY_NOTES.md，已自动补齐 warning 交付复核说明")
    after = collect_quality_evidence(project)
    for item in after.get("missing", []):
        if item in {"test_report", "delivery_notes"}:
            known_limits.append(f"pre-package audit still missing {item}")
    return {
        "quality_evidence": after,
        "initial_quality_evidence": before,
        "missing": original_missing,
        "remaining_missing": after.get("missing", []),
        "repairs": repairs,
        "known_limits": known_limits,
    }


def _nested_action(step: dict[str, Any]) -> dict[str, Any]:
    return step.get("action", {}) if isinstance(step.get("action"), dict) else {}


def _step_action(step: dict[str, Any]) -> dict[str, Any]:
    step_type = str(step.get("type", ""))
    nested = _nested_action(step)
    if step_type == "package_project":
        return {"type": "package_project", "startup_command": str(step.get("startup_command", "")), "known_limits": step.get("known_limits", [])}
    if step_type == "run_command":
        return {"type": "run_command", "command": str(step.get("command") or nested.get("command", ""))}
    if step_type == "use_skill":
        return {
            "type": "use_skill",
            "name": str(step.get("name") or step.get("skill") or nested.get("name", "")),
            "args": step.get("args") if isinstance(step.get("args"), dict) else nested.get("args", {}),
        }
    return {}


def _run_agent_turn(
    *,
    session_file: pathlib.Path,
    executor: local_agent_actions.LocalAgentActionExecutor,
    manifest: dict[str, Any],
    step: dict[str, Any],
    model: str,
    timeout: int,
    max_turns: int,
    agent: AgentCallable | None,
) -> dict[str, Any]:
    role = _role_by_id(manifest, str(step.get("role", "")))
    allowed_actions = {str(item) for item in step.get("allowed_actions", [])}
    last_error = ""
    for turn in range(1, max(1, max_turns) + 1):
        system_prompt = _system_prompt(role, step, manifest)
        events = _history_for_step(session_file, system_prompt)
        try:
            response = agent(events, model, timeout) if agent else _call_step_agent(events, model, timeout, role=role, step=step)
        except Exception as exc:
            last_error = str(exc)
            agent_conversation_loop.append_event(
                session_file,
                {"kind": "agent_error", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "error": last_error},
            )
            continue
        parsed = agent_conversation_loop.parse_agent_response(response)
        actions = parsed.get("actions", [])
        parse_error = str(parsed.get("parse_error", "")).strip()
        agent_conversation_loop.append_event(
            session_file,
            {
                "kind": "assistant",
                "role": role.get("id"),
                "step_id": step.get("id"),
                "turn": turn,
                "message": parsed.get("message", ""),
                "actions": actions,
                "parse_error": parse_error,
            },
        )
        if not actions:
            last_error = f"agent returned malformed JSON: {parse_error}" if parse_error else "agent returned no actions"
            agent_conversation_loop.append_event(
                session_file,
                {
                    "kind": "tool_result",
                    "role": role.get("id"),
                    "step_id": step.get("id"),
                    "turn": turn,
                    "ok": False,
                    "error": last_error,
                    "repair_instruction": "Return strict JSON with a non-empty actions array for this same manifest step.",
                    "raw_preview": str(parsed.get("raw", ""))[:1000],
                },
            )
            continue
        failed = bool(parse_error)
        if parse_error:
            last_error = f"agent response was partially recovered from malformed JSON: {parse_error}"
            agent_conversation_loop.append_event(
                session_file,
                {
                    "kind": "tool_result",
                    "role": role.get("id"),
                    "step_id": step.get("id"),
                    "turn": turn,
                    "ok": False,
                    "error": last_error,
                    "repair_instruction": "Some complete write_file actions were executed, but the same manifest step must return strict JSON to finish.",
                    "raw_preview": str(parsed.get("raw", ""))[:1000],
                },
            )
        package_result: dict[str, Any] | None = None
        for action in actions:
            if str(action.get("type") or action.get("action") or "") == "package_project":
                audit = pre_package_audit(session_file, executor.project_dir, manifest)
                merged_limits = list(action.get("known_limits", []) if isinstance(action.get("known_limits"), list) else [])
                merged_limits.extend(audit.get("known_limits", []))
                action = dict(action)
                action["known_limits"] = merged_limits
            agent_conversation_loop.append_event(session_file, {"kind": "action", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "action": action})
            result = _execute_manifest_action(executor, action, allowed_actions)
            agent_conversation_loop.append_event(
                session_file,
                {"kind": "tool_result", "role": role.get("id"), "step_id": step.get("id"), "turn": turn, "action": action, "result": result},
            )
            if not result.get("ok"):
                failed = True
                last_error = str(result.get("error") or "action failed")
            if str(action.get("type") or action.get("action") or "") == "package_project" and result.get("ok"):
                package_result = result
        if package_result:
            return {"status": "ok", "summary": "package_project action completed", "package_result": package_result}
        if not failed:
            return {"status": "ok", "summary": str(parsed.get("message") or "step completed")}
    return {"status": "failed", "summary": last_error or "agent step failed"}


def _fallback_to_agent_loop(
    *,
    session_file: pathlib.Path,
    project: pathlib.Path,
    model: str,
    timeout: int,
    max_turns: int,
    reason: str,
) -> dict[str, Any]:
    agent_conversation_loop.append_event(session_file, {"kind": "pipeline_fallback", "role": "system", "reason": reason})
    result = agent_conversation_loop.run_agent_loop(
        session_path=session_file,
        project_dir=project,
        model=model,
        timeout=timeout,
        max_turns=max_turns,
    )
    result["driver"] = "agent_conversation_loop_fallback"
    return result


def run_dynamic_pipeline(
    *,
    session_path: str | pathlib.Path,
    project_dir: str | pathlib.Path,
    pipeline_manifest: dict[str, Any],
    model: str = "gpt-5.4-nano",
    timeout: int = 120,
    max_turns: int = 12,
    agent: AgentCallable | None = None,
    fallback_to_agent_loop: bool = True,
    whiteboard: dict[str, Any] | None = None,
    skip_user_evidence_checkpoint: bool = False,
    start_stage: str = "",
) -> dict[str, Any]:
    session_file = pathlib.Path(session_path).resolve()
    project = pathlib.Path(project_dir).resolve()
    ok, errors = pipeline_manifest_module.validate_pipeline_manifest(pipeline_manifest)
    if not ok:
        reason = "; ".join(errors)
        if fallback_to_agent_loop:
            return _fallback_to_agent_loop(session_file=session_file, project=project, model=model, timeout=timeout, max_turns=max_turns, reason=reason)
        raise RuntimeError(reason)

    executor = local_agent_actions.LocalAgentActionExecutor(project)
    agent_conversation_loop.append_event(session_file, {"kind": "pipeline_manifest", "role": "system", "manifest": pipeline_manifest})
    limits = pipeline_manifest.get("limits", {}) if isinstance(pipeline_manifest.get("limits"), dict) else {}
    per_step_turns = max(1, min(int(limits.get("max_agent_turns_per_step", 3) or 3), max(1, int(max_turns or 1))))
    max_steps = max(1, min(int(limits.get("max_total_steps", 12) or 12), 12))
    package_result: dict[str, Any] | None = None

    try:
        steps = pipeline_manifest.get("steps", [])[:max_steps]
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id", ""))
            step_type = str(step.get("type", ""))
            if _should_skip_for_start_stage(step, start_stage):
                agent_conversation_loop.append_event(
                    session_file,
                    {
                        "kind": "pipeline_step_skipped",
                        "step_id": step_id,
                        "reason": "resume_start_stage",
                        "start_stage": start_stage,
                    },
                )
                continue
            if step_type == "agent_turn":
                result = _run_agent_turn(
                    session_file=session_file,
                    executor=executor,
                    manifest=pipeline_manifest,
                    step=step,
                    model=model,
                    timeout=timeout,
                    max_turns=per_step_turns,
                    agent=agent,
                )
                if result.get("status") == "ok" and _is_worker_build_step(step) and not _has_later_stage_step(steps, step_index, "build"):
                    audit = _build_completion_audit(project, pipeline_manifest, whiteboard)
                    if not audit.get("ok"):
                        result = {
                            "status": "rework_blocked",
                            "summary": "build output is incomplete: " + ", ".join(audit.get("missing", [])),
                            "quality_audit": audit,
                        }
                        agent_conversation_loop.append_event(
                            session_file,
                            {"kind": "build_output_audit", "role": "system", "step_id": step_id, "status": "rework_blocked", "audit": audit},
                        )
                if result.get("status") == "ok" and _is_qa_completion_step(step) and not _has_later_stage_step(steps, step_index, "test"):
                    audit = _qa_completion_audit(project)
                    if not audit.get("ok"):
                        result = {
                            "status": "rework_blocked",
                            "summary": "QA evidence is incomplete: " + ", ".join(audit.get("missing", [])),
                            "quality_audit": audit,
                        }
                        agent_conversation_loop.append_event(
                            session_file,
                            {"kind": "qa_output_audit", "role": "system", "step_id": step_id, "status": "rework_blocked", "audit": audit},
                        )
                agent_conversation_loop.append_event(
                    session_file,
                    {
                        "kind": "pipeline_step_result",
                        "step_id": step_id,
                        "role": step.get("role"),
                        "status": result.get("status"),
                        "summary": result.get("summary", ""),
                    },
                )
                if result.get("package_result"):
                    package_result = result["package_result"]
                    break
                if result.get("status") == "rework_blocked":
                    return _pipeline_rework_blocked(
                        session_file=session_file,
                        project=project,
                        pipeline_manifest=pipeline_manifest,
                        step_id=step_id,
                        reason=str(result.get("summary", "")),
                        audit=result.get("quality_audit", {}) if isinstance(result.get("quality_audit"), dict) else {},
                    )
                if result.get("status") != "ok":
                    raise RuntimeError(f"pipeline step failed: {step_id}: {result.get('summary', '')}")
                stages = pipeline_manifest_module._stage_values(step.get("stage"))
                if "evidence_review" in stages:
                    evidence = collect_user_review_evidence(project)
                    requires_review = requires_user_evidence_judgement(pipeline_manifest, whiteboard)
                    missing_evidence = _evidence_blockers(evidence, pipeline_manifest, whiteboard)
                    if requires_review and missing_evidence:
                        audit = {"evidence": evidence, "missing": missing_evidence}
                        agent_conversation_loop.append_event(
                            session_file,
                            {
                                "kind": "user_evidence_checkpoint",
                                "role": "system",
                                "step_id": step_id,
                                "status": "rework_blocked",
                                "evidence": evidence,
                                "requires_user_judgement": True,
                                "message": "中间证据不完整，不能请求用户确认；需要先回到构建/测试补齐。",
                            },
                        )
                        agent_conversation_loop.append_event(
                            session_file,
                            {
                                "kind": "pipeline_step_result",
                                "step_id": step_id,
                                "role": step.get("role"),
                                "status": "rework_blocked",
                                "summary": "evidence review is incomplete: " + ", ".join(missing_evidence),
                            },
                        )
                        return _pipeline_rework_blocked(
                            session_file=session_file,
                            project=project,
                            pipeline_manifest=pipeline_manifest,
                            step_id=step_id,
                            reason="evidence review is incomplete: " + ", ".join(missing_evidence),
                            audit=audit,
                        )
                    agent_conversation_loop.append_event(
                        session_file,
                        {
                            "kind": "user_evidence_checkpoint",
                            "role": "system",
                            "step_id": step_id,
                            "evidence": evidence,
                            "requires_user_judgement": requires_review,
                            "message": "中间测试和预览证据已准备好，等待用户判断或继续。",
                        },
                    )
                    if requires_review and not skip_user_evidence_checkpoint:
                        return {
                            "status": "waiting_user_review",
                            "session_path": str(session_file),
                            "project_dir": str(project),
                            "pipeline_manifest": pipeline_manifest,
                            "evidence": evidence,
                            "requires_user_judgement": True,
                            "message": "中间测试和预览证据已准备好，等待用户判断或继续。",
                        }
            elif step_type in {"use_skill", "run_command", "package_project"}:
                action = _step_action(step)
                if step_type == "package_project":
                    audit = pre_package_audit(session_file, project, pipeline_manifest)
                    known_limits = list(action.get("known_limits", []) if isinstance(action.get("known_limits"), list) else [])
                    known_limits.extend(audit.get("known_limits", []))
                    action["known_limits"] = known_limits
                    action["user_review_required"] = requires_user_evidence_judgement(pipeline_manifest, whiteboard)
                    action["user_review_completed"] = bool(skip_user_evidence_checkpoint) or not action["user_review_required"]
                allowed = {action["type"]} if action.get("type") else set()
                if action.get("type") == "run_command" and _forbidden_command(str(action.get("command", ""))):
                    result = {"ok": False, "type": "run_command", "error": "legacy generation command rejected"}
                else:
                    result = _execute_manifest_action(executor, action, allowed)
                agent_conversation_loop.append_event(session_file, {"kind": "action", "role": "system", "step_id": step_id, "action": action})
                agent_conversation_loop.append_event(session_file, {"kind": "tool_result", "role": "system", "step_id": step_id, "action": action, "result": result})
                status = "ok" if result.get("ok") else "failed"
                agent_conversation_loop.append_event(
                    session_file,
                    {"kind": "pipeline_step_result", "step_id": step_id, "role": "system", "status": status, "summary": str(result.get("error") or action.get("type", ""))},
                )
                if not result.get("ok"):
                    raise RuntimeError(f"pipeline step failed: {step_id}: {result.get('error', '')}")
                if step_type == "package_project":
                    package_result = result
                    break
            elif step_type == "update_whiteboard":
                agent_conversation_loop.append_event(
                    session_file,
                    {
                        "kind": "whiteboard_patch_requested",
                        "role": "system",
                        "step_id": step_id,
                        "patch": step.get("patch", {}),
                        "goal": step.get("goal", ""),
                    },
                )
                agent_conversation_loop.append_event(
                    session_file,
                    {"kind": "pipeline_step_result", "step_id": step_id, "role": "system", "status": "ok", "summary": "whiteboard patch request recorded"},
                )
        if package_result:
            manifest = package_result.get("manifest", {}) if isinstance(package_result.get("manifest"), dict) else {}
            return {
                "status": str(manifest.get("status") or "ready"),
                "session_path": str(session_file),
                "project_dir": str(project),
                "manifest": manifest,
                "package_path": manifest.get("package_path", ""),
                "manifest_path": manifest.get("manifest_path", ""),
                "pipeline_manifest": pipeline_manifest,
            }
        raise RuntimeError("pipeline completed without package_project result")
    except Exception as exc:
        if fallback_to_agent_loop:
            return _fallback_to_agent_loop(
                session_file=session_file,
                project=project,
                model=model,
                timeout=timeout,
                max_turns=max_turns,
                reason=str(exc),
            )
        raise
pipeline_manifest_module = pipeline_manifest
