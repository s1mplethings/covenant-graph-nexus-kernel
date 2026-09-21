from __future__ import annotations

import json
import pathlib
import time

from scripts import post_build_repair, run_local_pipeline_impl


ROOT = pathlib.Path(__file__).resolve().parents[1]


def pipeline(path: str, component: str = "backend") -> dict:
    return {
        "components": [
            {
                "id": component,
                "required_paths": [path],
                "leaf_work_graph": {
                    "leaves": [{"leaf_id": f"{component}.leaf.001", "owns": [path]}]
                },
            }
        ]
    }


def action_for(row: dict, issue_id: str, path: str, component: str) -> dict:
    return {
        "path": path,
        "component": component,
        "provider_job_id": f"{component}.leaf.001",
        "issue_ids": [issue_id],
        "instruction": "Fix only this evidenced failure.",
        "evidence_facts": [
            {
                "issue_id": issue_id,
                "failed_requirement": row["kind"],
                "expected_behavior": row["expected_behavior"],
                "observed_behavior": row["observed_behavior"],
                "evidence": [{**row, "authority": "deterministic_build_coherence"}],
            }
        ],
    }


def execute(tmp_path, monkeypatch, *, candidate, path, component, content, action):
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_generate_project_by_components",
        lambda *args, **kwargs: {"files": [{"path": path, "content": content}]},
    )
    return run_local_pipeline_impl.execute_provider_job_patch_generation(
        candidate_dir=candidate,
        repair_plan={"attempt_number": 1, "provider_actions": [action]},
        user_goal="repair the candidate",
        component_pipeline=pipeline(path, component),
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        model="provider-model",
        timeout=30,
        internal_context="",
        deadline=time.monotonic() + 30,
        run_dir=tmp_path / "run",
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )


def test_one_of_two_endpoint_issues_fixed_advances_candidate_source(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "app").mkdir(parents=True)
    (candidate / "frontend").mkdir(parents=True)
    backend = (
        "from flask import Flask\napp = Flask(__name__)\n"
        "@app.route('/')\ndef root(): return 'ok'\n"
    )
    (candidate / "app" / "main.py").write_text(backend, encoding="utf-8")
    (candidate / "frontend" / "app.js").write_text(
        "fetch('/api/export'); fetch('/api/preview');\n", encoding="utf-8"
    )
    rows = run_local_pipeline_impl.candidate_build_coherence_issues(candidate)
    export = next(row for row in rows if "/api/export" in row["expected_behavior"])
    repaired = backend + "@app.route('/api/export')\ndef export(): return 'csv'\n"

    result = execute(
        tmp_path,
        monkeypatch,
        candidate=candidate,
        path="app/main.py",
        component="backend",
        content=repaired,
        action=action_for(export, "ENDPOINT-EXPORT", "app/main.py", "backend"),
    )

    assert result["status"] == "applied"
    assert result["issues_fixed_by_partial_acceptance"] == 1
    assert result["accepted_partial_deltas"] == 1
    assert "/api/export" in (candidate / "app" / "main.py").read_text(encoding="utf-8")
    assert any("/api/preview" in row["expected_behavior"] for row in run_local_pipeline_impl.candidate_build_coherence_issues(candidate))


def test_dom_issue_reduction_is_accepted_without_requiring_full_disappearance(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "frontend").mkdir(parents=True)
    original = "\n".join(f"document.getElementById('{name}');" for name in "abcde") + "\n"
    repaired = "\n".join(f"document.getElementById('{name}');" for name in "de") + "\n"
    (candidate / "frontend" / "app.js").write_text(original, encoding="utf-8")
    (candidate / "frontend" / "index.html").write_text(
        '<main></main><script src="app.js"></script>', encoding="utf-8"
    )
    row = run_local_pipeline_impl.candidate_build_coherence_issues(candidate)[0]

    result = execute(
        tmp_path,
        monkeypatch,
        candidate=candidate,
        path="frontend/app.js",
        component="frontend",
        content=repaired,
        action=action_for(row, "DOM-REDUCE", "frontend/app.js", "frontend"),
    )

    assert result["status"] == "applied"
    assert result["issue_acceptance"][0]["fixed_by_delta"] is True
    assert "Missing DOM ids: d, e" in result["issue_acceptance"][0]["coherence_checks_after"][0]["observed_behavior"]


def test_non_json_provider_payload_blocked_without_candidate_materialization(tmp_path, monkeypatch) -> None:
    calls = {"generation": 0}

    def fail_generation(*args, **kwargs):
        calls["generation"] += 1
        raise run_local_pipeline_impl.ProviderContractRepairExhaustedError(
            "component foundation generation failed: provider contract repair exhausted after one request: provider returned non-json project payload",
            raw_output="still prose, not json",
        )

    monkeypatch.setattr(run_local_pipeline_impl, "provider_generate_project_by_components", fail_generation)
    out_dir = tmp_path / "candidate"
    result = run_local_pipeline_impl.run_provider_semantic_review_with_repair(
        user_goal="build a board",
        plan_doc={},
        blueprint={},
        online_inputs={},
        market_research={},
        component_pipeline={"components": []},
        repair_errors=[],
        model="provider-model",
        timeout=30,
        internal_context="",
        deadline=time.time() + 30,
        run_dir=tmp_path / "run",
        out_dir=out_dir,
        result_path=tmp_path / "result.json",
        max_repair_attempts=3,
        phase_log_path=tmp_path / "phase.jsonl",
    )

    assert calls["generation"] == 1
    assert result["provider_failure_classification"] == "BLOCKED_PROVIDER_NON_JSON_PAYLOAD"
    assert result["evidence_status"] == "BLOCKED_PROVIDER"
    assert result["diagnostics"]["schema_repair_attempts"] == 1
    assert result["diagnostics"]["raw_response_excerpt"] == "still prose, not json"
    assert not out_dir.exists()


def test_case03_non_json_provider_payload_classified() -> None:
    exc = run_local_pipeline_impl.ProviderContractRepairExhaustedError(
        "provider returned non-json project payload", raw_output="plain prose"
    )
    diagnostics = run_local_pipeline_impl.provider_non_json_payload_diagnostics(
        exc, component="foundation"
    )
    assert diagnostics["provider_failure_classification"] == "BLOCKED_PROVIDER_NON_JSON_PAYLOAD"
    assert diagnostics["failed_component"] == "foundation"
    assert diagnostics["expected_schema"]["required"] == ["files"]


def test_non_json_payload_does_not_materialize_candidate(tmp_path) -> None:
    exc = run_local_pipeline_impl.ProviderContractRepairExhaustedError(
        "provider returned non-json project payload", raw_output="plain prose"
    )
    candidate = tmp_path / "candidate"
    diagnostics = run_local_pipeline_impl.write_provider_non_json_payload_failure(
        tmp_path / "run", candidate, exc, [], None, component="foundation"
    )
    assert diagnostics["candidate_created"] is False
    assert diagnostics["materialized"] is False
    assert not candidate.exists()


def test_non_json_payload_gets_one_schema_repair_attempt(monkeypatch) -> None:
    calls = {"count": 0}

    def non_json_repair(*args, **kwargs):
        calls["count"] += 1
        return "still not json"

    monkeypatch.setattr(run_local_pipeline_impl, "provider_text", non_json_repair)
    try:
        run_local_pipeline_impl.parse_provider_json_object_with_one_repair(
            "not json",
            model="provider-model",
            timeout=30,
            stage="component_file_generation",
            component="foundation",
            target_file="app.py",
            max_tokens=1000,
            phase_log_path=None,
            routing_policy=None,
        )
    except run_local_pipeline_impl.ProviderContractRepairExhaustedError as exc:
        assert "after one request" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("non-JSON schema repair must be blocked")
    assert calls["count"] == 1


def test_schema_repair_failure_reports_blocked_provider_non_json_payload() -> None:
    exc = run_local_pipeline_impl.ProviderContractRepairExhaustedError(
        "provider contract repair exhausted after one request", raw_output="bad"
    )
    diagnostics = run_local_pipeline_impl.provider_non_json_payload_diagnostics(exc)
    assert diagnostics["schema_repair_attempts"] == 1
    assert diagnostics["provider_failure_classification"] == "BLOCKED_PROVIDER_NON_JSON_PAYLOAD"


def test_bounded_json_extraction_avoids_schema_repair_call(monkeypatch) -> None:
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "provider_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("repair should not run")),
    )
    doc, raw = run_local_pipeline_impl.parse_provider_json_object_with_one_repair(
        'preface {"files":[{"path":"app.py","content":"print(1)"}]} suffix',
        model="provider-model",
        timeout=30,
        stage="component_file_generation",
        component="foundation",
        target_file="app.py",
        max_tokens=1000,
        phase_log_path=None,
        routing_policy=None,
    )
    assert doc["files"][0]["path"] == "app.py"
    assert raw.startswith("preface")


def test_invalid_python_delta_is_rejected_before_candidate_write(tmp_path, monkeypatch) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "app").mkdir(parents=True)
    original = "value = b'x'.decode('UTF8-SIG')\n"
    (candidate / "app" / "main.py").write_text(original, encoding="utf-8")
    row = run_local_pipeline_impl.candidate_build_coherence_issues(candidate)[0]
    result = execute(
        tmp_path,
        monkeypatch,
        candidate=candidate,
        path="app/main.py",
        component="backend",
        content="def broken(:\n",
        action=action_for(row, "CODEC", "app/main.py", "backend"),
    )
    assert result["status"] == "failed"
    assert result["rejected_target_files"]["app/main.py"]["reason"] == "SYNTAX_VALIDATION_FAILED"
    assert (candidate / "app" / "main.py").read_text(encoding="utf-8") == original


def test_generic_component_repair_expansion_is_forbidden() -> None:
    issue = {
        "issue_id": "CSV-UPLOAD",
        "failed_requirement": "CSV upload contract",
        "expected_behavior": "Upload a real CSV file.",
        "observed_behavior": "The upload endpoint rejects the file.",
        "evidence": [{"authority": "independent_evaluator"}],
    }
    plan = post_build_repair.bind_repair_plan_to_issue_ledger(
        {"provider_actions": [{"path": "frontend/index.html"}]},
        {
            "root_causes_total": 1,
            "repair_bundles": [
                {
                    "bundle_id": "B-1",
                    "component": "frontend",
                    "ownership_unit": "frontend.leaf.001",
                    "issue_ids": ["CSV-UPLOAD"],
                    "affected_files": ["frontend/app.js"],
                    "instruction": "Repair only the evidenced upload contract.",
                    "acceptance_conditions": ["CSV upload succeeds"],
                    "evidence_facts": [issue],
                }
            ],
        },
        {
            "components": [
                {
                    "id": "frontend",
                    "leaf_work_graph": {
                        "leaves": [
                            {
                                "leaf_id": "frontend.leaf.001",
                                "owns": ["frontend/app.js", "frontend/index.html"],
                            }
                        ]
                    },
                }
            ]
        },
    )

    assert plan["target_files"] == ["frontend/app.js"]
    assert [row["path"] for row in plan["provider_actions"]] == ["frontend/app.js"]
    assert plan["partial_acceptance_policy"]["whole_component_acceptance_required"] is False


def test_only_one_provider_execution_path() -> None:
    contracts = (ROOT / "scripts" / "provider_jobs.py").read_text(encoding="utf-8")
    production = (ROOT / "scripts" / "run_local_pipeline_impl.py").read_text(
        encoding="utf-8"
    )

    assert "ThreadPoolExecutor" not in contracts
    assert "def execute_provider_jobs" not in contracts
    assert "ThreadPoolExecutor" in production
    assert "def execute_provider_job_patch_generation" in production
