from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_mixed_backend_branch_phase import BACKEND_LEAF_ORDER, LEAF_SPECS, _controlled_content, run_mixed_backend_branch_phase


def provider_output_for_leaf(leaf: str) -> str:
    return json.dumps({"files": [{"path": rel, "content": _controlled_content(leaf, rel)} for rel in LEAF_SPECS[leaf][1]]})


def test_mixed_backend_branch_merges_real_search_leaf_with_controlled_leaves(tmp_path: pathlib.Path) -> None:
    raw = json.dumps(
        {
            "files": [
                {
                    "path": "app/services/search_service.py",
                    "content": "def search_documents(documents, query):\n    return [doc for doc in documents if query.lower() in doc.get('content', '').lower()]\n",
                },
                {
                    "path": "tests/test_search_service.py",
                    "content": "from app.services.search_service import search_documents\n\n\ndef test_search_documents():\n    assert search_documents([{'content': 'local knowledge'}], 'knowledge')\n",
                },
            ]
        }
    )

    result = run_mixed_backend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        real_provider_leaves=["search_service_leaf"],
        readiness_override={"provider_ready": True},
        provider_output_overrides={"search_service_leaf": raw},
    )

    assert result["classification"] == "mixed_backend_search_real_pass"
    assert result["verdict"] == "PASS"
    merge = json.loads((tmp_path / "merge_results" / "backend_branch_agent.json").read_text(encoding="utf-8"))
    assert merge["merge_verdict"] == "PASS"
    backend_tests = json.loads((tmp_path / "backend_branch_test_execution.json").read_text(encoding="utf-8"))
    assert backend_tests["exit_code"] == 0
    search_checkpoint = json.loads((tmp_path / "checkpoints" / "search_service_leaf.json").read_text(encoding="utf-8"))
    assert search_checkpoint["provider_mode"] == "real_provider"
    assert search_checkpoint["can_merge"] is True
    assert search_checkpoint["blocked_files"] == []
    controlled_checkpoint = json.loads((tmp_path / "checkpoints" / "task_service_leaf.json").read_text(encoding="utf-8"))
    assert controlled_checkpoint["provider_mode"] == "controlled"


def test_mixed_backend_branch_blocks_when_provider_unavailable(tmp_path: pathlib.Path) -> None:
    result = run_mixed_backend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        real_provider_leaves=["search_service_leaf"],
        readiness_override={"provider_ready": False},
    )

    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"
    assert not (tmp_path / "project" / "app" / "services" / "search_service.py").exists()


def test_mixed_backend_branch_merges_search_and_task_real_provider_leaves(tmp_path: pathlib.Path) -> None:
    overrides = {leaf: provider_output_for_leaf(leaf) for leaf in ("search_service_leaf", "task_service_leaf")}

    result = run_mixed_backend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        real_provider_leaves=["search_service_leaf", "task_service_leaf"],
        readiness_override={"provider_ready": True},
        provider_output_overrides=overrides,
    )

    assert result["classification"] == "mixed_backend_multi_real_pass"
    assert result["verdict"] == "PASS"
    for leaf in ("search_service_leaf", "task_service_leaf"):
        checkpoint = json.loads((tmp_path / "checkpoints" / f"{leaf}.json").read_text(encoding="utf-8"))
        assert checkpoint["provider_mode"] == "real_provider"
        assert checkpoint["can_merge"] is True


def test_mixed_backend_branch_merges_all_backend_leaves_as_real_provider(tmp_path: pathlib.Path) -> None:
    overrides = {leaf: provider_output_for_leaf(leaf) for leaf in BACKEND_LEAF_ORDER}

    result = run_mixed_backend_branch_phase(
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        real_provider_leaves=list(BACKEND_LEAF_ORDER),
        readiness_override={"provider_ready": True},
        provider_output_overrides=overrides,
    )

    assert result["classification"] == "mixed_backend_multi_real_pass"
    assert result["verdict"] == "PASS"
    assert result["controlled_leaves"] == []
    backend_tests = json.loads((tmp_path / "backend_branch_test_execution.json").read_text(encoding="utf-8"))
    assert backend_tests["exit_code"] == 0
    for leaf in BACKEND_LEAF_ORDER:
        checkpoint = json.loads((tmp_path / "checkpoints" / f"{leaf}.json").read_text(encoding="utf-8"))
        assert checkpoint["provider_mode"] == "real_provider"
        assert checkpoint["verdict"] == "PASS"
