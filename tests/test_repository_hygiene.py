from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "repository_hygiene.py"


def load_module():
    spec = importlib.util.spec_from_file_location("repository_hygiene_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_minimum_repository(root: pathlib.Path, module) -> None:
    for relative in module.REQUIRED_SURFACES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    (root / ".gitignore").write_text("\n".join(module.REQUIRED_IGNORE_RULES) + "\n", encoding="utf-8")


def test_minimum_repository_passes_hygiene_check(tmp_path: pathlib.Path) -> None:
    module = load_module()
    write_minimum_repository(tmp_path, module)
    report = module.inspect_repository(tmp_path)
    assert report["ok"] is True, report["issues"]
    assert report["issues"] == []
    assert "formal delivery evidence" in report["note"]


def test_hygiene_check_reports_temp_and_missing_ignore_rule(tmp_path: pathlib.Path) -> None:
    module = load_module()
    write_minimum_repository(tmp_path, module)
    (tmp_path / ".tmp_debug").mkdir()
    ignore = tmp_path / ".gitignore"
    ignore.write_text(ignore.read_text(encoding="utf-8").replace("/runs/\n", ""), encoding="utf-8")

    report = module.inspect_repository(tmp_path)
    codes = {item["code"] for item in report["issues"]}

    assert report["ok"] is False
    assert "ROOT_TEMP_PRESENT" in codes
    assert "IGNORE_BOUNDARY_MISSING" in codes


def test_tracked_runtime_and_runtime_data_under_examples_are_rejected(tmp_path: pathlib.Path) -> None:
    module = load_module()
    issues, warnings = module.inspect_tracked_paths(
        {
            "runs/run-1/run_manifest.json": 100,
            "artifacts/raw/provider_response.json": 100,
            "examples/project_memory/chat/PROJECT_MEMORY.md": 100,
            ".cgkn/agent-kit.json": 100,
        },
        tmp_path,
    )
    codes = [item["code"] for item in issues]
    assert codes.count("TRACKED_RUNTIME_OUTPUT") == 3
    assert "RUNTIME_DATA_UNDER_EXAMPLES" in codes
    assert warnings == []


def test_size_policy_warns_then_fails(tmp_path: pathlib.Path) -> None:
    module = load_module()
    issues, warnings = module.inspect_tracked_paths(
        {
            "docs/large.md": module.SIZE_WARNING_BYTES + 1,
            "docs/too-large.md": module.SIZE_FAILURE_BYTES + 1,
        },
        tmp_path,
    )
    assert {item["code"] for item in warnings} == {"TRACKED_FILE_LARGE"}
    assert {item["code"] for item in issues} == {"TRACKED_FILE_TOO_LARGE"}


def test_no_tracked_runtime_output() -> None:
    module = load_module()
    report = module.inspect_repository(ROOT)
    runtime_issues = {
        item["code"]
        for item in report["issues"]
        if item["code"] in {"TRACKED_RUNTIME_OUTPUT", "RUNTIME_DATA_UNDER_EXAMPLES"}
    }
    assert runtime_issues == set(), report["issues"]
