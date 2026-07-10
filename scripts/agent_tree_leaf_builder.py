from __future__ import annotations

import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_tree_action_protocol import AgentActionRecorder
    from agent_tree_contracts import now, write_json
    import local_packager
    import real_test_execution
    import runtime_visual_evidence
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_action_protocol import AgentActionRecorder
    from scripts.agent_tree_contracts import now, write_json
    from scripts import local_packager, real_test_execution, runtime_visual_evidence


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _record(recorder: AgentActionRecorder, stage: dict[str, Any], local_context: dict[str, Any], action: str, reason: str) -> None:
    recorder.record(
        agent_id=str(stage["agent"]),
        agent_role="LeafBuilder" if str(stage["agent"]).endswith("_leaf") else "SpecialistAgent",
        stage=str(stage["id"]),
        action=action,
        target_files=list(stage.get("expected_files", [])),
        outputs=list(stage.get("outputs", [])),
        reason=reason,
        input_context_id=str(local_context.get("context_id", "")),
        expected_verification=list(stage.get("verify", [])),
        claimed_complete=False,
    )


def build_controlled_stage(
    stage: dict[str, Any],
    *,
    shared_context: dict[str, Any],
    local_context: dict[str, Any],
    project_dir: str | pathlib.Path,
    out_dir: str | pathlib.Path,
    recorder: AgentActionRecorder,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    out = pathlib.Path(out_dir)
    stage_id = str(stage["id"])
    if stage_id == "requirement_freeze":
        _record(recorder, stage, local_context, "freeze_requirements", "Required by requirement_freeze stage in build DAG")
        frozen = {
            "kind": "AgentTreeFrozenRequirement",
            "project_name": shared_context["project_name"],
            "user_goal": shared_context["user_goal"],
            "requirements": list(shared_context["acceptance_contract"]),
            "allowed_context_terms": list(shared_context["allowed_context_terms"]),
            "forbidden_context_terms": list(shared_context["forbidden_context_terms"]),
            "created_at": now(),
        }
        shared_context["frozen_requirements"] = frozen["requirements"]
        write_json(out / "frozen_requirement.json", frozen)
        return {"status": "ok", "outputs": ["frozen_requirement.json"]}

    if stage_id == "foundation":
        _record(recorder, stage, local_context, "create_foundation_files", "Required by foundation stage in build DAG")
        _write(
            project / "README.md",
            "# Local AI Knowledge Studio\n\n"
            "A local-first knowledge workspace for document import, knowledge base search, summaries, tasks, reports, and local model adapter configuration.\n\n"
            "## Run\n\n```bash\npython app/main.py\n```\n\n"
            "Set `LOCAL_MODEL_ENDPOINT` or `MODEL_PATH` before enabling real local inference. If a model file or endpoint is missing, the app must not claim real inference.\n",
        )
        _write(project / "requirements.txt", "pytest\n")
        _write(project / "app" / "__init__.py", "")
        _write(
            project / "app" / "main.py",
            "from __future__ import annotations\n\n"
            "from app.services.document_service import import_document\n"
            "from app.services.search_service import search_documents\n"
            "from app.services.task_service import create_task\n"
            "from app.services.report_service import build_report\n\n"
            "def application_summary() -> dict:\n"
            "    doc = import_document('Welcome', 'Local knowledge base content')\n"
            "    task = create_task('Review imported material')\n"
            "    return {\n"
            "        'document': doc,\n"
            "        'search': search_documents('knowledge'),\n"
            "        'task': task,\n"
            "        'report': build_report([doc], [task]),\n"
            "    }\n\n"
            "if __name__ == '__main__':\n"
            "    print(application_summary())\n",
        )
        _write(project / "api_contract.json", '{"routes": ["/documents", "/search", "/tasks", "/reports", "/settings"]}\n')
        _write(project / "config" / "settings.example.env", "LOCAL_MODEL_ENDPOINT=http://localhost:11434\nMODEL_PATH=\n")
        return {"status": "ok"}

    if stage_id == "backend_services":
        _record(recorder, stage, local_context, "create_backend_services", "Required by backend_services stage in build DAG")
        _write(project / "app" / "services" / "__init__.py", "")
        _write(project / "app" / "services" / "storage.py", "DOCUMENTS = []\nTASKS = []\n")
        _write(
            project / "app" / "services" / "document_service.py",
            "from __future__ import annotations\n\nfrom app.services.storage import DOCUMENTS\n\n"
            "def import_document(title: str, content: str) -> dict:\n"
            "    item = {'id': len(DOCUMENTS) + 1, 'title': title, 'content': content}\n"
            "    DOCUMENTS.append(item)\n"
            "    return item\n",
        )
        _write(
            project / "app" / "services" / "search_service.py",
            "from __future__ import annotations\n\nfrom app.services.storage import DOCUMENTS\n\n"
            "def search_documents(query: str) -> list[dict]:\n"
            "    lowered = query.lower()\n"
            "    return [item for item in DOCUMENTS if lowered in item['content'].lower() or lowered in item['title'].lower()]\n",
        )
        _write(
            project / "app" / "services" / "model_adapter.py",
            "from __future__ import annotations\n\n"
            "def adapter_status(config: dict | None = None) -> dict:\n"
            "    config = config or {}\n"
            "    endpoint = config.get('LOCAL_MODEL_ENDPOINT') or config.get('MODEL_PATH') or ''\n"
            "    return {'configured': bool(endpoint), 'limit': '' if endpoint else 'missing model file or endpoint; cannot claim real inference'}\n",
        )
        _write(
            project / "app" / "services" / "task_service.py",
            "from __future__ import annotations\n\nfrom app.services.storage import TASKS\n\n"
            "def create_task(title: str) -> dict:\n"
            "    task = {'id': len(TASKS) + 1, 'title': title, 'status': 'open'}\n"
            "    TASKS.append(task)\n"
            "    return task\n",
        )
        _write(
            project / "app" / "services" / "report_service.py",
            "from __future__ import annotations\n\n"
            "def build_report(documents: list[dict], tasks: list[dict]) -> dict:\n"
            "    return {'document_count': len(documents), 'task_count': len(tasks), 'sections': ['summary', 'tasks', 'next steps']}\n",
        )
        return {"status": "ok"}

    if stage_id == "frontend_views":
        _record(recorder, stage, local_context, "create_frontend_views", "Required by frontend_views stage in build DAG")
        pages = {
            "dashboard": "Dashboard",
            "documents": "Document Import",
            "search": "Knowledge Search",
            "tasks": "Tasks",
            "reports": "Reports",
            "settings": "Local Model Settings",
        }
        for name, title in pages.items():
            _write(
                project / "app" / "templates" / f"{name}.html",
                f"<!doctype html><html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>Local AI Knowledge Studio {title.lower()} view.</p></main></body></html>\n",
            )
        _write(
            project / "index.html",
            "<!doctype html><html><head><title>Local AI Knowledge Studio</title></head><body><nav>Dashboard Documents Search Tasks Reports Settings</nav><main>Local AI Knowledge Studio</main></body></html>\n",
        )
        return {"status": "ok"}

    if stage_id == "tests":
        _record(recorder, stage, local_context, "create_and_run_tests", "Required by tests stage in build DAG")
        _write(
            project / "tests" / "test_smoke.py",
            "from app.main import application_summary\n"
            "from app.services.model_adapter import adapter_status\n\n"
            "def test_application_summary_contains_core_sections():\n"
            "    summary = application_summary()\n"
            "    assert summary['document']['title'] == 'Welcome'\n"
            "    assert summary['search']\n"
            "    assert summary['report']['document_count'] >= 1\n\n"
            "def test_local_model_adapter_documents_missing_config_limit():\n"
            "    status = adapter_status({})\n"
            "    assert status['configured'] is False\n"
            "    assert 'missing model' in status['limit']\n",
        )
        result = real_test_execution.run_tests(project, timeout=60)
        return {"status": "ok" if result.get("verdict") == "PASS" else "fail", "test_result": result}

    if stage_id == "visual":
        _record(recorder, stage, local_context, "create_visual_evidence", "Required by visual stage in build DAG")
        for name in ("app_home", "search_results", "report_preview"):
            runtime_visual_evidence.write_runtime_preview_png(project / "screenshots" / f"{name}.png", title=name)
        result = runtime_visual_evidence.collect_visual_evidence(project)
        return {"status": "ok" if result.get("verdict") == "PASS" else "fail", "visual_result": result}

    if stage_id == "delivery":
        _record(recorder, stage, local_context, "package_delivery", "Required by delivery stage in build DAG")
        _write(project / "DELIVERY_NOTES.md", "# Delivery Notes\n\ncontrolled_agent_tree_lane: PASS\nnot_real_provider_proof: true\n")
        manifest = local_packager.package_project(
            project,
            output_dir=project,
            startup_command="python app/main.py",
            screenshot_path=project / "screenshots" / "app_home.png",
        )
        return {"status": "ok", "manifest": manifest}

    return {"status": "skipped", "reason": f"unknown stage {stage_id}"}
