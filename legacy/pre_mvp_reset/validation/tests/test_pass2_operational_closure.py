import json
import os

import pytest

from scripts import codex_conversation, production_candidate_provenance, provider_causal_trace
from scripts import run_pass2_operational_closure


@pytest.fixture(autouse=True)
def _isolated_production_root(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(production_candidate_provenance, "PRODUCTION_CANDIDATE_ROOT", tmp_path)
    monkeypatch.setattr(codex_conversation.production_candidate_provenance, "PRODUCTION_CANDIDATE_ROOT", tmp_path)
    monkeypatch.setattr(provider_causal_trace.production_candidate_provenance, "PRODUCTION_CANDIDATE_ROOT", tmp_path)


def test_operational_revision_closure_and_cold_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CGNK_LOCAL_STUDIO_CONVERSATION_ROOT", "sentinel-conversations")
    monkeypatch.delenv("CGNK_MANAGED_PROJECT_ROOT", raising=False)
    report = run_pass2_operational_closure.run(tmp_path)
    assert report["status"] == "PASS"
    assert len(report["rounds"]) == 3
    assert [len(row["data_rows"]) for row in report["rounds"]] == [1, 2, 3]
    assert len(report["cold_start"]["data_rows"]) == 3
    assert all(row["execution"]["public_delivery_gate"]["delivery_allowed"] is True for row in report["rounds"])
    assert all(row["independent_business_acceptance"]["status"] == "PASS" for row in report["rounds"])
    assert os.environ["CGNK_LOCAL_STUDIO_CONVERSATION_ROOT"] == "sentinel-conversations"
    assert "CGNK_MANAGED_PROJECT_ROOT" not in os.environ


def test_independent_acceptance_rejects_semantic_mutation_missed_by_generated_tests(tmp_path) -> None:
    project = tmp_path / "mutated"
    run_pass2_operational_closure.materialize(project, priority=False, max_title=24)
    (project / "data.json").write_text(
        json.dumps([{"title": "round-1", "priority": "high"}, {"title": "round-2", "priority": "high"}, {"title": "round-3"}]),
        encoding="utf-8",
    )
    source_path = project / "main.py"
    source_path.write_text(
        source_path.read_text(encoding="utf-8").replace(
            "print(json.dumps(load(path), ensure_ascii=False)); return 0",
            "print(json.dumps([{'title': 'CORRUPTED'}], ensure_ascii=False)); return 0",
        ),
        encoding="utf-8",
    )

    generated_tests = run_pass2_operational_closure.verify
    completed = run_pass2_operational_closure.subprocess.run(
        [run_pass2_operational_closure.sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )
    acceptance = run_pass2_operational_closure.independent_business_acceptance(
        project,
        round_index=3,
        priority_enabled=False,
        max_title=24,
    )

    assert generated_tests is not None
    assert completed.returncode == 0
    assert acceptance["status"] == "FAIL"
    assert "persisted_titles_mismatch" in acceptance["errors"]
