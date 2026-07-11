#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_test_environment
import run_local_pipeline


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "candidate_smoke_benchmark_report.json"
DEFAULT_RUN_DIR = ROOT / "examples" / "runtime_runs" / "local-pipeline-execution"


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_benchmark(candidate_dir: pathlib.Path, run_dir: pathlib.Path = DEFAULT_RUN_DIR) -> dict[str, Any]:
    environment = check_test_environment.check_environment(candidate_dir)
    post_build = run_local_pipeline.run_candidate_post_build_finalize(
        project_dir=candidate_dir,
        run_dir=run_dir,
        user_goal="candidate smoke benchmark",
        generated_files=[path.relative_to(candidate_dir).as_posix() for path in candidate_dir.rglob("*") if path.is_file()][:200] if candidate_dir.exists() else [],
        online_inputs={},
        example_outputs={},
        model="unused",
        timeout=120,
        phase_log_path=run_dir / "provider_phase_log.jsonl",
        deadline=run_local_pipeline.ProgressDeadline(time.time() + 180, extension_seconds=60),
        classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
    )
    screenshot_status = "pass" if post_build.get("screenshots") else "blocked"
    screenshot_failure = ""
    if post_build.get("screenshot_blocked"):
        try:
            blocked = json.loads(pathlib.Path(str(post_build.get("screenshot_blocked"))).read_text(encoding="utf-8", errors="replace"))
            screenshot_failure = str(blocked.get("failure_reason", ""))
        except Exception:
            screenshot_failure = "unknown"
    video_status = "pass" if post_build.get("video") else "blocked"
    video_failure = ""
    if post_build.get("video_blocked"):
        try:
            blocked = json.loads(pathlib.Path(str(post_build.get("video_blocked"))).read_text(encoding="utf-8", errors="replace"))
            video_failure = str(blocked.get("failure_reason", ""))
        except Exception:
            video_failure = "unknown"
    report = {
        "environment": environment,
        "candidate_dir": str(candidate_dir),
        "npm_test": {
            "status": post_build.get("test_result", {}).get("status", ""),
            "returncode": post_build.get("test_result", {}).get("returncode", None),
        },
        "ui_smoke": post_build.get("ui_smoke", {}),
        "screenshot": {
            "status": screenshot_status,
            "path": (post_build.get("screenshots") or [""])[0] if post_build.get("screenshots") else "",
            "failure_reason": screenshot_failure,
        },
        "video": {
            "status": video_status,
            "path": str(post_build.get("video", "")),
            "failure_reason": video_failure,
        },
        "artifact_integrity": post_build.get("artifact_integrity", {}),
        "verdict": "ASK_USER_REVIEW" if post_build.get("candidate_review_ready") else "NEEDS_REWORK",
        "final_zip_generated": (candidate_dir / "final_project_bundle.zip").exists(),
        "delivery_manifest_generated": (candidate_dir / "delivery_manifest.json").exists(),
    }
    write_json(DEFAULT_REPORT, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", default=str(run_local_pipeline.DEFAULT_CANDIDATE_DIR))
    args = parser.parse_args()
    report = run_benchmark(pathlib.Path(args.candidate_dir).resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report.get("artifact_integrity", {}).get("status") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
