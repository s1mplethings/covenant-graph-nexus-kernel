#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


GUI_KEYWORDS = ("gui", "界面", "窗口", "图片", "image", "截图", "screenshot", "visual")
DATA_KEYWORDS = ("excel", "csv", "数据", "表格", "spreadsheet")


def split_text(value: str | None) -> list[str]:
    if not value:
        return []
    parts = []
    for chunk in value.replace("，", ",").replace("、", ",").replace("；", ",").split(","):
        item = chunk.strip()
        if item:
            parts.append(item)
    return parts or [value.strip()]


def contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_roles(goal: str, input_text: str, output_text: str) -> list[str]:
    combined = " ".join([goal, input_text, output_text])
    roles = [
        "Product Lead",
        "Solution Architect",
        "Implementation Engineer",
        "QA Engineer",
        "Delivery Manager",
    ]
    if contains_keyword(combined, GUI_KEYWORDS):
        roles.extend(["UX Designer", "Media Pipeline Engineer"])
    if contains_keyword(combined, DATA_KEYWORDS):
        roles.append("Data Engineer")
    return unique(roles)


def build_required_outputs(output_text: str, has_gui_or_image: bool) -> list[str]:
    outputs = split_text(output_text)
    defaults = [
        "runnable_project",
        "README",
        "test_data",
        "test_report",
        "delivery_bundle",
    ]
    if has_gui_or_image:
        defaults.extend(["screenshots", "visual_evidence"])
    return unique(outputs + defaults)


def build_product_studio_run(goal: str, input_text: str, output_text: str, constraints: list[str]) -> dict[str, Any]:
    combined = " ".join([goal, input_text, output_text])
    has_gui_or_image = contains_keyword(combined, GUI_KEYWORDS)
    roles = build_roles(goal, input_text, output_text)
    required_outputs = build_required_outputs(output_text, has_gui_or_image)
    known_limits = [
        "This run only generates a Product Studio run artifact.",
        "No real project has been generated yet.",
        "No GUI has been launched yet.",
        "No real screenshot has been captured yet.",
    ]

    return {
        "customer_intent": {
            "kind": "customer_intent",
            "goal": goal,
            "input_expectation": split_text(input_text),
            "output_expectation": split_text(output_text),
            "constraints": constraints,
            "raw_request": {
                "goal": goal,
                "input": input_text,
                "output": output_text,
                "constraints": constraints,
            },
        },
        "output_contract": {
            "kind": "output_contract",
            "required_outputs": required_outputs,
            "runtime_target": "local GUI" if has_gui_or_image else "local runnable project",
            "delivery_format": "compact product_studio_run artifact plus future delivery bundle",
        },
        "virtual_team_roster": {
            "kind": "virtual_team_roster",
            "lead_agent": "Lead Agent",
            "specialist_agents": roles,
            "dynamic_role_reasoning": "Lead Agent selected specialist agents from the user's goal, input, and output requirements.",
        },
        "product_story": {
            "kind": "product_story",
            "product_name": goal[:80],
            "main_problem": f"User needs a delivered project for: {goal}",
            "acceptance_implications": [
                "Output contract must be preserved.",
                "Test data and test_report are required before PASS.",
                "delivery_bundle is required before PASS.",
                "GUI or visual work requires screenshots or visual_evidence before PASS.",
            ],
        },
        "mvp_scope": {
            "kind": "mvp_scope",
            "must_have": [
                "Preserve customer_intent and output_contract.",
                "Create an executable build plan for the requested project.",
                "Collect test evidence before PASS.",
                "Package delivery bundle before PASS.",
            ],
            "deferred_items": [
                "Real project generation.",
                "Runner execution.",
                "QA evidence capture.",
            ],
        },
        "technical_plan": {
            "kind": "technical_plan",
            "runtime_target": "local GUI" if has_gui_or_image else "local project",
            "technology_choices": [
                "Use local tooling only in this skeleton phase.",
                "Do not call network or provider.",
            ],
        },
        "build_plan": {
            "kind": "build_plan",
            "tasks": [
                "Hand off compact product_studio_run to Agent Build.",
                "Generate real project files in a later phase.",
                "Run or attempt validation in a later phase.",
                "Collect QA evidence and delivery bundle in a later phase.",
            ],
        },
        "test_evidence": {
            "kind": "test_evidence",
            "status": "PARTIAL",
            "test_data": [],
            "test_results": [
                "Product Studio run artifact generated.",
                "No real tests were run in this skeleton phase.",
            ],
            "visual_evidence": [] if has_gui_or_image else ["Not required unless visual output is requested."],
        },
        "delivery_bundle": {
            "kind": "delivery_bundle",
            "status": "PARTIAL",
            "included_evidence": [
                "product_studio_run.json",
                "run_summary.md",
            ],
            "known_limits": known_limits,
            "next_step": "Proceed to Agent Build / Runner / QA Evidence.",
        },
    }


def write_summary(path: pathlib.Path, run_doc: dict[str, Any]) -> None:
    roles = run_doc["virtual_team_roster"]["specialist_agents"]
    outputs = run_doc["output_contract"]["required_outputs"]
    goal = run_doc["customer_intent"]["goal"]
    summary = "\n".join(
        [
            "# Product Studio Run Summary",
            "",
            f"识别到的项目目标: {goal}",
            "",
            "创建的虚拟角色:",
            *[f"- {role}" for role in ["Lead Agent"] + roles],
            "",
            "预期输出:",
            *[f"- {item}" for item in outputs],
            "",
            "当前状态: PARTIAL",
            "",
            "原因: 本轮只生成 Product Studio run artifact，尚未生成真实项目、运行 GUI、执行测试或捕获真实截图。",
            "",
            "下一步: 进入 Agent Build / Runner / QA Evidence。",
            "",
        ]
    )
    path.write_text(summary, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a minimal compact Product Studio run artifact.")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--input", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    run_doc = build_product_studio_run(args.goal, args.input, args.output, args.constraint)

    run_path = out_dir / "product_studio_run.json"
    summary_path = out_dir / "run_summary.md"
    run_path.write_text(json.dumps(run_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_summary(summary_path, run_doc)
    print(f"Wrote {run_path}")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
