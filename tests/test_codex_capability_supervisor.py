from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

import jsonschema
import pytest

from scripts import codex_capability_supervisor as supervisor
from scripts import dynamic_pipeline_runner
from scripts import pipeline_manifest
from scripts import run_local_pipeline_impl
from scripts import requirement_decision_lane


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _request() -> dict:
    return supervisor.build_escalation_request(
        goal_summary="Build an offline task and bug CLI with real CRUD and atomic JSON persistence.",
        capability_gap="The generated project exposed command names but implemented a generic stage skeleton instead of domain behavior.",
        category="generation_failure",
        librarian_context={
            "kind": "CGKNLibrarianContextPack",
            "selected_items": [
                {
                    "id": f"ctx-{index}",
                    "path": f"evidence/{index}.json",
                    "summary": "Direct requirement or interface evidence " + ("x" * 2000),
                }
                for index in range(20)
            ],
            "api_key": "sk-this-value-must-never-survive",
            "excluded_count": 12,
        },
        failure_evidence=[
            {
                "id": "provider-run",
                "kind": "provider_phase_log",
                "path": "generated/run/provider_phase_log.jsonl",
                "summary": "87 requests; 70 belonged to tests; Bearer abcdefghijklmnopqrstuvwxyz",
            }
        ],
        prior_attempts=["Provider generation stopped after disproportionate test retries."],
    )


def test_escalation_request_is_bounded_redacted_hashed_and_schema_valid() -> None:
    request = _request()

    assert supervisor.validate_escalation_request(request) == []
    assert len(request["librarian_context"]["selected_items"]) == 8
    serialized = json.dumps(request, ensure_ascii=False)
    assert "sk-this-value" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized
    assert len(serialized) <= request["budgets"]["max_request_chars"]
    jsonschema.Draft202012Validator(
        _schema("codex_capability_escalation.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(request)


def test_response_builds_valid_advisory_brief_and_shared_handoff() -> None:
    request = _request()
    response = supervisor.build_supervisor_response(
        request,
        workflow_state="ready",
        summary="Replace the generic pipeline skeleton with a direct domain model and bounded command services.",
        diagnosis=[
            "Manifest expansion treated each test intent as a separate generation leaf.",
            "CLI dispatch passed command-name strings where the orchestrator required callables.",
        ],
        provider_guidance=[
            "Implement one WorkItem model, one atomic JSON repository, and direct command handlers before generating tests.",
            "Cap the medium CLI at eight implementation files and five test files; reject manifests that do not map every requested command to a concrete handler.",
        ],
        repair_targets=["scripts/requirement_decision_lane.py", "scripts/run_local_pipeline_impl.py"],
        acceptance_checks=[
            "A CLI smoke flow adds, moves, lists, summarizes, exports, and imports one task and one bug.",
            "A deterministic preflight rejects a manifest whose command handlers are absent from published interfaces.",
        ],
        tool_evidence_requests=["Run the candidate pytest suite with host plugin autoload disabled."],
        known_limits=["This brief is advisory and does not prove the generated candidate passes."],
    )
    brief = supervisor.build_capability_brief(request, response)
    patch = supervisor.whiteboard_patch_from_brief(brief)

    assert supervisor.validate_supervisor_response(request, response) == []
    assert brief["kind"] == supervisor.BRIEF_KIND
    assert brief["authority"]["formal_evidence_status"] == "NOT_EVALUATED"
    assert patch["codex_capability_supervision"]["advisory_only"] is True
    assert patch["codex_capability_supervision"]["provider_guidance"]
    jsonschema.Draft202012Validator(
        _schema("codex_capability_supervisor_response.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(response)
    jsonschema.Draft202012Validator(
        _schema("codex_capability_brief.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(brief)

    with tempfile.TemporaryDirectory() as temp_dir:
        session_path = pathlib.Path(temp_dir) / "agent_session.jsonl"
        supervisor.append_handoff_event(session_path, request)
        supervisor.append_handoff_event(session_path, response)
        supervisor.append_handoff_event(session_path, brief)
        events = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]

    assert [event["kind"] for event in events] == [
        "codex_capability_escalation_requested",
        "codex_capability_supervisor_responded",
        "codex_capability_brief_validated",
    ]
    assert all(event["advisory_only"] is True for event in events)


def test_formal_provider_projection_accepts_only_valid_ready_brief() -> None:
    request = _request()
    response = supervisor.build_supervisor_response(
        request,
        workflow_state="ready",
        summary="Keep the child project compact and bind every command to one concrete handler.",
        provider_guidance=["Use direct model, repository, service, and CLI ownership boundaries."],
        acceptance_checks=["Run add, list, search, and delete through the real CLI."],
        known_limits=["Agent guidance is advisory and cannot authorize delivery."],
    )
    brief = supervisor.build_capability_brief(request, response)

    assert supervisor.validate_capability_brief(brief) == []
    projection = run_local_pipeline_impl.codex_capability_brief_provider_projection(brief)
    pipeline = run_local_pipeline_impl.apply_codex_capability_supervision(
        {"components": [{"id": "foundation"}, {"id": "backend"}]},
        projection,
    )

    assert projection["authority"]["candidate_write_authorized"] is False
    assert pipeline["codex_capability_supervision"]["brief_sha256"] == brief["brief_sha256"]
    assert all(
        component["codex_capability_supervision"]["brief_sha256"] == brief["brief_sha256"]
        for component in pipeline["components"]
    )


def test_formal_provider_projection_rejects_tampering_and_binds_checkpoint_identity() -> None:
    request = _request()
    response = supervisor.build_supervisor_response(
        request,
        workflow_state="ready",
        summary="Bounded guidance",
        provider_guidance=["Implement direct handlers."],
    )
    brief = supervisor.build_capability_brief(request, response)
    projection = run_local_pipeline_impl.codex_capability_brief_provider_projection(brief)
    first = {"id": "backend", "codex_capability_supervision": projection}
    second = json.loads(json.dumps(first))
    second["codex_capability_supervision"]["brief_sha256"] = "f" * 64

    assert run_local_pipeline_impl.component_checkpoint_contract_hash(first) != run_local_pipeline_impl.component_checkpoint_contract_hash(second)

    tampered = json.loads(json.dumps(brief))
    tampered["authority"]["candidate_write_authorized"] = True
    with pytest.raises(RuntimeError, match="CODEX_CAPABILITY_BRIEF_INVALID"):
        run_local_pipeline_impl.codex_capability_brief_provider_projection(tampered)


def test_projectpulse_brief_rejects_generic_plan_drift_and_accepts_matching_plan() -> None:
    request = _request()
    response = supervisor.build_supervisor_response(
        request,
        workflow_state="ready",
        summary="Keep ProjectPulse aligned to its named package and public interfaces.",
        provider_guidance=[
            "Create projectpulse/model.py with required code symbol `Task`.",
            "Create projectpulse/repository.py with required code symbol `JSONRepository`.",
            "Create projectpulse/service.py with required code symbol `TaskService`; also create projectpulse/cli.py plus __main__.py.",
            "Provide pyproject.toml with projectpulse console entry point.",
        ],
        acceptance_checks=[
            "python -m projectpulse add returns 0.",
            "Generated source contains no subprocess, eval, exec, shell invocation, credential literals or network dependency.",
        ],
        known_limits=["The Provider candidate still requires execution evidence."],
    )
    brief = supervisor.build_capability_brief(request, response)
    projection = run_local_pipeline_impl.codex_capability_brief_provider_projection(brief)
    contract = run_local_pipeline_impl.codex_capability_plan_contract(projection)
    goal = (
        "Generate a Python CLI named ProjectPulse with add, list, complete, delete, summary, "
        "JSON import and export; expose python -m projectpulse, use the standard library, "
        "never execute arbitrary commands, and store no secrets."
    )
    spec = requirement_decision_lane.build_goal_spec(goal, contract)
    matching_plan = requirement_decision_lane.build_goal_project_plan(spec)

    with pytest.raises(RuntimeError, match="CODEX_CAPABILITY_PLAN_DRIFT"):
        run_local_pipeline_impl.bind_codex_capability_plan_contract(
            {
                "goal_spec": {**spec, "entities": ["Note", "NoteRepository", "NoteService"]},
                "project_plan": {
                    **matching_plan,
                    "expected_project_structure": ["backend/record_model_repository.py", "main.py"],
                },
            },
            projection,
        )

    bound = run_local_pipeline_impl.bind_codex_capability_plan_contract(
        {"goal_spec": spec, "project_plan": matching_plan}, projection
    )
    assert bound["codex_capability_plan_contract"]["brief_sha256"] == brief["brief_sha256"]
    assert "projectpulse/model.py" in matching_plan["expected_project_structure"]
    assert spec["entities"][:2] == ["Task", "JSONRepository"]

    missing = run_local_pipeline_impl.missing_canonical_project_plan_paths(
        [
            {"path": "requirements.txt", "content": "# stdlib\n"},
            {"path": "pyproject.toml", "content": "[project]\nname='projectpulse'\n"},
            {"path": "projectpulse/__init__.py", "content": "__all__ = []\n"},
        ],
        matching_plan,
    )
    assert "projectpulse/model.py" in missing
    assert "projectpulse/cli.py" in missing
    assert "tests/test_projectpulse.py" in missing


def test_plan_contract_requires_explicit_symbol_wording() -> None:
    contract = run_local_pipeline_impl.codex_capability_plan_contract(
        {
            "brief_sha256": "a" * 64,
            "provider_guidance": [
                "Use Python 3.11 with SQLite persistence.",
                "Keep implementation depth and symbol contracts stable.",
                "Expose required code symbol `StudyPlan`.",
            ],
            "acceptance_checks": [],
        }
    )

    assert contract["required_symbols"] == ["StudyPlan"]
    assert "SQLite" not in contract["required_symbols"]
    assert "contracts" not in contract["required_symbols"]


def test_plan_contract_distinguishes_bounded_subprocess_use_from_a_ban() -> None:
    contract = run_local_pipeline_impl.codex_capability_plan_contract(
        {
            "brief_sha256": "a" * 64,
            "provider_guidance": [],
            "acceptance_checks": [
                "CLI tests use subprocess only to deliver the request through stdin.",
                "The product has no network, credential literals, eval, exec, or shell invocation.",
            ],
        }
    )

    assert "subprocess" not in contract["forbidden_capabilities"]
    assert {
        "network",
        "credential",
        "eval",
        "exec",
        "shell",
    } <= set(contract["forbidden_capabilities"])


def test_feature_unit_plan_binding_normalizes_package_entry_and_network_scope() -> None:
    projection = {
        "brief_sha256": "a" * 64,
        "provider_guidance": [
            "Implement qwen_leaf_probe/normalize_title.py and qwen_leaf_probe/__main__.py; expose it through __init__.py."
        ],
        "acceptance_checks": [
            "python -m qwen_leaf_probe prints one JSON object and contains no network dependency."
        ],
    }
    goal = (
        "Create a minimal Python project named qwen_leaf_probe. Implement "
        "normalize_title(value: str) -> str function. The CLI prints JSON. "
        "Do not add networking or unrelated features."
    )
    spec = requirement_decision_lane.build_goal_spec(goal)
    plan = requirement_decision_lane.build_goal_project_plan(spec)

    bound = run_local_pipeline_impl.bind_codex_capability_plan_contract(
        {"goal_spec": spec, "project_plan": plan}, projection
    )

    assert "no_network" in spec["constraints"]
    assert "qwen_leaf_probe.__main__" in plan["entrypoints"]
    assert bound["codex_capability_plan_contract"]["required_entrypoints"] == [
        "qwen_leaf_probe"
    ]
    assert bound["codex_capability_plan_contract"]["required_path_bindings"][
        "__init__.py"
    ] == "qwen_leaf_probe/__init__.py"


def test_plan_contract_rejects_ambiguous_bare_filename() -> None:
    projection = {
        "brief_sha256": "a" * 64,
        "provider_guidance": ["Expose both packages through __init__.py."],
        "acceptance_checks": [],
    }
    with pytest.raises(RuntimeError, match="ambiguous brief-required basename paths"):
        run_local_pipeline_impl.bind_codex_capability_plan_contract(
            {
                "goal_spec": {},
                "project_plan": {
                    "expected_project_structure": ["first/__init__.py", "second/__init__.py"]
                },
            },
            projection,
        )


def test_response_rejects_delivery_claim_extra_field_and_unsafe_target() -> None:
    request = _request()
    response = supervisor.build_supervisor_response(
        request,
        workflow_state="ready",
        summary="Bounded advice",
        provider_guidance=["Implement the direct command contract."],
    )
    response["evidence_status"] = "PASS"
    response["repair_targets"] = ["../sealed-candidate/app.py"]
    response["response_sha256"] = supervisor._canonical_hash(
        supervisor._without_hash(response, "response_sha256")
    )

    errors = supervisor.validate_supervisor_response(request, response)

    assert any("unsupported fields" in error for error in errors)
    assert any("prohibited authority" in error for error in errors)
    assert any("unsafe advisory repair target" in error for error in errors)


def test_support_manifest_places_external_codex_role_above_librarian_output() -> None:
    manifest = pipeline_manifest.default_minimal_pipeline_manifest(
        {"project_summary": "Build a local CLI"}
    )
    role = next(
        item for item in manifest["roles"]
        if item["id"] == "codex_capability_supervisor"
    )
    synthetic_step = {
        "id": "capability_escalation",
        "type": "agent_turn",
        "stage": "technical_plan",
        "role": role["id"],
        "goal": "Resolve the validated librarian escalation.",
        "allowed_actions": ["read_file", "list_files", "use_skill"],
    }
    prompt = dynamic_pipeline_runner._system_prompt(role, synthetic_step, manifest)

    assert manifest["cfo_contract"]["support_artifacts"]["codex_capability_brief"] == "CODEX_CAPABILITY_BRIEF.json"
    assert "codex_capability_supervision" in manifest["shared_whiteboard_keys"]
    assert "above the context librarian" in prompt
    assert "supervise-cgkn-capabilities" in prompt
    assert "must not write generated product source" in prompt
    assert "optional CODEX_CAPABILITY_BRIEF.json" in next(
        step["goal"] for step in manifest["steps"] if step["id"] == "build"
    )


def test_codex_role_never_falls_through_to_provider_impersonation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dynamic_pipeline_runner,
        "_call_step_provider",
        lambda *_args, **_kwargs: pytest.fail("provider must not impersonate Codex"),
    )

    with pytest.raises(RuntimeError, match="requires_external_codex_handoff"):
        dynamic_pipeline_runner._call_step_agent(
            [],
            "gpt-test",
            1,
            role={"id": "codex_capability_supervisor"},
            step={"id": "capability_escalation"},
        )


def test_direct_cli_prepare_writes_bounded_request_and_agent_session(tmp_path: pathlib.Path) -> None:
    librarian = tmp_path / "librarian.json"
    evidence = tmp_path / "evidence.json"
    request = tmp_path / "request.json"
    session = tmp_path / "agent_session.jsonl"
    librarian.write_text(
        json.dumps({"kind": "CGKNLibrarianContextPack", "selected_items": []}),
        encoding="utf-8",
    )
    evidence.write_text(json.dumps({"evidence": []}), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "codex_capability_supervisor.py"),
            "prepare",
            "--goal",
            "Build a bounded CLI",
            "--gap",
            "Provider output missed the domain contract",
            "--category",
            "generation_failure",
            "--librarian-json",
            str(librarian),
            "--evidence-json",
            str(evidence),
            "--output",
            str(request),
            "--session",
            str(session),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert supervisor.validate_escalation_request(json.loads(request.read_text(encoding="utf-8"))) == []
    event = json.loads(session.read_text(encoding="utf-8").strip())
    assert event["kind"] == "codex_capability_escalation_requested"
