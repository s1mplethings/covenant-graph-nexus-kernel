#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def stable_hash(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(str(text).encode("utf-8", errors="replace")).hexdigest()


def page_count(page_map: dict[str, Any]) -> int:
    pages = page_map.get("pages")
    if isinstance(pages, list):
        return len([item for item in pages if item])
    return 0


def module_count(feature_matrix: dict[str, Any]) -> int:
    modules = feature_matrix.get("modules")
    if isinstance(modules, list):
        return len([item for item in modules if item])
    return 0


def evidence_text(project: pathlib.Path) -> str:
    parts = [
        read_text(project / "README.md"),
        read_text(project / "index.html"),
        read_text(project / "app.js"),
        json.dumps(read_json(project / "page_map.json"), ensure_ascii=False),
        json.dumps(read_json(project / "feature_matrix.json"), ensure_ascii=False),
        json.dumps(read_json(project / "acceptance_matrix.json"), ensure_ascii=False),
    ]
    return "\n".join(parts).lower().replace("_", " ")


def privacy_safety(project: pathlib.Path, case_id: str) -> dict[str, Any]:
    if case_id != "clinic_workflow_studio":
        return {"status": "not_applicable", "issues": []}
    demo_root = project / "demo_data"
    text = "\n".join(read_text(path) for path in demo_root.glob("*.json")) if demo_root.exists() else ""
    issues: list[str] = []
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        issues.append("ssn_like_value")
    if re.search(r"\b(?:\+?\d[\d -]{8,}\d)\b", text):
        issues.append("phone_like_value")
    if re.search(r"[\w.-]+@[\w.-]+\.\w+", text):
        issues.append("email_like_value")
    if "synthetic" not in text.lower() and "fake" not in text.lower() and "demo" not in text.lower():
        issues.append("missing_fake_data_marker")
    return {"status": "pass" if not issues else "fail", "issues": issues}


def audit_case(case: dict[str, Any]) -> dict[str, Any]:
    project = pathlib.Path(str(case.get("final_project") or ""))
    required = [str(item) for item in case.get("required_modules", [])]
    page_map = read_json(project / "page_map.json")
    feature_matrix = read_json(project / "feature_matrix.json")
    text = evidence_text(project)
    detected = [module for module in required if module.lower().replace("_", " ") in text]
    missing = [module for module in required if module not in detected]
    manifest = pathlib.Path(str(case.get("delivery_manifest") or project / "delivery_manifest.json"))
    bundle = pathlib.Path(str(case.get("final_bundle") or project / "final_project_bundle.zip"))
    screenshot = pathlib.Path(str(case.get("screenshot_evidence") or ""))
    ledger = pathlib.Path(str(case.get("agent_decision_ledger") or ""))
    checks = {
        "run_dir_exists": pathlib.Path(str(case.get("run_dir") or "")).is_dir(),
        "final_project_exists": project.is_dir(),
        "delivery_manifest_exists": manifest.is_file(),
        "final_bundle_exists": bundle.is_file() and bundle.stat().st_size > 0 if bundle.exists() else False,
        "screenshot_evidence_exists": screenshot.is_file(),
        "agent_decision_ledger_exists": ledger.is_file(),
        "complexity_pass": str(case.get("complexity_status") or "").lower() == "pass",
        "page_count_ok": int(case.get("page_count") or page_count(page_map)) >= 8,
        "module_count_ok": int(case.get("module_count") or module_count(feature_matrix)) >= 6,
        "product_acceptance_pass": str(case.get("product_acceptance") or "").lower() == "pass",
        "commercial_ready": case.get("commercial_status") == "COMMERCIAL_READY",
        "public_gate_ready": case.get("public_delivery_gate") == "READY",
        "remaining_blockers_empty": not case.get("remaining_blockers"),
        "required_modules_present": not missing,
    }
    privacy = privacy_safety(project, str(case.get("case_id") or ""))
    if privacy["status"] == "fail":
        checks["privacy_safety"] = False
    else:
        checks["privacy_safety"] = True
    failures = [name for name, passed in checks.items() if not passed]
    status = "pass" if not failures and case.get("status") == "pass" else "fail"
    return {
        **case,
        "status": status,
        "page_count": int(case.get("page_count") or page_count(page_map)),
        "module_count": int(case.get("module_count") or module_count(feature_matrix)),
        "detected_modules": detected,
        "missing_modules": missing,
        "privacy_safety": privacy,
        "checks": checks,
        "failures": failures,
    }


def domain_diversity(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    case_names = [str(case.get("case_id") or "") for case in case_results]
    module_sets = {tuple(sorted(case.get("required_modules", []))) for case in case_results}
    fingerprints: set[str] = set()
    for case in case_results:
        project = pathlib.Path(str(case.get("final_project") or ""))
        fp = stable_hash(
            {
                "readme": read_text(project / "README.md"),
                "feature_matrix": read_json(project / "feature_matrix.json"),
                "page_map": read_json(project / "page_map.json"),
            }
        )
        fingerprints.add(fp)
    issues: list[str] = []
    if len(set(case_names)) != len(case_names):
        issues.append("duplicate_case_names")
    if len(module_sets) != len(case_results):
        issues.append("duplicate_required_modules")
    if len(fingerprints) != len(case_results):
        issues.append("insufficient_domain_diversity")
    return {"status": "pass" if not issues else "fail", "issues": issues}


def audit_report(report: dict[str, Any]) -> dict[str, Any]:
    cases = report.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    case_results = [audit_case(case) for case in cases if isinstance(case, dict)]
    shared_failures: list[str] = []
    if len(case_results) < 3:
        shared_failures.append("insufficient_case_count")
    diversity = domain_diversity(case_results) if case_results else {"status": "fail", "issues": ["insufficient_domain_diversity"]}
    shared_failures.extend(diversity.get("issues", []))
    passed = sum(1 for case in case_results if case.get("status") == "pass")
    failed = sum(1 for case in case_results if case.get("status") == "fail")
    blocked = sum(1 for case in case_results if case.get("status") == "blocked")
    if failed:
        shared_failures.extend(sorted({failure for case in case_results for failure in case.get("failures", [])}))
    status = "pass" if len(case_results) >= 3 and passed == len(case_results) and diversity["status"] == "pass" else ("partial" if passed else "fail")
    return {
        "status": status,
        "case_count": len(case_results),
        "passed_cases": passed,
        "failed_cases": failed,
        "blocked_cases": blocked,
        "domain_diversity": diversity["status"],
        "case_results": case_results,
        "shared_failures": list(dict.fromkeys(shared_failures)),
        "unstable_components": [],
        "recommended_next_fixes": [] if status == "pass" else ["repair_generalization_case_failures"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    source = read_json(pathlib.Path(args.report))
    audit = audit_report(source)
    if args.out:
        path = pathlib.Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
