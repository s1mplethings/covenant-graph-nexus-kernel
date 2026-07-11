from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_quick_large_sync_tree_benchmark import build_multi_environment_acceptance_contract


def test_contract_contains_required_environments() -> None:
    contract = build_multi_environment_acceptance_contract("Multi-Environment Studio Operations Platform")

    assert contract["required_environments"] == ["dev", "test", "demo", "prod-like local"]


def test_contract_contains_required_capabilities() -> None:
    contract = build_multi_environment_acceptance_contract("goal")

    for item in (
        "asset_library",
        "bug_tracker",
        "build_release_records",
        "docs_guidelines",
        "release_checklist",
        "team_roles",
        "import_export",
    ):
        assert item in contract["required_capabilities"]


def test_contract_forbidden_scope_blocks_task_board_only() -> None:
    contract = build_multi_environment_acceptance_contract("goal")

    assert "no task-board-only output" in contract["forbidden_scope"]


def test_contract_delivery_requires_readme_tests_screenshots_and_bundle() -> None:
    contract = build_multi_environment_acceptance_contract("goal")
    delivery = set(contract["required_delivery"])

    assert {"README", "test_report", "screenshots", "bundle"}.issubset(delivery)


def test_contract_builder_does_not_call_provider() -> None:
    contract = build_multi_environment_acceptance_contract("goal")

    assert contract["kind"] == "MultiEnvironmentAcceptanceContract"
    assert "provider" not in " ".join(contract.keys()).lower()
