from __future__ import annotations

import json

from scripts import decomposition_tree


def pipeline() -> dict:
    return {
        "components": [
            {"id": "backend", "required_paths": ["app/main.py"]},
            {
                "id": "frontend",
                "required_paths": ["frontend/index.html", "frontend/app.js"],
            },
            {"id": "tests", "required_paths": ["tests/test_board.py"]},
        ]
    }


def test_decomposition_tree_required_for_generation_run(tmp_path) -> None:
    tree = decomposition_tree.build_case03_tree(
        user_goal="Build a local project board",
        project_plan={"expected_project_structure": ["app/main.py", "frontend/index.html", "frontend/app.js", "tests/test_board.py"]},
        component_pipeline=pipeline(),
    )
    assert tree["required_for_generation"] is True
    assert tree["release_authority"] is False
    assert decomposition_tree.validate_tree(tree) == []
    assert tree["plan_tree"]["node_ids"] == tree["issue_tree"]["node_ids"]
    assert tree["plan_tree"]["node_ids"] == tree["evidence_tree"]["node_ids"]
    path = tmp_path / "artifacts" / "project_decomposition_tree.json"
    decomposition_tree.write_tree(path, tree)
    assert json.loads(path.read_text(encoding="utf-8"))["tree_sha256"] == tree["tree_sha256"]


def test_case01_and_case03_required_nodes_exist() -> None:
    case01 = decomposition_tree.build_case01_tree(
        user_goal="Clean CSV data",
        project_plan={"expected_project_structure": ["app/main.py", "frontend/index.html", "frontend/app.js"]},
        component_pipeline=pipeline(),
    )
    case03 = decomposition_tree.build_case03_tree(
        user_goal="Build a local project board",
        project_plan={"expected_project_structure": ["app/main.py", "frontend/index.html", "frontend/app.js", "tests/test_board.py"]},
        component_pipeline=pipeline(),
    )
    ids01 = {item["node_id"] for item in case01["nodes"]}
    ids03 = {item["node_id"] for item in case03["nodes"]}
    assert {
        "capability.static_web_entry",
        "capability.csv_upload",
        "capability.clean_preview",
        "capability.export_csv",
        "capability.delivery_evidence",
    } <= ids01
    assert {
        "semantic_contract.main_entry",
        "test_contract.canonical_verifier",
        "capability.static_web_entry",
        "capability.dom_alignment",
        "capability.crud",
        "capability.move_status",
        "capability.persistence",
        "capability.export",
    } <= ids03


def test_repairable_semantic_failure_materializes_but_fatal_fake_blocks() -> None:
    assert decomposition_tree.semantic_failure_is_repairable(
        "implementation depth contract mismatch: missing expected symbols: main"
    )
    assert decomposition_tree.semantic_failure_is_repairable(
        "tests/test_board.py imports test-local browser driver dependency selenium"
    )
    assert not decomposition_tree.semantic_failure_is_repairable(
        "unsafe path with fake artifact final_project_bundle.zip"
    )


def test_repairable_semantic_issue_can_materialize_candidate_with_warning() -> None:
    from scripts import candidate_materializer

    files = [{"path": "app/main.py", "content": "def start():\n    return 0\n"}]
    assessment = candidate_materializer.assess_build_complete(
        files,
        required_paths=["app/main.py"],
        safety_blockers=[],
    )
    assert assessment["build_complete"] is True
    assert decomposition_tree.semantic_failure_is_repairable("missing expected symbols: main")


def test_fatal_fake_artifact_still_blocks_candidate() -> None:
    from scripts import candidate_materializer

    assessment = candidate_materializer.assess_build_complete(
        [{"path": "app/main.py", "content": "def main():\n    return 0\n"}],
        required_paths=["app/main.py"],
        safety_blockers=["fake artifact final_project_bundle.zip"],
    )
    assert assessment["build_complete"] is False
