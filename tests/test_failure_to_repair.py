from __future__ import annotations

import json
import pathlib

import pytest

from benchmarks.project_generation_v1 import audit_failure_to_repair, independent_evaluator
from scripts import issue_ledger, post_build_repair, repair_evidence_contract, run_local_pipeline_impl


def canonical_repair_evidence(
    candidate: pathlib.Path,
    *,
    repair_round: int = 1,
    repair_eligible: bool = True,
    blocking_reason: str = "",
) -> dict:
    return repair_evidence_contract.build(
        run_id="RUN-1",
        project_id="PROJECT-1",
        user_goal="Build a local application",
        candidate_dir=candidate,
        candidate_sha256=run_local_pipeline_impl._plain_tree_sha256(candidate),
        repair_round=repair_round,
        failure_category="RUNTIME",
        failures=[
            {
                "criterion_id": "runtime.documented_entrypoint",
                "status": "FAIL",
                "failure_category": "RUNTIME",
                "observed_behavior": "documented entry point exits with status 1",
                "affected_files": ["app/main.py"],
                "affected_work_nodes": ["backend.leaf.001"],
            }
        ],
        repair_eligible=repair_eligible,
        blocking_reason=blocking_reason,
        constraints={"maximum_total_rounds": 2},
    )


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


def test_failure_audit_is_case_name_path_and_number_independent(tmp_path) -> None:
    run = tmp_path / "arbitrary-run"
    case = run / "cases" / "opaque-name"
    artifacts = run / "production_slots" / "worker-x" / "run" / "artifacts"
    case.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    (case / "case_result.json").write_text(json.dumps({"case_id": "HOLDOUT-ZETA", "hard_failures": ["behavior.export"], "metrics": {"production_return_code": 0}}), encoding="utf-8")
    issue = {"issue_id": "I-Z", "requirement": "behavior.export", "affected_files": ["src/feature.py"]}
    (artifacts / "post_build_issue_ledger_v0.json").write_text(json.dumps({"issues": [issue]}), encoding="utf-8")
    (artifacts / "repair_plan.json").write_text(json.dumps({"provider_actions": [{"provider_job_id": "J-Z", "issue_ids": ["I-Z"], "acceptance_conditions": ["observable behavior restored"]}]}), encoding="utf-8")
    (artifacts / "repair_call_accounting.json").write_text(json.dumps({"rows": [{"issue_ids": ["I-Z"], "accepted": True, "fixed_by_delta": True}]}), encoding="utf-8")
    phase = run / "production_slots" / "worker-x" / "run" / "provider_phase_log.jsonl"
    phase.write_text("\n".join(json.dumps(row) for row in [{"event": "provider_request", "target_file": "src/feature.py"}, {"event": "component_leaf_completed", "target_file": "src/feature.py"}]), encoding="utf-8")
    audited = audit_failure_to_repair.audit_case(run)
    assert audited["case_id"] == "HOLDOUT-ZETA"
    assert audited["fixed_failure_count"] == 1

    # Keeping every fixture label and path stable must not preserve the old
    # answer when the observed requirement changes.
    (case / "case_result.json").write_text(json.dumps({"case_id": "HOLDOUT-ZETA", "hard_failures": ["behavior.import"], "metrics": {"production_return_code": 0}}), encoding="utf-8")
    changed = audit_failure_to_repair.audit_case(run)
    assert changed["fixed_failure_count"] == 0
    assert changed["unmapped_failure_count"] == 1


def test_ordinary_runtime_failure_prepares_existing_provider_job_repair(
    tmp_path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    candidate = tmp_path / "production-candidate"
    evaluated = tmp_path / "evaluated-copy"
    (run_dir / "artifacts").mkdir(parents=True)
    for root in (candidate, evaluated):
        (root / "app").mkdir(parents=True)
        (root / "app" / "main.py").write_text("print('start')\n", encoding="utf-8")

    def fake_prepare(run_dir_value, audit, *, user_goal):
        pending = pathlib.Path(run_dir_value) / "artifacts" / "pending_repair_plan.json"
        pending.write_text(
            json.dumps(
                {
                    "kind": "CGKNSupervisionProviderRepairPlan",
                    "provider_actions": [
                        {
                            "component": "backend",
                            "path": "app/main.py",
                            "provider_job_id": "backend.leaf.001",
                        }
                    ],
                    "affected_components": ["backend"],
                    "affected_files": ["app/main.py"],
                    "supervision_scope": "project",
                    "checkpoint_id": "old",
                }
            ),
            encoding="utf-8",
        )
        return {
            "status": "pending_provider_repair",
            "affected_components": ["backend"],
            "affected_files": ["app/main.py"],
            "provider_authoring_required": True,
        }

    monkeypatch.setattr(
        run_local_pipeline_impl,
        "prepare_supervision_provider_repair",
        fake_prepare,
    )
    evidence = canonical_repair_evidence(evaluated)

    receipt = run_local_pipeline_impl.prepare_observed_project_failure_provider_repair(
        run_dir,
        evidence,
        user_goal="Build a local application",
        candidate_dir=candidate,
    )

    assert receipt["status"] == "pending_provider_repair"
    assert receipt["triggered_by_independent_failure"] is True
    pending = json.loads(
        (run_dir / "artifacts" / "pending_repair_plan.json").read_text(
            encoding="utf-8"
        )
    )
    assert pending["kind"] == "CGKNObservedProjectFailureProviderRepairPlan"
    assert pending["repair_round"] == 1
    assert pending["maximum_total_rounds"] == 2
    assert pending["affected_files"] == ["app/main.py"]
    assert "supervision_scope" not in pending


def test_true_policy_blocker_does_not_prepare_provider_repair(tmp_path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_text("print('x')\n", encoding="utf-8")
    receipt = run_local_pipeline_impl.prepare_observed_project_failure_provider_repair(
        tmp_path,
        canonical_repair_evidence(
            candidate, repair_eligible=False, blocking_reason="policy_violation"
        ),
        user_goal="Build an unsafe project",
        candidate_dir=candidate,
    )

    assert receipt["status"] == "blocked"
    assert receipt["blocking_reason"] == "policy_violation"
    assert receipt["provider_authoring_required"] is False


def test_observed_failure_repair_rejects_round_three(tmp_path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_text("print('x')\n", encoding="utf-8")
    evidence = canonical_repair_evidence(candidate)
    evidence["repair_round"] = 3
    with pytest.raises(RuntimeError, match="repair_round_invalid"):
        run_local_pipeline_impl.prepare_observed_project_failure_provider_repair(
            tmp_path,
            evidence,
            user_goal="Build a project",
            candidate_dir=candidate,
        )


def test_python_dependency_contract_rejects_undeclared_runtime_import() -> None:
    issues = run_local_pipeline_impl.python_dependency_contract_issues(
        [
            {
                "path": "app/main.py",
                "content": "from flask import Flask\napp = Flask(__name__)\n",
            },
            {"path": "requirements.txt", "content": "pytest==8.0.0\n"},
            {
                "path": "pyproject.toml",
                "content": "[project]\nname='demo'\nversion='0.1.0'\ndependencies=[]\n",
            },
        ]
    )

    assert len(issues) == 1
    assert issues[0]["kind"] == "external_dependency_not_declared"
    assert issues[0]["path"] == "requirements.txt"
    assert issues[0]["related_paths"] == ["app/main.py"]


def test_python_dependency_contract_accepts_stdlib_local_and_declared_imports() -> None:
    issues = run_local_pipeline_impl.python_dependency_contract_issues(
        [
            {
                "path": "app/main.py",
                "content": "import json\nfrom src.storage import load\nfrom flask import Flask\n",
            },
            {"path": "src/storage.py", "content": "def load(): return {}\n"},
            {"path": "requirements.txt", "content": "Flask==3.1.0\n"},
        ]
    )

    assert issues == []


def test_documented_entrypoint_contract_rejects_missing_python_target() -> None:
    issues = run_local_pipeline_impl.documented_entrypoint_contract_issues(
        [{"path": "README.md", "content": "```bash\npython app.py\n```\n"}]
    )

    assert [item["kind"] for item in issues] == ["documented_entrypoint_target_missing"]


def test_documented_entrypoint_contract_accepts_delivered_target() -> None:
    issues = run_local_pipeline_impl.documented_entrypoint_contract_issues(
        [
            {"path": "README.md", "content": "```bash\npython app/main.py\n```\n"},
            {"path": "app/main.py", "content": "print('ready')\n"},
        ]
    )

    assert issues == []


def test_clean_directory_import_smoke_rejects_host_only_dependency(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("import package_only_on_developer_machine\n", encoding="utf-8")
    env_root = tmp_path / "venv"
    prepared = independent_evaluator.prepare_clean_environment(project, env_root)

    checks = independent_evaluator.static_checks(
        project, independent_evaluator._venv_python(env_root)
    )

    assert prepared["status"] == "PASS"
    assert prepared["network_attempts"] == 0
    assert checks["compileall"]["status"] == "PASS"
    assert checks["import_smoke"]["status"] == "FAIL"
    assert checks["status"] == "FAIL"


def test_clean_runtime_bootstraps_missing_state_directory_and_restarts(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("Run `python app.py`.\n", encoding="utf-8")
    (project / "app.py").write_text(
        """from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os
from pathlib import Path
DATA = Path('data/state.json')
DATA.parent.mkdir(parents=True, exist_ok=True)
if not DATA.exists(): DATA.write_text('[]', encoding='utf-8')
class H(BaseHTTPRequestHandler):
    def _send(self, value):
        body=json.dumps(value).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/': self._send({'app':'ready'})
        elif self.path == '/health': self._send({'ok':True})
        elif self.path == '/api/records': self._send(json.loads(DATA.read_text(encoding='utf-8')))
        else: self.send_error(404)
    def do_POST(self):
        if self.path != '/api/records': self.send_error(404); return
        value=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}'); rows=json.loads(DATA.read_text(encoding='utf-8')); rows.append(value); DATA.write_text(json.dumps(rows),encoding='utf-8'); self._send(value)
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', int(os.environ.get('PORT','8000'))), H).serve_forever()
""",
        encoding="utf-8",
    )
    env_root = tmp_path / "venv"
    prepared = independent_evaluator.prepare_clean_environment(project, env_root)

    receipt = independent_evaluator.runtime_probe(
        project,
        independent_evaluator._venv_python(env_root),
        "CASE_09_LOCAL_REST_SERVICE_DASHBOARD",
        tmp_path / "evidence",
    )

    assert prepared["status"] == "PASS"
    assert receipt["status"] == "PASS"
    assert receipt["restart"]["status"] == "PASS"
    assert receipt["restart"]["persisted_marker"] is True
    assert receipt["shutdown"] == "terminated"


def test_runtime_probe_reports_missing_documented_entrypoint_as_fail(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("Run `python app.py`.", encoding="utf-8")
    monkeypatch.setattr(
        independent_evaluator.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing executable")),
    )

    receipt = independent_evaluator.runtime_probe(
        project,
        pathlib.Path("python"),
        "CASE_03_LOCAL_PROJECT_BOARD",
        tmp_path / "evidence",
    )

    assert receipt["status"] == "FAIL"
    assert receipt["mode"] == "launch"
    assert receipt["error_type"] == "FileNotFoundError"
    assert "could not be launched" in receipt["reason"]
