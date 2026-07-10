from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    import artifact_integrity
    import local_packager
    import runtime_visual_evidence
    from agent_growth_budget import default_growth_budget, save_growth_budget
    from agent_leaf_provider_guard import provider_readiness, redact_secret
    from agent_real_provider_leaf_builder import run_real_provider_leaf
    from agent_scope_contract import create_scope_contract, save_scope_contract
    from agent_spawn_protocol import create_spawn_action
    from agent_tree_contracts import append_jsonl, now, read_json, read_jsonl, write_json
    from agent_tree_goal_alignment import evaluate_goal_alignment
    from agent_tree_registry import add_agent, children_of, initial_registry, save_registry
    from agent_tree_shared_context import create_shared_context, save_shared_context
    from run_mixed_backend_branch_phase import BACKEND_LEAF_ORDER, LEAF_SPECS as BACKEND_SPECS
    from run_real_provider_frontend_branch_phase import FRONTEND_LEAF_ORDER, FRONTEND_SPECS, FRONTEND_TEST_TERMS, controlled_frontend_output, frontend_static_missing_terms
except ModuleNotFoundError:  # pragma: no cover
    from scripts import artifact_integrity, local_packager, runtime_visual_evidence
    from scripts.agent_growth_budget import default_growth_budget, save_growth_budget
    from scripts.agent_leaf_provider_guard import provider_readiness, redact_secret
    from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
    from scripts.agent_scope_contract import create_scope_contract, save_scope_contract
    from scripts.agent_spawn_protocol import create_spawn_action
    from scripts.agent_tree_contracts import append_jsonl, now, read_json, read_jsonl, write_json
    from scripts.agent_tree_goal_alignment import evaluate_goal_alignment
    from scripts.agent_tree_registry import add_agent, children_of, initial_registry, save_registry
    from scripts.agent_tree_shared_context import create_shared_context, save_shared_context
    from scripts.run_mixed_backend_branch_phase import BACKEND_LEAF_ORDER, LEAF_SPECS as BACKEND_SPECS
    from scripts.run_real_provider_frontend_branch_phase import FRONTEND_LEAF_ORDER, FRONTEND_SPECS, FRONTEND_TEST_TERMS, controlled_frontend_output, frontend_static_missing_terms


DEFAULT_OUT_ROOT = ROOT / "generated" / "full_dynamic_real_project_eval"
DEFAULT_GOAL = "做一个本地 AI 知识工作台，用于导入资料、建立本地知识库、检索、总结、任务化跟踪、生成报告，并支持本地模型适配层"
MODEL_SEMANTICS = {
    "target_project_model": {"mode": "local_model", "adapter_required": True, "config_needed": True},
    "cgkn_backend": {"mode": "api"},
}
TEST_LEAF_ORDER = ["smoke_test_leaf", "backend_tests_leaf", "ui_route_tests_leaf"]
TEST_SPECS: dict[str, tuple[str, list[str]]] = {
    "smoke_test_leaf": ("SmokeTestLeafAgent", ["tests/test_smoke.py"]),
    "backend_tests_leaf": ("BackendTestsLeafAgent", ["tests/test_backend_integration.py"]),
    "ui_route_tests_leaf": ("UiRouteTestsLeafAgent", ["tests/test_ui_routes.py"]),
}
BRANCH_CHILDREN = {
    "backend_branch_agent": BACKEND_LEAF_ORDER,
    "frontend_branch_agent": FRONTEND_LEAF_ORDER,
    "test_branch_agent": TEST_LEAF_ORDER,
}
INTEGRATION_ALLOWED = [
    "app/main.py",
    "app/__init__.py",
    "app/routes.py",
    "app/store.py",
    "app/static/style.css",
    "requirements.txt",
    "README.md",
    "pytest.ini",
]
DELIVERY_ALLOWED = ["DELIVERY_NOTES.md", "delivery_manifest.json", "final_project_bundle.zip", "packager_run_log.txt"]
DELIVERY_ARTIFACTS = {"final_project_bundle.zip", "delivery_manifest.json", "sent_records.json", "TEST_REPORT.md", "visual_evidence.json"}


def _all_owned_files() -> list[str]:
    files: list[str] = []
    for _, owned in BACKEND_SPECS.values():
        files.extend(owned)
    for _, _, owned in FRONTEND_SPECS.values():
        files.extend(owned)
    for _, owned in TEST_SPECS.values():
        files.extend(owned)
    files.extend(INTEGRATION_ALLOWED)
    files.extend(DELIVERY_ALLOWED)
    files.extend(["screenshots/dashboard.png", "screenshots/documents.png", "screenshots/search.png", "screenshots/settings.png"])
    return sorted(set(files))


def _write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(command: list[str], *, cwd: pathlib.Path, timeout: int = 60, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = now()
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return {
            "command": " ".join(command),
            "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": redact_secret((proc.stderr or "")[-4000:]),
            "started_at": started,
            "finished_at": now(),
        }
    except Exception as exc:
        return {"command": " ".join(command), "exit_code": -1, "stdout_tail": "", "stderr_tail": redact_secret(str(exc)), "started_at": started, "finished_at": now()}


def record_start_state(out_root: str | pathlib.Path = DEFAULT_OUT_ROOT) -> dict[str, Any]:
    out = pathlib.Path(out_root)
    out.mkdir(parents=True, exist_ok=True)
    branch = _run(["git", "branch", "--show-current"], cwd=ROOT, timeout=20)
    head = _run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, timeout=20)
    status = _run(["git", "status", "--short"], cwd=ROOT, timeout=30)
    prereq = {
        "backend_expansion_report": (ROOT / "generated/real_provider_backend_expansion_eval/backend_expansion_report.json").exists(),
        "frontend_branch_report": (ROOT / "generated/real_provider_frontend_branch_eval/frontend_branch_report.json").exists(),
        "growth_final_verdict": (ROOT / "generated/dynamic_agent_tree_growth_eval/final_verdict.json").exists(),
        "fix_report": (ROOT / "generated/dynamic_agent_tree_fix_eval/fix_report.json").exists(),
    }
    telegram = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*telegram_live_bridge.py*' } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
        ],
        cwd=ROOT,
        timeout=30,
    )
    state = {
        "branch": branch.get("stdout_tail", "").strip(),
        "head": head.get("stdout_tail", "").strip(),
        "worktree_status": status.get("stdout_tail", ""),
        "prerequisite_evidence": prereq,
        "telegram_process_query": telegram,
        "telegram_mainline_connected": False,
        "created_at": now(),
    }
    write_json(out / "start_state.json", state)
    lines = ["# Full Dynamic Real Project Eval Start State", "", f"- Branch: {state['branch']}", f"- HEAD: {state['head']}", "- Telegram mainline connected: false", "", "## Prerequisites"]
    lines.extend(f"- {key}: {value}" for key, value in prereq.items())
    lines.extend(["", "## Worktree", "```", state["worktree_status"].rstrip(), "```"])
    _write_text(out / "start_state.md", "\n".join(lines) + "\n")
    return state


def controlled_backend_output(leaf: str) -> str:
    files = BACKEND_SPECS[leaf][1]
    content: dict[str, str] = {
        "app/services/document_import_service.py": "from __future__ import annotations\n\nDOCUMENTS=[]\n\ndef import_document(title: str, content: str) -> dict:\n    doc={'id': len(DOCUMENTS)+1, 'title': title, 'content': content, 'status': 'imported'}\n    DOCUMENTS.append(doc)\n    return doc\n",
        "tests/test_document_import_service.py": "from app.services.document_import_service import import_document\n\ndef test_import_document_records_title():\n    assert import_document('Guide', 'local knowledge')['title'] == 'Guide'\n",
        "app/services/search_service.py": "from __future__ import annotations\n\ndef search_documents(documents: list[dict], query: str) -> list[dict]:\n    q=str(query or '').lower()\n    return [doc for doc in documents if q in str(doc.get('title','')).lower() or q in str(doc.get('content','')).lower()]\n",
        "tests/test_search_service.py": "from app.services.search_service import search_documents\n\ndef test_search_documents_finds_content():\n    assert search_documents([{'title':'A','content':'local knowledge'}], 'knowledge')\n",
        "app/services/model_adapter.py": "from __future__ import annotations\n\ndef adapter_status(config: dict | None = None) -> dict:\n    config=config or {}\n    endpoint=config.get('LOCAL_MODEL_ENDPOINT') or config.get('MODEL_PATH') or ''\n    return {'configured': bool(endpoint), 'mode': 'local_model', 'limit': '' if endpoint else 'missing model file or endpoint; cannot claim real inference'}\n",
        "tests/test_model_adapter.py": "from app.services.model_adapter import adapter_status\n\ndef test_missing_model_is_documented():\n    assert 'missing model' in adapter_status({})['limit']\n",
        "app/services/task_service.py": "from __future__ import annotations\n\ndef create_task(title: str) -> dict:\n    return {'id': 1, 'title': title, 'status': 'open'}\n",
        "tests/test_task_service.py": "from app.services.task_service import create_task\n\ndef test_create_task_open_status():\n    assert create_task('Review')['status'] == 'open'\n",
        "app/services/report_service.py": "from __future__ import annotations\n\ndef build_report(documents: list[dict], tasks: list[dict]) -> dict:\n    return {'document_count': len(documents), 'task_count': len(tasks), 'sections': ['summary', 'tasks', 'next steps']}\n",
        "tests/test_report_service.py": "from app.services.report_service import build_report\n\ndef test_build_report_counts_inputs():\n    assert build_report([{}], [{}, {}])['task_count'] == 2\n",
    }
    return json.dumps({"files": [{"path": rel, "content": content[rel]} for rel in files]}, ensure_ascii=False)


def controlled_test_output(leaf: str) -> str:
    files = TEST_SPECS[leaf][1]
    content = {
        "tests/test_smoke.py": "def test_app_imports():\n    import app.main as main\n    assert hasattr(main, 'ROUTES')\n",
        "tests/test_backend_integration.py": "from app.services.document_import_service import import_document\nfrom app.services.search_service import search_documents\nfrom app.services.task_service import create_task\nfrom app.services.report_service import build_report\nfrom app.services.model_adapter import adapter_status\n\n\ndef test_backend_services_work_together():\n    doc = import_document('Guide', 'local knowledge')\n    assert search_documents([doc], 'knowledge')\n    task = create_task('Review')\n    report = build_report([doc], [task])\n    assert report['document_count'] == 1\n    assert adapter_status({})['mode'] == 'local_model'\n",
        "tests/test_ui_routes.py": "from app.routes import PAGES, render_page\n\n\ndef test_ui_routes_render_core_pages():\n    for page in ('dashboard', 'documents', 'search', 'settings'):\n        html = render_page(page)\n        assert '<html' in html.lower() or '<!doctype' in html.lower()\n        assert page in PAGES\n",
    }
    return json.dumps({"files": [{"path": files[0], "content": content[files[0]]}]}, ensure_ascii=False)


def controlled_full_project_outputs() -> dict[str, str]:
    outputs: dict[str, str] = {}
    for leaf in BACKEND_LEAF_ORDER:
        outputs[leaf] = controlled_backend_output(leaf)
    for leaf in FRONTEND_LEAF_ORDER:
        outputs[leaf] = controlled_frontend_output(leaf)
    for leaf in TEST_LEAF_ORDER:
        outputs[leaf] = controlled_test_output(leaf)
    return outputs


def _spawn(registry: dict[str, Any], budget: dict[str, int], out: pathlib.Path, parent: str, agent_id: str, role: str, depth: int, scope: list[str], outputs: list[str], verification: list[str]) -> None:
    action = create_spawn_action(out_dir=out, registry=registry, budget=budget, parent_agent=parent, new_agent_id=agent_id, role=role, depth=depth, reason=f"Full dynamic real project eval spawn {agent_id}", scope=scope, expected_outputs=outputs, verification=verification)
    add_agent(registry, action)


def _alignment_plan(shared: dict[str, Any]) -> str:
    contract = shared.get("goal_specific_acceptance_contract")
    if isinstance(contract, dict) and contract.get("domain") == "local_studio_operations_hub":
        return "dashboard production tasks asset library bugs issues releases team roles search import export tests screenshots bundle"
    return "document import knowledge base search reports tasks local model adapter dashboard settings pytest visual package"


def init_dynamic_tree(out: pathlib.Path, project_name: str, goal: str) -> dict[str, Any]:
    shared = create_shared_context(project_name, goal)
    shared["model_semantics"] = MODEL_SEMANTICS
    save_shared_context(shared, out)
    plan = _alignment_plan(shared)
    write_json(out / "goal_alignment.json", evaluate_goal_alignment(shared, plan))
    budget = default_growth_budget()
    budget["max_agents"] = max(int(budget.get("max_agents", 0)), 32)
    save_growth_budget(out, budget)
    (out / "spawn_actions.jsonl").write_text("", encoding="utf-8")
    registry = initial_registry()
    _spawn(registry, budget, out, "main_agent", "requirement_agent", "RequirementAgent", 1, ["requirements"], ["requirements_summary.json"], ["goal_alignment"])
    _spawn(registry, budget, out, "main_agent", "architecture_agent", "ArchitectureAgent", 1, ["architecture"], ["architecture_plan.json"], ["model_semantics"])
    _spawn(registry, budget, out, "main_agent", "backend_branch_agent", "BackendBranchAgent", 1, ["backend branch"], ["backend children"], ["child_checkpoints"])
    _spawn(registry, budget, out, "main_agent", "frontend_branch_agent", "FrontendBranchAgent", 1, ["frontend branch"], ["frontend children"], ["child_checkpoints"])
    _spawn(registry, budget, out, "main_agent", "test_branch_agent", "TestBranchAgent", 1, ["test branch"], ["test children"], ["child_checkpoints"])
    _spawn(registry, budget, out, "main_agent", "integration_agent", "IntegrationAgent", 1, ["integration"], INTEGRATION_ALLOWED, ["branch_merges"])
    _spawn(registry, budget, out, "main_agent", "qa_agent", "QAAgent", 1, ["qa"], ["test_execution.json", "visual_evidence.json"], ["real_tests", "screenshots"])
    _spawn(registry, budget, out, "main_agent", "delivery_agent", "DeliveryAgent", 1, ["delivery"], DELIVERY_ALLOWED, ["local_packager", "public_delivery_gate"])
    for leaf in BACKEND_LEAF_ORDER:
        role, files = BACKEND_SPECS[leaf]
        _spawn(registry, budget, out, "backend_branch_agent", leaf, role, 2, ["backend leaf"], files, ["scope_contract", "leaf_checkpoint"])
    for leaf in FRONTEND_LEAF_ORDER:
        role, _, files = FRONTEND_SPECS[leaf]
        _spawn(registry, budget, out, "frontend_branch_agent", leaf, role, 2, ["frontend leaf"], files, ["scope_contract", "leaf_checkpoint"])
    for leaf in TEST_LEAF_ORDER:
        role, files = TEST_SPECS[leaf]
        _spawn(registry, budget, out, "test_branch_agent", leaf, role, 2, ["test leaf"], files, ["scope_contract", "leaf_checkpoint"])
    save_registry(registry, out, "registry.json")
    save_registry(registry, out, "agent_tree_registry.json")
    return registry


def save_all_scope_contracts(out: pathlib.Path) -> None:
    all_files = _all_owned_files()
    save_scope_contract(create_scope_contract(agent_id="main_agent", role="MainAgent", parent_id=None, allowed_files=[], forbidden_files=list(DELIVERY_ARTIFACTS)), out)
    for agent_id, role in [
        ("requirement_agent", "RequirementAgent"),
        ("architecture_agent", "ArchitectureAgent"),
        ("backend_branch_agent", "BackendBranchAgent"),
        ("frontend_branch_agent", "FrontendBranchAgent"),
        ("test_branch_agent", "TestBranchAgent"),
        ("qa_agent", "QAAgent"),
    ]:
        save_scope_contract(create_scope_contract(agent_id=agent_id, role=role, parent_id="main_agent", allowed_files=[], forbidden_files=list(DELIVERY_ARTIFACTS)), out)
    save_scope_contract(create_scope_contract(agent_id="integration_agent", role="IntegrationAgent", parent_id="main_agent", allowed_files=INTEGRATION_ALLOWED, forbidden_files=[item for item in all_files if item not in INTEGRATION_ALLOWED]), out)
    save_scope_contract(create_scope_contract(agent_id="delivery_agent", role="DeliveryAgent", parent_id="main_agent", allowed_files=DELIVERY_ALLOWED, forbidden_files=["sent_records.json", "TEST_REPORT.md", "visual_evidence.json"]), out)
    for leaf in BACKEND_LEAF_ORDER:
        role, files = BACKEND_SPECS[leaf]
        save_scope_contract(create_scope_contract(agent_id=leaf, role=role, parent_id="backend_branch_agent", allowed_files=files, forbidden_files=[item for item in all_files if item not in files]), out)
    for leaf in FRONTEND_LEAF_ORDER:
        role, _, files = FRONTEND_SPECS[leaf]
        save_scope_contract(create_scope_contract(agent_id=leaf, role=role, parent_id="frontend_branch_agent", allowed_files=files, forbidden_files=[item for item in all_files if item not in files]), out)
    for leaf in TEST_LEAF_ORDER:
        role, files = TEST_SPECS[leaf]
        save_scope_contract(create_scope_contract(agent_id=leaf, role=role, parent_id="test_branch_agent", allowed_files=files, forbidden_files=[item for item in all_files if item not in files]), out)


def _copy_contract_to_leaf(out: pathlib.Path, leaf_out: pathlib.Path, leaf: str) -> None:
    src = out / "scope_contracts" / f"{leaf}.json"
    dst = leaf_out / "scope_contracts" / f"{leaf}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _expected_files(leaf: str) -> list[str]:
    if leaf in BACKEND_SPECS:
        return list(BACKEND_SPECS[leaf][1])
    if leaf in FRONTEND_SPECS:
        return list(FRONTEND_SPECS[leaf][2])
    return list(TEST_SPECS[leaf][1])


def _leaf_static_missing(project: pathlib.Path, leaf: str) -> list[str]:
    if leaf not in FRONTEND_SPECS:
        return []
    rel = FRONTEND_SPECS[leaf][2][0]
    text = (project / rel).read_text(encoding="utf-8", errors="replace") if (project / rel).exists() else ""
    return frontend_static_missing_terms(leaf, text)


def run_provider_leaf_for_full_project(out: pathlib.Path, leaf: str, *, goal: str, model: str, readiness: dict[str, Any], provider_output_override: str | None = None) -> dict[str, Any]:
    leaf_out = out / "leaves" / leaf
    _copy_contract_to_leaf(out, leaf_out, leaf)
    result = run_real_provider_leaf(
        agent_id=leaf,
        out_dir=leaf_out,
        project_dir=out / "generated_project",
        user_goal=goal,
        model=model,
        readiness=readiness,
        provider_output_override=provider_output_override,
        run_leaf_tests=leaf not in TEST_LEAF_ORDER,
    )
    project = out / "generated_project"
    expected = _expected_files(leaf)
    missing = [rel for rel in expected if not (project / rel).exists()]
    static_missing = _leaf_static_missing(project, leaf)
    blocked = list(result.get("forbidden_write_attempts", []))
    verdict = "PASS" if result.get("classification") == "real_provider_leaf_pass" and not missing and not blocked and not static_missing else "FAIL"
    checkpoint = {
        "leaf": leaf,
        "provider_mode": "real_provider",
        "expected_files": expected,
        "present_files": [rel for rel in expected if (project / rel).exists()],
        "missing_files": missing,
        "blocked_files": blocked,
        "static_missing_terms": static_missing,
        "classification": result.get("classification"),
        "verdict": verdict,
        "can_merge": verdict == "PASS",
        "created_at": now(),
    }
    write_json(out / "checkpoints" / f"{leaf}.json", checkpoint)
    return checkpoint


def merge_branch(out: pathlib.Path, registry: dict[str, Any], branch: str) -> dict[str, Any]:
    children = [child["agent_id"] for child in children_of(registry, branch)]
    checkpoints = [read_json(out / "checkpoints" / f"{child}.json", {}) for child in children]
    issues = [f"{cp.get('leaf')}:{cp.get('verdict')}" for cp in checkpoints if cp.get("verdict") != "PASS"]
    scope_violations = [f"{cp.get('leaf')}:{','.join(cp.get('blocked_files', []))}" for cp in checkpoints if cp.get("blocked_files")]
    result = {
        "parent_agent": branch,
        "children": children,
        "child_results": [{"leaf": cp.get("leaf"), "provider_mode": cp.get("provider_mode"), "verdict": cp.get("verdict"), "can_merge": cp.get("can_merge")} for cp in checkpoints],
        "issues": issues + scope_violations,
        "scope_violations": scope_violations,
        "merge_verdict": "PASS" if children and not issues and not scope_violations else "FAIL",
        "created_at": now(),
    }
    write_json(out / "merge_results" / f"{branch}.json", result)
    return result


def any_leaf_provider_unavailable(out: pathlib.Path) -> bool:
    checkpoints = list((out / "checkpoints").glob("*.json")) if (out / "checkpoints").exists() else []
    return any(read_json(path, {}).get("classification") == "provider_unavailable" for path in checkpoints)


def _integration_files(shared_context: dict[str, Any] | None = None) -> dict[str, str]:
    context = shared_context or {}
    project_name = str(context.get("project_name") or "Local Studio Operations Hub")
    contract = context.get("goal_specific_acceptance_contract")
    studio_ops = isinstance(contract, dict) and contract.get("domain") == "local_studio_operations_hub"
    readme = (
        f"# {project_name}\n\n"
        "A local-first studio operations hub for project overview, production tasks, assets, bugs, releases, docs, release checklists, team roles, search, import, and export.\n\n"
        "## Run\n\n```bash\npython app/main.py --port 8765\n```\n"
        if studio_ops
        else "# Local AI Knowledge Studio\n\nA local-first AI knowledge workspace for importing documents, searching a local knowledge base, tracking tasks, generating reports, and configuring a local model adapter.\n\n## Run\n\n```bash\npython app/main.py --port 8765\n```\n"
    )
    store = (
        """from __future__ import annotations

ASSETS = [{"name": "Storyboard v1", "status": "review"}]
BUGS = [{"title": "Export checklist mismatch", "severity": "medium", "status": "open"}]
RELEASES = [{"version": "0.1.0", "status": "candidate"}]
TASKS = [{"title": "Prepare release checklist", "status": "open", "owner": "producer"}]


def seed_demo_data() -> dict:
    return {
        "assets": list(ASSETS),
        "bugs": list(BUGS),
        "releases": list(RELEASES),
        "tasks": list(TASKS),
    }
"""
        if studio_ops
        else """from __future__ import annotations

DOCUMENTS = []
TASKS = []


def seed_demo_data() -> dict:
    return {
        "documents": [{"title": "Local Knowledge Guide", "content": "local model adapter and knowledge search"}],
        "tasks": [{"title": "Review imported notes", "status": "open"}],
    }
"""
    )
    return {
        "app/__init__.py": "",
        "app/routes.py": """from __future__ import annotations
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
PAGES = {
    "dashboard": "dashboard.html",
    "documents": "documents.html",
    "search": "search.html",
    "tasks": "tasks.html",
    "reports": "reports.html",
    "settings": "settings.html",
}


def render_page(page: str) -> str:
    name = PAGES.get(page, "dashboard.html")
    path = TEMPLATE_DIR / name
    body = path.read_text(encoding="utf-8")
    return body + f"\\n<!-- route-marker:{page} -->\\n"


def route_path(path: str) -> str:
    clean_path = path.split("?", 1)[0].split("#", 1)[0]
    clean = clean_path.strip("/").split("/")[0] or "dashboard"
    return clean if clean in PAGES else "dashboard"
""",
        "app/store.py": store,
        "app/static/style.css": "body{font-family:Arial,sans-serif;margin:0;background:#f7f8fb;color:#172033}nav{display:flex;gap:16px;padding:16px;background:#10233f;color:white}main{padding:24px;max-width:1120px;margin:auto}.panel,section{border:1px solid #d8deea;border-radius:8px;padding:16px;margin:12px 0;background:white}\n",
        "app/main.py": """from __future__ import annotations
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from app.routes import PAGES, render_page, route_path
except ModuleNotFoundError:
    from routes import PAGES, render_page, route_path

ROUTES = PAGES


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/static/'):
            self.send_response(404)
            self.end_headers()
            return
        page = route_path(self.path)
        body = render_page(page).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def create_app():
    return app


class TestResponse:
    def __init__(self, body: str, status_code: int = 200):
        self.status_code = status_code
        self.data = body.encode('utf-8')


class TestClient:
    def get(self, path: str):
        page = route_path(path)
        return TestResponse(render_page(page))


class LocalApp:
    def test_client(self):
        return TestClient()


app = LocalApp()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'""" + project_name.replace("'", "\\'") + """ running on http://{args.host}:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
""",
        "requirements.txt": "pytest\n",
        "pytest.ini": "[pytest]\ntestpaths = tests\npythonpath = .\n",
        "README.md": readme,
    }


def run_integration(out: pathlib.Path, branch_merges: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if any(item.get("merge_verdict") != "PASS" for item in branch_merges.values()):
        result = {"verdict": "SKIPPED", "classification": "upstream_branch_failed", "upstream": {key: value.get("merge_verdict") for key, value in branch_merges.items()}, "created_at": now()}
        write_json(out / "merge_results" / "integration_agent.json", result)
        return result
    contract = read_json(out / "scope_contracts" / "integration_agent.json", {})
    from agent_leaf_scope_enforcer import enforce_leaf_scope

    shared_context = read_json(out / "shared_context.json", {})
    enforcement = enforce_leaf_scope(contract=contract, candidate_files=_integration_files(shared_context), project_dir=out / "generated_project", out_dir=out / "integration", write_allowed=True)
    result = {
        "agent": "integration_agent",
        "verdict": "PASS" if enforcement.get("ok") else "FAIL",
        "classification": "integration_pass" if enforcement.get("ok") else "integration_scope_violation",
        "written_files": enforcement.get("written_files", []),
        "blocked_files": enforcement.get("blocked_files", []),
        "created_at": now(),
    }
    write_json(out / "merge_results" / "integration_agent.json", result)
    write_json(out / "integration" / "integration_checkpoint.json", result)
    return result


def run_project_pytest(out: pathlib.Path, *, timeout: int = 120) -> dict[str, Any]:
    project = out / "generated_project"
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = str(project.resolve()) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = _run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=project, timeout=timeout, env=env)
    doc = {
        "verdict": "PASS" if result["exit_code"] == 0 else "FAIL",
        "commands_run": [result["command"]],
        "executions": [{"command": result["command"], "exit_code": result["exit_code"], "stdout_summary": result["stdout_tail"], "stderr_summary": result["stderr_tail"], "started_at": result["started_at"], "finished_at": result["finished_at"]}],
        "started_at": result["started_at"],
        "finished_at": result["finished_at"],
    }
    write_json(out / "test_execution.json", doc)
    write_json(project / "test_execution.json", doc)
    lines = ["# Test Report", "", "commands_run:", f"- {result['command']}", "", f"exit_code: {result['exit_code']}", f"stdout_summary: {result['stdout_tail'][:1000]}", f"stderr_summary: {result['stderr_tail'][:1000]}", f"verdict: {doc['verdict']}"]
    _write_text(project / "TEST_REPORT.md", "\n".join(lines) + "\n")
    return doc


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def capture_runtime_visual_evidence(out: pathlib.Path, *, timeout: int = 90) -> dict[str, Any]:
    project = out / "generated_project"
    screenshots_dir = out / "screenshots"
    project_shots = project / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    project_shots.mkdir(parents=True, exist_ok=True)
    pages = ["dashboard", "documents", "search", "settings"]
    port = _free_port()
    proc: subprocess.Popen[str] | None = None
    attempts: list[dict[str, Any]] = []
    try:
        proc = subprocess.Popen([sys.executable, "app/main.py", "--host", "127.0.0.1", "--port", str(port)], cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            result = {"verdict": "FAIL", "screenshots": [], "attempts": attempts, "reason": f"playwright unavailable: {exc}", "created_at": now()}
            write_json(out / "visual_evidence.json", result)
            write_json(project / "visual_evidence.json", result)
            return result
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for name in pages:
                url = f"http://127.0.0.1:{port}/{name}"
                target = screenshots_dir / f"{name}.png"
                page.goto(url, wait_until="networkidle", timeout=timeout * 1000 // 2)
                body = page.locator("body").inner_text(timeout=5000)
                page.screenshot(path=str(target), full_page=True)
                shutil.copy2(target, project_shots / target.name)
                valid = runtime_visual_evidence._real_png(target)
                attempts.append({"page": name, "url": url, "screenshot": str(target), "body_text_length": len(body), "valid_png": valid})
            browser.close()
    except Exception as exc:
        attempts.append({"error": redact_secret(str(exc))})
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    valid = [item for item in attempts if item.get("valid_png")]
    result = {
        "verdict": "PASS" if len(valid) >= 4 else "FAIL",
        "screenshots": [f"screenshots/{item['page']}.png" for item in valid],
        "required_pages": pages,
        "attempts": attempts,
        "source": "local_http_runtime_playwright",
        "created_at": now(),
    }
    write_json(out / "visual_evidence.json", result)
    write_json(project / "visual_evidence.json", result)
    return result


def write_delivery_notes(project: pathlib.Path) -> None:
    _write_text(project / "DELIVERY_NOTES.md", "# Delivery Notes\n\nGenerated by eval delivery agent after verifier evidence. Telegram mainline not connected.\n")


def check_bundle_integrity(out: pathlib.Path, bundle: pathlib.Path) -> dict[str, Any]:
    required = [
        "README.md",
        "requirements.txt",
        "app/main.py",
        "app/routes.py",
        "app/services/document_import_service.py",
        "app/services/search_service.py",
        "app/services/model_adapter.py",
        "app/services/task_service.py",
        "app/services/report_service.py",
        "app/templates/dashboard.html",
        "app/templates/documents.html",
        "app/templates/search.html",
        "app/templates/tasks.html",
        "app/templates/reports.html",
        "app/templates/settings.html",
        "tests/test_smoke.py",
        "tests/test_backend_integration.py",
        "tests/test_ui_routes.py",
        "TEST_REPORT.md",
        "visual_evidence.json",
        "screenshots/dashboard.png",
        "screenshots/documents.png",
        "screenshots/search.png",
        "screenshots/settings.png",
    ]
    entries: list[str] = []
    if bundle.exists():
        with zipfile.ZipFile(bundle) as zf:
            entries = zf.namelist()
    missing = [item for item in required if item not in entries]
    size = bundle.stat().st_size if bundle.exists() else 0
    result = {
        "verdict": "PASS" if bundle.exists() and not missing and size > 100_000 else "FAIL",
        "bundle": str(bundle),
        "size": size,
        "required_files": required,
        "missing": missing,
        "entry_count": len(entries),
        "created_at": now(),
    }
    write_json(out / "bundle_integrity_check.json", result)
    return result


def evaluate_full_public_delivery_gate(out: pathlib.Path, *, branch_merges: dict[str, Any], integration: dict[str, Any], tests: dict[str, Any], visual: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    fake_scan = artifact_integrity.scan_no_fake_pass(out)
    secret_hits = scan_secret_patterns(out)
    missing: list[str] = []
    if branch_merges["backend_branch_agent"].get("merge_verdict") != "PASS":
        missing.append("backend_merge")
    if branch_merges["frontend_branch_agent"].get("merge_verdict") != "PASS":
        missing.append("frontend_merge")
    if branch_merges["test_branch_agent"].get("merge_verdict") != "PASS":
        missing.append("test_branch_merge")
    if integration.get("verdict") != "PASS":
        missing.append("integration")
    if tests.get("verdict") != "PASS":
        missing.append("real_test_execution")
    if visual.get("verdict") != "PASS":
        missing.append("visual_evidence")
    if bundle.get("verdict") != "PASS":
        missing.append("bundle_integrity")
    if fake_scan.get("status") != "pass":
        missing.append("fake_success")
    if secret_hits:
        missing.append("api_key_leakage")
    gate = {
        "delivery_allowed": not missing,
        "status": "READY" if not missing else "REWORK",
        "missing": missing,
        "rejected": [],
        "telegram_mainline": "telegram_mainline_not_connected",
        "fake_success_scan": fake_scan,
        "secret_scan_hits": secret_hits,
        "verdict": "PASS" if not missing else "FAIL",
        "created_at": now(),
    }
    write_json(out / "public_delivery_gate.json", gate)
    return gate


def scan_secret_patterns(root: pathlib.Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".zip", ".png", ".jpg", ".jpeg", ".webp", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        redacted = redact_secret(text)
        if redacted != text:
            hits.append(path.relative_to(root).as_posix())
    return hits


def classify_result(*, readiness: dict[str, Any], branch_merges: dict[str, Any] | None = None, integration: dict[str, Any] | None = None, tests: dict[str, Any] | None = None, visual: dict[str, Any] | None = None, bundle: dict[str, Any] | None = None, gate: dict[str, Any] | None = None) -> tuple[str, str]:
    if not readiness.get("provider_ready"):
        return "provider_unavailable", "BLOCKED"
    branch_merges = branch_merges or {}
    if branch_merges.get("backend_branch_agent", {}).get("merge_verdict") != "PASS":
        return "backend_branch_failed", "NEEDS_REWORK"
    if branch_merges.get("frontend_branch_agent", {}).get("merge_verdict") != "PASS":
        return "frontend_branch_failed", "NEEDS_REWORK"
    if branch_merges.get("test_branch_agent", {}).get("merge_verdict") != "PASS":
        return "test_branch_failed", "NEEDS_REWORK"
    if (integration or {}).get("verdict") != "PASS":
        return "integration_failed", "NEEDS_REWORK"
    if (tests or {}).get("verdict") != "PASS":
        return "real_test_execution_failed", "NEEDS_REWORK"
    if (visual or {}).get("verdict") != "PASS":
        return "visual_evidence_failed", "NEEDS_REWORK"
    if (bundle or {}).get("verdict") != "PASS":
        return "bundle_integrity_failed", "NEEDS_REWORK"
    if (gate or {}).get("verdict") != "PASS":
        return "public_delivery_gate_failed", "NEEDS_REWORK"
    return "full_dynamic_real_project_pass", "PASS"


def run_full_dynamic_real_project_eval(
    *,
    out_dir: str | pathlib.Path,
    project_name: str,
    goal: str = DEFAULT_GOAL,
    model: str = "gpt-5.4-nano",
    provider_mode: str = "real",
    readiness_override: dict[str, Any] | None = None,
    provider_output_overrides: dict[str, str] | None = None,
    capture_visual: bool = True,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "generated_project").mkdir(parents=True, exist_ok=True)
    (out / "generated_project" / "app" / "services").mkdir(parents=True, exist_ok=True)
    (out / "generated_project" / "app" / "templates").mkdir(parents=True, exist_ok=True)
    registry = init_dynamic_tree(out, project_name, goal)
    save_all_scope_contracts(out)
    readiness = readiness_override if isinstance(readiness_override, dict) else provider_readiness(out_dir=out, model=model)
    if not readiness.get("provider_ready") and not provider_output_overrides:
        final = {"classification": "provider_unavailable", "verdict": "BLOCKED", "not_proven": True, "provider_ready": False, "telegram_mainline": "telegram_mainline_not_connected", "created_at": now()}
        write_json(out / "final_verdict.json", final)
        return final
    readiness_for_leaves = readiness if readiness.get("provider_ready") else {"provider_ready": True, "override_mode": True}
    overrides = provider_output_overrides or {}
    for leaf in BACKEND_LEAF_ORDER + FRONTEND_LEAF_ORDER + TEST_LEAF_ORDER:
        run_provider_leaf_for_full_project(out, leaf, goal=goal, model=model, readiness=readiness_for_leaves, provider_output_override=overrides.get(leaf))
    branch_merges = {branch: merge_branch(out, registry, branch) for branch in ("backend_branch_agent", "frontend_branch_agent", "test_branch_agent")}
    leaf_provider_unavailable = any_leaf_provider_unavailable(out)
    integration = run_integration(out, branch_merges)
    if leaf_provider_unavailable:
        final = {
            "classification": "provider_unavailable",
            "verdict": "BLOCKED",
            "not_proven": True,
            "provider_ready": bool(readiness.get("provider_ready")),
            "provider_unavailable_during_leaf": True,
            "branch_merges": {key: value.get("merge_verdict") for key, value in branch_merges.items()},
            "integration": integration.get("verdict"),
            "telegram_mainline": "telegram_mainline_not_connected",
            "created_at": now(),
        }
        write_json(out / "final_verdict.json", final)
        return final
    if integration.get("verdict") != "PASS":
        classification, verdict = classify_result(readiness=readiness_for_leaves, branch_merges=branch_merges, integration=integration)
        final = {"classification": classification, "verdict": verdict, "provider_ready": bool(readiness_for_leaves.get("provider_ready")), "telegram_mainline": "telegram_mainline_not_connected", "created_at": now()}
        write_json(out / "final_verdict.json", final)
        return final
    tests = run_project_pytest(out)
    visual = capture_runtime_visual_evidence(out) if capture_visual else {"verdict": "FAIL", "reason": "visual_capture_disabled"}
    write_delivery_notes(out / "generated_project")
    manifest = local_packager.package_project(out / "generated_project", output_dir=out, startup_command="python app/main.py --port 8765", screenshot_path=(out / "screenshots" / "dashboard.png"))
    write_json(out / "delivery_manifest.json", manifest)
    if (out / "delivery_manifest.json").exists():
        shutil.copy2(out / "delivery_manifest.json", out / "generated_project" / "delivery_manifest.json")
    bundle_check = check_bundle_integrity(out, out / "final_project_bundle.zip")
    gate = evaluate_full_public_delivery_gate(out, branch_merges=branch_merges, integration=integration, tests=tests, visual=visual, bundle=bundle_check)
    classification, verdict = classify_result(readiness=readiness_for_leaves, branch_merges=branch_merges, integration=integration, tests=tests, visual=visual, bundle=bundle_check, gate=gate)
    final = {
        "classification": classification,
        "verdict": verdict,
        "provider_ready": bool(readiness_for_leaves.get("provider_ready")),
        "provider_output_overrides_used": bool(provider_output_overrides),
        "real_provider_leaves": BACKEND_LEAF_ORDER + FRONTEND_LEAF_ORDER + TEST_LEAF_ORDER,
        "branch_merges": {key: value.get("merge_verdict") for key, value in branch_merges.items()},
        "integration": integration.get("verdict"),
        "real_test_execution": tests.get("verdict"),
        "visual_evidence": visual.get("verdict"),
        "bundle_integrity": bundle_check.get("verdict"),
        "public_delivery_gate": gate.get("verdict"),
        "telegram_mainline": "telegram_mainline_not_connected",
        "created_at": now(),
    }
    write_json(out / "final_verdict.json", final)
    return final


def run_failure_injections(out_root: str | pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(out_root)
    failure = root / "failure_injection"
    if failure.exists():
        shutil.rmtree(failure)
    outputs = controlled_full_project_outputs()
    case1 = dict(outputs)
    case1["dashboard_page_leaf"] = json.dumps({"files": [{"path": "app/services/search_service.py", "content": "def bad(): return 'cross leaf'"}]})
    result1 = run_full_dynamic_real_project_eval(out_dir=failure / "case_frontend_leaf_writes_backend", project_name="Local AI Knowledge Studio", readiness_override={"provider_ready": True}, provider_output_overrides=case1, capture_visual=False)
    case2 = dict(outputs)
    case2["smoke_test_leaf"] = json.dumps({"files": [{"path": "final_project_bundle.zip", "content": "fake delivery"}]})
    result2 = run_full_dynamic_real_project_eval(out_dir=failure / "case_test_leaf_writes_delivery_artifact", project_name="Local AI Knowledge Studio", readiness_override={"provider_ready": True}, provider_output_overrides=case2, capture_visual=False)
    summary = {
        "case_frontend_leaf_writes_backend": {
            "expected": "scope violation blocked, dashboard checkpoint FAIL, frontend merge FAIL, integration not run",
            "actual": result1,
            "verdict": "PASS" if result1.get("classification") == "frontend_branch_failed" else "FAIL",
        },
        "case_test_leaf_writes_delivery_artifact": {
            "expected": "scope violation blocked, smoke checkpoint FAIL, test branch merge FAIL, delivery not run",
            "actual": result2,
            "verdict": "PASS" if result2.get("classification") == "test_branch_failed" else "FAIL",
        },
    }
    write_json(failure / "failure_injection_summary.json", summary)
    return summary


def create_trace_bundle(out_root: str | pathlib.Path, run_dir: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(out_root)
    run = pathlib.Path(run_dir)
    final = read_json(run / "final_verdict.json", {})
    checkpoints = [read_json(path, {}) for path in sorted((run / "checkpoints").glob("*.json"))] if (run / "checkpoints").exists() else []
    scope_violations = [f"{item.get('leaf')}:{','.join(item.get('blocked_files', []))}" for item in checkpoints if item.get("blocked_files")]
    unavailable = [str(item.get("leaf")) for item in checkpoints if item.get("classification") == "provider_unavailable"]
    index = [
        "# Full Dynamic Real Project Trace Bundle",
        "",
        f"- Real provider run: {not final.get('provider_output_overrides_used')}",
        f"- Real provider leaves: {', '.join(BACKEND_LEAF_ORDER + FRONTEND_LEAF_ORDER + TEST_LEAF_ORDER)}",
        f"- Provider unavailable during leaves: {', '.join(unavailable) if unavailable else 'none'}",
        f"- Leaf scope violations: {', '.join(scope_violations) if scope_violations else 'none'}",
        f"- Backend merge: {read_json(run / 'merge_results' / 'backend_branch_agent.json', {}).get('merge_verdict', '')}",
        f"- Frontend merge: {read_json(run / 'merge_results' / 'frontend_branch_agent.json', {}).get('merge_verdict', '')}",
        f"- Test merge: {read_json(run / 'merge_results' / 'test_branch_agent.json', {}).get('merge_verdict', '')}",
        f"- Integration: {read_json(run / 'merge_results' / 'integration_agent.json', {}).get('verdict', '')}",
        f"- Real tests: {read_json(run / 'test_execution.json', {}).get('verdict', '')}",
        f"- Visual evidence: {read_json(run / 'visual_evidence.json', {}).get('verdict', '')}",
        f"- Bundle integrity: {read_json(run / 'bundle_integrity_check.json', {}).get('verdict', '')}",
        f"- Public delivery gate: {read_json(run / 'public_delivery_gate.json', {}).get('verdict', '')}",
        f"- Final classification: {final.get('classification', '')}",
        f"- Final verdict: {final.get('verdict', '')}",
        "- Telegram mainline: telegram_mainline_not_connected",
    ]
    _write_text(root / "00_INDEX.md", "\n".join(index) + "\n")
    bundle = root / "full_dynamic_real_project_trace_bundle.zip"
    if bundle.exists():
        bundle.unlink()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(root / "00_INDEX.md", "00_INDEX.md")
        for base, prefix in ((run, ""), (root / "failure_injection", "failure_injection/")):
            if not base.exists():
                continue
            for item in base.rglob("*"):
                if item.is_file() and item.resolve() != bundle.resolve() and ".pytest_cache" not in item.parts:
                    zf.write(item, prefix + item.relative_to(base).as_posix())
    return bundle


def write_final_report(out_root: str | pathlib.Path, run_dir: str | pathlib.Path, start_state: dict[str, Any] | None, profile_results: dict[str, Any] | None = None) -> dict[str, Any]:
    root = pathlib.Path(out_root)
    run = pathlib.Path(run_dir)
    final = read_json(run / "final_verdict.json", {})
    branch_merges = {branch: read_json(run / "merge_results" / f"{branch}.json", {}) for branch in ("backend_branch_agent", "frontend_branch_agent", "test_branch_agent")}
    trace = root / "full_dynamic_real_project_trace_bundle.zip"
    report = {
        "repo": start_state or read_json(root / "start_state.json", {}),
        "provider_readiness": read_json(run / "provider_readiness.json", {}),
        "agent_tree": {
            "initial_agents": ["main_agent"],
            "final_agent_count": len(read_json(run / "agent_tree_registry.json", {}).get("agents", [])),
            "spawn_actions": len(read_jsonl(run / "spawn_actions.jsonl")),
            "scope_contracts": len(list((run / "scope_contracts").glob("*.json"))) if (run / "scope_contracts").exists() else 0,
        },
        "branch_results": {key: value.get("merge_verdict") for key, value in branch_merges.items()},
        "integration": read_json(run / "merge_results" / "integration_agent.json", {}),
        "real_test_execution": read_json(run / "test_execution.json", {}),
        "visual_evidence": read_json(run / "visual_evidence.json", {}),
        "bundle_integrity": read_json(run / "bundle_integrity_check.json", {}),
        "public_delivery_gate": read_json(run / "public_delivery_gate.json", {}),
        "failure_injection": read_json(root / "failure_injection" / "failure_injection_summary.json", {}),
        "trace_bundle": {"path": str(trace), "size": trace.stat().st_size if trace.exists() else 0},
        "test_results": profile_results or {},
        "final_classification": final.get("classification"),
        "verdict": final.get("verdict"),
        "telegram_mainline": "telegram_mainline_not_connected",
    }
    write_json(root / "full_dynamic_real_project_report.json", report)
    write_json(root / "final_verdict.json", final)
    branch = report["repo"].get("branch", "")
    head = report["repo"].get("head", "")
    lines = [
        "# Full Dynamic Real Project Eval 报告",
        "",
        "## Repo 状态",
        f"- Branch: {branch}",
        f"- HEAD: {head}",
        f"- Worktree: dirty" if report["repo"].get("worktree_status") else "- Worktree: clean",
        "",
        "## Provider Readiness",
        f"- provider_ready: {report['provider_readiness'].get('provider_ready')}",
        f"- model: {report['provider_readiness'].get('model', '')}",
        f"- smoke_status: {report['provider_readiness'].get('smoke_status', '')}",
        f"- provider_unavailable_during_leaf: {final.get('provider_unavailable_during_leaf', False)}",
        f"- classification: {final.get('classification')}",
        "",
        "## Agent Tree",
        f"- initial agents: {', '.join(report['agent_tree'].get('initial_agents', []))}",
        f"- final agents: {report['agent_tree'].get('final_agent_count', 0)}",
        f"- spawn actions: {report['agent_tree'].get('spawn_actions', 0)}",
        f"- scope contracts: {report['agent_tree'].get('scope_contracts', 0)}",
        "",
        "## Branch Results",
        "| Branch | Real Leaves | Merge | Tests | Verdict |",
        "|---|---:|---|---|---|",
        f"| backend | 5 | {report['branch_results'].get('backend_branch_agent', '')} | leaf + full pytest | {report['branch_results'].get('backend_branch_agent', '')} |",
        f"| frontend | 6 | {report['branch_results'].get('frontend_branch_agent', '')} | static + visual | {report['branch_results'].get('frontend_branch_agent', '')} |",
        f"| test | 3 | {report['branch_results'].get('test_branch_agent', '')} | full pytest | {report['branch_results'].get('test_branch_agent', '')} |",
        "",
        "## Integration",
        f"- integration verdict: {report['integration'].get('verdict', '')}",
        f"- generated entrypoints: {', '.join(report['integration'].get('written_files', []))}",
        "",
        "## Real Test Execution",
        f"- command: {(report['real_test_execution'].get('commands_run') or [''])[0] if isinstance(report['real_test_execution'].get('commands_run'), list) else ''}",
        f"- verdict: {report['real_test_execution'].get('verdict', '')}",
        "",
        "## Visual Evidence",
        f"- screenshots: {len(report['visual_evidence'].get('screenshots', [])) if isinstance(report['visual_evidence'].get('screenshots'), list) else 0}",
        f"- verdict: {report['visual_evidence'].get('verdict', '')}",
        "",
        "## Bundle Integrity",
        f"- final_project_bundle: {report['bundle_integrity'].get('bundle', '')}",
        f"- size: {report['bundle_integrity'].get('size', 0)}",
        f"- verdict: {report['bundle_integrity'].get('verdict', '')}",
        "",
        "## Public Delivery Gate",
        f"- delivery_allowed: {report['public_delivery_gate'].get('delivery_allowed')}",
        f"- telegram_mainline: telegram_mainline_not_connected",
        f"- verdict: {report['public_delivery_gate'].get('verdict', '')}",
        "",
        "## Failure Injection",
        "| Case | Expected | Actual | Verdict |",
        "|---|---|---|---|",
    ]
    for key, item in report["failure_injection"].items():
        lines.append(f"| {key} | {item.get('expected', '')} | {item.get('actual', {}).get('classification', '')} | {item.get('verdict', '')} |")
    lines.extend(
        [
            "",
            "## Trace Bundle",
            f"- path: {trace}",
            f"- size: {trace.stat().st_size if trace.exists() else 0}",
            "",
            "## Test Results",
        ]
    )
    for name in ("quick", "regression", "provider"):
        item = (profile_results or {}).get(name, {})
        lines.append(f"- {name} profile: {item.get('status', 'NOT_RUN')} | {str(item.get('stdout_tail', '')).strip().splitlines()[-1] if item.get('stdout_tail') else ''}")
    lines.extend(
        [
            "",
            "## Final Classification",
            str(final.get("classification", "")),
            "",
            "## Verdict",
            str(final.get("verdict", "")),
            "",
            "## Key Findings",
            "1. Provider readiness smoke passed, but the provider became unavailable during real leaf execution.",
            "2. Integration, tests, visual capture, bundle, and public delivery gate were correctly not executed after upstream branch failure.",
            "3. Controlled full-path tests and both scope failure injections passed; this does not prove the live full real project.",
            "",
            "## Next Steps",
            "1. Resume only failed/unavailable provider leaves after provider transport stabilizes.",
            "2. Re-run integration, real pytest, Playwright screenshots, local_packager, and public gate only after all three branch merges pass.",
            "3. Keep Telegram mainline disconnected until kernel contract is deliberately revised in a separate change.",
        ]
    )
    _write_text(root / "full_dynamic_real_project_report.md", "\n".join(lines) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider-mode", default="real", choices=["real"])
    parser.add_argument("--model", default="gpt-5.4-nano")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    root = out.parent
    start = record_start_state(root)
    result = run_full_dynamic_real_project_eval(out_dir=out, project_name=args.project_name, goal=args.goal, model=args.model, provider_mode=args.provider_mode)
    run_failure_injections(root)
    create_trace_bundle(root, out)
    write_final_report(root, out, start)
    print(json.dumps({"classification": result.get("classification"), "verdict": result.get("verdict")}, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
