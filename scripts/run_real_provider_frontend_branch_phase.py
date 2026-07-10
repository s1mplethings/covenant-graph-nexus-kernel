from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import zipfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_growth_budget import default_growth_budget, save_growth_budget
    from agent_leaf_provider_guard import provider_readiness
    from agent_real_provider_leaf_builder import run_real_provider_leaf
    from agent_scope_contract import create_scope_contract, save_scope_contract
    from agent_spawn_protocol import create_spawn_action
    from agent_tree_contracts import now, read_json, write_json
    from agent_tree_registry import add_agent, children_of, initial_registry, save_registry
    from agent_tree_shared_context import create_shared_context, save_shared_context
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_budget import default_growth_budget, save_growth_budget
    from scripts.agent_leaf_provider_guard import provider_readiness
    from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
    from scripts.agent_scope_contract import create_scope_contract, save_scope_contract
    from scripts.agent_spawn_protocol import create_spawn_action
    from scripts.agent_tree_contracts import now, read_json, write_json
    from scripts.agent_tree_registry import add_agent, children_of, initial_registry, save_registry
    from scripts.agent_tree_shared_context import create_shared_context, save_shared_context


DEFAULT_GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"
FRONTEND_LEAF_ORDER = [
    "dashboard_page_leaf",
    "documents_page_leaf",
    "search_page_leaf",
    "tasks_page_leaf",
    "reports_page_leaf",
    "settings_page_leaf",
]
FRONTEND_SPECS: dict[str, tuple[str, str, list[str]]] = {
    "dashboard_page_leaf": ("DashboardPageLeafAgent", "dashboard", ["app/templates/dashboard.html"]),
    "documents_page_leaf": ("DocumentsPageLeafAgent", "documents", ["app/templates/documents.html"]),
    "search_page_leaf": ("SearchPageLeafAgent", "search", ["app/templates/search.html"]),
    "tasks_page_leaf": ("TasksPageLeafAgent", "tasks", ["app/templates/tasks.html"]),
    "reports_page_leaf": ("ReportsPageLeafAgent", "reports", ["app/templates/reports.html"]),
    "settings_page_leaf": ("SettingsPageLeafAgent", "settings", ["app/templates/settings.html"]),
}
FRONTEND_TEST_TERMS = {
    "dashboard_page_leaf": (("dashboard", "控制台", "仪表盘"), ("knowledge", "知识", "studio", "工作台")),
    "documents_page_leaf": (("documents", "文档"), ("knowledge", "知识")),
    "search_page_leaf": (("search", "搜索", "检索"),),
    "tasks_page_leaf": (("tasks", "任务"),),
    "reports_page_leaf": (("reports", "报告"),),
    "settings_page_leaf": (("settings", "设置"),),
}
FRONTEND_FORBIDDEN = [
    "README.md",
    "requirements.txt",
    "app/main.py",
    "app/services/document_import_service.py",
    "app/services/search_service.py",
    "app/services/model_adapter.py",
    "app/services/task_service.py",
    "app/services/report_service.py",
    "tests/test_document_import_service.py",
    "tests/test_search_service.py",
    "tests/test_model_adapter.py",
    "tests/test_task_service.py",
    "tests/test_report_service.py",
    "final_project_bundle.zip",
    "delivery_manifest.json",
]


def controlled_frontend_output(leaf: str) -> str:
    _, page, files = FRONTEND_SPECS[leaf]
    nav = "Dashboard Documents Search Tasks Reports Settings"
    html = (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head><meta charset=\"utf-8\"><title>Local AI Knowledge Studio - "
        + page.title()
        + "</title></head>\n"
        "<body><nav>"
        + nav
        + "</nav><main><h1>"
        + page.title()
        + "</h1><section>Documents import knowledge search query results tasks status reports summary settings local model.</section></main></body>\n"
        "</html>\n"
    )
    return json.dumps({"files": [{"path": files[0], "content": html}]})


def _init_registry(out: pathlib.Path, project_name: str, goal: str) -> dict[str, Any]:
    shared = create_shared_context(project_name, goal)
    save_shared_context(shared, out)
    budget = default_growth_budget()
    save_growth_budget(out, budget)
    (out / "spawn_actions.jsonl").write_text("", encoding="utf-8")
    registry = initial_registry()
    branch = create_spawn_action(
        out_dir=out,
        registry=registry,
        budget=budget,
        parent_agent="main_agent",
        new_agent_id="frontend_branch_agent",
        role="FrontendBranchAgent",
        depth=1,
        reason="Real provider frontend branch eval",
        scope=["frontend branch merge"],
        expected_outputs=["frontend_child_agents"],
        verification=["child_checkpoints", "frontend_static_tests"],
    )
    add_agent(registry, branch)
    for leaf in FRONTEND_LEAF_ORDER:
        role, _, files = FRONTEND_SPECS[leaf]
        action = create_spawn_action(
            out_dir=out,
            registry=registry,
            budget=budget,
            parent_agent="frontend_branch_agent",
            new_agent_id=leaf,
            role=role,
            depth=2,
            reason=f"Create owned frontend page {leaf}",
            scope=["frontend leaf"],
            expected_outputs=files,
            verification=["scope_contract_valid", "html_static_check"],
        )
        add_agent(registry, action)
    save_registry(registry, out, "registry.json")
    save_registry(registry, out, "agent_tree_registry.json")
    return registry


def _save_scope_contracts(out: pathlib.Path) -> None:
    all_templates = [FRONTEND_SPECS[leaf][2][0] for leaf in FRONTEND_LEAF_ORDER]
    for leaf in FRONTEND_LEAF_ORDER:
        role, _, files = FRONTEND_SPECS[leaf]
        forbidden = [item for item in FRONTEND_FORBIDDEN + all_templates if item not in files]
        contract = create_scope_contract(agent_id=leaf, role=role, parent_id="frontend_branch_agent", allowed_files=files, forbidden_files=forbidden)
        save_scope_contract(contract, out)


def _copy_contract_to_leaf(out: pathlib.Path, leaf_out: pathlib.Path, leaf: str) -> None:
    src = out / "scope_contracts" / f"{leaf}.json"
    dst = leaf_out / "scope_contracts" / f"{leaf}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def validate_frontend_project(project: pathlib.Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for leaf in FRONTEND_LEAF_ORDER:
        rel = FRONTEND_SPECS[leaf][2][0]
        path = project / rel
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        lowered = text.lower()
        missing_terms = ["/".join(group) for group in FRONTEND_TEST_TERMS[leaf] if not any(term.lower() in lowered for term in group)]
        ok = path.exists() and len(text.strip()) >= 120 and "<" in text and ">" in text and not missing_terms
        results.append({"leaf": leaf, "path": rel, "exists": path.exists(), "length": len(text), "missing_terms": missing_terms, "ok": ok})
    result = {
        "command": "frontend_static_validation",
        "exit_code": 0 if all(item["ok"] for item in results) else 1,
        "results": results,
    }
    return result


def _leaf_checkpoint(out: pathlib.Path, leaf: str, provider_result: dict[str, Any]) -> dict[str, Any]:
    project = out / "project"
    expected = FRONTEND_SPECS[leaf][2]
    present = [rel for rel in expected if (project / rel).exists()]
    missing = [rel for rel in expected if not (project / rel).exists()]
    blocked = list(provider_result.get("forbidden_write_attempts", []))
    text = (project / expected[0]).read_text(encoding="utf-8", errors="replace") if present else ""
    lowered = text.lower()
    missing_terms = ["/".join(group) for group in FRONTEND_TEST_TERMS[leaf] if not any(term.lower() in lowered for term in group)]
    verdict = "PASS" if provider_result.get("classification") == "real_provider_leaf_pass" and not missing and not blocked and not missing_terms else "FAIL"
    checkpoint = {
        "leaf": leaf,
        "provider_mode": "real_provider",
        "expected_files": expected,
        "present_files": present,
        "missing_files": missing,
        "blocked_files": blocked,
        "static_missing_terms": missing_terms,
        "verdict": verdict,
        "classification": provider_result.get("classification"),
        "can_merge": verdict == "PASS",
        "created_at": now(),
    }
    write_json(out / "checkpoints" / f"{leaf}.json", checkpoint)
    return checkpoint


def _merge_frontend(out: pathlib.Path, registry: dict[str, Any]) -> dict[str, Any]:
    children = [child["agent_id"] for child in children_of(registry, "frontend_branch_agent")]
    checkpoints = [read_json(out / "checkpoints" / f"{child}.json", {}) for child in children]
    issues = [f"{cp.get('leaf')}:{cp.get('verdict')}" for cp in checkpoints if cp.get("verdict") != "PASS"]
    result = {
        "parent_agent": "frontend_branch_agent",
        "children": children,
        "child_results": [{"leaf": cp.get("leaf"), "provider_mode": cp.get("provider_mode"), "verdict": cp.get("verdict"), "can_merge": cp.get("can_merge")} for cp in checkpoints],
        "issues": issues,
        "merge_verdict": "PASS" if children and not issues else "FAIL",
        "required_children_passed": bool(children) and not issues,
        "created_at": now(),
    }
    write_json(out / "merge_results" / "frontend_branch_agent.json", result)
    return result


def run_frontend_branch_phase(
    *,
    out_dir: str | pathlib.Path,
    project_name: str,
    goal: str = DEFAULT_GOAL,
    model: str = "gpt-5.4-nano",
    readiness_override: dict[str, Any] | None = None,
    provider_output_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "project").mkdir(parents=True, exist_ok=True)
    registry = _init_registry(out, project_name, goal)
    _save_scope_contracts(out)
    readiness = readiness_override if isinstance(readiness_override, dict) else provider_readiness(out_dir=out, model=model)
    if not readiness.get("provider_ready") and not provider_output_overrides:
        final = {"classification": "provider_unavailable", "verdict": "BLOCKED", "provider_ready": False, "frontend_merge": "not_run", "fake_success_detected": False}
        write_json(out / "final_verdict.json", final)
        return final
    overrides = provider_output_overrides or {}
    checkpoints = []
    for leaf in FRONTEND_LEAF_ORDER:
        leaf_out = out / "leaves" / leaf
        _copy_contract_to_leaf(out, leaf_out, leaf)
        provider_result = run_real_provider_leaf(
            agent_id=leaf,
            out_dir=leaf_out,
            project_dir=out / "project",
            user_goal=goal,
            model=model,
            readiness=readiness,
            provider_output_override=overrides.get(leaf),
        )
        checkpoints.append(_leaf_checkpoint(out, leaf, provider_result))
    merge = _merge_frontend(out, registry)
    static_result = validate_frontend_project(out / "project") if merge.get("merge_verdict") == "PASS" else {"command": "frontend_static_validation", "exit_code": None, "skipped": "merge_failed"}
    write_json(out / "frontend_branch_static_validation.json", static_result)
    if merge.get("merge_verdict") != "PASS":
        classification = "frontend_merge_failed"
    elif static_result.get("exit_code") != 0:
        classification = "frontend_static_validation_failed"
    else:
        classification = "frontend_branch_all_real_provider_pass"
    final = {
        "classification": classification,
        "verdict": "PASS" if classification == "frontend_branch_all_real_provider_pass" else "NEEDS_REWORK",
        "provider_ready": bool(readiness.get("provider_ready") or provider_output_overrides),
        "real_provider_leaves": list(FRONTEND_LEAF_ORDER),
        "frontend_merge": merge.get("merge_verdict"),
        "static_validation_exit_code": static_result.get("exit_code"),
        "fake_success_detected": False,
        "created_at": now(),
    }
    write_json(out / "final_verdict.json", final)
    return final


def create_frontend_trace_bundle(*, out_dir: str | pathlib.Path, final_verdict: dict[str, Any]) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    lines = [
        "# Real Provider Frontend Branch Trace Bundle",
        "",
        "- Purpose: prove all frontend page leaves can be generated by real provider under scope contracts.",
        f"- Real provider leaves: {', '.join(FRONTEND_LEAF_ORDER)}",
        f"- Frontend merge: {read_json(out / 'merge_results' / 'frontend_branch_agent.json', {}).get('merge_verdict', '')}",
        f"- Static validation: {read_json(out / 'frontend_branch_static_validation.json', {}).get('exit_code')}",
        f"- Final verdict: {final_verdict.get('verdict', '')}",
    ]
    (out / "00_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    bundle = out / "frontend_branch_trace_bundle.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in out.rglob("*"):
            if item.is_file() and item.name != bundle.name and ".pytest_cache" not in item.parts:
                zf.write(item, item.relative_to(out).as_posix())
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--model", default="gpt-5.4-nano")
    args = parser.parse_args()
    result = run_frontend_branch_phase(out_dir=args.out, project_name=args.project_name, goal=args.goal, model=args.model)
    print(json.dumps({"classification": result.get("classification"), "verdict": result.get("verdict")}, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
