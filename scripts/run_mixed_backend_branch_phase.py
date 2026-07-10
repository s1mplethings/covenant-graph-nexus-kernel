from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_growth_budget import default_growth_budget, save_growth_budget
    from agent_leaf_provider_guard import provider_readiness
    from agent_real_provider_leaf_builder import run_real_provider_leaf
    from agent_scope_contract import create_scope_contract, save_scope_contract
    from agent_spawn_protocol import create_spawn_action
    from agent_tree_contracts import append_jsonl, now, read_json, write_json
    from agent_tree_registry import add_agent, children_of, initial_registry, save_registry
    from agent_tree_shared_context import create_shared_context, save_shared_context
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_budget import default_growth_budget, save_growth_budget
    from scripts.agent_leaf_provider_guard import provider_readiness
    from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
    from scripts.agent_scope_contract import create_scope_contract, save_scope_contract
    from scripts.agent_spawn_protocol import create_spawn_action
    from scripts.agent_tree_contracts import append_jsonl, now, read_json, write_json
    from scripts.agent_tree_registry import add_agent, children_of, initial_registry, save_registry
    from scripts.agent_tree_shared_context import create_shared_context, save_shared_context


DEFAULT_GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"
BACKEND_LEAF_ORDER = ["document_import_leaf", "search_service_leaf", "model_adapter_leaf", "task_service_leaf", "report_service_leaf"]
BACKEND_TESTS = [
    "tests/test_document_import_service.py",
    "tests/test_search_service.py",
    "tests/test_model_adapter.py",
    "tests/test_task_service.py",
    "tests/test_report_service.py",
]
LEAF_SPECS: dict[str, tuple[str, list[str]]] = {
    "document_import_leaf": ("DocumentImportLeafAgent", ["app/services/document_import_service.py", "tests/test_document_import_service.py"]),
    "search_service_leaf": ("SearchServiceLeafAgent", ["app/services/search_service.py", "tests/test_search_service.py"]),
    "model_adapter_leaf": ("ModelAdapterLeafAgent", ["app/services/model_adapter.py", "tests/test_model_adapter.py"]),
    "task_service_leaf": ("TaskServiceLeafAgent", ["app/services/task_service.py", "tests/test_task_service.py"]),
    "report_service_leaf": ("ReportServiceLeafAgent", ["app/services/report_service.py", "tests/test_report_service.py"]),
}
REAL_LEAF_FORBIDDEN = [
    "README.md",
    "requirements.txt",
    "app/main.py",
    "app/services/document_import_service.py",
    "app/services/model_adapter.py",
    "app/services/task_service.py",
    "app/services/report_service.py",
    "app/templates/dashboard.html",
    "app/templates/documents.html",
    "app/templates/search.html",
    "app/templates/tasks.html",
    "app/templates/reports.html",
    "app/templates/settings.html",
    "final_project_bundle.zip",
    "delivery_manifest.json",
]


def _write(project: pathlib.Path, rel: str, text: str) -> None:
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _controlled_content(leaf: str, rel: str) -> str:
    if rel.endswith("test_document_import_service.py"):
        return "from app.services.document_import_service import import_document\n\n\ndef test_import_document_records_title():\n    assert import_document('Guide', 'Knowledge')['title'] == 'Guide'\n"
    if rel.endswith("test_search_service.py"):
        return "from app.services.search_service import search_documents\n\n\ndef test_search_documents_finds_content():\n    docs = [{'title': 'A', 'content': 'local knowledge'}]\n    assert search_documents(docs, 'knowledge')\n"
    if rel.endswith("test_model_adapter.py"):
        return "from app.services.model_adapter import adapter_status\n\n\ndef test_missing_model_is_documented():\n    assert 'missing model' in adapter_status({})['limit']\n"
    if rel.endswith("test_task_service.py"):
        return "from app.services.task_service import create_task\n\n\ndef test_create_task_open_status():\n    assert create_task('Review')['status'] == 'open'\n"
    if rel.endswith("test_report_service.py"):
        return "from app.services.report_service import build_report\n\n\ndef test_build_report_counts_inputs():\n    assert build_report([{}], [{}, {}])['task_count'] == 2\n"
    if rel.endswith("document_import_service.py"):
        return (
            "from __future__ import annotations\n\n"
            "def import_document(title: str, content: str) -> dict:\n"
            "    return {'id': 1, 'title': title, 'content': content, 'status': 'imported'}\n"
        )
    if rel.endswith("search_service.py"):
        return (
            "from __future__ import annotations\n\n"
            "def search_documents(documents: list[dict], query: str) -> list[dict]:\n"
            "    q = str(query or '').lower()\n"
            "    return [doc for doc in documents if q in str(doc.get('title', '')).lower() or q in str(doc.get('content', '')).lower()]\n"
        )
    if rel.endswith("model_adapter.py"):
        return (
            "from __future__ import annotations\n\n"
            "def adapter_status(config: dict | None = None) -> dict:\n"
            "    config = config or {}\n"
            "    endpoint = config.get('LOCAL_MODEL_ENDPOINT') or config.get('MODEL_PATH') or ''\n"
            "    return {'configured': bool(endpoint), 'limit': '' if endpoint else 'missing model file or endpoint; cannot claim real inference'}\n"
        )
    if rel.endswith("task_service.py"):
        return "from __future__ import annotations\n\n\ndef create_task(title: str) -> dict:\n    return {'id': 1, 'title': title, 'status': 'open'}\n"
    if rel.endswith("report_service.py"):
        return "from __future__ import annotations\n\n\ndef build_report(documents: list[dict], tasks: list[dict]) -> dict:\n    return {'document_count': len(documents), 'task_count': len(tasks), 'sections': ['summary', 'tasks', 'next steps']}\n"
    return f"# controlled file for {leaf}\n"


def _prepare_package_markers(project: pathlib.Path) -> list[str]:
    written: list[str] = []
    for rel in ("app/__init__.py", "app/services/__init__.py"):
        target = project / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
            written.append(rel)
    return written


def _run_pytest(project: pathlib.Path, tests: list[str], *, timeout: int = 90) -> dict[str, Any]:
    _prepare_package_markers(project)
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    python_paths = [str(project.resolve())]
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    test_args = [str((project / test).resolve()) for test in tests]
    proc = subprocess.run([sys.executable, "-m", "pytest", *test_args, "--rootdir", str(project.resolve()), "-q"], cwd=project, capture_output=True, text=True, timeout=timeout, env=env)
    return {
        "command": "python -m pytest " + " ".join(tests) + " -q",
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def _init_registry(out: pathlib.Path, project_name: str, goal: str) -> dict[str, Any]:
    shared = create_shared_context(project_name, goal)
    save_shared_context(shared, out)
    budget = default_growth_budget()
    save_growth_budget(out, budget)
    (out / "spawn_actions.jsonl").write_text("", encoding="utf-8")
    registry = initial_registry()
    backend = create_spawn_action(
        out_dir=out,
        registry=registry,
        budget=budget,
        parent_agent="main_agent",
        new_agent_id="backend_branch_agent",
        role="BackendBranchAgent",
        depth=1,
        reason="Mixed backend branch integration eval",
        scope=["backend branch merge"],
        expected_outputs=["backend_branch_plan.json", "backend_child_agents"],
        verification=["child_checkpoints", "backend_tests"],
    )
    add_agent(registry, backend)
    for leaf_id in BACKEND_LEAF_ORDER:
        role, files = LEAF_SPECS[leaf_id]
        action = create_spawn_action(
            out_dir=out,
            registry=registry,
            budget=budget,
            parent_agent="backend_branch_agent",
            new_agent_id=leaf_id,
            role=role,
            depth=2,
            reason=f"Create backend unit {leaf_id}",
            scope=["backend leaf"],
            expected_outputs=files,
            verification=["scope_contract_valid", "leaf_test"],
        )
        add_agent(registry, action)
    save_registry(registry, out, "registry.json")
    save_registry(registry, out, "agent_tree_registry.json")
    return registry


def _save_scope_contracts(out: pathlib.Path) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for leaf_id in BACKEND_LEAF_ORDER:
        role, files = LEAF_SPECS[leaf_id]
        forbidden = [item for item in REAL_LEAF_FORBIDDEN if item not in files]
        contract = create_scope_contract(agent_id=leaf_id, role=role, parent_id="backend_branch_agent", allowed_files=files, forbidden_files=forbidden)
        save_scope_contract(contract, out)
        contracts[leaf_id] = contract
    return contracts


def _copy_contract_to_leaf(out: pathlib.Path, leaf_out: pathlib.Path, leaf: str) -> None:
    src = out / "scope_contracts" / f"{leaf}.json"
    dst = leaf_out / "scope_contracts" / f"{leaf}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _leaf_checkpoint(
    *,
    out: pathlib.Path,
    leaf: str,
    provider_mode: str,
    expected_files: list[str],
    blocked_files: list[str],
    test_result: dict[str, Any],
    verdict: str,
    classification: str,
) -> dict[str, Any]:
    project = out / "project"
    present = [rel for rel in expected_files if (project / rel).exists()]
    missing = [rel for rel in expected_files if not (project / rel).exists()]
    checkpoint = {
        "leaf": leaf,
        "provider_mode": provider_mode,
        "expected_files": expected_files,
        "present_files": present,
        "missing_files": missing,
        "blocked_files": list(blocked_files),
        "test_command": test_result.get("command", ""),
        "test_exit_code": test_result.get("exit_code"),
        "verdict": verdict,
        "classification": classification,
        "can_merge": verdict == "PASS" and not missing and not blocked_files,
        "created_at": now(),
    }
    write_json(out / "checkpoints" / f"{leaf}.json", checkpoint)
    return checkpoint


def _run_controlled_leaf(out: pathlib.Path, leaf: str) -> dict[str, Any]:
    project = out / "project"
    _prepare_package_markers(project)
    _, files = LEAF_SPECS[leaf]
    leaf_out = out / "leaves" / leaf
    leaf_out.mkdir(parents=True, exist_ok=True)
    for rel in files:
        _write(project, rel, _controlled_content(leaf, rel))
        append_jsonl(leaf_out / "file_write_log.jsonl", {"agent_id": leaf, "path": rel, "status": "written_controlled"})
    test_file = next((rel for rel in files if rel.startswith("tests/") and rel.endswith(".py")), "")
    test_result = _run_pytest(project, [test_file], timeout=60) if test_file else {"exit_code": 0, "command": ""}
    write_json(leaf_out / "test_execution_result.json", test_result)
    verdict = "PASS" if test_result.get("exit_code") == 0 else "FAIL"
    return _leaf_checkpoint(
        out=out,
        leaf=leaf,
        provider_mode="controlled",
        expected_files=files,
        blocked_files=[],
        test_result=test_result,
        verdict=verdict,
        classification="controlled_leaf_pass" if verdict == "PASS" else "controlled_leaf_test_failed",
    )


def _run_real_leaf(out: pathlib.Path, leaf: str, *, goal: str, model: str, readiness: dict[str, Any], provider_output_override: str | None = None) -> dict[str, Any]:
    leaf_out = out / "leaves" / leaf
    _copy_contract_to_leaf(out, leaf_out, leaf)
    result = run_real_provider_leaf(
        agent_id=leaf,
        out_dir=leaf_out,
        project_dir=out / "project",
        user_goal=goal,
        model=model,
        readiness=readiness,
        provider_output_override=provider_output_override,
    )
    _, expected_files = LEAF_SPECS[leaf]
    test_result = read_json(leaf_out / "test_execution_result.json", {"exit_code": None, "command": ""})
    checkpoint_verdict = "PASS" if result.get("classification") == "real_provider_leaf_pass" else "FAIL"
    return _leaf_checkpoint(
        out=out,
        leaf=leaf,
        provider_mode="real_provider",
        expected_files=expected_files,
        blocked_files=list(result.get("forbidden_write_attempts", [])),
        test_result=test_result,
        verdict=checkpoint_verdict,
        classification=str(result.get("classification", "")),
    )


def _merge_backend(out: pathlib.Path, registry: dict[str, Any]) -> dict[str, Any]:
    children = [child["agent_id"] for child in children_of(registry, "backend_branch_agent")]
    checkpoints = [read_json(out / "checkpoints" / f"{child}.json", {}) for child in children]
    issues = [f"{cp.get('leaf')}:{cp.get('verdict')}" for cp in checkpoints if cp.get("verdict") != "PASS"]
    scope_issues = [f"{cp.get('leaf')}:{','.join(cp.get('blocked_files', []))}" for cp in checkpoints if cp.get("blocked_files")]
    result = {
        "parent_agent": "backend_branch_agent",
        "children": children,
        "child_results": [{"leaf": cp.get("leaf"), "provider_mode": cp.get("provider_mode"), "verdict": cp.get("verdict"), "can_merge": cp.get("can_merge")} for cp in checkpoints],
        "issues": issues + scope_issues,
        "merge_verdict": "PASS" if children and not issues and not scope_issues else "FAIL",
        "required_children_passed": bool(children) and not issues,
        "scope_violations": scope_issues,
        "created_at": now(),
    }
    write_json(out / "merge_results" / "backend_branch_agent.json", result)
    return result


def run_mixed_backend_branch_phase(
    *,
    out_dir: str | pathlib.Path,
    project_name: str,
    real_provider_leaves: list[str],
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
    real_leaves = [leaf.strip() for leaf in real_provider_leaves if leaf.strip()]
    if any(leaf not in LEAF_SPECS for leaf in real_leaves):
        raise ValueError("real_provider_leaves must be backend leaf ids")
    if real_leaves and not readiness.get("provider_ready") and not provider_output_overrides:
        final = {
            "classification": "provider_unavailable",
            "verdict": "BLOCKED",
            "provider_ready": False,
            "real_provider_leaves": real_leaves,
            "fake_success_detected": False,
            "backend_merge": "not_run",
        }
        write_json(out / "final_verdict.json", final)
        return final

    checkpoints: list[dict[str, Any]] = []
    overrides = provider_output_overrides or {}
    for leaf in BACKEND_LEAF_ORDER:
        if leaf in real_leaves:
            checkpoints.append(_run_real_leaf(out, leaf, goal=goal, model=model, readiness=readiness, provider_output_override=overrides.get(leaf)))
        else:
            checkpoints.append(_run_controlled_leaf(out, leaf))
    merge = _merge_backend(out, registry)
    backend_test = _run_pytest(out / "project", BACKEND_TESTS, timeout=120) if merge.get("merge_verdict") == "PASS" else {"command": "python -m pytest " + " ".join(BACKEND_TESTS) + " -q", "exit_code": None, "skipped": "merge_failed"}
    write_json(out / "backend_branch_test_execution.json", backend_test)

    real_failures = [cp for cp in checkpoints if cp.get("provider_mode") == "real_provider" and cp.get("verdict") != "PASS"]
    if any(cp.get("blocked_files") for cp in real_failures):
        classification = "real_leaf_scope_violation_blocked"
    elif any(cp.get("classification") == "real_provider_leaf_missing_files" for cp in real_failures):
        classification = "real_leaf_missing_files"
    elif any(cp.get("classification") == "real_provider_leaf_test_failed" for cp in real_failures):
        classification = "real_leaf_test_failed"
    elif merge.get("merge_verdict") != "PASS" or backend_test.get("exit_code") != 0:
        classification = "backend_merge_failed"
    else:
        classification = "mixed_backend_search_real_pass" if real_leaves == ["search_service_leaf"] else "mixed_backend_multi_real_pass"
    verdict = "PASS" if classification.startswith("mixed_backend") else "NEEDS_REWORK"
    final = {
        "classification": classification,
        "verdict": verdict,
        "provider_ready": bool(readiness.get("provider_ready") or provider_output_overrides),
        "real_provider_leaves": real_leaves,
        "controlled_leaves": [leaf for leaf in BACKEND_LEAF_ORDER if leaf not in real_leaves],
        "backend_merge": merge.get("merge_verdict"),
        "backend_test_exit_code": backend_test.get("exit_code"),
        "fake_success_detected": False,
        "created_at": now(),
    }
    write_json(out / "final_verdict.json", final)
    return final


def run_scope_violation_injection(*, out_dir: str | pathlib.Path, project_name: str, goal: str = DEFAULT_GOAL) -> dict[str, Any]:
    raw = json.dumps({"files": [{"path": "README.md", "content": "# forbidden"}]})
    result = run_mixed_backend_branch_phase(
        out_dir=out_dir,
        project_name=project_name,
        real_provider_leaves=["search_service_leaf"],
        goal=goal,
        readiness_override={"provider_ready": True},
        provider_output_overrides={"search_service_leaf": raw},
    )
    project_readme_exists = (pathlib.Path(out_dir) / "project" / "README.md").exists()
    result["forbidden_file"] = "README.md"
    result["forbidden_file_written"] = project_readme_exists
    result["verdict"] = "PASS" if result.get("classification") == "real_leaf_scope_violation_blocked" and not project_readme_exists else "FAIL"
    write_json(pathlib.Path(out_dir) / "final_verdict.json", result)
    return result


def create_mixed_backend_trace_bundle(*, out_dir: str | pathlib.Path, final_verdict: dict[str, Any]) -> pathlib.Path:
    out = pathlib.Path(out_dir)
    index = [
        "# Real Provider Mixed Backend Branch Trace Bundle",
        "",
        "- Purpose: prove one real provider backend leaf can merge with controlled backend leaves.",
        "- Real provider leaf: search_service_leaf",
        "- Controlled leaves: document_import_leaf, model_adapter_leaf, task_service_leaf, report_service_leaf",
        f"- Real leaf scope violations: {read_json(out / 'phase1_search_real' / 'checkpoints' / 'search_service_leaf.json', {}).get('blocked_files', [])}",
        f"- Backend merge: {read_json(out / 'phase1_search_real' / 'merge_results' / 'backend_branch_agent.json', {}).get('merge_verdict', '')}",
        f"- Failure injection: {read_json(out / 'failure_injection_scope_violation' / 'final_verdict.json', {}).get('verdict', '')}",
        f"- Final verdict: {final_verdict.get('verdict', '')}",
    ]
    (out / "00_INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    bundle = out / "mixed_backend_branch_trace_bundle.zip"
    wanted = [
        "00_INDEX.md",
        "provider_readiness.json",
        "phase1_search_real",
        "failure_injection_scope_violation",
        "final_verdict.json",
    ]
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in wanted:
            path = out / rel
            if path.is_file():
                zf.write(path, rel)
            elif path.is_dir():
                for item in path.rglob("*"):
                    if item.is_file():
                        zf.write(item, item.relative_to(out).as_posix())
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--real-provider-leaves", default="search_service_leaf")
    parser.add_argument("--failure-injection", action="store_true")
    args = parser.parse_args()
    leaves = [item.strip() for item in args.real_provider_leaves.split(",") if item.strip()]
    if args.failure_injection:
        result = run_scope_violation_injection(out_dir=args.out, project_name=args.project_name, goal=args.goal)
    else:
        result = run_mixed_backend_branch_phase(out_dir=args.out, project_name=args.project_name, real_provider_leaves=leaves, goal=args.goal, model=args.model)
    print(json.dumps({"classification": result.get("classification"), "verdict": result.get("verdict")}, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
