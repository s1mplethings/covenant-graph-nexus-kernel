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
LEGACY_WRAPPER_FILES = [
    ("scripts/generate_project.py", ["LEGACY CLI ONLY", "Not used by Telegram formal generation"]),
    ("scripts/legacy_provider_pipeline.py", ["LEGACY ONLY", "Not part of CGNK formal Telegram generation"]),
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
SPLIT_MODULE_FILES = [
    "scripts/provider_project_compatibility.py",
    "scripts/project_signal_terms.py",
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
    bridge = read_text("scripts/telegram_live_bridge.py")
    model_policy = read_text("scripts/model_policy.py") if (ROOT / "scripts/model_policy.py").exists() else ""
    revision_lane = read_text("scripts/project_revision_lane.py") if (ROOT / "scripts/project_revision_lane.py").exists() else ""
    local_studio = read_text("scripts/local_studio_cli.py") if (ROOT / "scripts/local_studio_cli.py").exists() else ""
    revision_doc = read_text("docs/09_project_revision_lane.md") if (ROOT / "docs/09_project_revision_lane.md").exists() else ""
    connectivity = read_text("scripts/check_connectivity.py")

    for path, text in (("AGENTS.md", agents), ("docs/00_kernel_contract.md", kernel)):
        missing = [term for term in ROUTE_TERMS if term not in text]
        add(checks, f"{path} names reviewed Telegram route", not missing, ", ".join(missing))

    missing_team_files = [path for path in PROJECT_TEAM_FILES if not (ROOT / path).exists()]
    add(checks, "project team manager modules exist", not missing_team_files, ", ".join(missing_team_files))
    missing_split_modules = [path for path in SPLIT_MODULE_FILES if not (ROOT / path).exists()]
    add(checks, "bridge bloat functions are split into modules", not missing_split_modules, ", ".join(missing_split_modules))

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
        "start_agent_generation" in confirmation_branch and not bad_confirmation,
        ", ".join(bad_confirmation) or "start_agent_generation missing",
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

    provider_route_body = function_body(bridge, "run_provider_generation_job") + "\n" + function_body(bridge, "run_provider_execute_with_retries")
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
        "telegram default session carries active project state",
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
        "telegram revision branch delegates out of bridge",
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
        "telegram bridge does not call provider revision job",
        "run_provider_revision_job(" not in bridge,
        "telegram_live_bridge.py must not directly call run_provider_revision_job",
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

    for path, markers in LEGACY_WRAPPER_FILES:
        if not (ROOT / path).exists():
            continue
        text = read_text(path)
        missing_markers = [marker for marker in markers if marker not in text]
        add(
            checks,
            f"{path} is marked legacy-only",
            not missing_markers,
            ", ".join(missing_markers),
        )

    exposed_wrappers: list[str] = []
    for name in LEGACY_BRIDGE_WRAPPERS:
        marker = f"def {name}"
        if bridge.find(marker) >= 0:
            exposed_wrappers.append(name)
    add(
        checks,
        "legacy wrapper functions are not exposed by the bridge",
        not exposed_wrappers,
        ", ".join(exposed_wrappers),
    )

    line_count = bridge.count("\n") + 1
    if line_count > 5200:
        warnings.append(
            {
                "name": "telegram_live_bridge.py is too large",
                "detail": f"{line_count} lines; extract modules before adding more logic",
            }
        )
    bloat_hits = [term for term in BLOAT_HINTS if term in bridge]
    add(checks, "domain-specific compatibility terms stay out of the bridge", not bloat_hits, ", ".join(bloat_hits))

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
