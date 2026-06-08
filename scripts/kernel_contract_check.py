#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def read_rel(path: str) -> str:
    full = ROOT / path
    if not full.exists():
        raise FileNotFoundError(path)
    return full.read_text(encoding="utf-8", errors="replace")


def section_between(text: str, start_pattern: str, end_pattern: str) -> str:
    start = re.search(start_pattern, text, flags=re.S | re.M)
    if not start:
        return ""
    end = re.search(end_pattern, text[start.end() :], flags=re.S | re.M)
    if not end:
        return text[start.start() :]
    return text[start.start() : start.end() + end.start()]


def function_body(text: str, name: str) -> str:
    match = re.search(rf"^def\s+{re.escape(name)}\s*\(", text, flags=re.M)
    if not match:
        return ""
    next_match = re.search(r"^def\s+\w+\s*\(", text[match.end() :], flags=re.M)
    if not next_match:
        return text[match.start() :]
    return text[match.start() : match.end() + next_match.start()]


def contains_all(text: str, needles: list[str]) -> tuple[bool, list[str]]:
    missing = [needle for needle in needles if needle not in text]
    return not missing, missing


def add(results: list[CheckResult], name: str, ok: bool, detail: str = "") -> None:
    results.append(CheckResult(name, ok, "" if ok else detail))


def check_telegram(results: list[CheckResult]) -> None:
    text = read_rel("scripts/telegram_live_bridge.py")
    bridge_forbidden = [
        item
        for item in [
            "generate_project.py",
            "run_generation_subprocess(args",
            "generation_subprocess_command",
        ]
        if item in text
    ]
    add(results, "telegram bridge does not embed naked legacy CLI pipeline", not bridge_forbidden, ", ".join(bridge_forbidden))

    ok, missing = contains_all(
        text,
        [
            "start_agent_generation",
            "run_provider_generation_job",
            "backend_dialogue_loop",
            "apply_backend_dialogue_tick",
            "should_auto_start_generation",
            "agent_session_path",
            "finish_agent_loop_delivery",
        ],
    )
    add(results, "telegram bridge exposes required kernel functions", ok, ", ".join(missing))

    backend_control = function_body(text, "append_backend_control")
    ok, missing = contains_all(backend_control, ['"BackendControlLog"', '"log_only": True', 'status: str = "logged"'])
    add(results, "backend_controls remain log-only compatibility records", ok, ", ".join(missing))

    generation_branch = section_between(text, r'if\s+intent\s*==\s*"generation_confirmation"\s*:', r'^\s*if\s+intent\s*==\s*"escalation_request"\s*:')
    forbidden = [
        item
        for item in [
            "generate_project.py",
            "run_local_pipeline",
            "simulator",
            "run_generation_subprocess",
            "run_agent_loop",
            "run_generation_job",
        ]
        if item in generation_branch
    ]
    add(results, "generation_confirmation does not call legacy pipeline", bool(generation_branch) and not forbidden, ", ".join(forbidden))
    generation_calls = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", generation_branch)
    start_calls = [call for call in generation_calls if call == "start_agent_generation"]
    forbidden_generation_calls = [call for call in generation_calls if call in {"run_agent_loop", "run_generation_job", "run_generation_subprocess"}]
    add(
        results,
        "generation_confirmation only starts formal generation through start_agent_generation",
        bool(start_calls) and not forbidden_generation_calls,
        ", ".join(forbidden_generation_calls) or "start_agent_generation missing",
    )

    gate_pattern = r'if[^\n]*(soft_questions|blocking_questions)[^\n]*:\s*\n(?:\s+.*\n){0,6}?\s+return\b'
    gate = re.search(gate_pattern, generation_branch)
    add(results, "soft/blocking questions are not hard generation gates", bool(generation_branch) and gate is None, "return under question branch" if gate else "")

    start = function_body(text, "start_agent_generation")
    ok, missing = contains_all(start, ['driver": "api_provider_project_generation"', "target=run_provider_generation_job"])
    agent_default_forbidden = [item for item in ['driver": "agent_generated_pipeline"', "target=run_agent_generation_job"] if item in start]
    add(
        results,
        "Telegram default generation dispatch uses provider project route",
        ok and not agent_default_forbidden,
        ", ".join(missing + agent_default_forbidden),
    )

    provider_job = function_body(text, "run_provider_generation_job") + function_body(text, "run_provider_execute_with_retries")
    ok, missing = contains_all(
        provider_job,
        [
            "provider_project_pipeline.execute",
            "api-provider-project-generated",
            "provider-output-validated",
            "provider-project-files-written",
            "runtime-artifacts-written",
            "local_packager.package_project",
            "evaluate_public_delivery_gate",
            "provider_success_artifact_audit",
            "mark_public_delivery_rework",
            "finish_agent_loop_delivery",
        ],
    )
    add(results, "provider generation route is wrapped by packager and public gate", ok, ", ".join(missing))

    job = function_body(text, "run_agent_generation_job")
    planner_index = job.find("pipeline_planner_agent.plan_pipeline")
    runner_index = job.find("dynamic_pipeline_runner.run_dynamic_pipeline")
    manifest_index = job.find("pipeline_manifest_module.write_pipeline_manifest")
    fallback_index = job.find('"pipeline_fallback"')
    finish_index = job.find("finish_agent_loop_delivery")
    ok, missing = contains_all(
        job,
        [
            "pipeline_planner_agent.plan_pipeline",
            "pipeline_manifest_module.write_pipeline_manifest",
            "dynamic_pipeline_runner.run_dynamic_pipeline",
            '"pipeline_fallback"',
            "finish_agent_loop_delivery",
        ],
    )
    add(results, "support agent pipeline contains consolidated pipeline landmarks", ok, ", ".join(missing))
    add(
        results,
        "support agent pipeline plans manifest before dynamic runner",
        planner_index >= 0 and runner_index > planner_index and manifest_index > planner_index and manifest_index < runner_index,
        "planner/write/runner order missing",
    )
    add(results, "pipeline fallback is explicitly recorded", fallback_index >= 0, "pipeline_fallback missing")
    add(results, "finish_agent_loop_delivery remains final handoff", finish_index > runner_index, "finish_agent_loop_delivery not after runner")


def check_planner(results: list[CheckResult]) -> None:
    text = read_rel("scripts/pipeline_planner_agent.py")
    ok, missing = contains_all(text, ["plan_pipeline", "pipeline_manifest", "default_minimal_pipeline_manifest"])
    add(results, "pipeline planner exists with fallback", ok, ", ".join(missing))
    forbidden = [item for item in [".write_text(", "write_file", "LocalAgentActionExecutor"] if item in function_body(text, "plan_pipeline")]
    add(results, "pipeline planner does not directly write project files", not forbidden, ", ".join(forbidden))


def check_manifest(results: list[CheckResult]) -> None:
    text = read_rel("scripts/pipeline_manifest.py")
    ok, missing = contains_all(
        text,
        [
            "validate_pipeline_manifest",
            "normalize_pipeline_manifest",
            "default_minimal_pipeline_manifest",
            "REQUIRED_STAGES",
            "validate_required_stages",
            "product_plan",
            "technical_plan",
            "ALLOWED_STEP_TYPES",
            "MAX_ROLES",
            "MAX_STEPS",
            "steps[{index}].type is not allowed",
            "must not call legacy generation paths",
            "FORBIDDEN_LEGACY_PATTERNS",
        ],
    )
    add(results, "pipeline manifest validates allowed step types", ok, ", ".join(missing))


def check_runner(results: list[CheckResult]) -> None:
    text = read_rel("scripts/dynamic_pipeline_runner.py")
    ok, missing = contains_all(
        text,
        [
            "run_dynamic_pipeline",
            "pipeline_manifest",
            "pipeline_step_result",
            "package_project",
            "local_agent_actions.LocalAgentActionExecutor",
        ],
    )
    add(results, "dynamic runner interprets manifest through local actions", ok, ", ".join(missing))
    forbidden = [item for item in ["exec(", "eval(", "compile(", "subprocess.run("] if item in text]
    add(results, "dynamic runner does not expose arbitrary Python execution", not forbidden, ", ".join(forbidden))


def check_local_actions(results: list[CheckResult]) -> None:
    text = read_rel("scripts/local_agent_actions.py")
    ok, missing = contains_all(
        text,
        ["write_file", "read_file", "list_files", "run_command", "package_project", "search_skills", "use_skill", "propose_skill", "_project_path", "_inside"],
    )
    add(results, "local agent actions keep tool and path boundary", ok, ", ".join(missing))


def check_packager(results: list[CheckResult]) -> None:
    text = read_rel("scripts/local_packager.py")
    ok, missing = contains_all(text, ["package_project", "final_project_bundle.zip", "delivery_manifest.json", "quality_evidence", "TEST_REPORT.md", "DELIVERY_NOTES.md"])
    add(results, "local packager remains delivery exit", ok, ", ".join(missing))


def check_legacy_isolation(results: list[CheckResult]) -> None:
    legacy_provider = ROOT / "scripts" / "legacy_provider_pipeline.py"
    if legacy_provider.exists():
        text = legacy_provider.read_text(encoding="utf-8", errors="replace")
        ok, missing = contains_all(text, ["LEGACY ONLY", "Not part of CGNK formal Telegram generation"])
        add(results, "legacy provider pipeline is explicitly marked legacy", ok, ", ".join(missing))
    wrapper = ROOT / "scripts" / "generate_project.py"
    if wrapper.exists():
        text = wrapper.read_text(encoding="utf-8", errors="replace")
        ok, missing = contains_all(text, ["LEGACY CLI ONLY", "Not used by Telegram formal generation"])
        add(results, "generate_project CLI wrapper is explicitly marked legacy", ok, ", ".join(missing))


def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    for checker in (check_telegram, check_planner, check_manifest, check_runner, check_local_actions, check_packager, check_legacy_isolation):
        try:
            checker(results)
        except Exception as exc:
            add(results, checker.__name__, False, str(exc))
    return results


def main() -> int:
    results = run_checks()
    overall = all(result.ok for result in results)
    print("PASS" if overall else "FAIL")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        suffix = f" - {result.detail}" if result.detail else ""
        print(f"{status}: {result.name}{suffix}")
    if not overall:
        missing = [result.name for result in results if not result.ok]
        print("Missing or broken checks:")
        for name in missing:
            print(f"- {name}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
