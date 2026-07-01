#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import zipfile
import json
import tempfile
from typing import Any

try:
    import visual_evidence
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import visual_evidence
    from scripts.pipeline_contracts import base_result


FINAL_ARTIFACT_NAMES = {"final_project_bundle.zip", "delivery_manifest.json"}
FAKE_PASS_TOKENS = {"PASS_FINAL", "final_delivered", "delivery_manifest_sent", "delivered=true"}


def _zip_names(path: pathlib.Path) -> tuple[list[str], str]:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist(), ""
    except Exception as exc:
        return [], str(exc)


def _real_image_file(path: pathlib.Path) -> bool:
    try:
        return bool(visual_evidence.real_image_file(path))
    except Exception:
        return False


def _image_entries(entries: list[str]) -> list[str]:
    return [item for item in entries if pathlib.PurePosixPath(item).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]


def _invalid_zip_images(bundle: pathlib.Path, entries: list[str]) -> list[str]:
    invalid: list[str] = []
    images = _image_entries(entries)
    if not images:
        return invalid
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        with zipfile.ZipFile(bundle) as zf:
            for name in images:
                try:
                    data = zf.read(name)
                except Exception:
                    invalid.append(name)
                    continue
                target = root / pathlib.PurePosixPath(name).name
                target.write_bytes(data)
                if not _real_image_file(target):
                    invalid.append(name)
    return invalid


def validate_candidate_bundle(candidate_bundle: pathlib.Path, *, require_video: bool = False) -> dict[str, Any]:
    bundle = pathlib.Path(candidate_bundle)
    issues: list[str] = []
    if not bundle.exists() or bundle.stat().st_size <= 0:
        issues.append("candidate bundle missing or empty")
        entries: list[str] = []
        zip_error = ""
    else:
        entries, zip_error = _zip_names(bundle)
        if zip_error:
            issues.append("candidate bundle unreadable")
        entry_names = {pathlib.PurePosixPath(item).name for item in entries}
        for name in FINAL_ARTIFACT_NAMES:
            if name in entry_names:
                issues.append(f"candidate bundle contains {name}")
        required = {"candidate_review_summary.json", "TEST_REPORT.md", "known_limits.json", "repair_plan.json"}
        for name in sorted(required - entry_names):
            issues.append(f"candidate bundle missing {name}")
        if require_video and "video_blocked.json" not in entry_names and not any(pathlib.PurePosixPath(item).suffix.lower() in {".mp4", ".webm"} for item in entries):
            issues.append("candidate bundle missing video or video_blocked")
        image_entries = _image_entries(entries)
        if "screenshot_blocked.json" not in entry_names and not image_entries:
            issues.append("candidate bundle missing screenshot or screenshot_blocked")
        if image_entries:
            for name in _invalid_zip_images(bundle, entries):
                issues.append(f"corrupt_image: candidate bundle screenshot invalid: {name}")
    return base_result(
        status="fail" if issues else "pass",
        verdict="candidate_bundle_integrity",
        artifacts=[str(bundle)] if bundle.exists() else [],
        blockers=issues,
        metadata={"bundle_entry_count": len(entries), "zip_error": zip_error if bundle.exists() else ""},
    )


def validate_final_package(project_dir: pathlib.Path, final_bundle: pathlib.Path, delivery_manifest: pathlib.Path, *, require_video: bool = False) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    bundle = pathlib.Path(final_bundle)
    manifest = pathlib.Path(delivery_manifest)
    issues: list[str] = []
    if bundle.name != "final_project_bundle.zip" or not bundle.exists() or bundle.stat().st_size <= 0:
        issues.append("missing real final_project_bundle.zip")
    if not manifest.exists() or manifest.stat().st_size <= 0:
        issues.append("missing real delivery_manifest.json")
        manifest_doc: dict[str, Any] = {}
    else:
        try:
            manifest_doc = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            manifest_doc = {}
        if not isinstance(manifest_doc, dict):
            manifest_doc = {}
        package_path = pathlib.Path(str(manifest_doc.get("package_path", "")))
        if package_path.name == "candidate_diagnostic_bundle.zip":
            issues.append("delivery_manifest points to candidate_diagnostic_bundle.zip")
        if package_path.name and package_path.name != "final_project_bundle.zip":
            issues.append("delivery_manifest package_path is not final_project_bundle.zip")
        if package_path and package_path.name == "final_project_bundle.zip":
            try:
                if package_path.resolve() != bundle.resolve():
                    issues.append("delivery_manifest package_path does not match final_project_bundle.zip")
            except Exception:
                issues.append("delivery_manifest package_path could not be resolved")
    marker = project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json"
    if marker.exists():
        issues.append("candidate marker present in final project")
    entries: list[str] = []
    if bundle.exists() and bundle.is_file() and bundle.stat().st_size > 0:
        entries, zip_error = _zip_names(bundle)
        if zip_error:
            issues.append("final_project_bundle.zip unreadable")
        entry_names = {pathlib.PurePosixPath(item).name for item in entries}
        if "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json" in entry_names:
            issues.append("final package contains candidate marker")
        for required in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
            if required not in entry_names:
                issues.append(f"final package missing {required}")
        image_entries = _image_entries(entries)
        if not image_entries:
            issues.append("final package missing screenshot evidence")
        else:
            for name in _invalid_zip_images(bundle, entries):
                issues.append(f"corrupt_image: final package screenshot invalid: {name}")
        if require_video and not any(pathlib.PurePosixPath(item).suffix.lower() in {".mp4", ".webm"} for item in entries):
            issues.append("final package missing video evidence")
    return base_result(
        status="fail" if issues else "pass",
        verdict="final_package_integrity",
        blockers=issues,
        artifacts=[str(bundle), str(manifest)],
        metadata={"bundle_entry_count": len(entries)},
    )


def validate_visual_evidence(project_dir: pathlib.Path, visual_result: dict[str, Any]) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    issues: list[str] = []
    screenshots = visual_result.get("screenshots", []) if isinstance(visual_result, dict) else []
    if not isinstance(screenshots, list):
        screenshots = []
    for item in screenshots:
        path = pathlib.Path(str(item))
        if not path.is_absolute():
            path = project / path
        resolved = path.resolve()
        if not str(resolved).lower().startswith(str(project).lower()):
            issues.append(f"screenshot path escapes candidate: {item}")
            continue
        if not resolved.exists() or resolved.stat().st_size <= 0:
            issues.append(f"invalid_screenshot_file: screenshot missing or empty: {item}")
            continue
        if not _real_image_file(resolved):
            issues.append(f"blank_or_invalid_screenshot: screenshot is not a real image: {item}")
    if bool(visual_result.get("fake")) or bool(visual_result.get("provider_generated")):
        issues.append("visual evidence result claims provider-generated or fake evidence")
    return base_result(status="fail" if issues else "pass", verdict="visual_evidence_integrity", blockers=issues, artifacts=[str(item) for item in screenshots])


def scan_no_fake_pass(root: pathlib.Path) -> dict[str, Any]:
    issues: list[str] = []
    base = pathlib.Path(root)
    if base.exists():
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".zip", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for token in FAKE_PASS_TOKENS:
                if token in text:
                    issues.append(f"{path.relative_to(base).as_posix()} contains {token}")
    return base_result(status="fail" if issues else "pass", verdict="fake_pass_scan", blockers=issues)


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="truth_module",
        metadata={
            "responsibilities": ["candidate bundle integrity", "runnable candidate integrity", "final package integrity", "no fake PASS scan"],
            "replaceable": False,
        },
    )
