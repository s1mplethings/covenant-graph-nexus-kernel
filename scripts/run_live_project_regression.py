#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import provider_resilience


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "live_project_regression_report.json"
PROJECTS = [
    "独立游戏任务与 Bug 工作台",
    "CSV Dashboard",
    "Markdown 笔记搜索器",
    "库存管理器",
    "本地 API + 前端 dashboard",
]


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def planned_result(project_name: str, reason: str) -> dict[str, Any]:
    return {
        "project_name": project_name,
        "candidate": "not_run",
        "post_build": "not_run",
        "screenshot": "not_run",
        "video": "not_run",
        "final_promotion": "not_run",
        "product_acceptance": "not_run",
        "verdict": reason,
    }


def run_regression(*, repeats: int = 10, provider_config: dict[str, Any] | None = None, allow_live: bool = False) -> dict[str, Any]:
    provider = provider_resilience.provider_preflight(provider_config, goal="multi project live regression")
    if not provider.get("metadata", {}).get("live_generation_allowed") or not allow_live:
        reason = "PROVIDER_BLOCKED_OR_LIVE_DISABLED" if not allow_live else "PROVIDER_BLOCKED"
        runs = [planned_result(PROJECTS[index % len(PROJECTS)], reason) for index in range(repeats)]
        return {
            "status": "skipped",
            "provider": provider.get("metadata", {}),
            "target_runs": repeats,
            "runs": runs,
            "stats": {"flaky_stage": {}, "provider_errors": [], "PASS_FINAL": 0, "DELIVER_WITH_WARNINGS": 0, "ASK_USER_REVIEW": 0, "NEEDS_REWORK": 0},
        }
    runs = [planned_result(PROJECTS[index % len(PROJECTS)], "LIVE_RUNNER_NOT_CONNECTED_IN_GUARD") for index in range(repeats)]
    return {
        "status": "planned",
        "provider": provider.get("metadata", {}),
        "target_runs": repeats,
        "runs": runs,
        "stats": {"flaky_stage": {}, "provider_errors": [], "PASS_FINAL": 0, "DELIVER_WITH_WARNINGS": 0, "ASK_USER_REVIEW": 0, "NEEDS_REWORK": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    report = run_regression(repeats=max(1, args.repeats), allow_live=args.allow_live)
    write_json(pathlib.Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
