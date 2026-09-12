from __future__ import annotations

import json

from scripts import audit_failure_to_repair, issue_ledger, post_build_repair


def pipeline() -> dict:
    return {
        "components": [
            {
                "id": "backend",
                "leaf_work_graph": {
                    "leaves": [
                        {"leaf_id": "backend.leaf.001", "owns": ["app/main.py"]},
                        {"leaf_id": "backend.leaf.002", "owns": ["src/csv_export.py"]},
                    ]
                },
            },
            {
                "id": "frontend",
                "leaf_work_graph": {
                    "leaves": [
                        {"leaf_id": "frontend.leaf.001", "owns": ["frontend/index.html"]},
                        {"leaf_id": "frontend.leaf.002", "owns": ["frontend/app.js"]},
                    ]
                },
            },
        ]
    }


def test_issue_ledger_maps_unmatched_evaluator_failure_to_exact_provider_jobs() -> None:
    ledger = post_build_repair.enrich_issue_ledger_with_evaluator_evidence(
        {"issues": [], "issues_total": 0},
        [
            {
                "criterion_id": "export_download_failure",
                "status": "FAIL",
                "user_action": "Export the cleaned CSV",
                "expected_behavior": "A CSV download starts.",
                "observed_behavior": "The export button returns 404.",
            }
        ],
        pipeline(),
    )

    assert ledger["issues_total"] == 2
    assert {row["affected_provider_job"] for row in ledger["issues"]} == {
        "backend.leaf.001",
        "frontend.leaf.002",
    }
    assert all(row["repairable"] is True for row in ledger["issues"])
    assert all(len(row["affected_files"]) == 1 for row in ledger["issues"])


def test_issue_ledger_does_not_expand_unmapped_failure_to_component_scope() -> None:
    ownership = post_build_repair.provider_job_ownership_map(pipeline())
    issues = issue_ledger.issues_from_evaluator_failure(
        {
            "criterion_id": "unknown_product_failure",
            "status": "FAIL",
            "expected_behavior": "The product behaves correctly.",
            "observed_behavior": "Unknown failure with no path evidence.",
        },
        ownership,
    )

    assert len(issues) == 1
    assert issues[0]["repairable"] is False
    assert issues[0]["affected_files"] == []
    assert issues[0]["repair_route"] == "halt"


def test_failure_to_repair_audit_tracks_fixed_delta(tmp_path) -> None:
    run = tmp_path / "run"
    case = run / "cases" / "CASE_01_CSV_DATA_CLEANER"
    artifacts = run / "production_slots" / "slot" / "run" / "artifacts"
    case.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    (case / "case_result.json").write_text(
        json.dumps(
            {
                "case_id": "CASE_01_CSV_DATA_CLEANER",
                "score": 40,
                "hard_failures": ["csv.export"],
                "metrics": {"production_return_code": 0},
            }
        ),
        encoding="utf-8",
    )
    issue = {
        "issue_id": "ISSUE-1",
        "requirement": "csv.export",
        "affected_provider_job": "backend.leaf.001",
        "affected_files": ["app/main.py"],
    }
    (artifacts / "post_build_issue_ledger_attempt_1.json").write_text(
        json.dumps({"issues": [issue]}), encoding="utf-8"
    )
    (artifacts / "post_build_repair_plan_attempt_1.json").write_text(
        json.dumps(
            {
                "provider_actions": [
                    {
                        "provider_job_id": "backend.leaf.001",
                        "issue_ids": ["ISSUE-1"],
                        "path": "app/main.py",
                        "acceptance_conditions": ["download succeeds"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "repair_call_accounting.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "issue_ids": ["ISSUE-1"],
                        "accepted": True,
                        "fixed_by_delta": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    phase = run / "production_slots" / "slot" / "run" / "provider_phase_log.jsonl"
    phase.write_text(
        "\n".join(
            [
                json.dumps({"event": "provider_request", "target_file": "app/main.py"}),
                json.dumps({"event": "component_leaf_completed", "target_file": "app/main.py"}),
            ]
        ),
        encoding="utf-8",
    )

    audited = audit_failure_to_repair.audit_case(run)

    assert audited["mapped_to_issue_count"] == 1
    assert audited["provider_jobs_created_count"] == 1
    assert audited["provider_calls_count"] == 1
    assert audited["provider_deltas_count"] == 1
    assert audited["accepted_delta_count"] == 1
    assert audited["fixed_failure_count"] == 1


def test_case03_timeout_explains_zero_repair_calls(tmp_path) -> None:
    run = tmp_path / "case03"
    case = run / "cases" / "CASE_03_LOCAL_PROJECT_BOARD"
    case.mkdir(parents=True)
    (case / "case_result.json").write_text(
        json.dumps(
            {
                "case_id": "CASE_03_LOCAL_PROJECT_BOARD",
                "score": 5,
                "hard_failures": ["delivery_not_independently_runnable"],
                "metrics": {"production_return_code": 124},
            }
        ),
        encoding="utf-8",
    )

    audited = audit_failure_to_repair.audit_case(run)

    assert audited["case03_no_repair_reason"] == "production_timeout_before_post_build_issue_ledger"
    assert audited["case03_repair_skipped"]["evaluator_failures_seen"] == 1
    assert audited["case03_repair_skipped"]["fix_required_module"] == "production_stage_before_post_build"
    assert audited["unmapped_failure_count"] == 1


def test_case03_semantic_review_block_explains_zero_post_build_repair(tmp_path) -> None:
    run = tmp_path / "case03"
    case = run / "cases" / "CASE_03_LOCAL_PROJECT_BOARD"
    slot = run / "production_slots" / "slot"
    case.mkdir(parents=True)
    slot.mkdir(parents=True)
    (case / "case_result.json").write_text(
        json.dumps(
            {
                "case_id": "CASE_03_LOCAL_PROJECT_BOARD",
                "score": 5,
                "hard_failures": ["candidate_missing"],
                "metrics": {"production_return_code": 1},
            }
        ),
        encoding="utf-8",
    )
    (slot / "production_result.json").write_text(
        json.dumps(
            {
                "candidate_materialized": False,
                "diagnostics": {"stage": "provider_semantic_review", "status": "blocked"},
            }
        ),
        encoding="utf-8",
    )

    audited = audit_failure_to_repair.audit_case(run)

    skipped = audited["case03_repair_skipped"]
    assert skipped["case03_repair_skipped"] is True
    assert skipped["skip_reason"] == "candidate_not_materialized_provider_semantic_review_blocked_before_post_build"
    assert skipped["issues_extracted"] == 0
    assert skipped["provider_jobs_planned"] == 0
    assert skipped["fix_required_module"] == "scripts/run_local_pipeline_impl.py:run_provider_semantic_review_with_repair"


def test_score_drop_route_audit_recognizes_factory_app_variable() -> None:
    source = """
@app_instance.route('/health', methods=['GET'])
def health(): ...

@api.post('/upload')
def upload(): ...
"""

    assert audit_failure_to_repair.routes(source) == ["/health", "/upload"]
