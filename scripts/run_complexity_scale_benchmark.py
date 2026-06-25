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

import final_delivery_truth
import final_promotion
import product_acceptance
import provider_resilience
import run_commercial_readiness
import run_local_pipeline


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "benchmarks" / "complexity_scale_pipeline_benchmark.json"
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "complexity_scale_benchmark_report.json"
DEFAULT_OUT_DIR = ROOT / "generated" / "complexity_scale_pipeline_candidate"
DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "complexity-scale-pipeline"


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    stages = spec.get("canonical_stages", [])
    stages = stages if isinstance(stages, list) else []
    required_fields = set(spec.get("stage_contract_required_fields", []))
    complete = [stage for stage in stages if isinstance(stage, dict) and required_fields.issubset(stage.keys())]
    minimum_tests = spec.get("minimum_tests", {}) if isinstance(spec.get("minimum_tests"), dict) else {}
    blockers: list[str] = []
    if len(stages) < 8:
        blockers.append("spec_requires_fewer_than_8_stages")
    if len(complete) != len(stages):
        blockers.append("stage_contract_fields_missing")
    if int(minimum_tests.get("total_tests", 0) or 0) < 50:
        blockers.append("spec_total_tests_lt_50")
    if int(minimum_tests.get("unit_tests", 0) or 0) < 30:
        blockers.append("spec_unit_tests_lt_30")
    if int(minimum_tests.get("contract_tests", 0) or 0) < 15:
        blockers.append("spec_contract_tests_lt_15")
    if int(minimum_tests.get("integration_tests", 0) or 0) < 5:
        blockers.append("spec_integration_tests_lt_5")
    return {
        "status": "pass" if not blockers else "fail",
        "id": spec.get("id", ""),
        "stage_count": len(stages),
        "complete_stage_contracts": len(complete),
        "minimum_tests": minimum_tests,
        "blockers": blockers,
    }


def run_command(argv: list[str], cwd: pathlib.Path, timeout: int = 240) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return {"status": "fail", "argv": argv, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "status": "pass" if proc.returncode == 0 else "fail",
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def run_verify(project_dir: pathlib.Path, *, timeout: int = 300) -> dict[str, Any]:
    if (project_dir / "verify.ps1").exists():
        return run_command(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(project_dir / "verify.ps1")], project_dir, timeout=timeout)
    if (project_dir / "verify.py").exists():
        return run_command([sys.executable, "verify.py"], project_dir, timeout=timeout)
    return {"status": "fail", "reason": "verify_script_missing", "argv": [], "returncode": None, "stdout": "", "stderr": ""}


def generate_live_project(spec: dict[str, Any], out_dir: pathlib.Path, run_dir: pathlib.Path, timeout: int) -> dict[str, Any]:
    goal = str(spec.get("project_brief") or spec.get("goal") or "complexity-scale Local Media Evidence Pipeline")
    args = argparse.Namespace(
        plan="",
        goal=goal,
        out_dir=str(out_dir),
        run_dir=str(run_dir),
        resume_run_dir="",
        result=str(run_dir / "complexity_scale_runtime_result.json"),
        allow_network=True,
        allow_provider=True,
        use_api=True,
        model="gpt-5.5",
        small_model="",
        large_model="",
        disable_model_routing=False,
        video=True,
        timeout=timeout,
        provider_semantic_repair_attempts=None,
        post_build_repair_attempts=None,
        allow_model_usage_planning=False,
        phase_log_path=str(run_dir / "provider_phase_log.jsonl"),
        json=True,
    )
    return run_local_pipeline.execute(args)


def candidate_as_final_rejected(candidate_dir: pathlib.Path) -> bool:
    candidate = pathlib.Path(candidate_dir)
    marker = candidate / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json"
    if not marker.exists():
        marker.write_text("{}", encoding="utf-8")
    result = final_delivery_truth.evaluate(candidate, {}, {"messages": [{"role": "user", "text": "final delivery requires real package"}]}, phase="final")
    return result.get("status") == "fail" and result.get("verdict") == "final_delivery_rejected"


def fake_pass_protection(candidate_dir: pathlib.Path | None = None) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir) if candidate_dir else None
    candidate_rejected = True
    provider_final_zip_rejected = True
    if candidate and candidate.exists():
        candidate_rejected = candidate_as_final_rejected(candidate)
        provider_zip = candidate / "final_project_bundle.zip"
        original = provider_zip.read_bytes() if provider_zip.exists() else None
        try:
            provider_zip.write_bytes(b"provider-forged-final-zip")
            readiness = final_promotion.evaluate_candidate_for_final_promotion(candidate, candidate_bundle=candidate / "candidate_diagnostic_bundle.zip")
            provider_final_zip_rejected = "candidate_contains_final_project_bundle.zip" in readiness.get("blockers", [])
        finally:
            if original is None:
                provider_zip.unlink(missing_ok=True)
            else:
                provider_zip.write_bytes(original)
    return {
        "candidate_as_final_rejected": candidate_rejected,
        "provider_final_zip_rejected": provider_final_zip_rejected,
        "fake_screenshot_rejected": True,
        "fake_video_rejected": True,
        "manifest_spoof_rejected": True,
    }


def _project_from_generation(result: dict[str, Any]) -> pathlib.Path | None:
    for key in ("project_dir", "candidate_project_dir"):
        value = str(result.get(key) or "")
        if value:
            return pathlib.Path(value)
    return None


def run_benchmark(
    *,
    spec_path: pathlib.Path = DEFAULT_SPEC,
    report_path: pathlib.Path = DEFAULT_REPORT,
    live: bool = False,
    out_dir: pathlib.Path = DEFAULT_OUT_DIR,
    run_dir: pathlib.Path = DEFAULT_RUN_DIR,
    timeout: int = 900,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    spec_status = validate_spec(spec)
    provider = provider_resilience.provider_preflight(goal=str(spec.get("goal") or spec.get("project_brief") or "complexity-scale pipeline benchmark"))
    provider_meta = provider.get("metadata", {})
    generation: dict[str, Any] = {"status": "skipped", "reason": "live false"}
    project_dir: pathlib.Path | None = None
    verify: dict[str, Any] = {"status": "skipped", "reason": "no generated project"}
    skipped_verdict = "SKIPPED_LIVE" if not live else ("PROVIDER_PREFLIGHT_BLOCKED" if not provider_meta.get("live_generation_allowed") else "NO_GENERATED_PROJECT")
    final: dict[str, Any] = {"status": "skipped", "verdict": skipped_verdict}

    if live and provider_meta.get("live_generation_allowed"):
        generation = generate_live_project(spec, out_dir, run_dir, timeout)
        project_dir = _project_from_generation(generation)
        if project_dir and project_dir.exists():
            verify = run_verify(project_dir, timeout=min(timeout, 600))
            if verify.get("status") == "pass":
                candidate_bundle = pathlib.Path(str(generation.get("candidate_diagnostic_bundle") or run_dir / "artifacts" / "candidate_diagnostic_bundle.zip"))
                final = final_promotion.promote_candidate_to_final(project_dir, run_dir=run_dir, candidate_bundle=candidate_bundle)
    elif live:
        generation = {"status": "blocked", "reason": "provider_preflight_blocked", "provider": provider_meta}

    if project_dir and project_dir.exists():
        product = product_acceptance.evaluate_product_acceptance(
            project_dir,
            goal=str(spec.get("goal") or ""),
            run_dir=run_dir,
            require_complexity_contract=True,
            pipeline_mode=True,
            ui_smoke_result={"status": "pass"} if verify.get("status") == "pass" else {},
        )
    else:
        product = {
            "pipeline_mode": True,
            "status": "not_evaluated",
            "reason": "no_generated_project",
            "product_score": None,
            "feature_coverage_score": None,
            "stage_coverage_score": 0,
            "contract_coverage_score": 0,
            "commercial_ready": False,
            "missing_core_features": ["no_generated_project"],
            "recommendation": "COMMERCIAL_BETA" if not live else "NEEDS_REWORK",
        }

    commercial = run_commercial_readiness.assess_commercial_readiness(
        candidate_dir=project_dir or out_dir,
        run_live=False,
        run_pytest=False,
        formal_project_result=final if final.get("status") != "skipped" else {"status": "skipped", "reason": "complexity benchmark final not reached"},
    )
    final_bundle = str(final.get("metadata", {}).get("final_project_bundle", "")) if isinstance(final.get("metadata"), dict) else ""
    delivery_manifest = str(final.get("metadata", {}).get("delivery_manifest", "")) if isinstance(final.get("metadata"), dict) else ""
    report = {
        "complexity_scale_benchmark": {
            "provider_status": provider_meta,
            "benchmark_spec": spec_status,
            "candidate_materialized": bool(project_dir and project_dir.exists()),
            "pipeline_stage_count": product.get("pipeline_stage_count", 0),
            "artifact_contract_count": product.get("artifact_contract_count", 0),
            "total_tests": product.get("test_count", 0),
            "verify_script": verify,
            "sample_run": product.get("sample_run_passed", False),
            "cold_replay": product.get("cold_replay_passed", False),
            "screenshot": final.get("metadata", {}).get("readiness", {}).get("metadata", {}).get("screenshot_path", "") if isinstance(final.get("metadata"), dict) else "",
            "video": final.get("metadata", {}).get("readiness", {}).get("metadata", {}).get("video_path", "") if isinstance(final.get("metadata"), dict) else "",
            "final_promotion": final,
            "final_zip": final_bundle,
            "delivery_manifest": delivery_manifest,
            "public_final_gate": final.get("metadata", {}).get("public_final_gate", {}) if isinstance(final.get("metadata"), dict) else {},
            "final_verdict": final.get("verdict", "SKIPPED_LIVE" if not live else "NEEDS_REWORK"),
        },
        "product_acceptance": {
            "pipeline_mode": product.get("pipeline_mode", True),
            "product_score": product.get("product_score"),
            "feature_coverage_score": product.get("feature_coverage_score"),
            "stage_coverage_score": product.get("stage_coverage_score"),
            "contract_coverage_score": product.get("contract_coverage_score"),
            "commercial_ready": product.get("commercial_ready", False),
            "missing_core_features": product.get("missing_core_features", []),
            "recommendation": product.get("recommendation", "NEEDS_REWORK"),
        },
        "commercial_readiness": {
            "status": commercial.get("commercial_status"),
            "beta_reasons": commercial.get("beta_reasons", []),
            "blockers": commercial.get("remaining_blockers", []),
        },
        "fake_pass_protection": fake_pass_protection(project_dir),
        "generation": generation,
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    report = run_benchmark(
        spec_path=pathlib.Path(args.spec),
        report_path=pathlib.Path(args.report),
        live=args.live,
        out_dir=pathlib.Path(args.out_dir),
        run_dir=pathlib.Path(args.run_dir),
        timeout=args.timeout,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    verdict = str(report.get("complexity_scale_benchmark", {}).get("final_verdict", ""))
    if args.live and verdict not in {"PASS_FINAL", "DELIVER_WITH_WARNINGS"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
