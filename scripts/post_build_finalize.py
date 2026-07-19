#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import pathlib
import sys
from typing import Any

try:
    import visual_evidence
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import visual_evidence
    from scripts.pipeline_contracts import base_result


def _legacy() -> Any:
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "run_candidate_post_build_finalize"):
        return main
    packaged = sys.modules.get("scripts.run_local_pipeline")
    if packaged is not None and hasattr(packaged, "run_candidate_post_build_finalize"):
        return packaged
    top_level = sys.modules.get("run_local_pipeline")
    if top_level is not None and hasattr(top_level, "run_candidate_post_build_finalize"):
        return top_level
    implementation = sys.modules.get("scripts.run_local_pipeline_impl")
    if implementation is not None and hasattr(implementation, "run_candidate_post_build_finalize"):
        return implementation
    try:
        return importlib.import_module("scripts.run_local_pipeline_impl")
    except ModuleNotFoundError:
        return importlib.import_module("run_local_pipeline_impl")


def run(**kwargs: Any) -> dict[str, Any]:
    legacy = _legacy()
    result = legacy.run_candidate_post_build_finalize(**kwargs)
    project_dir = pathlib.Path(str(kwargs.get("project_dir", "")))
    if str(project_dir):
        ensure_candidate_review_artifacts(project_dir, result)
        ensure_video_evidence(project_dir, pathlib.Path(str(kwargs.get("run_dir", project_dir))), result, explicit_requested=kwargs.get("video_requested") if isinstance(kwargs.get("video_requested"), bool) else None, timeout=int(kwargs.get("timeout", 60) or 60))
    return result


def ensure_candidate_review_artifacts(project_dir: pathlib.Path, result: dict[str, Any]) -> None:
    legacy = _legacy()
    project = pathlib.Path(project_dir)
    test_result = result.get("test_result", {}) if isinstance(result.get("test_result"), dict) else {}
    test_status = str(test_result.get("status", "unknown"))
    screenshots = result.get("screenshots", []) if isinstance(result.get("screenshots"), list) else []
    if test_status.lower() != "pass" and not result.get("screenshot_blocked"):
        blocked = legacy.write_screenshot_blocked(
            project,
            "tests did not pass yet",
            failure_type="tests_not_passed",
            details={
                "startup_command": "",
                "startup_cwd": str(project),
                "startup_returncode": None,
                "startup_stdout_tail": "",
                "startup_stderr_tail": "",
                "port": None,
                "server_ready": False,
                "opened_url": "",
                "failure_reason": "tests_not_passed",
                "screenshot_attempted": False,
                "next_repair_hint": "Repair npm test before collecting screenshot evidence.",
            },
        )
        result["screenshot_blocked"] = blocked
        result["screenshot_capture"] = {"status": "skipped", "reason": "tests did not pass yet"}
    if result.get("screenshot_blocked"):
        ensure_startup_diagnostics(pathlib.Path(str(result.get("screenshot_blocked"))), project)
    if not (project / "candidate_review_summary.json").exists():
        verdict = "ASK_USER_REVIEW" if test_status.lower() == "pass" else "NEEDS_REWORK"
        known_limits = result.get("known_limits", []) if isinstance(result.get("known_limits"), list) else []
        summary = legacy.write_candidate_review_summary(
            project,
            verdict=verdict,
            test_status=test_status,
            screenshots=[str(item) for item in screenshots],
            video_blocked=str(result.get("video_blocked", "")),
            known_limits=[str(item) for item in known_limits],
        )
        result["candidate_review_summary"] = summary
    update_candidate_review_video_status(project, result)


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _video_failure_reason(video_blocked: str) -> str:
    if not video_blocked:
        return ""
    return str(_read_json(pathlib.Path(video_blocked)).get("failure_reason", "unknown") or "unknown")


def ensure_video_evidence(
    project_dir: pathlib.Path,
    run_dir: pathlib.Path,
    result: dict[str, Any],
    *,
    explicit_requested: bool | None = None,
    timeout: int = 60,
) -> None:
    project = pathlib.Path(project_dir)
    requested = visual_evidence.video_requested(explicit_requested)
    existing_video = pathlib.Path(str(result.get("video", ""))) if str(result.get("video", "")).strip() else None
    if existing_video and visual_evidence.video_file_diagnostics(existing_video).get("valid"):
        result["video_requested"] = requested
        result["video_status"] = "pass"
        result["video_path"] = str(existing_video)
        result["video"] = str(existing_video)
        result["video_blocked"] = ""
        stale_blocked = project / "video_blocked.json"
        if stale_blocked.exists():
            try:
                stale_blocked.unlink()
            except Exception:
                pass
        update_candidate_review_video_status(project, result)
        recreate_candidate_diagnostic_package(project, run_dir, result)
        write_post_build_result(run_dir, result)
        return

    old_blocked = pathlib.Path(str(result.get("video_blocked", ""))) if str(result.get("video_blocked", "")).strip() else None
    old_reason = _video_failure_reason(str(old_blocked)) if old_blocked else ""
    if not requested:
        blocked = visual_evidence.write_video_blocked(
            project,
            "video capture disabled by user option",
            failure_reason="not_requested",
            environment=getattr(_legacy(), "screenshot_environment_diagnostics")(),
            video_requested_value=False,
        )
        result.update({"video": "", "video_blocked": blocked, "video_requested": False, "video_status": "blocked", "video_failure_reason": "not_requested"})
        update_candidate_review_video_status(project, result)
        recreate_candidate_diagnostic_package(project, run_dir, result)
        return

    # Legacy finalize wrote not_requested when no external usage-agent video existed.
    # Default formal projects now attempt browser video evidence instead.
    if old_reason == "not_requested" or not old_blocked or not old_blocked.exists():
        video_result = visual_evidence.capture_candidate_video(project, run_dir, timeout=min(timeout, 90), explicit_requested=True)
        result["video_requested"] = True
        if video_result.get("status") == "pass" and video_result.get("video"):
            result["video"] = str(video_result.get("video", ""))
            result["video_path"] = str(video_result.get("video", ""))
            result["video_blocked"] = ""
            result["video_status"] = "pass"
            result["video_failure_reason"] = ""
            stale_blocked = project / "video_blocked.json"
            if stale_blocked.exists():
                try:
                    stale_blocked.unlink()
                except Exception:
                    pass
        else:
            result["video"] = ""
            result["video_path"] = ""
            result["video_blocked"] = str(video_result.get("video_blocked", ""))
            result["video_status"] = "blocked"
            result["video_failure_reason"] = str(video_result.get("failure_reason") or _video_failure_reason(str(video_result.get("video_blocked", ""))) or "unknown")
    else:
        if old_reason == "not_requested":
            old_reason = "unknown"
        result.update({"video": "", "video_requested": True, "video_status": "blocked", "video_failure_reason": old_reason, "video_blocked": str(old_blocked)})

    known_limits = result.get("known_limits", []) if isinstance(result.get("known_limits"), list) else []
    if result.get("video_status") == "pass":
        known_limits = [item for item in known_limits if "video_blocked" not in str(item)]
    elif result.get("video_blocked") and not any("video_blocked" in str(item) for item in known_limits):
        known_limits.append("video_blocked: demo video was not produced during candidate post-build finalize")
    result["known_limits"] = known_limits
    update_candidate_review_video_status(project, result)
    recreate_candidate_diagnostic_package(project, run_dir, result)
    write_post_build_result(run_dir, result)


def update_candidate_review_video_status(project_dir: pathlib.Path, result: dict[str, Any]) -> None:
    project = pathlib.Path(project_dir)
    summary_path = project / "candidate_review_summary.json"
    if not summary_path.exists():
        return
    doc = _read_json(summary_path)
    video_path = str(result.get("video_path") or result.get("video") or "")
    video_blocked = str(result.get("video_blocked", "") or "")
    failure_reason = str(result.get("video_failure_reason") or _video_failure_reason(video_blocked) or "")
    requested = bool(result.get("video_requested", visual_evidence.video_requested()))
    status = "pass" if video_path and visual_evidence.video_file_diagnostics(pathlib.Path(video_path)).get("valid") else "blocked"
    doc.update(
        {
            "video_requested": requested,
            "video_status": status,
            "video_blocked": "" if status == "pass" else video_blocked,
            "video_path": video_path if status == "pass" else "",
            "video_blocked_path": video_blocked,
            "video_failure_reason": "" if status == "pass" else (failure_reason or "unknown"),
            "final_delivery": False,
        }
    )
    if status == "pass" and isinstance(doc.get("warnings"), list):
        doc["warnings"] = [item for item in doc["warnings"] if "video blocked" not in str(item).lower() and "video_blocked" not in str(item)]
    _write_json(summary_path, doc)
    result["candidate_review_summary"] = str(summary_path)


def recreate_candidate_diagnostic_package(project_dir: pathlib.Path, run_dir: pathlib.Path, result: dict[str, Any]) -> None:
    legacy = _legacy()
    if not hasattr(legacy, "create_candidate_diagnostic_package"):
        return
    try:
        package = legacy.create_candidate_diagnostic_package(pathlib.Path(project_dir), pathlib.Path(run_dir))
    except Exception:
        return
    result["diagnostic_package"] = str(package)


def write_post_build_result(run_dir: pathlib.Path, result: dict[str, Any]) -> None:
    path = pathlib.Path(run_dir) / "artifacts" / "candidate_post_build_finalize.json"
    try:
        _write_json(path, result)
    except Exception:
        return


def ensure_startup_diagnostics(blocked_path: pathlib.Path, project_dir: pathlib.Path) -> None:
    if not blocked_path.exists():
        return
    try:
        doc = json.loads(blocked_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return
    if not isinstance(doc, dict):
        return
    defaults = {
        "startup_command": "",
        "startup_cwd": str(project_dir),
        "startup_returncode": None,
        "startup_stdout_tail": "",
        "startup_stderr_tail": "",
        "port": None,
        "server_ready": False,
        "opened_url": "",
        "failure_reason": str(doc.get("failure_reason") or "startup_failed"),
        "next_repair_hint": str(doc.get("next_repair_hint") or ""),
    }
    changed = False
    for key, value in defaults.items():
        if key not in doc:
            doc[key] = value
            changed = True
    if "details" in doc and isinstance(doc["details"], dict):
        for key, value in defaults.items():
            if key not in doc["details"]:
                doc["details"][key] = value
                changed = True
    if changed:
        blocked_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="module_contract",
        metadata={
            "responsibilities": [
                "command execution",
                "npm test",
                "startup",
                "UI smoke",
                "TEST_REPORT",
                "DELIVERY_NOTES",
                "known_limits",
                "repair_plan",
                "video_blocked/screenshot_blocked",
            ],
            "forbidden": ["final package", "delivery manifest", "fake PASS"],
        },
    )
