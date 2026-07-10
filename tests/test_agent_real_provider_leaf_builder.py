from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_real_provider_leaf_builder
from scripts.agent_scope_contract import create_scope_contract, save_scope_contract

run_real_provider_leaf = agent_real_provider_leaf_builder.run_real_provider_leaf


def test_real_provider_leaf_builder_accepts_only_scoped_override_output(tmp_path: pathlib.Path) -> None:
    contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="SearchServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )
    save_scope_contract(contract, tmp_path)
    raw = json.dumps(
        {
            "files": [
                {
                    "path": "app/services/search_service.py",
                    "content": "def search_documents(documents, query):\n    return [d for d in documents if query.lower() in d.get('content','').lower()]\n",
                },
                {
                    "path": "tests/test_search_service.py",
                    "content": "import importlib.util\nfrom pathlib import Path\n\nspec = importlib.util.spec_from_file_location('search_service', Path('app/services/search_service.py'))\nmodule = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n\ndef test_search_documents():\n    assert module.search_documents([{'content':'local knowledge'}], 'knowledge')\n",
                },
            ]
        }
    )

    result = run_real_provider_leaf(
        agent_id="search_service_leaf",
        out_dir=tmp_path,
        project_dir=tmp_path / "project",
        user_goal="Local AI Knowledge Studio",
        readiness={"provider_ready": True},
        provider_output_override=raw,
    )

    assert result["classification"] == "real_provider_leaf_pass"
    assert result["checkpoint"] == "PASS"
    assert result["forbidden_write_attempts"] == []


def test_real_provider_leaf_builder_blocks_forbidden_provider_file(tmp_path: pathlib.Path) -> None:
    contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="SearchServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )
    save_scope_contract(contract, tmp_path)
    raw = json.dumps({"files": [{"path": "README.md", "content": "forbidden"}]})

    result = run_real_provider_leaf(
        agent_id="search_service_leaf",
        out_dir=tmp_path,
        project_dir=tmp_path / "project",
        user_goal="Local AI Knowledge Studio",
        readiness={"provider_ready": True},
        provider_output_override=raw,
    )

    assert result["classification"] == "real_provider_leaf_scope_violation_blocked"
    assert result["checkpoint"] == "FAIL"
    assert "README.md" in result["forbidden_write_attempts"]


def test_real_provider_leaf_builder_scaffolds_package_markers_for_direct_import_tests(tmp_path: pathlib.Path) -> None:
    contract = create_scope_contract(
        agent_id="search_service_leaf",
        role="SearchServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
    )
    save_scope_contract(contract, tmp_path)
    raw = json.dumps(
        {
            "files": [
                {
                    "path": "app/services/search_service.py",
                    "content": "def search_documents(documents, query):\n    return [{'content': query}]\n",
                },
                {
                    "path": "tests/test_search_service.py",
                    "content": "from app.services.search_service import search_documents\n\n\ndef test_search_documents():\n    assert search_documents([], 'knowledge')[0]['content'] == 'knowledge'\n",
                },
            ]
        }
    )

    result = run_real_provider_leaf(
        agent_id="search_service_leaf",
        out_dir=tmp_path,
        project_dir=tmp_path / "project",
        user_goal="Local AI Knowledge Studio",
        readiness={"provider_ready": True},
        provider_output_override=raw,
    )

    assert result["classification"] == "real_provider_leaf_pass"
    assert result["checkpoint"] == "PASS"
    assert result["written_files"] == ["app/services/search_service.py", "tests/test_search_service.py"]
    assert result["harness_scaffold_files"] == ["app/__init__.py", "app/services/__init__.py"]


def test_real_provider_leaf_builder_repairs_missing_file_with_second_real_attempt(tmp_path: pathlib.Path, monkeypatch) -> None:
    contract = create_scope_contract(
        agent_id="task_service_leaf",
        role="TaskServiceLeafAgent",
        parent_id="backend_branch_agent",
        allowed_files=["app/services/task_service.py", "tests/test_task_service.py"],
    )
    save_scope_contract(contract, tmp_path)
    responses = [
        json.dumps({"files": [{"path": "app/services/task_service.py", "content": "def create_task(title):\n    return {'title': title, 'status': 'open'}\n"}]}),
        json.dumps(
            {
                "files": [
                    {"path": "app/services/task_service.py", "content": "def create_task(title):\n    return {'title': title, 'status': 'open'}\n"},
                    {"path": "tests/test_task_service.py", "content": "from app.services.task_service import create_task\n\n\ndef test_create_task():\n    assert create_task('Review')['status'] == 'open'\n"},
                ]
            }
        ),
    ]

    def fake_call_provider(prompt: str, *, model: str, timeout: int):
        return responses.pop(0), ""

    monkeypatch.setattr(agent_real_provider_leaf_builder, "_call_provider", fake_call_provider)

    result = run_real_provider_leaf(
        agent_id="task_service_leaf",
        out_dir=tmp_path,
        project_dir=tmp_path / "project",
        user_goal="Local AI Knowledge Studio",
        readiness={"provider_ready": True},
        max_repair_attempts=1,
    )

    assert result["classification"] == "real_provider_leaf_pass"
    assert result["checkpoint"] == "PASS"
    assert len((tmp_path / "repair_attempts.jsonl").read_text(encoding="utf-8").splitlines()) == 2
