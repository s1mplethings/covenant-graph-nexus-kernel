from __future__ import annotations

from scripts.run_cgnk_evaluation import _context, capability_cases, evaluate_answer


def test_model_capability_taskset_has_required_distribution() -> None:
    cases = capability_cases()
    assert len(cases) == 29
    assert len([case for case in cases if case.case_id.startswith("CGNK-")]) == 8
    assert len([case for case in cases if case.case_id.startswith("ADV-")]) == 4
    assert len([case for case in cases if case.case_id.startswith("TESTAUTH-")]) == 5
    assert len({case.case_id for case in cases}) == len(cases)


def test_test_authority_cases_cover_explicit_unspecified_repair_and_ambiguity() -> None:
    cases = {case.case_id: case for case in capability_cases()}
    assert "header X" in cases["TESTAUTH-01"].question
    assert "unspecified" in cases["TESTAUTH-02"].question
    assert "old generated test" in cases["TESTAUTH-03"].question
    assert "Implementation violates" in cases["TESTAUTH-04"].question
    assert cases["TESTAUTH-05"].expect_abstention is True


def test_structured_context_is_local_and_flat_context_is_complete() -> None:
    case = next(case for case in capability_cases() if case.case_id == "CGNK-01")
    flat, flat_ids = _context(case, "R1")
    local, local_ids = _context(case, "R2")
    assert len(flat) > len(local) == 1
    assert set(flat_ids) > set(local_ids) == {"payments.retry"}


def test_deterministic_evaluator_rejects_unsupported_evidence() -> None:
    case = next(case for case in capability_cases() if case.case_id == "CAP-08")
    accepted = evaluate_answer(case, "R2", {
        "answer": "The release color is blue.",
        "claims": [{"text": "blue", "evidence_ids": ["E1"]}],
        "abstained": False, "selected_nodes": ["E1"], "actions": [],
    }, ("E1",))
    rejected = evaluate_answer(case, "R2", {
        "answer": "The release color is blue.",
        "claims": [{"text": "blue", "evidence_ids": ["MISSING"]}],
        "abstained": False, "selected_nodes": ["MISSING"], "actions": [],
    }, ("E1",))
    assert accepted["success"] is True
    assert rejected["success"] is False and rejected["unsupported_claims"] == 1


def test_abstention_case_requires_explicit_abstention() -> None:
    case = next(case for case in capability_cases() if case.case_id == "CAP-09")
    result = evaluate_answer(case, "R0", {
        "answer": "Insufficient evidence.", "claims": [], "abstained": True,
        "selected_nodes": [], "actions": [],
    }, ())
    assert result["success"] is True
