from __future__ import annotations

import pytest

from scripts import repair_acceptance


def issue(kind: str, path: str, expected: str, observed: str, **extra) -> dict:
    return {
        "kind": kind,
        "path": path,
        "expected_behavior": expected,
        "observed_behavior": observed,
        **extra,
    }


def fact(issue_id: str, row: dict) -> dict:
    return {
        "issue_id": issue_id,
        "failed_requirement": row["kind"],
        "expected_behavior": row["expected_behavior"],
        "observed_behavior": row["observed_behavior"],
        "evidence": [{**row, "authority": "deterministic_build_coherence"}],
    }


def assess(*, before, after, facts=None, target="app/main.py", old="old", new="new", **kwargs):
    return repair_acceptance.assess_provider_job_partial_acceptance(
        target_file=target,
        before_content=old,
        after_content=new,
        coherence_before=before,
        coherence_after=after,
        evidence_facts=facts or [],
        owned_paths={target},
        syntax_safe=kwargs.pop("syntax_safe", True),
        **kwargs,
    )


def test_partial_improvement_acceptance_keeps_valid_delta() -> None:
    export = issue(
        "frontend_backend_endpoint_mismatch",
        "app/main.py",
        "The backend publishes /api/export.",
        "Published routes: /api/import",
    )
    preview = issue(
        "frontend_backend_endpoint_mismatch",
        "app/main.py",
        "The backend publishes /api/preview.",
        "Published routes: /api/import",
    )

    result = assess(before=[export, preview], after=[preview], facts=[fact("I-1", export), fact("I-2", preview)])

    assert result["status"] == "accepted"
    assert result["issues_fixed_by_partial_acceptance"] == 1
    assert [row["issue_id"] for row in result["issue_acceptance"] if row["fixed_by_delta"]] == ["I-1"]
    assert result["accepted_without_target_issue_improvement"] == 0


def test_endpoint_mismatch_partial_reduction_is_accepted_per_issue() -> None:
    """Keep the descriptive regression name as an alias of the frozen contract."""
    test_partial_improvement_acceptance_keeps_valid_delta()


def test_dom_mismatch_cardinality_reduction_is_accepted() -> None:
    before = issue(
        "dom_id_contract_mismatch",
        "frontend/app.js",
        "Every referenced DOM id exists.",
        "Missing DOM ids: a, b, c, d, e",
    )
    after = {**before, "observed_behavior": "Missing DOM ids: d, e"}

    result = assess(
        target="frontend/app.js",
        before=[before],
        after=[after],
        facts=[fact("DOM-1", before)],
    )

    assert result["safe_to_accept_partial"] is True
    assert result["issue_acceptance"][0]["fixed_by_delta"] is True


def test_no_issue_level_improvement_is_rejected() -> None:
    blocker = issue("dom_id_contract_mismatch", "frontend/app.js", "ids exist", "Missing DOM ids: a")
    result = assess(target="frontend/app.js", before=[blocker], after=[blocker], facts=[fact("DOM-1", blocker)])
    assert result["status"] == "rejected"
    assert result["reason"] == "NO_TARGET_ISSUE_IMPROVEMENT"


def test_partial_improvement_rejects_patch_with_new_blocker() -> None:
    old = issue("invalid_literal_codec", "app/main.py", "registered codec", "UTF8-SIG")
    new = issue("static_server_root_mismatch", "app/main.py", "serve frontend", "wrong root", severity="critical")
    result = assess(before=[old], after=[new], facts=[fact("CODEC-1", old)])
    assert result["status"] == "rejected"
    assert result["reason"] == "NEW_EQUAL_OR_HIGHER_BLOCKER"


def test_passing_behavior_evidence_regression_is_rejected() -> None:
    old = issue("invalid_literal_codec", "app/main.py", "registered codec", "UTF8-SIG")
    result = assess(
        before=[old],
        after=[],
        facts=[fact("CODEC-1", old)],
        behavior_checks_before=[{"check_id": "import", "status": "PASS"}],
        behavior_checks_after=[{"check_id": "import", "status": "FAIL"}],
    )
    assert result["reason"] == "PASSING_EVIDENCE_REGRESSION"


def test_partial_improvement_accepts_codec_fix_even_if_export_still_fails() -> None:
    codec = issue("invalid_literal_codec", "app/main.py", "Use a registered codec.", "UTF8-SIG")
    export = issue("frontend_backend_endpoint_mismatch", "app/main.py", "Publish /api/export.", "missing")
    result = assess(before=[codec, export], after=[export], facts=[fact("CODEC", codec)])
    assert result["status"] == "accepted"
    assert result["issues_fixed_by_partial_acceptance"] == 1


def test_partial_improvement_accepts_static_root_fix_even_if_crud_still_fails() -> None:
    static = issue("static_server_root_mismatch", "app/main.py", "Serve frontend root.", "404")
    crud = issue("runtime_feature_failure", "app/main.py", "CRUD works.", "edit fails")
    result = assess(before=[static, crud], after=[crud], facts=[fact("STATIC", static)])
    assert result["status"] == "accepted"


def test_case_score_not_required_for_provider_job_acceptance() -> None:
    codec = issue("invalid_literal_codec", "app/main.py", "Use a registered codec.", "UTF8-SIG")
    result = assess(before=[codec], after=[], facts=[fact("CODEC", codec)])
    assert result["status"] == "accepted"
    assert "case_score" not in result


def test_partial_improvement_does_not_require_case_score_improvement() -> None:
    """Retain the original regression name used by the implementation increment."""
    test_case_score_not_required_for_provider_job_acceptance()


def test_accepted_without_target_issue_improvement_rejected() -> None:
    blocker = issue("invalid_literal_codec", "app/main.py", "Use a registered codec.", "UTF8-SIG")
    result = assess(before=[blocker], after=[blocker], facts=[fact("CODEC", blocker)])
    assert result["status"] == "rejected"
    assert result["accepted_without_target_issue_improvement"] == 0


def test_repair_accounting_records_partial_acceptance(tmp_path) -> None:
    from scripts import post_build_repair

    record = {
        "issue_id": "CODEC",
        "target_files": ["app/main.py"],
        "coherence_checks_before": [{"kind": "invalid_literal_codec"}],
        "coherence_checks_after": [],
        "fixed_by_delta": True,
        "introduced_new_blockers": [],
        "safe_to_accept_partial": True,
    }
    summary = post_build_repair.write_repair_call_accounting(
        tmp_path,
        [
            {
                "attempt_number": 1,
                "repair_result": {
                    "status": "applied",
                    "changed_files": ["app/main.py"],
                    "provider_calls": 1,
                    "issue_acceptance": [record],
                },
            }
        ],
    )
    assert summary["partial_improvement_accepted_count"] == 1
    assert summary["accepted_without_target_issue_improvement"] == 0
    assert summary["rows"][0]["case_score_required_for_acceptance"] is False
    assert (tmp_path / "repair_call_accounting.json").is_file()
    assert (tmp_path / "repair_call_accounting.csv").is_file()


def test_repair_accounting_records_pre_acceptance_provider_calls(tmp_path) -> None:
    from scripts import post_build_repair

    summary = post_build_repair.write_repair_call_accounting(
        tmp_path,
        [
            {
                "attempt_number": 1,
                "plan": {
                    "provider_actions": [
                        {"path": "frontend/app.js", "issue_ids": ["DOM-1"]}
                    ]
                },
                "repair_result": {
                    "status": "failed",
                    "reason": "PROVIDER_OUTPUT_INVALID",
                    "provider_calls": 2,
                    "changed_files": [],
                },
            }
        ],
    )
    assert len(summary["rows"]) == 2
    assert all(row["issue_level_acceptance"] is False for row in summary["rows"])
    assert all(row["partial_improvement_accepted"] is False for row in summary["rows"])
    assert summary["accepted_without_target_issue_improvement"] == 0


@pytest.mark.parametrize(
    ("target", "owned", "new_source", "syntax_safe", "reason"),
    [
        ("../escape.py", {"../escape.py"}, "print('x')", True, "OWNERSHIP_OR_PATH_REJECT"),
        ("bundle.zip", {"bundle.zip"}, "not a zip", True, "FORBIDDEN_GENERATED_OUTPUT"),
        ("delivery_manifest.json", {"delivery_manifest.json"}, "{}", True, "FORBIDDEN_GENERATED_OUTPUT"),
        ("artifacts/evidence/result.json", {"artifacts/evidence/result.json"}, "{}", True, "FORBIDDEN_GENERATED_OUTPUT"),
        ("app/main.py", {"app/main.py"}, "", True, "CORE_DELETION_OR_MOCK_ONLY_REJECT"),
        ("app/main.py", {"app/main.py"}, "pass", True, "CORE_DELETION_OR_MOCK_ONLY_REJECT"),
        ("app/main.py", {"app/main.py"}, "def broken(:", False, "SYNTAX_VALIDATION_FAILED"),
    ],
)
def test_hard_safety_rejections(target, owned, new_source, syntax_safe, reason) -> None:
    old = issue("invalid_literal_codec", target, "registered codec", "UTF8-SIG")
    result = repair_acceptance.assess_provider_job_partial_acceptance(
        target_file=target,
        before_content="old",
        after_content=new_source,
        coherence_before=[old],
        coherence_after=[],
        evidence_facts=[fact("I-1", old)],
        owned_paths=owned,
        syntax_safe=syntax_safe,
    )
    assert result["status"] == "rejected"
    assert result["reason"] == reason
