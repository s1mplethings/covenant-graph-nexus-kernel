#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
from typing import Any

try:
    import artifact_integrity
    import formal_model_contract
    import visual_evidence
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import artifact_integrity
    from scripts import formal_model_contract
    from scripts import visual_evidence


def read_json(path: str | pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _path(value: Any) -> pathlib.Path | None:
    text = str(value or "").strip()
    return pathlib.Path(text).resolve() if text else None


def _existing_file(value: Any) -> str:
    path = _path(value)
    return str(path) if path and path.exists() and path.is_file() and path.stat().st_size > 0 else ""


def _usage_plan(run_dir: pathlib.Path | None, formal_result: dict[str, Any]) -> dict[str, Any]:
    agent_usage = formal_result.get("agent_usage", {}) if isinstance(formal_result.get("agent_usage"), dict) else {}
    plan = agent_usage.get("plan", {}) if isinstance(agent_usage.get("plan"), dict) else {}
    if plan:
        return plan
    if run_dir:
        path = run_dir / "agent_usage" / "usage_plan.json"
        if path.exists():
            return read_json(path)
    return {}


def _audit_fallback(run_dir: pathlib.Path | None, *, package_path: pathlib.Path | None, manifest_path: pathlib.Path | None) -> dict[str, Any]:
    if not run_dir:
        return {"status": "not_evaluated", "attempted": False}
    path = run_dir / "artifacts" / "provider_fallback_evidence.json"
    if not path.exists():
        return {"status": "not_required", "attempted": False, "path": str(path)}
    doc = read_json(path)
    blockers: list[str] = []
    if doc.get("fallback_status") != "ok":
        blockers.append(f"provider_fallback_failed:{doc.get('error') or doc.get('fallback_status') or 'unknown'}")
    if doc.get("requires_reverify") is not True:
        blockers.append("provider_fallback_reverify_not_required")
    if doc.get("delivery_pass_allowed_without_reverify") is not False:
        blockers.append("provider_fallback_allows_delivery_without_reverify")
    reverify_refs = doc.get("reverify_refs", []) if isinstance(doc.get("reverify_refs"), list) else []
    reverify_status = str(doc.get("reverify_status", "") or "")
    reverified = False
    if doc.get("reverify_attempted") is True and reverify_status in {"pass", "failed"}:
        reverified = bool(reverify_refs)
    try:
        fallback_mtime = path.stat().st_mtime
        reverify_times = [
            candidate.stat().st_mtime
            for candidate in (package_path, manifest_path)
            if candidate is not None and candidate.exists()
        ]
        reverified = reverified or bool(reverify_times and max(reverify_times) >= fallback_mtime)
    except Exception:
        pass
    if doc.get("formal_chain_continued") and not reverified:
        blockers.append("provider_fallback_reverify_evidence_missing")
    return {
        "status": "pass" if not blockers else "fail",
        "attempted": True,
        "path": str(path),
        "primary_status": doc.get("primary_status", ""),
        "fallback_provider": doc.get("fallback_provider", ""),
        "fallback_model": doc.get("fallback_model", ""),
        "fallback_status": doc.get("fallback_status", ""),
        "requires_reverify": bool(doc.get("requires_reverify")),
        "reverify_attempted": bool(doc.get("reverify_attempted")),
        "reverify_status": reverify_status,
        "reverify_refs": reverify_refs,
        "reverified_after_fallback": reverified,
        "blockers": blockers,
    }


def audit_formal_delivery_evidence(
    formal_result: dict[str, Any],
    *,
    project_dir: str | pathlib.Path | None = None,
    run_dir: str | pathlib.Path | None = None,
    delivery_manifest: str | pathlib.Path | None = None,
    final_bundle: str | pathlib.Path | None = None,
    final_truth: dict[str, Any] | None = None,
    require_video: bool = False,
) -> dict[str, Any]:
    result = formal_result if isinstance(formal_result, dict) else {}
    run = _path(run_dir or result.get("run_dir"))
    project = _path(project_dir or result.get("final_project_dir") or result.get("project_dir") or result.get("candidate_project_dir"))
    manifest = _path(delivery_manifest or result.get("delivery_manifest"))
    bundle = _path(final_bundle or result.get("final_project_bundle"))
    if project and manifest is None:
        manifest = project / "delivery_manifest.json"
    if project and bundle is None:
        bundle = project / "final_project_bundle.zip"

    blockers: list[str] = []
    status = str(result.get("status") or "").lower()
    if status != "pass":
        reason = str(result.get("reason") or result.get("verdict") or "unknown")
        blockers.append(f"formal_generation_status_not_pass:{status or 'missing'}:{reason}")
    if not run or not run.exists():
        blockers.append("formal_run_dir_missing")
    if not project or not project.exists():
        blockers.append("formal_project_dir_missing")

    usage_plan = _usage_plan(run, result)
    model_gate = formal_model_contract.evaluate_model_participation(
        context="formal_live_generation",
        run_dir=run,
        usage_plan=usage_plan,
    )
    if model_gate.get("status") != "pass":
        blockers.append(f"formal_model_gate:{model_gate.get('reason', 'FORMAL_MODEL_EVIDENCE_MISSING')}")

    ledger = formal_model_contract.read_ledger(run) if run else []
    if not ledger:
        blockers.append("model_call_ledger_missing")

    manifest_doc = read_json(manifest) if manifest else {}
    if not manifest or not manifest.exists():
        blockers.append("delivery_manifest_missing")
    if not bundle or not bundle.exists() or bundle.stat().st_size <= 0:
        blockers.append("final_project_bundle_missing")

    integrity = (
        artifact_integrity.validate_final_package(project, bundle, manifest, require_video=require_video)
        if project and bundle and manifest
        else {"status": "fail", "blockers": ["final_package_inputs_missing"]}
    )
    if integrity.get("status") != "pass":
        blockers.extend(f"final_package_integrity:{item}" for item in integrity.get("blockers", []))

    screenshot = _existing_file(result.get("screenshot_path") or manifest_doc.get("screenshot_path"))
    if not screenshot:
        screenshots = result.get("screenshots", []) if isinstance(result.get("screenshots"), list) else []
        screenshot = next((_existing_file(item) for item in screenshots if _existing_file(item)), "")
    if not screenshot or not visual_evidence.real_image_file(pathlib.Path(screenshot)):
        blockers.append("screenshot_evidence_missing")

    video = _existing_file(result.get("video_path") or manifest_doc.get("video_path"))
    if not video:
        videos = result.get("videos", []) if isinstance(result.get("videos"), list) else []
        video = next((_existing_file(item) for item in videos if _existing_file(item)), "")
    video_diag = visual_evidence.video_file_diagnostics(pathlib.Path(video)) if video else {"valid": False, "reason": "missing"}
    if require_video and not video_diag.get("valid"):
        blockers.append(f"video_evidence_missing:{video_diag.get('reason', 'missing')}")

    truth = final_truth or result.get("final_delivery_truth") or result.get("final_truth") or {}
    public_gate = truth.get("metadata", {}).get("public_final_gate", {}) if isinstance(truth.get("metadata"), dict) else {}
    delivery_allowed = bool(truth.get("metadata", {}).get("delivery_allowed") or result.get("delivery_allowed"))
    if not delivery_allowed:
        missing = public_gate.get("missing", []) if isinstance(public_gate.get("missing"), list) else []
        blockers.append("public_delivery_gate_not_ready" + (":" + ",".join(str(item) for item in missing) if missing else ""))

    fallback = _audit_fallback(run, package_path=bundle, manifest_path=manifest)
    if fallback.get("status") == "fail":
        blockers.extend(str(item) for item in fallback.get("blockers", []))

    blockers = list(dict.fromkeys(item for item in blockers if item))
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "run_dir": str(run) if run else "",
        "project_dir": str(project) if project else "",
        "delivery_manifest": str(manifest) if manifest else "",
        "final_project_bundle": str(bundle) if bundle else "",
        "model_call_ledger": str(formal_model_contract.ledger_path(run)) if run else "",
        "model_gate": model_gate,
        "ledger_records": len(ledger),
        "fallback": fallback,
        "package_integrity": integrity,
        "screenshot_path": screenshot,
        "video_path": video,
        "video_diagnostics": video_diag,
        "require_video": bool(require_video),
        "public_final_gate": public_gate,
        "delivery_allowed": delivery_allowed,
    }
