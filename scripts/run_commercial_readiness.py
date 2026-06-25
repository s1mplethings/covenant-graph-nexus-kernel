#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import artifact_integrity
import check_test_environment
import commercial_warning_policy
import customer_status
import product_acceptance
import provider_resilience
import sandbox_security


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "commercial_readiness_report.json"


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(argv: list[str], timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return {"status": "fail", "argv": argv, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "status": "pass" if proc.returncode == 0 else "fail",
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def _status_pass(doc: dict[str, Any]) -> bool:
    return str(doc.get("status", "")).lower() in {"pass", "warn", "warning"}


def assess_commercial_readiness(
    *,
    provider_config: dict[str, Any] | None = None,
    candidate_dir: pathlib.Path | None = None,
    run_live: bool = False,
    run_pytest: bool = False,
    formal_project_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir or (ROOT / "generated" / "cgnk_generated_project_candidate"))
    environment = check_test_environment.check_environment(candidate)
    provider = provider_resilience.provider_preflight(provider_config, goal="commercial readiness formal project")
    provider_meta = provider.get("metadata", {})
    security = sandbox_security.scan_project(candidate if candidate.exists() else ROOT / "scripts", write_block_file=False)
    tests = run_command([sys.executable, "-m", "pytest", "-k", "provider_resilience or sandbox_security or commercial_warning or product_acceptance or customer_status or telegram_delivery or commercial_readiness or final_delivery_truth or artifact_integrity or candidate or screenshot or video or package or fake or kernel_contract", "-q"], timeout=240) if run_pytest else {"status": "skipped", "reason": "run_pytest false"}
    anti_fake_root = candidate if candidate.exists() else (ROOT / "generated")
    anti_fake = artifact_integrity.scan_no_fake_pass(anti_fake_root)
    product = product_acceptance.evaluate_product_acceptance(candidate, goal="commercial readiness project")
    warning_policy = commercial_warning_policy.classify_final_warnings(product.get("weak_features", []) + product.get("missing_core_features", []))
    status_sample = (
        customer_status.render_from_internal({"reason": "provider_quota", "can_continue": True, "can_retry": True})
        if provider_meta.get("commercial_blocker") == "provider_quota"
        else customer_status.render_status("READY_FOR_REVIEW")
    )

    formal_project = dict(formal_project_result) if isinstance(formal_project_result, dict) else {"status": "skipped", "reason": "run_live false"}
    if formal_project_result is not None:
        pass
    elif run_live and provider_meta.get("live_generation_allowed"):
        formal_project = {"status": "skipped", "reason": "live runner not invoked by readiness smoke"}
    elif not provider_meta.get("live_generation_allowed"):
        formal_project = {"status": "skipped", "reason": "provider_quota_or_unavailable"}

    blockers: list[str] = []
    beta_reasons: list[str] = []
    if security.get("status") == "fail":
        blockers.append("security_fail")
    if anti_fake.get("status") == "fail":
        blockers.append("fake_artifact_risk")
    if run_pytest and tests.get("status") != "pass":
        blockers.append("focused_pytest_failed")
    if provider_meta.get("commercial_blocker") == "provider_quota":
        beta_reasons.append("provider_quota")
    elif provider.get("status") == "fail":
        beta_reasons.append("provider_unavailable")
    if formal_project.get("status") != "pass":
        beta_reasons.append("formal_project_live_incomplete")
    if product.get("status") == "not_evaluated" and product.get("reason") == "NO_PRODUCT_EVIDENCE":
        beta_reasons.append("no_product_evidence")
    elif product.get("commercial_ready") is not True:
        beta_reasons.append("product_acceptance_not_commercial_ready")
    if warning_policy.get("metadata", {}).get("classification", {}).get("critical"):
        blockers.append("critical_final_warning")

    if blockers:
        commercial_status = "COMMERCIAL_BLOCKED"
    elif not beta_reasons:
        commercial_status = "COMMERCIAL_READY"
    else:
        commercial_status = "COMMERCIAL_BETA"
    if provider_meta.get("commercial_blocker") == "provider_quota":
        provider_meta["report_status"] = "COMMERCIAL_BETA_PROVIDER_BLOCKED"

    report = {
        "commercial_status": commercial_status,
        "environment": environment,
        "provider": provider_meta,
        "security": security,
        "tests": tests,
        "anti_fake": anti_fake,
        "formal_project": formal_project,
        "product_acceptance": product,
        "final_warning_policy": warning_policy,
        "telegram_delivery": {"status_renderer": status_sample, "split_modules": ["candidate_review_sender", "final_delivery_sender", "retry_recovery"]},
        "customer_status": status_sample,
        "remaining_blockers": blockers,
        "beta_reasons": beta_reasons,
        "recommended_release_label": "commercial-ready" if commercial_status == "COMMERCIAL_READY" else ("commercial-beta" if commercial_status == "COMMERCIAL_BETA" else "commercial-blocked"),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--provider-config", default="")
    parser.add_argument("--candidate-dir", default="")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--run-pytest", action="store_true")
    args = parser.parse_args()
    provider_config = provider_resilience.load_config(pathlib.Path(args.provider_config)) if args.provider_config else None
    report = assess_commercial_readiness(
        provider_config=provider_config,
        candidate_dir=pathlib.Path(args.candidate_dir) if args.candidate_dir else None,
        run_live=args.run_live,
        run_pytest=args.run_pytest,
    )
    write_json(pathlib.Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["commercial_status"] == "COMMERCIAL_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
