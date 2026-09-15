from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
AGENT_SRC = ROOT / "tools" / "cgkn-agent-kit" / "src"
for entry in (SCRIPTS, AGENT_SRC):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import run_local_pipeline
import run_local_pipeline_impl
import surrogate_provider_adapter as adapter
import canonical_goal_spec_compiler as goal_compiler
from cgkn_agent_kit import core


@pytest.fixture(autouse=True)
def _isolate_adapter_context():
    yield
    adapter._CONTEXT = None


def configured(tmp_path: pathlib.Path, mode: str = "codex_surrogate", replay_dir: pathlib.Path | None = None):
    run_dir = tmp_path / "run"
    context = adapter.configure(
        mode=mode,
        run_dir=run_dir,
        run_id="run-test",
        project_id="project-test",
        source_sha="a" * 64,
        replay_dir=replay_dir,
    )
    return context


def pending_request(tmp_path: pathlib.Path, *, stage: str = "requirements_planning"):
    context = configured(tmp_path)
    with pytest.raises(adapter.SurrogateResponseRequired):
        adapter.provider_text([{"role": "user", "content": "build"}], stage=stage)
    report = adapter.status(context.run_dir)
    request = adapter._read_json(pathlib.Path(report["requests"][0]["request_path"]))
    return context, request


def valid_payload() -> str:
    return json.dumps({"summary": "Plan the bounded tool.", "decisions": ["Use a CLI."], "risks": []})


def valid_requirement_payload(goal: str) -> str:
    user = "the user who supplied the goal"
    outcome = "Count characters, words, and lines from UTF-8 text and return one JSON result."
    capability = "count_text"
    workflow = "provide a UTF-8 file, run the counter, and review the JSON result"
    anchor = outcome
    constraint = goal_compiler.extract_explicit_constraints(goal)[0]
    values = {
        "intended_users": [user],
        "desired_outcomes": [outcome],
        "proposed_core_capabilities": [capability],
        "proposed_supporting_capabilities": [],
        "proposed_user_workflows": [workflow],
        "explicit_constraints_found": [constraint],
        "proposed_acceptance_anchors": [anchor],
        "proposed_forbidden_substitutions": ["Do not replace executable counting with documentation or a mock."],
    }
    grounding = []
    inferred = {"intended_users", "proposed_user_workflows", "proposed_forbidden_substitutions"}
    for field, items in values.items():
        for value in items:
            grounding.append({
                "target": field, "value": value,
                "source_kind": "NECESSARY_INFERENCE" if field in inferred else "RAW_GOAL",
                "source_excerpt": goal,
                "rationale": "This source directly requires or necessarily supports the bounded proposal item.",
            })
    grounding.append({
        "target": "proposed_workstreams", "value": "text_count",
        "source_kind": "NECESSARY_INFERENCE", "source_excerpt": goal,
        "rationale": "One bounded implementation workstream is necessary for the requested count operation.",
    })
    return json.dumps({
        "schema_version": "1.0", "interpreted_goal": goal,
        **values,
        "proposed_workstreams": [{"id": "text_count", "scope": "Implement the requested text count operation.", "covers_capabilities": [capability]}],
        "necessary_inferences": [], "assumptions": [], "open_questions": [],
        "source_grounding": grounding,
    })


def initialized_project(tmp_path: pathlib.Path) -> pathlib.Path:
    project = tmp_path / "project"
    project.mkdir()
    core.initialize_project(project, ROOT)
    return project


SMOKE_GOAL = (
    "Build a local command-line text count tool named textcounter. "
    "Implement count_text(text: str) -> dict using the Python standard library; "
    "return character, word, and line counts. The CLI accepts a UTF-8 file path "
    "and prints one JSON object. Raise ValueError for blank text. "
    "No GUI, network, database, or cloud."
)


def test_01_provider_modes_are_explicit() -> None:
    assert adapter.PROVIDER_MODES == ("live", "codex_surrogate", "deterministic_replay")


def test_02_agent_kit_surrogate_command_has_no_live_provider_flags(tmp_path: pathlib.Path) -> None:
    project = initialized_project(tmp_path)
    argv = core.generation_command(
        project, goal="Build a counter", brief_path=project / "brief.json",
        provider_mode="codex_surrogate",
    )
    assert argv[argv.index("--provider-mode") + 1] == "codex_surrogate"
    assert "--use-api" not in argv
    assert "--allow-provider" not in argv
    assert "--allow-network" not in argv


def test_03_live_command_remains_compatible(tmp_path: pathlib.Path) -> None:
    project = initialized_project(tmp_path)
    argv = core.generation_command(
        project, goal="Build a counter", brief_path=project / "brief.json",
        provider_mode="live", allow_network=True,
    )
    assert "--use-api" in argv and "--allow-provider" in argv and "--allow-network" in argv


def test_04_replay_requires_preexisting_replay_directory_argument(tmp_path: pathlib.Path) -> None:
    project = initialized_project(tmp_path)
    with pytest.raises(core.AgentKitError, match="requires replay_dir"):
        core.generation_command(
            project, goal="Build", brief_path=project / "brief.json",
            provider_mode="deterministic_replay",
        )


def test_05_fresh_provider_call_writes_scheduler_request(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    assert request["kind"] == "CGKNProviderJobRequest"
    assert pathlib.Path(adapter.status(context.run_dir)["requests"][0]["request_path"]).is_file()


def test_06_request_has_every_canonical_identity_field(tmp_path: pathlib.Path) -> None:
    _, request = pending_request(tmp_path)
    required = {
        "schema_version", "run_id", "project_id", "job_id", "attempt_id", "stage",
        "provider_mode", "requested_role", "request_schema", "expected_response_schema",
        "context_refs", "context_hashes", "source_sha", "benchmark_hash", "created_at", "request_hash",
    }
    assert required <= set(request)


def test_07_request_hash_binds_context(tmp_path: pathlib.Path) -> None:
    _, request = pending_request(tmp_path)
    value = dict(request)
    request_hash = value.pop("request_hash")
    assert request_hash == adapter.stable_hash(value)


def test_08_matching_response_is_accepted(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    receipt = adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    assert receipt["accepted"] is True
    assert all(receipt[key] for key in ("schema_valid", "identity_valid", "request_hash_valid", "payload_hash_valid"))


def test_09_response_is_consumed_and_accounted_once(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    first = adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning")
    second = adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning")
    report = adapter.status(context.run_dir)
    assert first == second == valid_payload()
    assert report["consumed_attempts"] == 1
    assert len(report["accounting"]) == 1


def test_10_identical_duplicate_submit_is_idempotent(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    assert adapter.submit_response(context.run_dir, response)["accepted"] is True
    duplicate = adapter.submit_response(context.run_dir, response)
    assert duplicate["accepted"] is True and duplicate["duplicate"] is True


def test_11_different_duplicate_is_rejected(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    duplicate = adapter.submit_response(context.run_dir, adapter.build_response(request, "different"))
    assert duplicate["accepted"] is False
    assert "different duplicate" in duplicate["rejection_reason"]


def test_12_wrong_request_hash_is_rejected(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    response["request_hash"] = "0" * 64
    receipt = adapter.submit_response(context.run_dir, response)
    assert receipt["accepted"] is False and receipt["request_hash_valid"] is False


def test_13_wrong_payload_hash_is_rejected(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    response["payload_hash"] = "0" * 64
    receipt = adapter.submit_response(context.run_dir, response)
    assert receipt["accepted"] is False and receipt["payload_hash_valid"] is False


@pytest.mark.parametrize("field", ["run_id", "project_id", "stage"])
def test_14_identity_mismatch_is_rejected(tmp_path: pathlib.Path, field: str) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    response[field] = "wrong"
    receipt = adapter.submit_response(context.run_dir, response)
    assert receipt["accepted"] is False and receipt["identity_valid"] is False


def test_15_unknown_job_is_an_orphan_response(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    response["job_id"] = "job-missing"
    with pytest.raises(adapter.SurrogateSubmissionError, match="orphan response"):
        adapter.submit_response(context.run_dir, response)


def test_16_unknown_attempt_is_an_orphan_response(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    response["attempt_id"] = "attempt-99"
    with pytest.raises(adapter.SurrogateSubmissionError, match="orphan response"):
        adapter.submit_response(context.run_dir, response)


def test_17_response_schema_mismatch_is_rejected(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    response = adapter.build_response(request, valid_payload())
    del response["surrogate_identity"]
    receipt = adapter.submit_response(context.run_dir, response)
    assert receipt["accepted"] is False and receipt["schema_valid"] is False


def test_18_candidate_path_traversal_is_rejected(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    payload = json.dumps({"files": [{"path": "../kernel.py", "content": "x"}]})
    receipt = adapter.submit_response(context.run_dir, adapter.build_response(request, payload))
    assert receipt["accepted"] is False and "unsafe candidate path" in receipt["rejection_reason"]


def test_19_direct_kernel_write_request_is_rejected(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    payload = json.dumps({"modify_cgkn_kernel": True, "files": []})
    receipt = adapter.submit_response(context.run_dir, adapter.build_response(request, payload))
    assert receipt["accepted"] is False and "kernel modification" in receipt["rejection_reason"]


def test_20_process_restart_can_resume_same_request(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    adapter.configure(
        mode="codex_surrogate", run_dir=context.run_dir, run_id="run-test",
        project_id="project-test", source_sha="b" * 64,
    )
    assert adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning") == valid_payload()


def test_21_resume_does_not_create_a_second_job(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning")
    adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning")
    assert len(adapter.status(context.run_dir)["requests"]) == 1


def test_22_changed_schema_repair_prompt_creates_next_attempt(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    adapter.submit_response(context.run_dir, adapter.build_response(request, "not-json"))
    assert adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning") == "not-json"
    with pytest.raises(adapter.SurrogateResponseRequired):
        adapter.provider_text(
            [{"role": "user", "content": "build"}, {"role": "user", "content": "SCHEMA_REPAIR_ATTEMPT_1"}],
            stage="requirements_planning",
        )
    attempts = adapter.status(context.run_dir)["requests"]
    assert [item["attempt_id"] for item in attempts] == ["attempt-1", "attempt-2"]


def test_23_replay_is_not_labeled_as_fresh_surrogate(tmp_path: pathlib.Path) -> None:
    replay = tmp_path / "replay"
    replay.mkdir()
    context = configured(tmp_path, mode="deterministic_replay", replay_dir=replay)
    with pytest.raises(adapter.SurrogateSubmissionError, match="replay response missing"):
        adapter.provider_text([{"role": "user", "content": "build"}], stage="planning")
    assert adapter.status(context.run_dir)["provider_mode"] == "deterministic_replay"


def test_24_replay_consumes_only_a_preexisting_bound_response(tmp_path: pathlib.Path) -> None:
    replay = tmp_path / "replay"
    replay.mkdir()
    context = configured(tmp_path, mode="deterministic_replay", replay_dir=replay)
    with pytest.raises(adapter.SurrogateSubmissionError):
        adapter.provider_text([{"role": "user", "content": "build"}], stage="planning")
    report = adapter.status(context.run_dir)
    request = adapter._read_json(pathlib.Path(report["requests"][0]["request_path"]))
    response = adapter.build_response(request, "fixed replay", surrogate_identity="replay-fixture")
    (replay / f"{request['job_id']}.{request['attempt_id']}.json").write_text(
        json.dumps(response), encoding="utf-8"
    )
    assert adapter.provider_text([{"role": "user", "content": "build"}], stage="planning") == "fixed replay"


def test_25_nonlive_provider_boundary_never_reaches_live_transports(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured(tmp_path)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: pytest.fail("credential resolution is a live transport boundary"),
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "try_local_provider_text",
        lambda *_args, **_kwargs: pytest.fail("local/SDK fallback must not execute"),
    )
    with pytest.raises(adapter.SurrogateResponseRequired):
        run_local_pipeline_impl.provider_text(
            [{"role": "user", "content": "build"}], "model", 5, stage="planning"
        )


def test_26_stage_parser_materializes_canonical_artifact(tmp_path: pathlib.Path) -> None:
    context = configured(tmp_path)
    with pytest.raises(adapter.SurrogateResponseRequired):
        run_local_pipeline_impl.provider_stage_checkpoint(
            provider_mode="codex_surrogate", stage="technical_design",
            context={"goal": "counter"}, run_dir=context.run_dir,
            phase_log_path=context.run_dir / "provider_phase_log.jsonl",
        )
    report = adapter.status(context.run_dir)
    request = adapter._read_json(pathlib.Path(report["requests"][0]["request_path"]))
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    artifact = run_local_pipeline_impl.provider_stage_checkpoint(
        provider_mode="codex_surrogate", stage="technical_design",
        context={"goal": "counter"}, run_dir=context.run_dir,
        phase_log_path=context.run_dir / "provider_phase_log.jsonl",
    )
    assert artifact["kind"] == "CGKNCanonicalProviderStageArtifact"
    assert (context.run_dir / "artifacts/provider_stage_artifacts/technical_design.json").is_file()


def test_27_formal_facade_pauses_with_zero_call_accounting(tmp_path: pathlib.Path) -> None:
    base = tmp_path / "formal"
    args = argparse.Namespace(
        plan="", goal=SMOKE_GOAL,
        out_dir=str(base / "project"), run_dir=str(base / "run"), resume_run_dir="",
        codex_capability_brief="", result=str(base / "result.json"),
        allow_network=False, allow_provider=False, use_api=False,
        provider_mode="codex_surrogate", project_id="text-counter", replay_dir="",
        model="gpt-4.1", small_model="gpt-4.1", large_model="gpt-4.1", repair_model="",
        disable_model_routing=False, timeout=120, allow_model_usage_planning=False,
        phase_log_path="", provider_semantic_repair_attempts=None,
        post_build_repair_attempts=None, json=True,
    )
    result = run_local_pipeline.execute(args)
    assert result["status"] == "WAITING_SURROGATE_RESPONSE"
    assert result["pending_requests"][0]["stage"] == "requirements_planning"
    assert result["real_provider_calls"] == result["network_attempts"] == 0
    assert result["provider_schedulers"] == 1


def test_28_formal_resume_materializes_planning_then_advances(tmp_path: pathlib.Path) -> None:
    base = tmp_path / "formal"
    args = argparse.Namespace(
        plan="", goal=SMOKE_GOAL,
        out_dir=str(base / "project"), run_dir=str(base / "run"), resume_run_dir="",
        codex_capability_brief="", result=str(base / "result.json"),
        allow_network=False, allow_provider=False, use_api=False,
        provider_mode="codex_surrogate", project_id="text-counter", replay_dir="",
        model="gpt-4.1", small_model="gpt-4.1", large_model="gpt-4.1", repair_model="",
        disable_model_routing=False, timeout=120, allow_model_usage_planning=False,
        phase_log_path="", provider_semantic_repair_attempts=None,
        post_build_repair_attempts=None, json=True,
    )
    first = run_local_pipeline.execute(args)
    request = adapter._read_json(pathlib.Path(first["pending_requests"][0]["request_path"]))
    adapter.submit_response(base / "run", adapter.build_response(request, valid_requirement_payload(SMOKE_GOAL)))
    args.resume_run_dir = str(base / "run")
    second = run_local_pipeline.execute(args)
    assert (base / "run/artifacts/provider_stage_artifacts/requirements_planning.json").is_file()
    assert second["status"] == "WAITING_SURROGATE_RESPONSE"
    assert any(item["stage"] == "product_design" for item in second["pending_requests"])


def test_29_plugin_exposes_mode_status_and_submit_tools() -> None:
    spec = importlib.util.spec_from_file_location("cgkn_mcp_surrogate_test", ROOT / "plugins/cgkn/scripts/cgkn_mcp_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    by_name = {item["name"]: item for item in module.TOOLS}
    assert {"cgkn_generate", "cgkn_surrogate_status", "cgkn_submit_surrogate_response"} <= set(by_name)
    assert by_name["cgkn_generate"]["inputSchema"]["properties"]["provider_mode"]["enum"] == list(adapter.PROVIDER_MODES)


def test_30_provider_mode_state_records_single_scheduler_and_zero_network(tmp_path: pathlib.Path) -> None:
    context, _ = pending_request(tmp_path)
    state = adapter._read_json(context.root / "provider_mode_state.json")
    assert state["provider_schedulers"] == 1
    assert state["real_provider_calls"] == 0
    assert state["network_attempts"] == 0


def test_31_product_governance_artifacts_are_not_writable_by_stage_payload(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    payload = json.dumps({"files": [{"path": ".cgkn/product_design_governance.json", "content": "{}"}]})
    receipt = adapter.submit_response(context.run_dir, adapter.build_response(request, payload))
    assert receipt["accepted"] is False


def test_32_accounting_rows_match_consumed_attempt_identities(tmp_path: pathlib.Path) -> None:
    context, request = pending_request(tmp_path)
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    adapter.provider_text([{"role": "user", "content": "build"}], stage="requirements_planning")
    report = adapter.status(context.run_dir)
    assert {
        (item["job_id"], item["attempt_id"]) for item in report["accounting"]
    } == {(request["job_id"], request["attempt_id"])}


@pytest.mark.parametrize(
    "stage",
    [
        "requirements_planning",
        "product_design",
        "interaction_design",
        "technical_design",
        "acceptance_design",
        "initial_build",
        "verification_directed_repair",
        "schema_repair",
        "design_replan",
    ],
)
def test_33_every_required_stage_uses_the_same_handshake_and_accounting(
    tmp_path: pathlib.Path, stage: str,
) -> None:
    context = configured(tmp_path)
    messages = [{"role": "user", "content": stage}]
    with pytest.raises(adapter.SurrogateResponseRequired):
        adapter.provider_text(messages, stage=stage)
    report = adapter.status(context.run_dir)
    request = adapter._read_json(pathlib.Path(report["requests"][0]["request_path"]))
    assert request["stage"] == stage
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    assert adapter.provider_text(messages, stage=stage) == valid_payload()
    accounting = adapter.status(context.run_dir)["accounting"]
    assert len(accounting) == 1
    assert accounting[0]["stage"] == stage
    assert accounting[0]["real_provider_calls"] == accounting[0]["network_attempts"] == 0


def test_34_completed_nonlive_result_records_mode_and_zero_call_totals(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = configured(tmp_path)
    result_path = tmp_path / "result.json"
    args = argparse.Namespace(
        provider_mode="codex_surrogate", use_api=False,
        resume_run_dir=str(context.run_dir), run_dir=str(context.run_dir),
        result=str(result_path), goal="counter", out_dir=str(tmp_path / "project"),
    )
    monkeypatch.setattr(
        run_local_pipeline._impl,
        "execute",
        lambda _args: {"status": "pass", "project_dir": _args.out_dir, "run_dir": _args.run_dir},
    )
    result = run_local_pipeline.execute(args)
    assert result["provider_mode"] == "codex_surrogate"
    assert result["provider_schedulers"] == 1
    assert result["real_provider_calls"] == result["network_attempts"] == 0
    assert adapter._read_json(result_path)["provider_mode"] == "codex_surrogate"


@pytest.mark.parametrize(
    "stage",
    ["verification_directed_repair", "schema_repair", "design_replan"],
)
def test_35_late_generation_stages_parse_and_materialize_canonical_artifacts(
    tmp_path: pathlib.Path, stage: str,
) -> None:
    context = configured(tmp_path)
    kwargs = {
        "provider_mode": "codex_surrogate",
        "stage": stage,
        "context": {"goal": "counter", "issue": "bounded repair"},
        "run_dir": context.run_dir,
        "phase_log_path": context.run_dir / "provider_phase_log.jsonl",
    }
    with pytest.raises(adapter.SurrogateResponseRequired):
        run_local_pipeline_impl.provider_stage_checkpoint(**kwargs)
    request_item = adapter.status(context.run_dir)["requests"][0]
    request = adapter._read_json(pathlib.Path(request_item["request_path"]))
    adapter.submit_response(context.run_dir, adapter.build_response(request, valid_payload()))
    artifact = run_local_pipeline_impl.provider_stage_checkpoint(**kwargs)
    assert artifact["stage"] == stage
    assert artifact["provider_mode"] == "codex_surrogate"
    assert (context.run_dir / "artifacts/provider_stage_artifacts" / f"{stage}.json").is_file()
    assert adapter.status(context.run_dir)["accounting"][0]["stage"] == stage
