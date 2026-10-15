from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "autonomous_project_acceptance", ROOT / "scripts" / "autonomous_project_acceptance.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def contract() -> dict:
    return {
        "kind": "CGKNTestabilityContract",
        "schema_version": "1.0",
        "project_goal": "Add records and export a summary.",
        "adapter": {"type": "cli", "working_directory": ".", "business_logic_entrypoint": "main.py"},
        "operations": [
            {
                "id": "add", "description": "Add a record.",
                "input_schema": {"type": "object", "additionalProperties": False, "required": ["title"], "properties": {"title": {"type": "string"}}},
                "argv": ["python", "main.py", "add", "{title}"], "expected_exit_codes": [0],
                "oracle": {"stdout_format": "none", "state_change": "must_change", "state_paths": ["data.json"], "required_artifacts": []},
                "affected_files": ["main.py"]
            },
            {
                "id": "export", "description": "Export a summary.",
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
                "argv": ["python", "main.py", "export"], "expected_exit_codes": [0],
                "oracle": {"stdout_format": "json", "stdout_schema": {"type": "object", "required": ["count"]}, "state_change": "any", "state_paths": ["data.json"], "required_artifacts": ["summary.json"]},
                "affected_files": ["main.py"]
            }
        ],
        "scenarios": [{
            "id": "add_export", "user_task": "Add and export one record.",
            "steps": [{"operation": "add", "args": {"title": "hello"}}, {"operation": "export", "args": {}}],
            "success_conditions": [{"kind": "file_exists", "path": "summary.json"}, {"kind": "json_pointer_number_equals", "path": "summary.json", "pointer": "/count", "expected": 1}]
        }],
        "observable_state": [{"id": "ledger", "path": "data.json", "format": "json", "verification": "JSON list"}],
        "final_artifacts": [{"id": "summary", "path": "summary.json", "format": "json", "verification": "count equals persisted records"}],
        "execution_limits": {"network": False, "shell": False, "max_operations": 8, "timeout_seconds": 10}
    }


def create_project(tmp_path: pathlib.Path) -> pathlib.Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text(
        "import json, pathlib, sys\n"
        "p=pathlib.Path('data.json'); rows=json.loads(p.read_text()) if p.exists() else []\n"
        "if sys.argv[1]=='add': rows.append({'title':sys.argv[2]}); p.write_text(json.dumps(rows)); raise SystemExit(0)\n"
        "out={'count':len(rows)}; pathlib.Path('summary.json').write_text(json.dumps(out)); print(json.dumps(out))\n",
        encoding="utf-8",
    )
    (project / "README.md").write_text("Run python main.py add TITLE.", encoding="utf-8")
    (project / "testability_contract.json").write_text(json.dumps(contract()), encoding="utf-8")
    return project


def test_contract_rejects_test_only_shortcut(tmp_path: pathlib.Path) -> None:
    project = create_project(tmp_path)
    value = contract()
    value["operations"][0]["argv"] = ["python", "tests/fake_success.py"]

    errors = module.validate_contract(value, project)

    assert any("test-only" in item for item in errors)


def test_operation_schema_rejects_unknown_without_mapping() -> None:
    action, error = module.validate_action(contract(), {"operation": "delete_all", "args": {}})
    assert action is None
    assert error["reason"] == "unsupported_operation"


def test_action_rejects_absolute_output_path_before_execution() -> None:
    value = contract()
    value["operations"][1]["input_schema"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["out"],
        "properties": {"out": {"type": "string"}},
    }
    value["operations"][1]["argv"] = [
        "python", "main.py", "export", "--out", "{out}"
    ]

    action, error = module.validate_action(
        value, {"operation": "export", "args": {"out": "/outside/report.json"}}
    )

    assert action is None
    assert error["reason"] == "unsafe_path_argument"


def test_real_cli_execution_and_independent_oracles(tmp_path: pathlib.Path) -> None:
    project = create_project(tmp_path)
    value = contract()
    actions = module.deterministic_actions(value)

    rows, scenario_issues = module._execute_sequence(project, value, actions)

    assert [row["returncode"] for row in rows] == [0, 0]
    assert all(not row["independent_issues"] for row in rows)
    assert scenario_issues == []
    assert json.loads((project / "summary.json").read_text())["count"] == 1


def test_missing_contract_blocks_instead_of_accepting(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('ok')\n", encoding="utf-8")
    report = module.run_acceptance(project, tmp_path / "run", public_goal="run")
    assert report["recommendation_status"] == "BLOCKED"
    assert report["formal_evidence_status"] == "NOT_EVALUATED"


def test_repair_audit_is_separate_from_formal_status() -> None:
    audit = module.acceptance_audit({"recommendation_status": "REPAIR_REQUIRED", "blockers": ["bad"], "findings": [{"finding_id": "F", "affected_files": ["main.py"]}]})
    assert audit["action"] == "rework_project"
    assert audit["repair_targets"] == ["main.py"]


def test_complete_acceptance_runs_real_program_and_emits_accepted(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = create_project(tmp_path)

    class FakeClient:
        def __init__(self, **_kwargs):
            self.calls = []

        def call(self, *_args, **_kwargs):
            receipt = {"project_id": "generated_project", "group": "semantic", "round": 1, "model": "fake", "provider_host": "local", "request_sha256": "0" * 64, "response_sha256": "1" * 64, "input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "estimated_cost_usd": 0, "duration_seconds": 0.01}
            self.calls.append(receipt)
            return {"document": {"actions": []}, "receipt": receipt}

    monkeypatch.setattr(module.p3, "ModelClient", FakeClient)
    report = module.run_acceptance(project, tmp_path / "run", public_goal="Add and export one record.", model="fake")

    assert report["recommendation_status"] == "ACCEPTED"
    assert report["formal_evidence_status"] == "NOT_EVALUATED"
    assert report["release_authority"] is False
    assert report["findings"] == []
    assert (tmp_path / "run" / "raw_execution.json").is_file()


def test_acceptance_report_schema_keeps_recommendation_separate() -> None:
    schema = json.loads((ROOT / "schemas" / "autonomous_project_acceptance_report_v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["formal_evidence_status"]["const"] == "NOT_EVALUATED"
    assert schema["properties"]["release_authority"]["const"] is False
    assert "ACCEPTED" in schema["properties"]["recommendation_status"]["enum"]

