#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

ROUTE_TERMS = [
    "API/provider project generation",
    "provider output validation",
    "post-build finalization",
    "local_packager",
    "public_delivery_gate",
    "delivery_manifest.json",
]
PUBLIC_SUFFIXES = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".zip"]
INTERNAL_SUFFIXES = [".md", ".json", ".jsonl", ".txt", ".log", ".yaml", ".yml", ".toml", ".ini"]
FORBIDDEN_CONFIRMATION_TERMS = [
    "generate_project.py",
    "run_local_pipeline",
    "run_generation_subprocess",
    "run_generation_job",
    "run_agent_generation_job",
    "simulator",
]
DELIVERY_GATE_FUNCTIONS = ["send_delivery_from_manifest", "send_evidence_checkpoint"]
DELIVERY_GATE_TERMS = ["evaluate_public_delivery_gate", "emit_public_delivery"]
RETIRED_GENERATION_FILES = [
    "scripts/generate_project.py",
    "scripts/legacy_provider_pipeline.py",
    "scripts/deliver_product_studio.py",
    "scripts/run_product_studio.py",
    "legacy/generate_project_legacy.py",
    "legacy/deliver_product_studio.py",
    "legacy/run_product_studio.py",
]
LEGACY_BRIDGE_WRAPPERS = ["build_generation_args", "run_generation_subprocess", "run_generation_job"]
PROVIDER_ROUTE_TERMS = [
    "provider_project_pipeline.execute",
    "provider-output-validated",
    "provider-project-files-written",
    "local_packager.package_project",
    "evaluate_public_delivery_gate",
    "finish_agent_loop_delivery",
]
BLOAT_HINTS = ["VNProjectCLI", "Flask create_app compatibility", "csgo", "鉴挂", "反作弊"]
PROJECT_TEAM_FILES = [
    "scripts/model_policy.py",
    "scripts/local_conversation_manager.py",
    "scripts/local_repo_manager.py",
    "scripts/main_agent_manager.py",
    "scripts/project_revision_lane.py",
]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def between(text: str, start: str, end: str) -> str:
    first = text.find(start)
    if first < 0:
        return ""
    second = text.find(end, first + len(start))
    if second < 0:
        return text[first:]
    return text[first:second]


def function_body(text: str, name: str) -> str:
    """Return the source of a top-level def, from its header to the next top-level def."""
    match = re.search(rf"^def\s+{re.escape(name)}\s*\(", text, flags=re.M)
    if not match:
        return ""
    next_match = re.search(r"^def\s+\w+\s*\(", text[match.end():], flags=re.M)
    if not next_match:
        return text[match.start():]
    return text[match.start(): match.end() + next_match.start()]


def add(checks: list[dict[str, object]], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": "" if ok else detail})


def run_checks(strict: bool = False) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    warnings: list[dict[str, str]] = []

    agents = read_text("AGENTS.md")
    kernel = read_text("docs/00_kernel_contract.md")
    bridge = read_text("scripts/codex_conversation.py")
    model_policy = read_text("scripts/model_policy.py") if (ROOT / "scripts/model_policy.py").exists() else ""
    revision_lane = read_text("scripts/project_revision_lane.py") if (ROOT / "scripts/project_revision_lane.py").exists() else ""
    local_studio = read_text("scripts/local_studio_cli.py") if (ROOT / "scripts/local_studio_cli.py").exists() else ""
    revision_doc = read_text("docs/09_project_revision_lane.md") if (ROOT / "docs/09_project_revision_lane.md").exists() else ""
    connectivity = read_text("scripts/check_connectivity.py")
    supervision_protocol = read_text("scripts/cgkn_supervision_protocol.py")
    supervision_host = read_text("scripts/cgkn_runtime_supervisor.py")
    supervision_router = read_text("scripts/cgkn_supervision_router.py")
    provider_jobs = read_text("scripts/provider_jobs.py")
    provider_impl = read_text("scripts/run_local_pipeline_impl.py")

    for path, text in (("AGENTS.md", agents), ("docs/00_kernel_contract.md", kernel)):
        missing = [term for term in ROUTE_TERMS if term not in text]
        add(checks, f"{path} names reviewed Codex conversation route", not missing, ", ".join(missing))
    add(
        checks,
        "kernel contract names adaptive delivery layers",
        "delivery_fact_check" in kernel and "agent_delivery_judgment" in kernel,
        "delivery_fact_check or agent_delivery_judgment missing",
    )
    add(
        checks,
        "codex bridge implements adaptive delivery layers",
        "def delivery_fact_check" in bridge and "def agent_delivery_judgment" in bridge,
        "adaptive delivery functions missing",
    )

    missing_team_files = [path for path in PROJECT_TEAM_FILES if not (ROOT / path).exists()]
    add(checks, "project team manager modules exist", not missing_team_files, ", ".join(missing_team_files))

    suffix_block = between(bridge, "PUBLIC_DELIVERY_SUFFIXES", "}")
    bad_suffixes = [suffix for suffix in INTERNAL_SUFFIXES if suffix in suffix_block]
    add(
        checks,
        "public delivery suffix whitelist is media/package only",
        all(suffix in suffix_block for suffix in PUBLIC_SUFFIXES) and not bad_suffixes,
        ", ".join(bad_suffixes) or "PUBLIC_DELIVERY_SUFFIXES missing expected media/package suffixes",
    )

    confirmation_branch = between(
        bridge,
        'if intent == "generation_confirmation":',
        'if intent == "escalation_request":',
    )
    bad_confirmation = [term for term in FORBIDDEN_CONFIRMATION_TERMS if term in confirmation_branch]
    add(
        checks,
        "generation confirmation dispatch stays thin",
        any(name in confirmation_branch for name in ("start_agent_generation", "start_generation_from_income"))
        and not bad_confirmation,
        ", ".join(bad_confirmation) or "reviewed generation starter missing",
    )

    start_body = between(bridge, "def start_agent_generation", "def ")
    add(
        checks,
        "default generation dispatch uses provider adapter",
        "run_provider_generation_job" in start_body and "run_agent_generation_job" not in start_body,
        "start_agent_generation route changed",
    )
    add(
        checks,
        "default generation dispatch marks api_provider_project_generation driver",
        "api_provider_project_generation" in start_body and "agent_generated_pipeline" not in start_body,
        "start_agent_generation driver is not api_provider_project_generation",
    )
    add(
        checks,
        "Codex audits only positive transitions",
        all(term in supervision_protocol for term in ("requirements_frozen", "integration_complete", "pre_public_delivery"))
        and "AUDIT_CHECKPOINT_TYPES" in supervision_host
        and '"pre_provider_generation"' not in bridge
        and '"provider_failure"' not in bridge,
        "bridge still emits an ordinary build/failure checkpoint or high-value audit set is missing",
    )
    add(
        checks,
        "ordinary product design does not invoke Codex",
        "run_codex_design_supervision" not in bridge
        and "CODEX_DESIGN_MODE" not in bridge
        and "provider_planner_ready" in bridge,
        "Codex design execution remains reachable from the production bridge",
    )
    add(
        checks,
        "retired planner and agent lanes are not production imports",
        all(
            marker not in bridge.splitlines()[:120]
            for marker in (
                "import agent_conversation_loop",
                "import dynamic_pipeline_runner",
                "import pipeline_planner_agent",
                "import pipeline_manifest as pipeline_manifest_module",
            )
        ),
        "retired support lane is still imported at module load time",
    )
    add(
        checks,
        "false-pass actions have one deterministic router",
        all(term in supervision_protocol for term in ("rework_project", "recheck_evidence", "repair_kernel", "user_decision"))
        and "provider_repair_required" in supervision_router
        and "canonical_verification_rerun_required" in supervision_router
        and "governed_kernel_repair_required" in supervision_router,
        "canonical audit action or deterministic route is missing",
    )
    add(
        checks,
        "production leaf executor is the only ProviderJob scheduler",
        "class ProviderJob" in provider_jobs
        and "CGKN_PROVIDER_PARALLELISM" in provider_jobs
        and "ThreadPoolExecutor" not in provider_jobs
        and "execute_provider_jobs" not in provider_jobs
        and "ThreadPoolExecutor" in provider_impl
        and "validate_patch_set" in provider_impl,
        "ProviderJob contract, unique production scheduler, or ownership boundary is missing",
    )
    add(
        checks,
        "production bridge consumes bounded false-pass routes",
        "MAX_SUPERVISION_REWORK_ROUNDS = 2" in bridge
        and "run_supervision_recovery_cycle" in bridge
        and "prepare_supervision_provider_repair" in bridge
        and "invalidate_supervision_evidence" in bridge
        and "execute_governed_supervision_repair" in bridge,
        "bounded production false-pass consumer is incomplete",
    )
    post_build_body = function_body(bridge, "post_build_finalize_provider_project")
    forbidden_kernel_repairs = [
        name
        for name in (
            "deterministic_post_build_repair",
            "ensure_provider_root_launcher",
            "repair_pydantic_basesettings",
            "repair_pillow_requirement",
            "repair_missing_test_import_requirements",
            "repair_common_provider_project_interfaces",
            "materialize_provider_test_artifacts",
        )
        if f"{name}(" in post_build_body
    ]
    add(
        checks,
        "post-build does not repair customer behavior in the kernel",
        not forbidden_kernel_repairs and "provider_repair_required" in post_build_body,
        ", ".join(forbidden_kernel_repairs) or "Provider repair routing marker missing",
    )

    provider_route_body = "\n".join(
        (
            function_body(bridge, "run_provider_generation_job"),
            function_body(bridge, "run_provider_execute_with_retries"),
            function_body(bridge, "execute_validated_provider_round"),
        )
    )
    missing_provider_terms = [term for term in PROVIDER_ROUTE_TERMS if term not in provider_route_body]
    add(
        checks,
        "provider route is behind validation packager and gate",
        bool(provider_route_body.strip()) and not missing_provider_terms,
        ", ".join(missing_provider_terms) or "provider route function bodies not found",
    )

    default_session_body = function_body(bridge, "default_session")
    add(
        checks,
        "codex default session carries active project state",
        "active_project" in default_session_body and "revision_history" in default_session_body,
        "default_session missing active_project or revision_history",
    )
    add(
        checks,
        "customer intents include project revision request",
        '"project_revision_request"' in between(bridge, "CUSTOMER_MESSAGE_INTENTS", "}"),
        "CUSTOMER_MESSAGE_INTENTS missing project_revision_request",
    )
    handle_body = function_body(bridge, "handle_text")
    revision_branch = between(handle_body, 'if intent == "project_revision_request":', 'if intent == "new_project_request":')
    add(
        checks,
        "codex revision branch delegates out of bridge",
        "MainAgentManager().start_project_revision" in revision_branch and "local_packager.package_project" not in revision_branch and "evaluate_public_delivery_gate" not in revision_branch,
        "revision handling should delegate without packaging or gate logic inside bridge",
    )
    add(
        checks,
        "revision manifest records previous manifest",
        "previous_manifest_ref" in revision_lane and "full_regenerate_reason" in revision_lane,
        "project_revision_lane missing revision manifest context fields",
    )
    add(
        checks,
        "revision delivery contract names packager and public gate",
        "local_packager" in revision_lane and "public_delivery_gate" in revision_lane and "delivery_manifest" in revision_lane,
        "project_revision_lane missing delivery contract terms",
    )
    add(
        checks,
        "revision failure does not promote current",
        "def mark_revision_failed" in revision_lane and "promote_revision_to_current" not in function_body(revision_lane, "mark_revision_failed"),
        "mark_revision_failed must not promote current",
    )
    provider_revision_body = function_body(revision_lane, "run_provider_revision_job")
    add(
        checks,
        "revision provider job is implemented",
        "def run_provider_revision_job" in revision_lane and "NotImplementedError" not in provider_revision_body,
        "project_revision_lane must implement Phase 2 provider revision execution",
    )
    required_revision_terms = ["local_packager", "public_delivery_gate", "mark_revision_success", "mark_revision_failed", "compute_changed_files"]
    missing_revision_terms = [term for term in required_revision_terms if term not in provider_revision_body]
    add(
        checks,
        "revision execution keeps delivery contract",
        not missing_revision_terms,
        ", ".join(missing_revision_terms),
    )
    add(
        checks,
        "revision docs declare phase 2 execution contract",
        "Phase 2 adds provider-backed revision execution" in revision_doc and "not a second public delivery route" in revision_doc,
        "docs/09_project_revision_lane.md must describe Phase 2 execution without adding a second route",
    )
    add(
        checks,
        "codex bridge does not call provider revision job",
        "run_provider_revision_job(" not in bridge,
        "codex_conversation.py must not directly call run_provider_revision_job",
    )
    add(
        checks,
        "model defaults are centralized for bridge and connectivity",
        "model_policy.select_model(\"provider_generation\")" in bridge and "model_policy.select_model(\"connectivity\")" in connectivity,
        "bridge or connectivity still bypasses model_policy defaults",
    )
    add(
        checks,
        "local studio routes through MainAgentManager only",
        "MainAgentManager" in local_studio
        and "run_local_pipeline" not in local_studio
        and "generate_project.py" not in local_studio
        and "simulator" not in local_studio,
        "local_studio_cli must not call legacy or support generation routes",
    )
    add(
        checks,
        "model policy exposes required task profiles",
        all(term in model_policy for term in ("provider_generation", "connectivity", "repair", "review", "CGNK_MODEL_PROFILE")),
        "model_policy missing required tasks or profile environment",
    )

    for name in DELIVERY_GATE_FUNCTIONS:
        body = between(bridge, f"def {name}", "\ndef ")
        missing_gate = [term for term in DELIVERY_GATE_TERMS if term not in body]
        add(
            checks,
            f"{name} delivers only through gate and emit",
            bool(body) and not missing_gate,
            ", ".join(missing_gate) or f"{name} not found",
        )

    retained_retired_files = [path for path in RETIRED_GENERATION_FILES if (ROOT / path).exists()]
    add(
        checks,
        "superseded generation files are absent",
        not retained_retired_files,
        ", ".join(retained_retired_files),
    )

    unmarked_wrappers: list[str] = []
    for name in LEGACY_BRIDGE_WRAPPERS:
        marker = f"def {name}"
        index = bridge.find(marker)
        if index < 0:
            continue
        if "LEGACY ONLY" not in bridge[max(0, index - 240):index]:
            unmarked_wrappers.append(name)
    add(
        checks,
        "retired generation wrapper functions are absent from the bridge",
        not unmarked_wrappers,
        ", ".join(unmarked_wrappers),
    )

    bloat_hits = [term for term in BLOAT_HINTS if term in post_build_body]
    if bloat_hits:
        warnings.append(
            {
                "name": "domain-specific bridge bloat",
                "detail": ", ".join(bloat_hits),
            }
        )

    ok = all(bool(check["ok"]) for check in checks) and (not strict or not warnings)
    return {"ok": ok, "strict": strict, "checks": checks, "warnings": warnings}


def print_human(result: dict[str, object]) -> None:
    print("PASS" if result["ok"] else "FAIL")
    for check in result["checks"]:  # type: ignore[index]
        status = "PASS" if check["ok"] else "FAIL"
        suffix = f" - {check['detail']}" if check.get("detail") else ""
        print(f"{status}: {check['name']}{suffix}")
    for warning in result["warnings"]:  # type: ignore[index]
        print(f"WARN: {warning['name']} - {warning['detail']}")
    if result.get("strict") and result.get("warnings"):
        print("Strict mode treats warnings as failures.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check CGNK slimming and route-hardening invariants.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Fail when advisory slimming warnings are present.")
    args = parser.parse_args(argv)

    result = run_checks(strict=args.strict)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
