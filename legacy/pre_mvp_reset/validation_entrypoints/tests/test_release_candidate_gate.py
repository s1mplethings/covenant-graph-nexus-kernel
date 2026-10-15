from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_candidate_gate as gate


def write_json(path: pathlib.Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_release_gate_has_no_independent_publish_classifier_or_allowlist() -> None:
    source = (ROOT / "scripts" / "release_candidate_gate.py").read_text(encoding="utf-8")
    assert "RECOMMENDED_COMMIT_FILES" not in source
    assert "def classify_path" not in source
    assert "git add" not in source
    assert "git push" not in source
    assert "canonical_repo_publish.build_change_manifest" in source


def test_release_candidate_ready_requires_full_pytest_and_commercial_false(tmp_path: pathlib.Path) -> None:
    root = tmp_path
    (root / "README.md").write_text("# CGKN\n\nCurrent product name: CGKN\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "release_candidate_acceptance.md").write_text("CGKN release candidate\n", encoding="utf-8")
    artifacts = root / "artifacts"
    write_json(artifacts / "requirement_decision_benchmark.json", {"score": 100, "verdict": "PASS"})
    write_json(artifacts / "complexity_scale_acceptance.json", {"overall_score": 95, "verdict": "PASS"})
    write_json(
        artifacts / "customer_agent_long_journey_trial.json",
        {"customer_journey_event_count": 29, "artifact_integrity": {"status": "PASS"}},
    )
    write_json(
        artifacts / "customer_agent_scorecard.json",
        {
            "total": 100,
            "verdict": "CUSTOMER_ACCEPTED",
            "customer_challenge_count": 3,
            "rework_request_count": 1,
            "delivery_evidence": {"status": "PASS", "screenshot_ok": True, "zip_ok": True},
            "capability_evidence": {"status": "PASS", "production_asr_claimed": False},
            "commercial_readiness": {
                "status": "COMMERCIAL_BETA",
                "commercial_ready": False,
                "why_not_commercial_ready": "real ASR evidence missing",
            },
            "blockers": [],
        },
    )
    write_json(
        artifacts / "reference_answer_trial.json",
        {
            "score": {"total": 100, "verdict": "PASS"},
            "name_leak_scan": {"status": "PASS"},
            "artifact_integrity": {"status": "PASS"},
            "commercial_readiness": {"commercial_ready": False},
            "known_gaps": ["real_asr_missing"],
        },
    )
    (artifacts / "cgkn_naming_consistency_report.md").write_text("- status: `PASS`\n", encoding="utf-8")
    write_json(artifacts / "release_candidate_file_classification.json", {"dirty_count": 1, "recommended_exclude_files": []})
    write_json(artifacts / "full_pytest_result.json", {"status": "PASS", "passed": 726})

    result = gate.evaluate_release_candidate(root)
    assert result["verdict"] == "RELEASE_CANDIDATE_READY"
    assert result["checks"]["commercial_ready_false_justified"] is True
    assert result["commercial_readiness"]["commercial_ready"] is False


def test_release_candidate_gate_reports_not_ready_without_full_pytest(tmp_path: pathlib.Path) -> None:
    root = tmp_path
    (root / "README.md").write_text("# CGKN\n\nCurrent product name: CGKN\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "release_candidate_acceptance.md").write_text("CGKN\n", encoding="utf-8")
    artifacts = root / "artifacts"
    write_json(artifacts / "release_candidate_file_classification.json", {"dirty_count": 1, "recommended_exclude_files": []})

    result = gate.evaluate_release_candidate(root)
    assert result["verdict"] == "NOT_READY"
    assert "full_pytest_pass" in result["blockers"]
