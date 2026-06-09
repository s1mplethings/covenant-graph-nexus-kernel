#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib

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
    "run_generation_subprocess",
    "run_generation_job",
    "run_agent_generation_job",
    "simulator",
]
PROVIDER_ROUTE_TERMS = [
    "provider_project_pipeline.execute",
    "provider-output-validated",
    "provider-project-files-written",
    "local_packager.package_project",
    "evaluate_public_delivery_gate",
    "finish_agent_loop_delivery",
]
BLOAT_HINTS = ["VNProjectCLI", "Flask create_app compatibility", "csgo", "鉴挂", "反作弊"]


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


def add(checks: list[dict[str, object]], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": "" if ok else detail})


def run_checks(strict: bool = False) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    warnings: list[dict[str, str]] = []

    agents = read_text("AGENTS.md")
    kernel = read_text("docs/00_kernel_contract.md")
    bridge = read_text("scripts/telegram_live_bridge.py")

    for path, text in (("AGENTS.md", agents), ("docs/00_kernel_contract.md", kernel)):
        missing = [term for term in ROUTE_TERMS if term not in text]
        add(checks, f"{path} names reviewed Telegram route", not missing, ", ".join(missing))

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

    missing_provider_terms = [term for term in PROVIDER_ROUTE_TERMS if term not in bridge]
    add(
        checks,
        "provider route is behind validation packager and gate",
        not missing_provider_terms,
        ", ".join(missing_provider_terms),
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
