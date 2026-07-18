#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
from datetime import datetime, timezone
from typing import Any

try:
    import check_connectivity
    import formal_model_contract
    import local_model_router
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import check_connectivity  # type: ignore[no-redef]
    from scripts import formal_model_contract  # type: ignore[no-redef]
    from scripts import local_model_router  # type: ignore[no-redef]


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _candidate_dirs(run_dir: pathlib.Path) -> list[pathlib.Path]:
    return [
        run_dir / "candidate_project",
        run_dir / "candidate",
        run_dir / "generated_project_candidate",
        run_dir / "artifacts" / "candidate_project",
        run_dir / "cgnk_generated_project_candidate",
        run_dir / "cgkn_generated_project_candidate",
    ]


def _final_dirs(run_dir: pathlib.Path) -> list[pathlib.Path]:
    return [
        run_dir / "final_project",
        run_dir / "artifacts" / "final_project",
        run_dir / "cgnk_generated_project_final",
        run_dir / "cgkn_generated_project_final",
    ]


def _first_existing_dir(paths: list[pathlib.Path]) -> pathlib.Path | None:
    return next((path for path in paths if path.exists() and path.is_dir()), None)


def _first_existing_file(paths: list[pathlib.Path]) -> pathlib.Path | None:
    return next((path for path in paths if path.exists() and path.is_file()), None)


def _has_named_file(run_dir: pathlib.Path, name: str) -> bool:
    search_roots = [run_dir, run_dir / "artifacts"]
    candidate = _first_existing_dir(_candidate_dirs(run_dir))
    final = _first_existing_dir(_final_dirs(run_dir))
    search_roots.extend(path for path in (candidate, final) if path is not None)
    return any((root / name).exists() for root in search_roots)


def _semantic_review_status(run_dir: pathlib.Path) -> str:
    paths = [
        run_dir / "semantic_review_result.json",
        run_dir / "semantic_review_report.json",
        run_dir / "artifacts" / "semantic_review_result.json",
        run_dir / "artifacts" / "semantic_review_report.json",
    ]
    candidate = _first_existing_dir(_candidate_dirs(run_dir))
    if candidate:
        paths.extend([candidate / "semantic_review_result.json", candidate / "semantic_review_report.json"])
    path = _first_existing_file(paths)
    if not path:
        return "missing"
    doc = _read_json(path)
    status = str(doc.get("status") or doc.get("verdict") or "").strip().lower()
    blockers = doc.get("blockers", [])
    issues = doc.get("issues", [])
    if status in {"pass", "passed", "ok", "ready"}:
        return "pass"
    if status in {"needs_rework", "rework", "fail", "failed", "reject", "rejected"}:
        return "needs_rework"
    if blockers or issues:
        return "needs_rework"
    return "missing"


def _delivery_manifest_path(run_dir: pathlib.Path) -> pathlib.Path | None:
    final = _first_existing_dir(_final_dirs(run_dir))
    paths = [run_dir / "delivery_manifest.json", run_dir / "artifacts" / "delivery_manifest.json"]
    if final:
        paths.append(final / "delivery_manifest.json")
    return _first_existing_file(paths)


def _final_bundle_path(run_dir: pathlib.Path) -> pathlib.Path | None:
    final = _first_existing_dir(_final_dirs(run_dir))
    paths = [run_dir / "final_project_bundle.zip", run_dir / "artifacts" / "final_project_bundle.zip"]
    if final:
        paths.append(final / "final_project_bundle.zip")
    return _first_existing_file(paths)


def _screenshot_exists(run_dir: pathlib.Path, manifest: dict[str, Any]) -> bool:
    refs = []
    if manifest.get("screenshot_path"):
        refs.append(pathlib.Path(str(manifest["screenshot_path"])))
    screenshots = manifest.get("screenshots", [])
    if isinstance(screenshots, list):
        refs.extend(pathlib.Path(str(item)) for item in screenshots)
    if any(path.exists() and path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES for path in refs):
        return True
    roots = [run_dir / "artifacts", run_dir]
    final = _first_existing_dir(_final_dirs(run_dir))
    candidate = _first_existing_dir(_candidate_dirs(run_dir))
    roots.extend(path for path in (final, candidate) if path is not None)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and "screenshot" in path.as_posix().lower():
                return True
    return False


def _public_gate_status(run_dir: pathlib.Path, manifest: dict[str, Any]) -> str:
    gate = manifest.get("public_final_gate") if isinstance(manifest.get("public_final_gate"), dict) else {}
    if gate:
        if gate.get("delivery_allowed") is True or str(gate.get("status", "")).upper() == "READY":
            return "READY"
        return "NOT_READY"
    for path in (run_dir / "artifacts" / "public_delivery_gate.json", run_dir / "public_delivery_gate.json"):
        doc = _read_json(path)
        if not doc:
            continue
        status = str(doc.get("status") or doc.get("public_gate_status") or "").upper()
        if status in {"READY", "PASS", "PASSED"} or doc.get("delivery_allowed") is True:
            return "READY"
        return "NOT_READY"
    return "missing"


def _commercial_status(run_dir: pathlib.Path) -> str:
    for path in (
        run_dir / "artifacts" / "commercial_readiness_report.json",
        run_dir / "commercial_readiness_report.json",
        run_dir / "artifacts" / "commercial_readiness.json",
    ):
        doc = _read_json(path)
        if doc:
            return str(doc.get("commercial_status") or doc.get("status") or "missing")
    return "missing"


def _iter_json_docs(run_dir: pathlib.Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    roots = [run_dir, run_dir / "artifacts", run_dir.parent]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            doc = _read_json(path)
            if doc:
                docs.append(doc)
    return docs


def _collect_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        if value.strip():
            strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(_collect_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(_collect_strings(item))
    return strings


def _provider_status(run_dir: pathlib.Path) -> dict[str, Any]:
    docs = _iter_json_docs(run_dir)
    text = "\n".join(item for doc in docs for item in _collect_strings(doc))
    provider_error_type = check_connectivity._provider_error_type(text) if text.strip() else ""
    if provider_error_type == "PROVIDER_KEY_USAGE_LIMIT":
        provider_error_type = "PROVIDER_QUOTA_EXCEEDED"
    provider_error_code = ""
    if provider_error_type:
        import re

        match = re.search(r"HTTP\s+(\d+)", text, flags=re.IGNORECASE)
        provider_error_code = match.group(1) if match else ""
    quota = provider_error_type == "PROVIDER_QUOTA_EXCEEDED"
    provider_available = bool(docs) and not quota and provider_error_type not in {
        "PROVIDER_FORBIDDEN",
        "PROVIDER_NON_RETRYABLE_HTTP",
        "PROVIDER_API_REQUEST_FAILED",
    }
    if not docs:
        provider_available = True
    return {
        "provider_available": provider_available,
        "provider_error_code": provider_error_code,
        "provider_error_type": provider_error_type or "",
        "provider_quota_exceeded": quota,
    }


def _local_model_available() -> bool:
    if os.environ.get("CGNK_TEST_LOCAL_MODEL_AVAILABLE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if os.environ.get("CGNK_TEST_LOCAL_MODEL_AVAILABLE", "").strip().lower() in {"0", "false", "no", "off"}:
        return False
    if os.environ.get("CGNK_LOCAL_MODEL_CMD", "").strip():
        return True
    if not local_model_router.local_model_requested():
        return False
    host = str(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).strip()
    return local_model_router.ollama_available(host)


def _writable_project_files_exist(run_dir: pathlib.Path) -> bool:
    candidate = _first_existing_dir(_candidate_dirs(run_dir))
    final = _first_existing_dir(_final_dirs(run_dir))
    for root in (candidate, final):
        if not root:
            continue
        files = [path for path in root.rglob("*") if path.is_file()]
        if any(path.name in {"index.html", "app.py", "main.py", "package.json", "pyproject.toml"} for path in files):
            return True
        if files:
            return True
    return False


def _model_participation_status(run_dir: pathlib.Path) -> str:
    ledger = formal_model_contract.ledger_path(run_dir)
    if not ledger.exists():
        return "missing"
    result = formal_model_contract.evaluate_model_participation(context="formal_live_generation", run_dir=run_dir)
    return "pass" if result.get("status") == "pass" else "fail"


def _fallback_reverify_status(run_dir: pathlib.Path) -> str:
    path = run_dir / "artifacts" / "provider_fallback_evidence.json"
    if not path.exists():
        return "missing"
    doc = _read_json(path)
    if doc.get("requires_reverify") is False:
        return "pass"
    if doc.get("reverify_attempted") is True and str(doc.get("reverify_status", "")).lower() in {"pass", "passed", "ok"}:
        return "pass"
    return "fail"


def observe_run_state(run_dir: str | pathlib.Path) -> dict[str, Any]:
    run = pathlib.Path(run_dir)
    manifest_path = _delivery_manifest_path(run)
    manifest = _read_json(manifest_path) if manifest_path else {}
    public_gate_status = _public_gate_status(run, manifest)
    commercial_status = _commercial_status(run)
    blockers: list[str] = []
    if public_gate_status == "NOT_READY":
        blockers.append("public_delivery_gate_not_ready")
    if commercial_status in {"COMMERCIAL_BLOCKED", "fail", "failed"}:
        blockers.append("commercial_readiness_blocked")
    provider = _provider_status(run)
    writable_project_files = _writable_project_files_exist(run)
    return {
        "run_dir": str(run),
        "has_project_spec": _has_named_file(run, "project_spec.json"),
        "has_acceptance_matrix": _has_named_file(run, "acceptance_matrix.json"),
        "candidate_exists": _first_existing_dir(_candidate_dirs(run)) is not None,
        "writable_project_files_exist": writable_project_files,
        "semantic_review_status": _semantic_review_status(run),
        "final_project_exists": _first_existing_dir(_final_dirs(run)) is not None,
        "formal_generation_materialized": bool(_first_existing_dir(_candidate_dirs(run)) and writable_project_files),
        "delivery_manifest_exists": manifest_path is not None,
        "final_bundle_exists": _final_bundle_path(run) is not None,
        "screenshot_evidence_exists": _screenshot_exists(run, manifest),
        "public_gate_status": public_gate_status,
        "commercial_status": commercial_status,
        **provider,
        "local_model_available": _local_model_available(),
        "remaining_blockers": blockers,
        "model_participation_status": _model_participation_status(run),
        "fallback_reverify_status": _fallback_reverify_status(run),
    }


def _mtime(path: pathlib.Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _latest_file(root: pathlib.Path, patterns: list[str]) -> pathlib.Path | None:
    matches: list[pathlib.Path] = []
    for pattern in patterns:
        matches.extend(path for path in root.glob(pattern) if path.is_file())
    return max(matches, key=_mtime) if matches else None


def _latest_json(root: pathlib.Path, patterns: list[str]) -> tuple[pathlib.Path | None, dict[str, Any]]:
    path = _latest_file(root, patterns)
    return path, (_read_json(path) if path else {})


def _iso_mtime(path: pathlib.Path | None) -> str:
    if not path:
        return ""
    return datetime.fromtimestamp(_mtime(path), timezone.utc).isoformat()


def _git_status(root: pathlib.Path) -> dict[str, Any]:
    try:
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=str(root), capture_output=True, text=True, timeout=20)
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=20)
        status = subprocess.run(["git", "status", "--short"], cwd=str(root), capture_output=True, text=True, timeout=20)
    except Exception as exc:
        return {"branch": "", "head": "", "dirty": True, "status_short": [f"git_status_error:{exc}"]}
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "branch": branch.stdout.strip(),
        "head": head.stdout.strip(),
        "dirty": bool(lines),
        "status_short": lines,
    }


def _selected_tools(*reports: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for report in reports:
        tools = report.get("selected_tools", [])
        if isinstance(tools, list):
            for tool in tools:
                value = str(tool)
                if value and value not in seen:
                    seen.append(value)
    return seen


def _latest_ledger(root: pathlib.Path, name: str) -> pathlib.Path | None:
    return _latest_file(root, [f"generated/**/{name}", f"artifacts/**/{name}", f"examples/**/{name}"])


def _pytest_state(root: pathlib.Path) -> dict[str, Any]:
    path, doc = _latest_json(root, ["artifacts/*pytest*result*.json", "generated/**/*pytest*result*.json", "examples/test_results/*pytest*result*.json"])
    if not path:
        return {"last_pytest_status": "missing", "failed_tests": [], "pytest_result": ""}
    status = str(doc.get("status") or doc.get("result") or "").lower()
    failed = doc.get("failed_tests", [])
    if not isinstance(failed, list):
        failed = [str(failed)]
    if status in {"pass", "passed", "ok"}:
        normalized = "pass"
    elif status in {"fail", "failed", "error"} or failed:
        normalized = "fail"
    else:
        normalized = "missing"
    return {"last_pytest_status": normalized, "failed_tests": failed, "pytest_result": str(path)}


def _report_status(doc: dict[str, Any]) -> str:
    value = str(doc.get("status") or doc.get("commercial_status") or "").strip()
    return value or "missing"


def _run_dir_from_report(report: dict[str, Any], fallback_report_path: pathlib.Path | None = None) -> pathlib.Path | None:
    for key in ("run_dir", "work_root"):
        if report.get(key):
            return pathlib.Path(str(report[key]))
    if fallback_report_path and fallback_report_path.parent.name != "generated":
        candidate = fallback_report_path.parent / "run"
        if candidate.exists():
            return candidate
    return None


def observe_repository_state(root: str | pathlib.Path | None = None) -> dict[str, Any]:
    repo = pathlib.Path(root or ROOT).resolve()
    generated = repo / "generated"
    agent_verify_path, agent_verify = _latest_json(generated, ["agent_led_verify/*/agent_led_verify_report.json"])
    benchmark_path, benchmark = _latest_json(generated, ["large_project_agent_led_benchmark/*/large_project_agent_led_benchmark_report.json"])
    closure_path, closure = _latest_json(generated, ["formal_live_delivery_closure/*/formal_live_delivery_closure_report.json", "agent_led_verify/*/formal_live_delivery_closure_report.json"])
    commercial_path, commercial = _latest_json(repo, ["generated/**/commercial_readiness_report.json", "examples/test_results/commercial_readiness_report.json"])
    product_path, product = _latest_json(repo, ["generated/**/product_acceptance_report.json", "examples/test_results/product_acceptance_report.json"])
    manifest_path = _latest_file(generated, ["**/delivery_manifest.json"])
    agent_ledger_path = _latest_ledger(repo, "agent_decision_ledger.jsonl")
    model_ledger_path = _latest_ledger(repo, "model_call_ledger.jsonl")

    latest_reports = {
        "agent_led_verify": str(agent_verify_path) if agent_verify_path else "",
        "large_project_benchmark": str(benchmark_path) if benchmark_path else "",
        "formal_live_delivery_closure": str(closure_path) if closure_path else "",
        "commercial_readiness": str(commercial_path) if commercial_path else "",
        "product_acceptance": str(product_path) if product_path else "",
        "complexity_audit": str(benchmark_path) if benchmark_path else "",
        "delivery_manifest": str(manifest_path) if manifest_path else "",
    }
    paths = [path for path in (agent_verify_path, benchmark_path, closure_path, commercial_path, product_path, manifest_path, agent_ledger_path, model_ledger_path) if path]
    newest = max(paths, key=_mtime) if paths else None
    stale: list[str] = []
    if newest:
        newest_mtime = _mtime(newest)
        for name, path_text in latest_reports.items():
            if not path_text:
                continue
            path = pathlib.Path(path_text)
            if newest_mtime - _mtime(path) > 7 * 24 * 60 * 60:
                stale.append(name)

    selected_tools = _selected_tools(agent_verify, benchmark)
    run_dir = _run_dir_from_report(agent_verify, agent_verify_path) or _run_dir_from_report(benchmark, benchmark_path)
    run_state = observe_run_state(run_dir) if run_dir else {}
    verify_state = agent_verify.get("state") if isinstance(agent_verify.get("state"), dict) else {}
    source_state = {**run_state, **verify_state}
    benchmark_complexity = benchmark.get("complexity", {}) if isinstance(benchmark.get("complexity"), dict) else {}
    complexity_audit = benchmark_complexity.get("audit", {}) if isinstance(benchmark_complexity.get("audit"), dict) else {}
    product_acceptance = benchmark.get("product_acceptance", {}) if isinstance(benchmark.get("product_acceptance"), dict) else product
    commercial_status = str(agent_verify.get("commercial_status") or benchmark.get("commercial_status") or commercial.get("commercial_status") or commercial.get("status") or source_state.get("commercial_status") or "missing")
    pytest_state = _pytest_state(repo)
    provider = {
        "provider_available": source_state.get("provider_available", True),
        "provider_error_code": source_state.get("provider_error_code") or None,
        "provider_error_type": source_state.get("provider_error_type") or None,
        "provider_quota_exceeded": bool(source_state.get("provider_quota_exceeded")),
        "local_model_available": bool(source_state.get("local_model_available")),
    }
    generation = {
        "formal_generation_materialized": bool(source_state.get("formal_generation_materialized")),
        "writable_project_files_exist": bool(source_state.get("writable_project_files_exist")),
        "candidate_exists": bool(source_state.get("candidate_exists")),
        "final_project_exists": bool(source_state.get("final_project_exists")),
        "semantic_review_status": source_state.get("semantic_review_status", "missing"),
        "final_promotion_status": source_state.get("final_promotion_status", "missing"),
    }
    delivery = {
        "delivery_manifest_exists": bool(source_state.get("delivery_manifest_exists") or manifest_path),
        "delivery_manifest": str(manifest_path) if manifest_path else str(agent_verify.get("delivery_manifest") or benchmark.get("delivery_manifest") or ""),
        "final_bundle_exists": bool(source_state.get("final_bundle_exists") or agent_verify.get("final_project_bundle") or benchmark.get("final_bundle")),
        "final_bundle": str(agent_verify.get("final_project_bundle") or benchmark.get("final_bundle") or ""),
        "screenshot_evidence_exists": bool(source_state.get("screenshot_evidence_exists") or agent_verify.get("screenshot_evidence_exists") or benchmark.get("screenshot_evidence")),
        "screenshot_evidence": str(benchmark.get("screenshot_evidence") or ""),
        "public_gate_status": source_state.get("public_gate_status", "missing"),
    }
    quality = {
        "complexity_status": complexity_audit.get("status") or benchmark_complexity.get("status") or "missing",
        "page_count": int(benchmark_complexity.get("page_count") or complexity_audit.get("page_count") or 0),
        "module_count": int(benchmark_complexity.get("module_count") or complexity_audit.get("module_count") or 0),
        "product_acceptance_status": product_acceptance.get("status", "missing") if isinstance(product_acceptance, dict) else "missing",
        "missing_core_features": product_acceptance.get("missing_core_features", []) if isinstance(product_acceptance, dict) else [],
        "weak_features": product_acceptance.get("weak_features", []) if isinstance(product_acceptance, dict) else [],
        "ux_score": product_acceptance.get("ux_score") if isinstance(product_acceptance, dict) else None,
        "commercial_status": commercial_status,
        "remaining_blockers": benchmark.get("remaining_blockers") or agent_verify.get("remaining_blockers") or source_state.get("remaining_blockers", []),
        "model_participation_status": source_state.get("model_participation_status", "missing"),
        "artifact_integrity_status": source_state.get("artifact_integrity_status", "missing"),
        "security_status": source_state.get("security_status", "missing"),
    }
    return {
        "latest_reports": latest_reports,
        "latest_report_status": {
            "agent_led_verify": _report_status(agent_verify),
            "large_project_benchmark": _report_status(benchmark),
            "formal_live_delivery_closure": _report_status(closure),
            "commercial_readiness": _report_status(commercial),
            "product_acceptance": _report_status(product),
        },
        "report_freshness": {
            "latest_timestamp": _iso_mtime(newest),
            "stale_reports": stale,
            "missing_reports": [name for name, path in latest_reports.items() if not path and name != "product_acceptance"],
        },
        "agent_led": {
            "director_loop_used": bool(agent_verify.get("director_loop_used") or benchmark.get("director_loop_used")),
            "decision_ledger_exists": bool(agent_ledger_path and agent_ledger_path.exists()),
            "selected_tools": selected_tools,
        },
        "provider": provider,
        "generation": generation,
        "delivery": delivery,
        "quality": quality,
        "tests": pytest_state,
        "ledgers": {
            "agent_decision_ledger": str(agent_ledger_path) if agent_ledger_path else "",
            "model_call_ledger": str(model_ledger_path) if model_ledger_path else "",
        },
        "git": _git_status(repo),
        "source_run_dir": str(run_dir) if run_dir else "",
    }
