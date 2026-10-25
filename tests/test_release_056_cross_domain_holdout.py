from __future__ import annotations

from experiments.release_056.cross_domain_holdout import (
    DOMAINS,
    evaluate_holdout_answer,
    frozen_cross_domain_holdout,
    holdout_manifest,
)


def test_holdout_is_frozen_balanced_and_unique() -> None:
    cases = frozen_cross_domain_holdout()
    assert len(cases) == 72
    assert len({case.case_id for case in cases}) == 72
    assert {case.domain for case in cases} == {row[0] for row in DOMAINS}
    assert all(sum(case.domain == domain for case in cases) == 6 for domain, *_ in DOMAINS)
    manifest = holdout_manifest()
    assert manifest["task_count"] == 72
    assert manifest["domain_count"] == 12
    assert manifest["execution_visibility"] == "PUBLIC_PACKET_ONLY"


def test_public_packets_do_not_expose_evaluator_fields() -> None:
    for case in frozen_cross_domain_holdout():
        packet = case.public_packet()
        assert "expected_terms" not in packet
        assert "forbidden_terms" not in packet
        assert "expect_abstention" not in packet


def test_hidden_evaluator_accepts_grounded_answer_and_rejects_leakage() -> None:
    case = frozen_cross_domain_holdout()[0]
    evidence_id = case.evidence[0][0]
    answer = {"answer": "three clean rows", "abstained": False, "evidence_ids": [evidence_id]}
    assert evaluate_holdout_answer(case, answer)["success"] is True
    answer["evidence_ids"] = ["HIDDEN-GOLD"]
    assert evaluate_holdout_answer(case, answer)["success"] is False


def test_conflict_and_missing_cases_require_abstention() -> None:
    cases = frozen_cross_domain_holdout()
    for case in cases:
        if case.expect_abstention:
            answer = {"answer": "insufficient evidence", "abstained": True, "evidence_ids": []}
            assert evaluate_holdout_answer(case, answer)["success"] is True
