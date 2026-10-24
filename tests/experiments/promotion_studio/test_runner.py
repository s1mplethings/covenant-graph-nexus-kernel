from __future__ import annotations

import json
import pathlib

from experiments.promotion_studio.runner import run_evaluation


def test_promotion_evaluation_is_complete_and_secret_safe(tmp_path: pathlib.Path):
    repo = pathlib.Path(__file__).resolve().parents[3]
    report = run_evaluation(repo_root=repo, output_dir=tmp_path / "evaluation")
    assert report["status"] == "PASS"
    assert report["signal_cases"]["passed"] == report["signal_cases"]["total"] == 20
    assert report["campaign_cases"]["passed"] == report["campaign_cases"]["total"] == 10
    assert len(report["real_campaign"]["assets"]) == 6
    assert len(report["native_adapter_qualification"]) == 3
    assert report["fake_publication"]["status"] == "PASS"
    assert report["real_publication"]["status"] == "BLOCKED_ENVIRONMENT"
    assert report["cost"]["provider_calls"] == 0 and report["cost"]["known_cost_usd"] == 0
    text = json.dumps(report, default=str)
    assert "offline-placeholder-never-sent" not in text
    assert report["security"]["external_writes"] == 0
    assert report["metrics"]["signal_precision"] == 1.0
    assert report["metrics"]["campaign_dedup_rate"] == 1.0
    assert report["metrics"]["approval_integrity"] == 1.0
    assert report["metrics"]["restart_correctness"] == 1.0
    assert len({item["asset_id"] for item in report["real_campaign"]["assets"]}) == 6
