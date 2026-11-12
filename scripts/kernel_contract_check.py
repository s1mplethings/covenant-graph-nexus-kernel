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


def check_codex(results: list[CheckResult]) -> None:
    text = read_rel("scripts/codex_conversation.py")
    bridge_forbidden = [
        item
        for item in [
            "generate_project.py",
            "run_generation_subprocess(args",
            "generation_subprocess_command",
        ]
        if item in text
    ]
    add(results, "codex bridge does not embed naked legacy CLI pipeline", not bridge_forbidden, ", ".join(bridge_forbidden))

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
    add(results, "codex bridge exposes required kernel functions", ok, ", ".join(missing))

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
    start_calls = [call for call in generation_calls if call in {"start_agent_generation", "start_generation_from_income"}]
    forbidden_generation_calls = [call for call in generation_calls if call in {"run_agent_loop", "run_generation_job", "run_generation_subprocess"}]
    add(
        results,
        "generation_confirmation only starts formal generation through the reviewed generation starter",
        bool(start_calls) and not forbidden_generation_calls,
        ", ".join(forbidden_generation_calls) or "reviewed generation starter missing",
    )

    income_start = function_body(text, "start_generation_from_income")
    ok, missing = contains_all(income_start, ["start_agent_generation", "PROJECT_SESSION_PROFILE_REQUIRED", "legacy simulator/replay lifecycle is offline-only"])
    add(
        results,
        "generation starter requires frozen session and rejects legacy simulator",
        ok,
        ", ".join(missing),
    )

    gate_pattern = r'if[^\n]*(soft_questions|blocking_questions)[^\n]*:\s*\n(?:\s+.*\n){0,6}?\s+return\b'
    gate = re.search(gate_pattern, generation_branch)
    add(results, "soft/blocking questions are not hard generation gates", bool(generation_branch) and gate is None, "return under question branch" if gate else "")

    start = function_body(text, "start_agent_generation")
    ok, missing = contains_all(start, ['project_session', 'target=run_provider_generation_job'])
    agent_default_forbidden = [item for item in ['driver": "agent_generated_pipeline"', "target=run_agent_generation_job"] if item in start]
    add(
        results,
        "Codex conversation default generation dispatch uses provider project route",
        ok and not agent_default_forbidden,
        ", ".join(missing + agent_default_forbidden),
    )

    provider_job = function_body(text, "run_provider_generation_job")
    service = read_rel("cgkn/application/software_project/service.py")
    ok, missing = contains_all(provider_job, ["SoftwareProjectGenerationService", "service.run_profile", "PRIOR_OUTCOME_UNKNOWN"])
    chain, chain_missing = contains_all(service, ["ProjectSession", "produce_project_session", "post_build_finalize_provider_project"])
    forbidden = [name for name in ["run_provider_execute_with_retries", "execute_validated_provider_round", "run_simulator_preflight"] if function_body(text,name)]
    add(results, "generation delegates to single session and existing finalization", ok and chain and not forbidden, ", ".join(missing+chain_missing+forbidden))
    adaptive_ok, adaptive_missing = contains_all(
        text,
        ["def delivery_fact_check", "def agent_delivery_judgment", "adaptive_delivery.delivery_fact_check", "adaptive_delivery.agent_delivery_judgment"],
    )
    add(results, "adaptive delivery fact and judgment layers are implemented", adaptive_ok, ", ".join(adaptive_missing))

    job = function_body(text, "run_agent_generation_job")
    add(results, "compatibility Agent entry delegates without alternate planner", "return run_provider_generation_job(" in job and "plan_pipeline(" not in job, "canonical delegation missing")


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
            "SoftwareProjectGenerationService",
            "PROJECT_SESSION_PROFILE_REQUIRED",
            "package_project",
            "local_agent_actions.LocalAgentActionExecutor",
        ],
    )
    add(results, "dynamic entry delegates to canonical session", ok, ", ".join(missing))
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
    retired = [
        "scripts/generate_project.py",
        "scripts/legacy_provider_pipeline.py",
        "scripts/deliver_product_studio.py",
        "scripts/run_product_studio.py",
        "legacy/generate_project_legacy.py",
        "legacy/deliver_product_studio.py",
        "legacy/run_product_studio.py",
    ]
    retained = [path for path in retired if (ROOT / path).exists()]
    add(results, "superseded generation surfaces are retired", not retained, ", ".join(retained))


def check_runtime_profiles(results: list[CheckResult]) -> None:
    bridge = read_rel("scripts/codex_conversation.py")
    supervisor = read_rel("scripts/cgkn_runtime_supervisor.py")
    bridge_ok, bridge_missing = contains_all(
        bridge,
        [
            "class CodexConversation",
            "The Codex app owns the sole user-facing conversation loop",
            "def start_generation_from_income",
            "local_packager",
            "public_delivery_gate",
        ],
    )
    add(results, "Codex app is the sole user-facing conversation surface", bridge_ok, ", ".join(bridge_missing))
    no_listener = all(
        marker not in bridge.lower()
        for marker in ("get" + "updates", "bot" + " token", "mini" + " app", "web" + "_app")
    ) and re.search(r"^def\s+main\s*\(", bridge, flags=re.MULTILINE) is None
    add(results, "Codex conversation module contains no external listener or alternate UI", no_listener)
    supervisor_ok = "_default_codex_argv" not in supervisor and "--start-codex" not in supervisor
    add(results, "persistent supervisor does not launch a second conversation service", supervisor_ok)


def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    for checker in (
        check_codex,
        check_planner,
        check_manifest,
        check_runner,
        check_local_actions,
        check_packager,
        check_legacy_isolation,
        check_runtime_profiles,
    ):
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
