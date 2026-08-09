from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_growth_budget import check_leaf_size, default_growth_budget
    from agent_growth_feedback_router import create_growth_feedback_task
    from agent_growth_merge_protocol import merge_branch_results
    from agent_growth_planner import plan_dynamic_growth
    from agent_growth_trace_bundle import create_growth_trace_bundle
    from agent_scope_contract import check_scope_write, load_scope_contract
    from agent_tree_action_protocol import AgentActionRecorder
    from agent_tree_context_reducer import reduce_context, save_local_context
    from agent_tree_contracts import append_jsonl, now, read_json, write_json
    from agent_tree_goal_alignment import evaluate_goal_alignment
    from agent_tree_registry import agent_by_id, children_of, render_tree
    from agent_tree_shared_context import create_shared_context, save_shared_context
    import local_packager
    import real_test_execution
    import runtime_visual_evidence
    import telegram_live_bridge
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_growth_budget import check_leaf_size, default_growth_budget
    from scripts.agent_growth_feedback_router import create_growth_feedback_task
    from scripts.agent_growth_merge_protocol import merge_branch_results
    from scripts.agent_growth_planner import plan_dynamic_growth
    from scripts.agent_growth_trace_bundle import create_growth_trace_bundle
    from scripts.agent_scope_contract import check_scope_write, load_scope_contract
    from scripts.agent_tree_action_protocol import AgentActionRecorder
    from scripts.agent_tree_context_reducer import reduce_context, save_local_context
    from scripts.agent_tree_contracts import append_jsonl, now, read_json, write_json
    from scripts.agent_tree_goal_alignment import evaluate_goal_alignment
    from scripts.agent_tree_registry import agent_by_id, children_of, render_tree
    from scripts.agent_tree_shared_context import create_shared_context, save_shared_context
    from scripts import local_packager, real_test_execution, runtime_visual_evidence, telegram_live_bridge


def _write(project: pathlib.Path, rel: str, text: str) -> None:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _checkpoint(out_dir: pathlib.Path, agent_id: str, verdict: str, *, present: list[str] | None = None, missing: list[str] | None = None, issues: list[str] | None = None) -> dict[str, Any]:
    doc = {
        "agent_id": agent_id,
        "verdict": verdict,
        "can_continue": verdict == "PASS",
        "present_files": list(present or []),
        "missing_files": list(missing or []),
        "issues": list(issues or []),
        "created_at": now(),
    }
    write_json(out_dir / "checkpoints" / f"{agent_id}.json", doc)
    return doc


def _record_leaf_action(out_dir: pathlib.Path, agent_id: str, files: list[str], scope_ok: dict[str, Any]) -> None:
    append_jsonl(
        out_dir / "leaf_build_actions.jsonl",
        {
            "action_id": f"L{len((out_dir / 'leaf_build_actions.jsonl').read_text(encoding='utf-8').splitlines()) + 1:04d}" if (out_dir / "leaf_build_actions.jsonl").exists() else "L0001",
            "agent_id": agent_id,
            "action": "controlled_leaf_write",
            "target_files": files,
            "scope_ok": scope_ok["ok"],
            "scope_violations": scope_ok["violations"],
            "created_at": now(),
        },
    )


def controlled_leaf_build(agent: dict[str, Any], *, project_dir: pathlib.Path, out_dir: pathlib.Path, budget: dict[str, int], injected_files: list[str] | None = None) -> dict[str, Any]:
    agent_id = str(agent["agent_id"])
    contract = load_scope_contract(out_dir, agent_id)
    expected_files = list(contract.get("allowed_files", []))
    size = check_leaf_size(expected_files, budget)
    if size["verdict"] == "NEEDS_SPLIT":
        cp = _checkpoint(out_dir, agent_id, "NEEDS_SPLIT", missing=expected_files, issues=[size["reason"]])
        create_growth_feedback_task(
            out_dir=out_dir,
            target_agent=str(agent.get("parent_id") or agent_id),
            failed_agent=agent_id,
            reason="ask parent to spawn smaller children",
            missing=expected_files,
            allowed_actions=["spawn_smaller_children"],
            success_condition="smaller child checkpoints PASS",
        )
        return cp
    attempted_files = list(injected_files or expected_files)
    scope_ok = check_scope_write(contract, attempted_files)
    _record_leaf_action(out_dir, agent_id, attempted_files, scope_ok)
    if not scope_ok["ok"]:
        cp = _checkpoint(out_dir, agent_id, "FAIL", missing=expected_files, issues=[f"scope_violation:{item}" for item in scope_ok["violations"]])
        create_growth_feedback_task(out_dir=out_dir, target_agent=agent_id, failed_agent=agent_id, reason="scope_violation", missing=scope_ok["violations"])
        return cp

    for rel in expected_files:
        _write(project_dir, rel, _controlled_file_content(agent_id, rel))
    present = [rel for rel in expected_files if (project_dir / rel).exists()]
    missing = [rel for rel in expected_files if not (project_dir / rel).exists()]
    return _checkpoint(out_dir, agent_id, "PASS" if not missing else "FAIL", present=present, missing=missing)


def _controlled_file_content(agent_id: str, rel: str) -> str:
    if rel.endswith("document_import_service.py"):
        return (
            "from __future__ import annotations\n\nfrom app.services.storage import DOCUMENTS\n\n"
            "def import_document(title: str, content: str) -> dict:\n"
            "    item = {'id': len(DOCUMENTS) + 1, 'title': title, 'content': content}\n"
            "    DOCUMENTS.append(item)\n"
            "    return item\n"
        )
    if rel.endswith("storage.py"):
        return "DOCUMENTS = []\nTASKS = []\n"
    if rel.endswith("search_service.py"):
        return (
            "from __future__ import annotations\n\n"
            "def search_documents(documents: list[dict], query: str) -> list[dict]:\n"
            "    q = query.lower()\n"
            "    return [doc for doc in documents if q in doc.get('title', '').lower() or q in doc.get('content', '').lower()]\n"
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
        return "from __future__ import annotations\n\nTASKS = []\n\ndef create_task(title: str) -> dict:\n    task = {'id': len(TASKS) + 1, 'title': title, 'status': 'open'}\n    TASKS.append(task)\n    return task\n"
    if rel.endswith("report_service.py"):
        return "from __future__ import annotations\n\ndef build_report(documents: list[dict], tasks: list[dict]) -> dict:\n    return {'document_count': len(documents), 'task_count': len(tasks), 'sections': ['summary', 'tasks', 'next steps']}\n"
    if rel.endswith(".html"):
        title = pathlib.Path(rel).stem.replace("_", " ").title()
        return f"<!doctype html><html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>Local AI Knowledge Studio {title.lower()} view.</p></main></body></html>\n"
    if rel.endswith("test_document_import_service.py"):
        return "from app.services.document_import_service import import_document\n\ndef test_import_document_records_title():\n    assert import_document('Guide', 'Knowledge')['title'] == 'Guide'\n"
    if rel.endswith("test_search_service.py"):
        return "from app.services.search_service import search_documents\n\ndef test_search_documents_finds_content():\n    docs = [{'title': 'A', 'content': 'local knowledge'}]\n    assert search_documents(docs, 'knowledge')\n"
    if rel.endswith("test_model_adapter.py"):
        return "from app.services.model_adapter import adapter_status\n\ndef test_missing_model_is_documented():\n    assert 'missing model' in adapter_status({})['limit']\n"
    if rel.endswith("test_task_service.py"):
        return "from app.services.task_service import create_task\n\ndef test_create_task_open_status():\n    assert create_task('Review')['status'] == 'open'\n"
    if rel.endswith("test_report_service.py"):
        return "from app.services.report_service import build_report\n\ndef test_build_report_counts_inputs():\n    assert build_report([{}], [{}, {}])['task_count'] == 2\n"
    if rel.endswith("test_smoke.py"):
        return "from app.main import application_summary\n\ndef test_application_summary_smoke():\n    assert application_summary()['report']['document_count'] >= 1\n"
    if rel.endswith("test_backend_services.py"):
        return "from app.main import application_summary\n\ndef test_backend_services_integrate():\n    summary = application_summary()\n    assert summary['search']\n    assert summary['task']['status'] == 'open'\n"
    if rel.endswith("test_ui_routes.py"):
        return "from pathlib import Path\n\ndef test_ui_templates_exist():\n    assert len(list(Path('app/templates').glob('*.html'))) >= 5\n"
    return f"# owned by {agent_id}\n"


def _run_special_agent(agent_id: str, *, shared_context: dict[str, Any], project_dir: pathlib.Path, out_dir: pathlib.Path) -> dict[str, Any]:
    contract = load_scope_contract(out_dir, agent_id)
    files = list(contract.get("allowed_files", []))
    scope_ok = check_scope_write(contract, files)
    _record_leaf_action(out_dir, agent_id, files, scope_ok)
    if not scope_ok["ok"]:
        return _checkpoint(out_dir, agent_id, "FAIL", missing=files, issues=scope_ok["violations"])
    if agent_id == "requirement_agent":
        _write(project_dir, "frozen_requirement.json", json.dumps({"project_name": shared_context["project_name"], "user_goal": shared_context["user_goal"], "requirements": shared_context["acceptance_contract"]}, ensure_ascii=False, indent=2))
    elif agent_id == "architecture_agent":
        _write(project_dir, "api_contract.json", '{"routes": ["/documents", "/search", "/tasks", "/reports", "/settings"]}\n')
        _write(project_dir, "config/settings.example.env", "LOCAL_MODEL_ENDPOINT=http://localhost:11434\nMODEL_PATH=\n")
        _write(project_dir, "architecture_plan.json", '{"layers": ["frontend", "services", "local_model_adapter"]}\n')
    elif agent_id == "integration_agent":
        _write(project_dir, "README.md", "# Local AI Knowledge Studio\n\nRun with `python app/main.py`.\n\nSet `LOCAL_MODEL_ENDPOINT` or `MODEL_PATH`. If a model file or endpoint is missing, the app must not claim real inference.\n")
        _write(project_dir, "requirements.txt", "pytest\n")
        _write(project_dir, "app/__init__.py", "")
        _write(project_dir, "app/services/__init__.py", "")
        _write(
            project_dir,
            "app/main.py",
            "from app.services.document_import_service import import_document\nfrom app.services.search_service import search_documents\nfrom app.services.task_service import create_task\nfrom app.services.report_service import build_report\n\n"
            "def application_summary() -> dict:\n    doc = import_document('Welcome', 'Local knowledge base content')\n    task = create_task('Review imported material')\n    docs = [doc]\n    return {'document': doc, 'search': search_documents(docs, 'knowledge'), 'task': task, 'report': build_report(docs, [task])}\n\nif __name__ == '__main__':\n    print(application_summary())\n",
        )
        _write(project_dir, "index.html", "<!doctype html><html><body><nav>Dashboard Documents Search Tasks Reports Settings</nav><main>Local AI Knowledge Studio</main></body></html>\n")
    elif agent_id == "qa_agent":
        for name in ("app_home", "search_results", "report_preview"):
            runtime_visual_evidence.write_runtime_preview_png(project_dir / "screenshots" / f"{name}.png", title=name)
        runtime_visual_evidence.collect_visual_evidence(project_dir)
    elif agent_id == "delivery_agent":
        _write(project_dir, "DELIVERY_NOTES.md", "# Delivery Notes\n\ncontrolled_dynamic_agent_tree_lane: PASS\nnot_real_provider_proof: true\n")
        manifest = local_packager.package_project(project_dir, output_dir=project_dir, startup_command="python app/main.py", screenshot_path=project_dir / "screenshots" / "app_home.png")
        session = {"messages": [{"role": "user", "text": shared_context["user_goal"]}], "whiteboard": {"project_summary": shared_context["user_goal"], "target_project_architecture": shared_context["target_project_model"], "delivery_requirements": ["project package"]}}
        gate = telegram_live_bridge.evaluate_public_delivery_gate(project_dir, manifest, session, phase="final")
        write_json(out_dir / "contract_checks" / "public_delivery_gate.json", gate)
    present = [rel for rel in files if (project_dir / rel).exists()]
    missing = [rel for rel in files if not (project_dir / rel).exists()]
    return _checkpoint(out_dir, agent_id, "PASS" if not missing else "FAIL", present=present, missing=missing)


def run_controlled_dynamic_growth(
    *,
    goal: str,
    project_name: str,
    out_dir: str | pathlib.Path,
    provider_mode: str = "controlled",
) -> dict[str, Any]:
    if provider_mode not in {"controlled", "mixed"}:
        raise ValueError("only controlled and mixed provider modes are supported in this eval lane")
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("spawn_actions.jsonl", "leaf_build_actions.jsonl", "feedback_tasks.jsonl"):
        (out / name).write_text("", encoding="utf-8")
    project = out / "generated_project"
    project.mkdir(parents=True, exist_ok=True)
    budget = default_growth_budget()

    shared_context = create_shared_context(project_name, goal)
    save_shared_context(shared_context, out)
    local_context = reduce_context(shared_context, agent_id="main_agent", stage="dynamic_growth", raw_context=goal)
    save_local_context(local_context, out)
    alignment_plan = " + ".join(
        str(item).replace("_", " ")
        for item in shared_context.get("goal_spec", {}).get("capabilities", [])
    )
    alignment = evaluate_goal_alignment(shared_context, alignment_plan)
    write_json(out / "goal_alignment.json", alignment)
    if alignment["verdict"] != "PASS":
        final = {"verdict": "FAIL", "reason": "goal_alignment_failed"}
        write_json(out / "final_verdict.json", final)
        return final

    registry = plan_dynamic_growth(shared_context, out, budget)
    for agent_id in ("requirement_agent", "architecture_agent"):
        _run_special_agent(agent_id, shared_context=shared_context, project_dir=project, out_dir=out)
    for parent_id in ("backend_branch_agent", "frontend_branch_agent"):
        for child in children_of(registry, parent_id):
            controlled_leaf_build(child, project_dir=project, out_dir=out, budget=budget)
        merge_branch_results(registry=registry, parent_agent=parent_id, out_dir=out, owned_outputs=["app/services/" if parent_id.startswith("backend") else "app/templates/"])
    _run_special_agent("integration_agent", shared_context=shared_context, project_dir=project, out_dir=out)
    for child in children_of(registry, "test_branch_agent"):
        controlled_leaf_build(child, project_dir=project, out_dir=out, budget=budget)
    test_result = real_test_execution.run_tests(project, timeout=60)
    write_json(out / "contract_checks" / "real_test_execution.json", test_result)
    merge_branch_results(registry=registry, parent_agent="test_branch_agent", out_dir=out, owned_outputs=["tests/"])
    _run_special_agent("qa_agent", shared_context=shared_context, project_dir=project, out_dir=out)
    _run_special_agent("delivery_agent", shared_context=shared_context, project_dir=project, out_dir=out)

    gate = read_json(out / "contract_checks" / "public_delivery_gate.json", {})
    merges = [read_json(out / "merge_results" / f"{name}.json", {}) for name in ("backend_branch_agent", "frontend_branch_agent", "test_branch_agent")]
    checkpoints = [read_json(path, {}) for path in (out / "checkpoints").glob("*.json")]
    final = {
        "kind": "DynamicAgentTreeControlledFinalVerdict",
        "verdict": "PASS" if gate.get("delivery_allowed") is True and all(item.get("merge_verdict") == "PASS" for item in merges) and all(item.get("verdict") == "PASS" for item in checkpoints) else "NEEDS_REWORK",
        "controlled_dynamic_lane_only": True,
        "provider_mode": provider_mode,
        "real_provider_proof": False,
        "agent_count": len(registry["agents"]),
        "tree": render_tree(registry),
        "public_delivery_gate": gate,
        "created_at": now(),
    }
    bundle = create_growth_trace_bundle(out_dir=out, project_dir=project, final_verdict=final)
    final["trace_bundle"] = str(bundle)
    write_json(out / "final_verdict.json", final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider-mode", default="controlled")
    parser.add_argument("--real-provider-leaves", default="")
    args = parser.parse_args()
    result = run_controlled_dynamic_growth(goal=args.goal, project_name=args.project_name, out_dir=args.out, provider_mode=args.provider_mode)
    print(result["verdict"])
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
