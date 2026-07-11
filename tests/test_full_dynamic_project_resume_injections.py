from __future__ import annotations

import pathlib

from scripts.full_dynamic_project_resume_runner import run_failure_injections


def test_all_resume_failure_injections_pass(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "resume"
    root.mkdir()
    result = run_failure_injections(root)

    assert result["verdict"] == "PASS"
    assert {case["case"] for case in result["cases"]} == {
        "pruned_original_tries_to_merge",
        "provider_unavailable_fake_file",
        "replacement_scope_violation",
    }
    assert all(case["verdict"] == "PASS" for case in result["cases"])
    assert not (root / "failure_injection" / "replacement_scope_violation" / "project" / "README.md").exists()
