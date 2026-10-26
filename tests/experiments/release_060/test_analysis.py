from __future__ import annotations

import json

from experiments.release_060.analysis import analyze, write_analysis_assets
from experiments.release_060.contracts import ArchitectureBaseline
from experiments.release_060.specs import formal_families


def _receipt(family_id: str, baseline: str, *, passed: bool, tokens: int, cost: float) -> dict:
    return {
        "family_id": family_id, "baseline": baseline, "split": "FORMAL_HOLDOUT", "source_version": "source",
        "status": "PASS" if passed else "FAIL", "provider_calls": 2,
        "usage_totals": {"total_tokens": tokens}, "estimated_cost_usd": cost, "duration_ms": 100,
        "call_records": [{"purpose":"GENERATION","status":"COMPLETED","request_chars":100},{"purpose":"PUBLIC_REPAIR","status":"COMPLETED","request_chars":150}],
        "public_results": [{"failure_class":"WRONG_OUTPUT"}] if not passed else [{"failure_class":""}],
    }


def test_analysis_is_stratified_and_writes_release_assets(tmp_path) -> None:
    receipts=[]
    for family in formal_families():
        for index, baseline in enumerate(ArchitectureBaseline):
            receipts.append(_receipt(family.family_id, baseline.value, passed=not (family.complexity == "HIGH" and baseline is ArchitectureBaseline.FULL_CGNK), tokens=100+index, cost=.01+index*.001))
    result=analyze(receipts, source_version="source")
    assert result["attempt_count"] == 96 and result["family_count"] == 24
    assert len(result["complexity_frontier"]) == 3
    assert len(result["project_type_matrix"]) == 8
    assert result["claim_ledger"]["FULL_CGNK_BENEFIT"] == "HARMFUL"
    assert result["claim_ledger"]["CORPUS_DIVERSITY_STATUS"] == "PROVEN"
    write_analysis_assets(result,tmp_path)
    expected={"complexity_frontier.json","project_type_matrix.json","failure_analysis.json","corpus_profile.json","claim_ledger.json","main_results.json","main_results.csv","modification_direction.md","future_project_problem_candidates.json","architecture_boundary_map.json","next_iteration_recommendation.md","technical_report.md"}
    assert expected <= {path.name for path in tmp_path.iterdir()}
    assert json.loads((tmp_path/"main_results.json").read_text(encoding="utf-8"))["analysis_hash"] == result["analysis_hash"]
    assert (tmp_path/"technical_report.md").read_text(encoding="utf-8").count("\n## ") == 40
