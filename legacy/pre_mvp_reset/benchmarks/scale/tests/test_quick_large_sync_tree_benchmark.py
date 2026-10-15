from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

pytestmark = pytest.mark.quick

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_quick_large_sync_tree_benchmark import run_benchmark


def test_runner_mock_mode_outputs_required_evidence(tmp_path: pathlib.Path) -> None:
    summary = run_benchmark(
        goal="Multi-Environment Studio Operations Platform",
        mode="mock",
        max_rounds=4,
        max_branches=7,
        max_leaves=28,
        require_multi_env=True,
        require_sync_growth=True,
        output_root=tmp_path / "generated" / "quick_large_sync_tree",
    )
    run_dir = pathlib.Path(summary["run_dir"])

    assert summary["benchmark_verdict"] == "FLOW_PASS_MOCK"
    assert (run_dir / "run_summary.json").exists()
    assert (run_dir / "sync_growth_ledger.jsonl").exists()
    assert (run_dir / "multi_env_acceptance_contract.json").exists()
    assert (run_dir / "sync_tree_rounds.json").exists()
    assert (run_dir / "branch_depth_summary.json").exists()
    assert (run_dir / "sync_tree_report.md").exists()
    assert (run_dir / "project_output_audit.json").exists()
    assert (run_dir / "acceptance_report.md").exists()


def test_runner_audit_status_passes_in_mock_mode(tmp_path: pathlib.Path) -> None:
    summary = run_benchmark(
        goal="Multi-Environment Studio Operations Platform",
        mode="mock",
        max_rounds=4,
        max_branches=7,
        max_leaves=28,
        require_multi_env=True,
        require_sync_growth=True,
        output_root=tmp_path / "generated" / "quick_large_sync_tree",
    )
    audit = json.loads((pathlib.Path(summary["run_dir"]) / "sync_growth_audit.json").read_text(encoding="utf-8"))

    assert audit["sync_status"] == "pass"
    assert audit["branch_count"] == 7
    assert audit["max_depth_gap"] <= 1


def test_runner_does_not_write_api_key(tmp_path: pathlib.Path) -> None:
    summary = run_benchmark(
        goal="Multi-Environment Studio Operations Platform",
        mode="mock",
        max_rounds=4,
        max_branches=7,
        max_leaves=28,
        require_multi_env=True,
        require_sync_growth=True,
        output_root=tmp_path / "generated" / "quick_large_sync_tree",
    )
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in pathlib.Path(summary["run_dir"]).rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md", ".txt", ".py"})

    assert "OPENAI_API_KEY" not in text
    assert "CGKN_OPENAI_API_KEY" not in text
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)


def test_runner_output_can_live_under_generated(tmp_path: pathlib.Path) -> None:
    output_root = tmp_path / "generated" / "quick_large_sync_tree"
    summary = run_benchmark(
        goal="Multi-Environment Studio Operations Platform",
        mode="mock",
        max_rounds=4,
        max_branches=7,
        max_leaves=28,
        require_multi_env=True,
        require_sync_growth=True,
        output_root=output_root,
    )

    assert pathlib.Path(summary["run_dir"]).is_relative_to(output_root)
