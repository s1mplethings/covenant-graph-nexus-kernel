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
    # The retained issue-level predicate is now an independent DAG checker.
    from scripts.repair_acceptance import assess_provider_job_partial_acceptance
    from tests.generation_migration_support import candidate_run
    from cgkn.orchestration import CapabilityNode
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    import hashlib
    before=(candidate/path).read_text(encoding='utf-8')
    coherence=run_local_pipeline_impl.candidate_build_coherence_issues(candidate)
    observations={}
    def check(root,contract):
        after=(root/path).read_text(encoding='utf-8');syntax=True
        if path.endswith('.py'):
            try:compile(after,path,'exec')
            except SyntaxError:syntax=False
        assessment=assess_provider_job_partial_acceptance(target_file=path,before_content=before,after_content=after,
            coherence_before=coherence,coherence_after=run_local_pipeline_impl.candidate_build_coherence_issues(root),
            evidence_facts=action['evidence_facts'],owned_paths={path},syntax_safe=syntax)
        observations.update(assessment)
        return {'passed':assessment['safe_to_accept_partial'],'observed':assessment}
    reads={p.relative_to(candidate).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in candidate.rglob('*') if p.is_file() and p.relative_to(candidate).as_posix()!=path}
    leaf=build_leaf_contract(goal='Repair the evidenced failure',kind='IMPLEMENTATION',scope=[path],
        acceptance=['current-contract'],checker='source',output_identity='repair',effect_domains=['filesystem','external_network'],
        executor='llm.cheap@1',expected_delta='Owned issue improves without regressions',read_scope=list(reads),read_subjects=reads)
    node=CapabilityNode('writer',capability_ref='code',config={'executor_ref':'llm.cheap@1','leaf_contract':leaf})
    summary,store,runner,tree,calls,work=candidate_run(tmp_path,workspace=candidate,files={path:content},check=check,nodes=(node,))
    return {**observations,'status':'applied' if summary.status=='SUCCEEDED' else 'failed',
            'rejected_target_files':{} if summary.status=='SUCCEEDED' else {path:{'reason':observations['reason']}}}


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
    from tests.generation_migration_support import assert_current_generation_behavior
    assert_current_generation_behavior(tmp_path,'invalid_json')


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
    assert "def execute_provider_job_patch_generation" not in production
    service=(ROOT/'cgkn/application/software_project/service.py').read_text(encoding='utf-8')
    assert 'produce_project_session' in service
    assert 'run_provider_generation_job' in (ROOT/'scripts/codex_conversation.py').read_text(encoding='utf-8')
