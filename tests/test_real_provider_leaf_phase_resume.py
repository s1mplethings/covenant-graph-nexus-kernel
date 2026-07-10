from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_real_provider_leaf_phase

run_leaf_phase = run_real_provider_leaf_phase.run_leaf_phase


def test_real_provider_leaf_phase_blocks_without_provider_and_writes_no_fake_files(tmp_path: pathlib.Path) -> None:
    result = run_leaf_phase(
        leaf="search_service_leaf",
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": False, "public_safe_error": "quota"},
    )

    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"
    assert result["provider_called"] is False
    assert result["project_files_created"] == 0
    assert (tmp_path / "final_verdict.json").exists()


def test_real_provider_leaf_phase_creates_scope_contract_before_resume(tmp_path: pathlib.Path) -> None:
    run_leaf_phase(
        leaf="search_service_leaf",
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": False},
    )

    contract = tmp_path / "scope_contracts" / "search_service_leaf.json"
    assert contract.exists()
    text = contract.read_text(encoding="utf-8")
    assert "app/services/search_service.py" in text
    assert "tests/test_search_service.py" in text


def test_real_provider_leaf_phase_uses_leaf_test_evidence_on_pass(tmp_path: pathlib.Path, monkeypatch) -> None:
    def fake_leaf(**kwargs):
        out = pathlib.Path(kwargs["out_dir"])
        run_real_provider_leaf_phase.write_json(
            out / "test_execution_result.json",
            {"exit_code": 0, "command": "python -m pytest tests/test_search_service.py", "stdout_tail": "1 passed"},
        )
        return {
            "classification": "real_provider_leaf_pass",
            "verdict": "PASS",
            "checkpoint": "PASS",
            "written_files": ["app/services/search_service.py", "tests/test_search_service.py"],
            "forbidden_write_attempts": [],
            "harness_scaffold_files": ["app/__init__.py", "app/services/__init__.py"],
        }

    monkeypatch.setattr(run_real_provider_leaf_phase, "run_real_provider_leaf", fake_leaf)

    result = run_leaf_phase(
        leaf="search_service_leaf",
        out_dir=tmp_path,
        project_name="Local AI Knowledge Studio",
        readiness_override={"provider_ready": True},
    )

    assert result["classification"] == "real_provider_leaf_pass"
    assert (tmp_path / "test_execution.json").read_text(encoding="utf-8").find('"exit_code": 0') >= 0
    assert "NO REAL TEST EXECUTION" not in (tmp_path / "TEST_REPORT.md").read_text(encoding="utf-8")
