#!/usr/bin/env python3
from __future__ import annotations

import json

import pytest

import compose_local_pipeline
import run_local_pipeline

pytestmark = pytest.mark.slow


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def test_component_plan() -> None:
    plan = compose_local_pipeline.build_component_pipeline(
        "Build a browser app with backend API, database storage, tests, docs, and image preview"
    )
    component_ids = [row["id"] for row in plan["components"]]
    for expected in ("foundation", "backend", "data", "frontend", "media", "tests", "docs"):
        assert_true(expected in component_ids, f"missing component {expected}")
    assert_true(plan["merge_policy"]["duplicate_path"] == "fail_unless_identical", "merge policy must reject conflicts")


def test_merge_success() -> None:
    result = run_local_pipeline.merge_component_files(
        [
            {
                "component_id": "foundation",
                "files": [
                    {"path": "pyproject.toml", "content": "[project]\nname='demo'\n"},
                    {"path": "src/app.py", "content": "print('ok')\n"},
                ],
            },
            {
                "component_id": "docs",
                "files": [
                    {"path": "README.md", "content": "# Demo\n"},
                    {"path": "TEST_PLAN.md", "content": "# Test Plan\n"},
                ],
            },
        ]
    )
    paths = [row["path"] for row in result]
    assert_true(paths == sorted(paths), "merged files should be stable-sorted")
    assert_true("README.md" in paths and "TEST_PLAN.md" in paths, "docs files missing")


def test_merge_conflict() -> None:
    try:
        run_local_pipeline.merge_component_files(
            [
                {"component_id": "frontend", "files": [{"path": "src/app.py", "content": "front\n"}]},
                {"component_id": "backend", "files": [{"path": "src/app.py", "content": "back\n"}]},
            ]
        )
    except RuntimeError as exc:
        assert_true("component file conflict" in str(exc), "wrong conflict error")
        return
    raise AssertionError("merge conflict was not detected")


def test_component_provider_orchestration() -> None:
    original = run_local_pipeline._impl.provider_generate_project_component

    def fake_provider(**kwargs):
        component = kwargs["component"]
        component_id = component["id"]
        if component_id == "foundation":
            files = [{"path": "src/app.py", "content": "def main(): return 'ok'\n"}]
        elif component_id == "docs":
            files = [
                {"path": "README.md", "content": "# Demo\n"},
                {"path": "TEST_PLAN.md", "content": "# Tests\n"},
            ]
        else:
            files = [{"path": f"{component_id}.txt", "content": f"{component_id}\n"}]
        return {
            "component_id": component_id,
            "summary": f"generated {component_id}",
            "files": files,
            "public_contract": {"exports": [component_id]},
            "manual_checks": [f"check {component_id}"],
            "self_test": {"status": "pass", "checks": [f"self {component_id}"]},
            "quality_gate": {"status": "pass", "reasons": [f"quality {component_id}"]},
        }

    try:
        run_local_pipeline._impl.provider_generate_project_component = fake_provider
        plan = {
            "kind": "ComponentPipelinePlan",
            "components": [
                {"id": "foundation", "depends_on": [], "path_hints": ["src/**"]},
                {"id": "docs", "depends_on": ["foundation"], "path_hints": ["README.md", "TEST_PLAN.md"]},
            ],
            "merge_policy": {"required_final_files": ["README.md", "TEST_PLAN.md"]},
        }
        generation = run_local_pipeline.provider_generate_project_by_components(
            "Build a demo",
            plan,
            {},
            {},
            {},
            {},
            [],
            "fake-model",
            1,
        )
    finally:
        run_local_pipeline._impl.provider_generate_project_component = original
    paths = {row["path"] for row in generation["files"]}
    assert_true(paths == {"src/app.py", "README.md", "TEST_PLAN.md"}, "component orchestration produced wrong files")
    assert_true([row["id"] for row in generation["components"]] == ["foundation", "docs"], "component order not preserved")


def main() -> int:
    test_component_plan()
    test_merge_success()
    test_merge_conflict()
    test_component_provider_orchestration()
    print(
        json.dumps(
            {"status": "pass", "tests": ["component_plan", "merge_success", "merge_conflict", "component_provider_orchestration"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
