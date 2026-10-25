from __future__ import annotations

import pathlib

from experiments.persona_digital_self.runner import lifelong_cases, run_evaluation


def test_lifelong_taskset_is_frozen_bounded_and_diverse():
    cases = lifelong_cases()
    assert len(cases) == 100
    assert len({row["subject_ref"] for row in cases}) == 12
    assert len({row["community_ref"] for row in cases}) == 6
    assert len({row["category"] for row in cases}) == 12
    assert all(row["hidden_rubric"]["must_not_invent_history"] for row in cases)


def test_full_persona_longitudinal_evaluation(tmp_path):
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    report = run_evaluation(repo_root=repo_root, output_dir=tmp_path)
    assert report["status"] == "PASS"
    variants = report["lifelong"]["variants"]
    assert tuple(variants) == ("P0", "P1", "P2", "P3")
    assert len(report["lifelong"]["windows"]) == 5
    p0 = variants["P0"]["metrics"]; p3 = variants["P3"]["metrics"]
    assert p3["identity_consistency_rate"] == 1
    assert p3["memory_hallucination_rate"] == 0
    assert p3["generic_reply_rate"] < p0["generic_reply_rate"]
    assert p3["relationship_continuity"] > p0["relationship_continuity"]
    assert p3["commitment_accuracy"] > p0["commitment_accuracy"]
    assert report["context_localization"]["reduction"] >= .4
    assert report["social_sandbox"]["cases"] == 30
    assert report["social_sandbox"]["human_review"]["cases"] == 15
    assert report["controlled_relationship"]["episodes"] == 8
    assert report["security"]["external_writes"] == 0
    assert (tmp_path / "persona_evaluation.json").is_file()
    assert (tmp_path / "lifelong_taskset.json").is_file()
