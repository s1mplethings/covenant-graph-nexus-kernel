#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

try:
    import artifact_integrity
    import commercial_warning_policy
    import final_delivery_truth
    import local_packager
    import visual_evidence
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import artifact_integrity
    from scripts import commercial_warning_policy
    from scripts import final_delivery_truth
    from scripts import local_packager
    from scripts import visual_evidence
    from scripts.pipeline_contracts import base_result


CANDIDATE_MARKER = "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json"
FINAL_PROJECT_DIR_NAME = "cgnk_generated_project_final"


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _first_existing(paths: list[str] | list[pathlib.Path]) -> str:
    for raw in paths:
        path = pathlib.Path(str(raw))
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return str(path)
    return ""


def _find_media(project_dir: pathlib.Path, suffixes: set[str], preferred_parts: tuple[str, ...]) -> str:
    candidates: list[tuple[int, float, pathlib.Path]] = []
    for path in pathlib.Path(project_dir).rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(project_dir).as_posix().lower()
        score = sum(1 for part in preferred_parts if part in rel)
        candidates.append((score, path.stat().st_mtime, path))  # type: ignore[arg-type]
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return str(candidates[0][2])  # type: ignore[index]


def _post_build_doc(candidate_dir: pathlib.Path, run_dir: pathlib.Path | None, post_build: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(post_build, dict) and post_build:
        return post_build
    if run_dir:
        path = pathlib.Path(run_dir) / "artifacts" / "candidate_post_build_finalize.json"
        doc = _read_json(path)
        if doc:
            return doc
    return {}


def _candidate_summary(candidate_dir: pathlib.Path) -> dict[str, Any]:
    return _read_json(pathlib.Path(candidate_dir) / "candidate_review_summary.json")


def _candidate_bundle_path(candidate_dir: pathlib.Path, run_dir: pathlib.Path | None, candidate_bundle: pathlib.Path | None) -> pathlib.Path:
    if candidate_bundle:
        return pathlib.Path(candidate_bundle)
    if run_dir:
        return pathlib.Path(run_dir) / "artifacts" / "candidate_diagnostic_bundle.zip"
    return pathlib.Path(candidate_dir) / "candidate_diagnostic_bundle.zip"


def _quality_paths(candidate_dir: pathlib.Path, post_build: dict[str, Any], summary: dict[str, Any]) -> dict[str, str]:
    screenshots = post_build.get("screenshots", []) if isinstance(post_build.get("screenshots"), list) else []
    summary_screens = summary.get("screenshot_paths", []) if isinstance(summary.get("screenshot_paths"), list) else []
    screenshot = _first_existing([str(item) for item in screenshots + summary_screens])
    if not screenshot:
        screenshot = _find_media(candidate_dir, {".png", ".jpg", ".jpeg", ".webp"}, ("screenshot", "candidate_home"))

    video = str(post_build.get("video") or summary.get("video_path") or "")
    if not video or not pathlib.Path(video).exists():
        video = _find_media(candidate_dir, {".webm", ".mp4"}, ("video", "candidate_demo"))

    return {
        "test_report": str(candidate_dir / "TEST_REPORT.md") if (candidate_dir / "TEST_REPORT.md").exists() else "",
        "readme": str(candidate_dir / "README.md") if (candidate_dir / "README.md").exists() else "",
        "delivery_notes": str(candidate_dir / "DELIVERY_NOTES.md") if (candidate_dir / "DELIVERY_NOTES.md").exists() else "",
        "screenshot": screenshot,
        "video": video,
    }


def evaluate_candidate_for_final_promotion(
    candidate_dir: pathlib.Path,
    *,
    run_dir: pathlib.Path | None = None,
    post_build: dict[str, Any] | None = None,
    candidate_bundle: pathlib.Path | None = None,
    require_video: bool = False,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir).resolve()
    blockers: list[str] = []
    warnings: list[str] = []
    if not candidate.exists() or not candidate.is_dir():
        blockers.append("candidate_project_dir_missing")
        return base_result(status="fail", verdict="final_promotion_rejected", blockers=blockers)
    if pathlib.Path(candidate_bundle or "").name == "final_project_bundle.zip":
        blockers.append("candidate_bundle_named_final_project_bundle")

    post = _post_build_doc(candidate, run_dir, post_build)
    summary = _candidate_summary(candidate)
    paths = _quality_paths(candidate, post, summary)

    runnable = any((candidate / name).exists() for name in ("index.html", "package.json", "app.py", "main.py"))
    if not runnable:
        blockers.append("runnable_candidate_missing")
    test_status = str((post.get("test_result") or {}).get("status") or summary.get("test_status") or "").lower()
    if test_status != "pass":
        blockers.append("npm_test_not_passed")

    ui_smoke = post.get("ui_smoke", {}) if isinstance(post.get("ui_smoke"), dict) else {}
    screenshot_capture = post.get("screenshot_capture", {}) if isinstance(post.get("screenshot_capture"), dict) else {}
    capture_smoke = screenshot_capture.get("ui_smoke", {}) if isinstance(screenshot_capture.get("ui_smoke"), dict) else {}
    if str(ui_smoke.get("status") or capture_smoke.get("status") or "").lower() != "pass":
        blockers.append("ui_smoke_not_passed")

    screenshot_path = pathlib.Path(paths["screenshot"]) if paths["screenshot"] else pathlib.Path()
    if not paths["screenshot"] or not visual_evidence.real_image_file(screenshot_path):
        blockers.append("screenshot_not_passed")

    video_blocked = str(post.get("video_blocked") or summary.get("video_blocked_path") or summary.get("video_blocked") or "")
    video_path = pathlib.Path(paths["video"]) if paths["video"] else pathlib.Path()
    video_pass = bool(paths["video"] and visual_evidence.video_file_diagnostics(video_path).get("valid"))
    video_warning = bool(video_blocked and pathlib.Path(video_blocked).exists())
    if require_video and not video_pass:
        blockers.append("video_missing")
    elif not video_pass and not video_warning:
        warnings.append("video_missing_optional")

    bundle = _candidate_bundle_path(candidate, run_dir, candidate_bundle)
    bundle_integrity = artifact_integrity.validate_candidate_bundle(bundle, require_video=require_video)
    if bundle_integrity.get("status") != "pass":
        blockers.append("candidate_artifact_integrity_failed")

    for name in ("final_project_bundle.zip", "delivery_manifest.json"):
        if (candidate / name).exists():
            blockers.append(f"candidate_contains_{name}")

    return base_result(
        status="fail" if blockers else "pass",
        verdict="final_promotion_ready" if not blockers else "final_promotion_rejected",
        blockers=blockers,
        warnings=warnings,
        artifacts=[str(path) for path in (screenshot_path, video_path, bundle) if str(path) and pathlib.Path(path).exists()],
        metadata={
            "candidate_dir": str(candidate),
            "runnable_candidate": runnable,
            "npm_test": test_status or "unknown",
            "ui_smoke": str(ui_smoke.get("status") or capture_smoke.get("status") or "unknown"),
            "screenshot_path": paths["screenshot"],
            "video_path": paths["video"],
            "video_pass": video_pass,
            "video_blocked": video_blocked,
            "video_warning": video_warning,
            "candidate_bundle": str(bundle),
            "candidate_bundle_integrity": bundle_integrity,
        },
    )


def _copy_candidate_to_final(candidate_dir: pathlib.Path, final_dir: pathlib.Path) -> None:
    candidate = pathlib.Path(candidate_dir).resolve()
    final = pathlib.Path(final_dir).resolve()
    if candidate == final:
        raise RuntimeError("final promotion requires a separate final project directory")
    if final.exists():
        shutil.rmtree(final)
    ignore = shutil.ignore_patterns(CANDIDATE_MARKER, "final_project_bundle.zip", "delivery_manifest.json")
    shutil.copytree(candidate, final, ignore=ignore)
    marker = final / CANDIDATE_MARKER
    if marker.exists():
        marker.unlink()


def promote_candidate_to_final(
    candidate_dir: pathlib.Path,
    *,
    run_dir: pathlib.Path | None = None,
    final_dir: pathlib.Path | None = None,
    post_build: dict[str, Any] | None = None,
    candidate_bundle: pathlib.Path | None = None,
    require_video: bool = False,
) -> dict[str, Any]:
    candidate = pathlib.Path(candidate_dir).resolve()
    run = pathlib.Path(run_dir).resolve() if run_dir else None
    readiness = evaluate_candidate_for_final_promotion(candidate, run_dir=run, post_build=post_build, candidate_bundle=candidate_bundle, require_video=require_video)
    if readiness.get("status") != "pass":
        return base_result(status="fail", verdict="final_promotion_rejected", blockers=list(readiness.get("blockers", [])), metadata={"readiness": readiness})

    metadata = readiness.get("metadata", {})
    destination = pathlib.Path(final_dir).resolve() if final_dir else candidate.parent / FINAL_PROJECT_DIR_NAME
    _copy_candidate_to_final(candidate, destination)
    final_project_manifest_path = destination / "final_project_manifest.json"
    _write_json(
        final_project_manifest_path,
        {
            "kind": "CGKNFinalProjectManifest",
            "final_project_dir": str(destination),
            "source_candidate_project_dir": str(candidate),
            "candidate_marker_removed": not (destination / CANDIDATE_MARKER).exists(),
            "local_packager_required": True,
            "delivery_manifest_required": True,
        },
    )

    rel_screenshot = pathlib.Path(str(metadata.get("screenshot_path", ""))).name
    screenshot_in_final = _find_media(destination, {".png", ".jpg", ".jpeg", ".webp"}, (rel_screenshot.lower(), "screenshot", "candidate_home"))
    known_limits = []
    summary = _candidate_summary(candidate)
    if isinstance(summary.get("warnings"), list):
        known_limits = [str(item) for item in summary["warnings"] if "final_project_bundle.zip" not in str(item) and "delivery_manifest.json" not in str(item)]
    try:
        manifest = local_packager.package_project(
            destination,
            output_dir=destination,
            startup_command="python -m http.server 5173 --bind 127.0.0.1",
            screenshot_path=screenshot_in_final,
            known_limits=known_limits,
        )
    except Exception as exc:
        return base_result(
            status="fail",
            verdict="local_packager_failed",
            blockers=[str(exc)],
            metadata={"input_candidate_dir": str(candidate), "final_project_dir": str(destination), "readiness": readiness},
        )

    final_video = _find_media(destination, {".webm", ".mp4"}, ("video", "candidate_demo"))
    final_screenshot = screenshot_in_final or _find_media(destination, {".png", ".jpg", ".jpeg", ".webp"}, ("screenshot", "candidate_home"))
    manifest_path = destination / "delivery_manifest.json"
    manifest.update(
        {
            "final_promotion": True,
            "source_candidate_project_dir": str(candidate),
            "candidate_diagnostic_bundle": str(_candidate_bundle_path(candidate, run, candidate_bundle)),
            "final_project_bundle": str(destination / "final_project_bundle.zip"),
            "test_report_path": str(destination / "TEST_REPORT.md"),
            "screenshot_path": final_screenshot,
            "video_path": final_video,
            "readme_path": str(destination / "README.md"),
            "delivery_notes_path": str(destination / "DELIVERY_NOTES.md"),
            "final_project_manifest": str(final_project_manifest_path),
            "final_verdict_candidate": "PASS_FINAL" if metadata.get("video_pass") else "DELIVER_WITH_WARNINGS",
        }
    )
    _write_json(manifest_path, manifest)

    session = {
        "messages": [{"role": "user", "text": "final delivery requires screenshot evidence" + (" and video evidence" if require_video else "")}],
        "whiteboard": {"delivery_requirements": ["screenshot", "video"] if require_video else ["screenshot"]},
    }
    usage_plan: dict[str, Any] = {}
    if run:
        usage_plan_path = run / "agent_usage" / "usage_plan.json"
        if usage_plan_path.exists():
            usage_plan = _read_json(usage_plan_path)
    evidence = {
        "screenshots": [final_screenshot] if final_screenshot else [],
        "videos": [final_video] if final_video else [],
        "run_dir": str(run) if run else "",
        "usage_plan": usage_plan,
    }
    final_truth = final_delivery_truth.evaluate(destination, manifest, session, evidence=evidence, phase="final")
    integrity = artifact_integrity.validate_final_package(destination, destination / "final_project_bundle.zip", manifest_path, require_video=require_video)
    warning_inputs = list(readiness.get("warnings", []))
    if metadata.get("video_warning") and not metadata.get("video_pass"):
        warning_inputs.append("video blocked but screenshot/test/final zip OK")
    warning_policy = commercial_warning_policy.classify_final_warnings(warning_inputs, readiness=readiness, final_truth=final_truth, integrity=integrity)
    allowed = (
        bool(final_truth.get("metadata", {}).get("delivery_allowed"))
        and integrity.get("status") == "pass"
        and not warning_policy.get("metadata", {}).get("classification", {}).get("critical")
    )
    pass_final_allowed = bool(warning_policy.get("metadata", {}).get("pass_final_allowed"))
    final_verdict = "PASS_FINAL" if allowed and (metadata.get("video_pass") or not require_video) and pass_final_allowed else ("DELIVER_WITH_WARNINGS" if allowed else "FINAL_PROMOTION_REJECTED")
    manifest["public_final_gate"] = final_truth.get("metadata", {}).get("public_final_gate", {})
    manifest["integrity_checks"] = {"final_package": integrity, "final_delivery_truth": final_truth}
    manifest["final_warning_policy"] = warning_policy
    manifest["final_verdict"] = final_verdict
    manifest["delivery_allowed"] = allowed
    _write_json(manifest_path, manifest)

    return base_result(
        status="pass" if allowed else "fail",
        verdict=final_verdict,
        artifacts=[str(destination / "final_project_bundle.zip"), str(manifest_path), final_screenshot, final_video],
        blockers=list(final_truth.get("blockers", [])) + list(integrity.get("blockers", [])),
        metadata={
            "input_candidate_dir": str(candidate),
            "final_project_dir": str(destination),
            "local_packager_manifest": manifest,
            "final_project_bundle": str(destination / "final_project_bundle.zip"),
            "delivery_manifest": str(manifest_path),
            "public_final_gate": final_truth.get("metadata", {}).get("public_final_gate", {}),
            "delivery_allowed": allowed,
            "final_warning_policy": warning_policy,
            "integrity": integrity,
            "readiness": readiness,
        },
    )


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="truth_module",
        metadata={
            "responsibilities": ["candidate-to-final promotion", "local_packager handoff", "delivery_manifest truth", "public final gate"],
            "forbidden": ["candidate_diagnostic_bundle as final package", "provider-generated final zip", "fake manifest"],
        },
    )
