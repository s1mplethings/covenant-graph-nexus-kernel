#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

import compose_local_pipeline
import requirement_blueprint
import run_local_pipeline

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "examples" / "test_results" / "customer_generation_result.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", str(text or "").strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "generated-project"


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def detect_missing(requirement: str) -> list[dict[str, str]]:
    text = str(requirement or "").strip().lower()
    checks = [
        (
            "target_user",
            "这个项目主要给谁用？",
            ("用户", "客户", "客服", "管理员", "团队", "员工", "商家", "学生", "user", "customer", "admin", "team"),
        ),
        (
            "core_features",
            "必须包含哪些核心功能？",
            ("新增", "编辑", "删除", "搜索", "统计", "看板", "登录", "导出", "通知", "create", "edit", "delete", "search"),
        ),
        (
            "data_storage",
            "数据要本地保存、文件保存，还是接数据库？",
            ("本地", "local", "sqlite", "数据库", "db", "文件", "storage", "保存"),
        ),
        (
            "acceptance",
            "你希望我用什么方式证明效果？",
            ("测试", "验收", "效果", "截图", "报告", "test", "report", "验证"),
        ),
    ]
    missing: list[dict[str, str]] = []
    for key, question, terms in checks:
        if not any(term in text for term in terms):
            missing.append({"field": key, "question": question})
    return missing


def default_answer(field: str, requirement: str = "") -> str:
    lowered = str(requirement or "").lower()
    if field == "target_user" and any(term in lowered for term in ("主播", "游戏", "高光", "直播", "streamer", "highlight")):
        return "目标用户为游戏主播、内容剪辑和直播运营人员。"
    defaults = {
        "target_user": "目标用户为需要日常管理业务事项的本地团队成员。",
        "core_features": "核心功能包含新增、编辑状态、删除、搜索/筛选、基础统计和本地保存。",
        "data_storage": "默认使用浏览器本地存储，后续可升级为文件或数据库。",
        "acceptance": "输出项目蓝图、生成过程、测试图、效果报告，并生成可打开的本地项目。",
    }
    return defaults.get(field, "使用保守默认值继续生成。")


def collect_answers(requirement: str, *, assume_defaults: bool) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    questions = detect_missing(requirement)
    answers: list[dict[str, str]] = []
    for row in questions:
        if assume_defaults:
            answer = default_answer(row["field"], requirement)
        else:
            print(f"客服问题：{row['question']}")
            answer = input("你的回答：").strip() or default_answer(row["field"], requirement)
        answers.append({"field": row["field"], "question": row["question"], "answer": answer})
    return questions, answers


def build_enriched_goal(requirement: str, answers: list[dict[str, str]], blueprint: dict[str, Any] | None = None) -> str:
    parts = [str(requirement or "").strip()]
    if answers:
        parts.append("客服澄清信息：")
        for row in answers:
            parts.append(f"- {row['field']}: {row['answer']}")
    if blueprint:
        parts.append("需求蓝图摘要：")
        requirement_spec = blueprint.get("requirement_spec", {})
        io_contract = blueprint.get("io_contract", {})
        feature_spec = blueprint.get("feature_spec", {})
        tech_decisions = blueprint.get("tech_decisions", {})
        project_type = requirement_spec.get("project_type", {}).get("value", "")
        output_types = io_contract.get("output_contract", {}).get("output_types", [])
        features = [item.get("name", "") for item in feature_spec.get("features", [])[:8]]
        decisions = [
            f"{item.get('capability')}: {item.get('selected_solution')}"
            for item in tech_decisions.get("tech_decisions", [])[:8]
        ]
        parts.append(f"- project_type: {project_type}")
        parts.append(f"- output_contract: {', '.join(str(item) for item in output_types)}")
        parts.append(f"- feature_modules: {', '.join(str(item) for item in features if item)}")
        parts.append(f"- tech_decisions: {', '.join(str(item) for item in decisions if item)}")
    parts.append("生成要求：输出真实项目文件、项目蓝图、生成过程、测试图、效果报告和 runtime_result。")
    return "\n".join(part for part in parts if part)


def run_generation(args: argparse.Namespace) -> dict[str, Any]:
    requirement = str(args.requirement or "").strip()
    if not requirement:
        raise SystemExit("--requirement is required")
    _, answers = collect_answers(requirement, assume_defaults=args.assume_defaults)
    project_slug = args.project_slug or slug(requirement)[:60]
    blueprint = requirement_blueprint.build_requirement_blueprint(
        requirement,
        answers,
        assume_defaults=bool(args.assume_defaults or answers),
    )
    enriched_goal = build_enriched_goal(requirement, answers, blueprint)
    composition_path = ROOT / "examples" / "test_results" / f"{project_slug}_composition.json"
    execution_path = ROOT / "examples" / "test_results" / f"{project_slug}_execution.json"
    requirement_blueprint_path = ROOT / "examples" / "test_results" / f"{project_slug}_requirement_blueprint.json"
    out_dir = ROOT / "generated" / project_slug
    run_dir = ROOT / "examples" / "runtime_runs" / project_slug

    composition = compose_local_pipeline.compose(
        enriched_goal,
        allow_network=bool(args.allow_network),
        allow_provider=bool(args.allow_provider),
        send_telegram=bool(args.send_telegram),
    )
    composition["requirement_blueprint"] = blueprint
    composition["requirement_blueprint_ref"] = str(requirement_blueprint_path)
    write_json(composition_path, composition)
    write_json(requirement_blueprint_path, blueprint)

    ns = argparse.Namespace(
        goal=enriched_goal,
        plan=str(composition_path),
        out_dir=str(out_dir),
        run_dir=str(run_dir),
        result_path=str(execution_path),
        allow_network=bool(args.allow_network),
        allow_provider=bool(args.allow_provider),
        use_api=bool(args.use_api),
        send_telegram=bool(args.send_telegram),
        telegram_chat_id=str(args.telegram_chat_id or ""),
        model=str(args.model),
        timeout=int(args.timeout),
        json=False,
    )
    execution = run_local_pipeline.execute(ns)

    effect_report_path = run_dir / "artifacts" / "effect_report.json"
    test_graph_path = run_dir / "artifacts" / "test_graph.mmd"
    result = {
        "kind": "CustomerProjectGenerationResult",
        "created_at": now(),
        "requirement": requirement,
        "customer_service": {
            "questions": [row["question"] for row in answers],
            "answers": answers,
            "mode": "defaults" if args.assume_defaults else "interactive",
        },
        "requirement_blueprint_path": str(requirement_blueprint_path),
        "requirement_blueprint_status": blueprint.get("status", "unknown"),
        "composition_path": str(composition_path),
        "execution_path": str(execution_path),
        "project_dir": str(out_dir),
        "runtime_dir": str(run_dir),
        "effect_report_path": str(effect_report_path),
        "test_graph_path": str(test_graph_path),
        "status": execution.get("payload", {}).get("status", "unknown"),
    }
    write_json(pathlib.Path(args.result_path).resolve(), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.set_defaults(allow_network=True, allow_provider=True, use_api=True)
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--project-slug", default="")
    parser.add_argument("--assume-defaults", action="store_true", help="Use conservative customer-service defaults for missing answers.")
    parser.add_argument("--allow-network", dest="allow_network", action="store_true", help="Allow network routes. Enabled by default for mixed API mode.")
    parser.add_argument("--no-network", dest="allow_network", action="store_false", help="Disable network routes for a fully local run.")
    parser.add_argument("--allow-provider", dest="allow_provider", action="store_true", help="Allow provider/API calls. Enabled by default for mixed API mode.")
    parser.add_argument("--no-provider", dest="allow_provider", action="store_false", help="Disable provider/API calls.")
    parser.add_argument("--use-api", dest="use_api", action="store_true", help="Use API for provider-side generation. Enabled by default.")
    parser.add_argument("--no-api", dest="use_api", action="store_false", help="Use the local static generator instead of API generation.")
    parser.add_argument("--send-telegram", action="store_true")
    parser.add_argument("--telegram-chat-id", default="")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--result-path", default=str(DEFAULT_RESULT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_generation(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CUSTOMER_PROJECT_GENERATION: {str(result['status']).upper()}")
        print(f"project_dir={result['project_dir']}")
        print(f"effect_report={result['effect_report_path']}")
        print(f"test_graph={result['test_graph_path']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
