from __future__ import annotations

import json
import pathlib

from experiments.community_operator.runner import run_evaluation


def test_offline_evaluation_meets_formal_case_counts(tmp_path):
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    report = run_evaluation(repo_root=repo_root, output_dir=tmp_path)
    assert report["status"] == "PASS"
    assert report["opportunity_benchmark"]["passed"] == 60
    assert report["reply_benchmark"]["passed"] == 30
    assert report["policy_benchmark"]["passed"] == 20
    assert report["followup_benchmark"]["passed"] == 10
    assert report["adapter_matrix"]["passed"] == 12
    assert report["official_adapter_contracts"]["passed"] == 4
    assert report["security"]["external_writes"] == 0
    assert json.loads((tmp_path / "community_evaluation.json").read_text(encoding="utf-8"))["evaluation_hash"] == report["evaluation_hash"]

