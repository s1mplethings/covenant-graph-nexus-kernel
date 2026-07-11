#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
from typing import Any

import requirement_acceptance_check
import requirement_decision_lane


ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
BENCHMARK_CASES = [
    "我想要一个本地视频素材处理工具",
    "我想做一个独立游戏团队管理工具",
    "我想做一个本地资料整理和研究工作台",
]


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def case_score(run_dir: pathlib.Path, result: dict[str, Any]) -> dict[str, Any]:
    req_dir = run_dir / "requirement_decision"
    candidates = requirement_decision_lane.read_json(req_dir / "candidate_requirements.json").get("candidates", [])
    selected = requirement_decision_lane.read_json(req_dir / "selected_requirement.json")
    contract = requirement_decision_lane.read_json(req_dir / "acceptance_contract.json")
    rejected = (req_dir / "rejected_requirements.md").exists() and (req_dir / "rejected_requirements.md").stat().st_size > 0
    mvp = (req_dir / "mvp_scope.md").exists() and "Must Do" in (req_dir / "mvp_scope.md").read_text(encoding="utf-8", errors="replace")
    non_goals = (req_dir / "non_goals.md").exists() and (req_dir / "non_goals.md").stat().st_size > 0
    summary = (req_dir / "customer_decision_summary.md").exists() and (req_dir / "customer_decision_summary.md").stat().st_size > 0
    layers = requirement_acceptance_check.evaluate_layers(run_dir=run_dir)
    checks = {
        "goal_understanding": bool((req_dir / "customer_goal_brief.md").exists()),
        "multi_direction": isinstance(candidates, list) and len(candidates) >= 3,
        "selection_reason": bool(selected.get("why_this_requirement")),
        "rejected_requirements": rejected,
        "mvp_scope": mvp,
        "non_goals": non_goals,
        "acceptance_contract": contract.get("contract_id") == "requirement_acceptance_contract_v1",
        "customer_summary": summary,
        "avoids_direct_code": not any((run_dir / "requirement_decision").rglob("*.py")),
        "layered_status": bool(layers.get("requirement_decision_status")),
    }
    score = 0
    score += 15 if checks["goal_understanding"] else 0
    score += 15 if checks["multi_direction"] else 0
    score += 20 if checks["selection_reason"] else 0
    score += 15 if checks["mvp_scope"] else 0
    score += 10 if checks["non_goals"] else 0
    score += 10 if checks["rejected_requirements"] else 0
    score += 10 if checks["acceptance_contract"] else 0
    score += 5 if checks["avoids_direct_code"] else 0
    verdict = "PASS" if score >= 85 else ("PARTIAL" if score >= 65 else "FAIL")
    return {
        "goal": result.get("raw_goal", ""),
        "run_dir": str(run_dir),
        "score": score,
        "verdict": verdict,
        "checks": checks,
        "status_layers": {
            "requirement_decision_status": layers.get("requirement_decision_status"),
            "product_contract_status": layers.get("product_contract_status"),
            "implementation_status": layers.get("implementation_status"),
            "delivery_status": layers.get("delivery_status"),
            "overall_status": layers.get("overall_status"),
        },
    }


def run_benchmark() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for index, goal in enumerate(BENCHMARK_CASES, start=1):
        run_dir = ARTIFACTS_DIR / "requirement_decision_benchmark_runs" / f"case_{index}"
        result = requirement_decision_lane.run_requirement_decision(goal, run_dir)
        cases.append(case_score(run_dir, result))
    average = round(sum(case["score"] for case in cases) / len(cases))
    verdict = "PASS" if average >= 85 else ("PARTIAL" if average >= 65 else "FAIL")
    return {
        "benchmark": "requirement_decision_benchmark",
        "score": average,
        "verdict": verdict,
        "cases": cases,
    }


def summary_text(report: dict[str, Any]) -> str:
    lines = [
        "# Requirement Decision Benchmark Summary",
        "",
        f"- score: `{report['score']}`",
        f"- verdict: `{report['verdict']}`",
        "",
    ]
    for case in report.get("cases", []):
        lines.extend(
            [
                f"## {case['goal']}",
                "",
                f"- score: `{case['score']}`",
                f"- verdict: `{case['verdict']}`",
                f"- requirement_decision_status: `{case['status_layers']['requirement_decision_status']}`",
                f"- delivery_status: `{case['status_layers']['delivery_status']}`",
                f"- run_dir: `{case['run_dir']}`",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    report = run_benchmark()
    write_json(ARTIFACTS_DIR / "requirement_decision_benchmark.json", report)
    write_text(ARTIFACTS_DIR / "requirement_decision_benchmark_summary.md", summary_text(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] in {"PASS", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
