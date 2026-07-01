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
import formal_delivery_evidence
import formal_model_contract
import product_acceptance
import provider_resilience
import check_connectivity
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


def _non_manifest_fake_blockers(blockers: list[str]) -> list[str]:
    ignored = {"delivery_manifest.json contains PASS_FINAL"}
    return [str(item) for item in blockers if str(item) not in ignored]


def _formal_user_goal(formal_project_result: dict[str, Any] | None) -> str:
    if not isinstance(formal_project_result, dict):
        return ""
    nested = formal_project_result.get("formal_result", {})
    if isinstance(nested, dict):
        for key in ("goal", "generation_context_goal", "raw_goal"):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    for key in ("goal", "generation_context_goal", "raw_goal"):
        value = str(formal_project_result.get(key) or "").strip()
        if value:
            return value
    return ""


def _formal_screenshot_metadata(formal_project_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(formal_project_result, dict):
        return {}
    path = str(formal_project_result.get("screenshot_path") or "").strip()
    if not path:
        evidence = formal_project_result.get("formal_delivery_evidence", {})
        if isinstance(evidence, dict):
            path = str(evidence.get("screenshot_path") or "").strip()
    return {"path": path, "valid": bool(path and pathlib.Path(path).exists())}


def _formal_ui_smoke(formal_project_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(formal_project_result, dict):
        return {}
    repair = formal_project_result.get("candidate_repair_closure", {})
    if isinstance(repair, dict):
        post_build = repair.get("post_build", {})
        if isinstance(post_build, dict):
            ui_smoke = post_build.get("ui_smoke", {})
            if isinstance(ui_smoke, dict):
                return ui_smoke
    return {}


def _formal_provider_status(formal_project_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(formal_project_result, dict):
        return {}
    explicit = formal_project_result.get("provider_status")
    if isinstance(explicit, dict):
        return explicit
    strings = json.dumps(formal_project_result, ensure_ascii=False, default=str)
    error_type = check_connectivity._provider_error_type(strings)
    return {
        "provider_error_type": error_type,
        "provider_quota_exceeded": error_type == provider_resilience.PROVIDER_QUOTA_EXCEEDED,
    }


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
    product = product_acceptance.evaluate_product_acceptance(
        candidate,
        goal=_formal_user_goal(formal_project_result),
        screenshot_metadata=_formal_screenshot_metadata(formal_project_result),
        ui_smoke_result=_formal_ui_smoke(formal_project_result),
    )
    warning_policy = commercial_warning_policy.classify_final_warnings(product.get("weak_features", []) + product.get("missing_core_features", []))
    status_sample = (
        customer_status.render_from_internal({"reason": "provider_quota", "can_continue": True, "can_retry": True})
        if provider_meta.get("commercial_blocker") == "provider_quota"
        else customer_status.render_status("READY_FOR_REVIEW")
    )

    formal_project = dict(formal_project_result) if isinstance(formal_project_result, dict) else {"status": "skipped", "reason": "run_live false"}
    formal_provider_status = _formal_provider_status(formal_project_result)
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
    if run_pytest and tests.get("status") != "pass":
        blockers.append("focused_pytest_failed")
    if provider_meta.get("commercial_blocker") == "provider_quota":
        beta_reasons.append("provider_quota")
    elif provider.get("status") == "fail":
        beta_reasons.append("provider_unavailable")
    if formal_project.get("status") != "pass":
        beta_reasons.append(
            "formal_project_status_not_pass:"
            + str(formal_project.get("status") or "missing")
            + ":"
            + str(formal_project.get("reason") or formal_project.get("verdict") or "unknown")
        )
    if formal_provider_status.get("provider_quota_exceeded"):
        beta_reasons.append("provider_quota_exceeded")
    if isinstance(formal_project_result, dict) and not (
        formal_project_result.get("project_dir")
        or formal_project_result.get("final_project_dir")
        or formal_project_result.get("candidate_project_dir")
    ):
        beta_reasons.append("no_formal_generation_materialized")
    formal_model_gate = {}
    formal_delivery_audit = {}
    if isinstance(formal_project_result, dict):
        run_dir = formal_project_result.get("run_dir") or formal_project_result.get("project_dir") or ""
        usage_plan = (
            formal_project_result.get("agent_usage", {}).get("plan", {})
            if isinstance(formal_project_result.get("agent_usage", {}), dict)
            else {}
        )
        formal_model_gate = formal_model_contract.evaluate_model_participation(
            context="commercial_readiness",
            run_dir=run_dir if run_dir else None,
            usage_plan=usage_plan,
        )
        if formal_model_gate.get("status") != "pass":
            beta_reasons.append(str(formal_model_gate.get("reason", "FORMAL_MODEL_EVIDENCE_MISSING")))
        formal_delivery_audit = formal_delivery_evidence.audit_formal_delivery_evidence(formal_project_result)
        if formal_delivery_audit.get("status") != "pass":
            beta_reasons.extend(f"formal_delivery:{item}" for item in formal_delivery_audit.get("blockers", []))
    anti_fake_blockers = [str(item) for item in anti_fake.get("blockers", [])] if isinstance(anti_fake.get("blockers", []), list) else []
    if anti_fake.get("status") == "fail":
        residual_fake_blockers = _non_manifest_fake_blockers(anti_fake_blockers) if formal_delivery_audit.get("status") == "pass" else anti_fake_blockers
        if residual_fake_blockers:
            blockers.append("fake_artifact_risk")
            blockers.append("fake_artifact_risk_detail:" + ";".join(residual_fake_blockers[:5]))
    if product.get("status") == "not_evaluated" and product.get("reason") == "NO_PRODUCT_EVIDENCE":
        beta_reasons.append("no_product_evidence")
    elif product.get("commercial_ready") is not True:
        details: list[str] = []
        missing = product.get("missing_core_features", []) if isinstance(product.get("missing_core_features", []), list) else []
        weak = product.get("weak_features", []) if isinstance(product.get("weak_features", []), list) else []
        if missing:
            details.append("missing_core_features=" + ",".join(str(item) for item in missing[:8]))
        if weak:
            details.append("weak_features=" + ",".join(str(item) for item in weak[:8]))
        if not details:
            layered = product.get("layered_acceptance", {}) if isinstance(product.get("layered_acceptance", {}), dict) else {}
            known_gaps = layered.get("known_gaps", []) if isinstance(layered.get("known_gaps", []), list) else []
            if known_gaps:
                details.append("known_gaps=" + ",".join(str(item) for item in known_gaps[:8]))
        beta_reasons.append("product_acceptance_not_commercial_ready:" + (";".join(details) if details else str(product.get("recommendation") or product.get("overall_status") or "unspecified")))
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
        "formal_provider_status": formal_provider_status,
        "formal_model_gate": formal_model_gate,
        "formal_delivery_evidence": formal_delivery_audit,
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
    parser.add_argument("--formal-result", default="")
    args = parser.parse_args()
    provider_config = provider_resilience.load_config(pathlib.Path(args.provider_config)) if args.provider_config else None
    formal_project_result = formal_delivery_evidence.read_json(args.formal_result) if args.formal_result else None
    report = assess_commercial_readiness(
        provider_config=provider_config,
        candidate_dir=pathlib.Path(args.candidate_dir) if args.candidate_dir else None,
        run_live=args.run_live,
        run_pytest=args.run_pytest,
        formal_project_result=formal_project_result,
    )
    write_json(pathlib.Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["commercial_status"] == "COMMERCIAL_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
