from __future__ import annotations

import copy
import argparse
import json
import pathlib
import sys

import jsonschema
import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import canonical_goal_spec_compiler as compiler
import requirement_decision_lane as lane
import run_local_pipeline_impl as pipeline
import run_local_pipeline
import source_identity
import surrogate_provider_adapter as adapter


def proposal(goal: str, *, core: list[str] | None = None, outcome: str | None = None) -> dict:
    core = core or ["perform_requested_workflow"]
    outcome = outcome or goal
    user = "the user who supplied the goal"
    workflow = "provide input, run the requested operation, and review the result"
    anchor = outcome
    workstreams = [
        {"id": f"work_{index}", "scope": f"Implement {capability}", "covers_capabilities": [capability]}
        for index, capability in enumerate(core, start=1)
    ]
    doc = {
        "schema_version": "1.0",
        "interpreted_goal": goal,
        "intended_users": [user],
        "desired_outcomes": [outcome],
        "proposed_core_capabilities": core,
        "proposed_supporting_capabilities": [],
        "proposed_user_workflows": [workflow],
        "proposed_workstreams": workstreams,
        "explicit_constraints_found": compiler.extract_explicit_constraints(goal),
        "necessary_inferences": [],
        "assumptions": ["Unspecified reversible details use conservative defaults."],
        "open_questions": [],
        "proposed_acceptance_anchors": [anchor],
        "proposed_forbidden_substitutions": ["Do not replace the requested outcome with an easier proxy."],
        "source_grounding": [],
    }
    inferred = {"intended_users", "proposed_user_workflows", "proposed_workstreams", "proposed_forbidden_substitutions"}
    fields = (
        "intended_users", "desired_outcomes", "proposed_core_capabilities",
        "proposed_supporting_capabilities", "proposed_user_workflows",
        "explicit_constraints_found", "proposed_acceptance_anchors",
        "proposed_forbidden_substitutions",
    )
    for field in fields:
        for value in doc[field]:
            doc["source_grounding"].append({
                "target": field,
                "value": value,
                "source_kind": "NECESSARY_INFERENCE" if field in inferred else "RAW_GOAL",
                "source_excerpt": goal,
                "rationale": "This bounded source directly requires or necessarily supports the proposed item.",
            })
    for row in workstreams:
        doc["source_grounding"].append({
            "target": "proposed_workstreams",
            "value": row["id"],
            "source_kind": "NECESSARY_INFERENCE",
            "source_excerpt": goal,
            "rationale": "A bounded implementation workstream is necessary to realize the grounded capability.",
        })
    return doc


def artifact(goal: str, doc: dict | None = None, *, mode: str = "codex_surrogate") -> dict:
    return compiler.build_planning_artifact(
        proposal=doc or proposal(goal),
        raw_goal=goal,
        provider_mode=mode,
        artifact_ref=f"C:/fresh/{mode}/requirements.json",
        transport_identity={
            "run_id": "run-fresh", "project_id": "project-fresh", "job_id": "job-plan",
            "attempt_id": "attempt-1", "stage": "requirements_planning",
            "request_hash": "request-hash", "response_hash": "response-hash",
            "accepted": True, "consumed": True, "validated": True,
        },
        created_at="2026-09-15T00:00:00+00:00",
    )


def compile_goal(goal: str, doc: dict | None = None, *, mode: str = "codex_surrogate") -> dict:
    return compiler.compile_goal_spec(raw_goal=goal, planning_artifact=artifact(goal, doc, mode=mode))


def test_01_planning_proposal_matches_registered_schema():
    goal = "Create a local calculator that adds two numbers."
    schema = json.loads((ROOT / "contracts" / "requirements_planning_proposal_v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(proposal(goal), schema)


def test_02_canonical_goal_spec_matches_registered_schema():
    goal = "Create a local calculator that adds two numbers."
    result = compile_goal(goal, proposal(goal, core=["add_numbers"]))
    schema = json.loads((ROOT / "contracts" / "canonical_goal_spec_v2.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(result, schema)


def test_03_accepted_planning_artifact_participates_in_compilation():
    goal = "Create a local microscope image measurement tool."
    result = compile_goal(goal, proposal(goal, core=["measure_microscope_images"]))
    assert result["status"] == "PASS"
    assert result["core_capabilities"] == ["measure_microscope_images"]
    assert result["planning_artifact_hash"]


def test_04_raw_goal_is_losslessly_preserved():
    goal = "做一个完全本地的显微镜图像测量工具。"
    goal = "\u505a\u4e00\u4e2a\u5b8c\u5168\u672c\u5730\u7684\u663e\u5fae\u955c\u56fe\u50cf\u6d4b\u91cf\u5de5\u5177\u3002"
    doc = proposal(goal, core=["measure_microscope_images"])
    doc["interpreted_goal"] = "a smaller goal"
    result = compile_goal(goal, doc)
    assert result["raw_goal"] == goal
    assert result["normalized_goal"] == goal


def test_05_goal_hash_and_self_hash_are_bound():
    goal = "Create a maintenance work-order tool."
    result = compile_goal(goal, proposal(goal, core=["manage_work_orders"]))
    assert result["raw_goal_hash"] == compiler.raw_goal_hash(goal)
    assert result["goal_spec_hash"] == compiler.stable_hash({k: v for k, v in result.items() if k != "goal_spec_hash"})


def test_06_chinese_character_clip_goal_preserves_identity_core():
    goal = "完全本地运行，从剧集视频中自动找出指定角色出现的所有片段，允许人工检查并导出视频片段。"
    goal = "\u5b8c\u5168\u672c\u5730\u8fd0\u884c\uff0c\u4ece\u5267\u96c6\u89c6\u9891\u4e2d\u81ea\u52a8\u627e\u51fa\u6307\u5b9a\u89d2\u8272\u51fa\u73b0\u7684\u6240\u6709\u7247\u6bb5\uff0c\u5141\u8bb8\u4eba\u5de5\u68c0\u67e5\u5e76\u5bfc\u51fa\u89c6\u9891\u7247\u6bb5\u3002"
    core = [
        "import_local_videos", "establish_character_identity",
        "detect_character_appearances", "review_candidates", "export_video_clips",
    ]
    result = compile_goal(goal, proposal(goal, core=core))
    assert result["status"] == "PASS"
    assert "establish_character_identity" in result["core_capabilities"]
    assert result["explicit_constraints"]
    assert len(result["workstreams"]) == 5


def test_07_unseen_microscope_domain_compiles_without_keyword_table():
    goal = "Build a local tool that imports microscope images, measures cell diameter, and exports a reviewable report."
    result = compile_goal(goal, proposal(goal, core=["import_microscope_images", "measure_cell_diameter", "export_review_report"]))
    assert result["status"] == "PASS"
    assert len(result["workstreams"]) == 3


def test_08_unseen_maintenance_domain_compiles():
    goal = "Build an offline maintenance planner that records equipment faults and schedules inspections."
    result = compile_goal(goal, proposal(goal, core=["record_equipment_faults", "schedule_inspections"]))
    assert result["status"] == "PASS"


def test_09_visual_novel_domain_compiles():
    goal = "Create a local visual novel editor for scenes, characters, branches, preview, and export."
    result = compile_goal(goal, proposal(goal, core=["edit_scenes", "edit_characters", "edit_branches", "preview_and_export"]))
    assert result["status"] == "PASS"


def test_10_simple_calculator_remains_small():
    goal = "Create a local calculator that adds two numbers."
    result = compile_goal(goal, proposal(goal, core=["add_numbers"]))
    plan = lane.build_goal_project_plan(result)
    assert result["core_capabilities"] == ["add_numbers"]
    assert len([row for row in plan["workstreams"] if row["id"].startswith("work_")]) == 1


def test_11_defaultable_ambiguity_becomes_assumption_not_blocker():
    goal = "Build a local reading tracker."
    doc = proposal(goal, core=["track_reading"])
    result = compile_goal(goal, doc)
    assert result["status"] == "PASS"
    assert result["assumptions"]


def test_12_true_contradiction_remains_user_decision_blocker():
    result = lane.build_goal_spec("The app must be online and must be offline.", planning_artifact={})
    assert result["status"] == "NEEDS_REWORK"
    assert result["reason"] == "USER_DECISION_REQUIRED"


def test_13_provider_proposal_has_no_governance_or_release_authority():
    plan = artifact("Create a local calculator.")
    assert plan["authority"] == "proposal"
    assert not plan["governance_authority"]
    assert not plan["acceptance_authority"]
    assert not plan["release_authority"]


def test_14_canonical_compiler_owns_only_requirement_authority():
    result = compile_goal("Create a local calculator.")
    assert result["authority"] == "canonical_requirement_authority"


def test_15_ungrounded_core_capability_is_rejected():
    goal = "Create a local calculator."
    doc = proposal(goal, core=["calculate"])
    doc["source_grounding"] = [row for row in doc["source_grounding"] if row["target"] != "proposed_core_capabilities"]
    result = compile_goal(goal, doc)
    assert result["status"] == "NEEDS_REWORK"
    assert result["core_capabilities"] == []


def test_16_ungrounded_supporting_capability_cannot_become_requirement():
    goal = "Create a local calculator."
    doc = proposal(goal, core=["calculate"])
    doc["proposed_supporting_capabilities"] = ["upload_telemetry"]
    result = compile_goal(goal, doc)
    assert "upload_telemetry" not in result["supporting_capabilities"]
    assert "upload_telemetry" not in result["capabilities"]


def test_17_color_proxy_for_identity_is_rejected():
    goal = "自动找出指定角色出现的所有片段。"
    result = compile_goal(goal, proposal(goal, core=["detect_red_clothing_color"]))
    assert "forbidden_proxy_substitution:semantic_identity_replaced" in result["grounding_validation"]["failures"]


def test_18_all_cannot_silently_become_sample():
    goal = "Find all maintenance failures."
    result = compile_goal(goal, proposal(goal, core=["find_failures"], outcome="Return a random sample of failures."))
    assert "silent_goal_reduction:all_replaced_by_sample" in result["grounding_validation"]["failures"]


def test_19_local_goal_cannot_gain_cloud_scope():
    goal = "Build a completely local maintenance tool."
    doc = proposal(goal, core=["manage_maintenance"])
    doc["proposed_supporting_capabilities"] = ["cloud upload"]
    doc["source_grounding"].append({
        "target": "proposed_supporting_capabilities", "value": "cloud upload",
        "source_kind": "NECESSARY_INFERENCE", "source_excerpt": goal,
        "rationale": "This deliberately malicious inference attempts to add an unrequested external service.",
    })
    result = compile_goal(goal, doc)
    assert any(item.startswith("unsupported_high_risk_addition") for item in result["grounding_validation"]["failures"])


def test_20_manual_review_cannot_replace_automatic_core():
    goal = "自动识别故障并允许人工复核。"
    result = compile_goal(goal, proposal(goal, core=["人工复核"]))
    goal = "\u81ea\u52a8\u8bc6\u522b\u6545\u969c\u5e76\u5141\u8bb8\u4eba\u5de5\u590d\u6838\u3002"
    result = compile_goal(goal, proposal(goal, core=["\u4eba\u5de5\u590d\u6838"]))
    assert "silent_goal_reduction:automatic_core_replaced_by_manual" in result["grounding_validation"]["failures"]


def test_21_video_export_cannot_become_timestamps_only():
    goal = "Find the person and export video clips."
    result = compile_goal(goal, proposal(goal, core=["identify_person"], outcome="timestamps only"))
    assert "silent_goal_reduction:video_export_replaced_by_metadata" in result["grounding_validation"]["failures"]


def test_22_workstream_must_cover_each_core_capability():
    goal = "Import microscope images and export measurements."
    doc = proposal(goal, core=["import_images", "export_measurements"])
    doc["proposed_workstreams"][1]["covers_capabilities"] = []
    result = compile_goal(goal, doc)
    assert "uncovered_core_capability:export_measurements" in result["grounding_validation"]["failures"]


def test_23_acceptance_anchor_must_cover_each_outcome():
    goal = "Create and export a maintenance schedule."
    doc = proposal(goal, core=["create_schedule"])
    doc["proposed_acceptance_anchors"] = ["Unrelated output"]
    for row in doc["source_grounding"]:
        if row["target"] == "proposed_acceptance_anchors":
            row["value"] = "Unrelated output"
            row["source_excerpt"] = "Create"
    result = compile_goal(goal, doc)
    assert any(item.startswith("uncovered_user_outcome") for item in result["grounding_validation"]["failures"])


def test_24_stale_raw_goal_binding_is_rejected():
    plan = artifact("Create a local calculator.")
    errors = compiler.validate_planning_artifact(plan, "Create a different tool.")
    assert "planning_artifact_raw_goal_hash" in errors


def test_25_tampered_artifact_hash_is_rejected():
    plan = artifact("Create a local calculator.")
    plan["proposal"]["interpreted_goal"] = "tampered"
    errors = compiler.validate_planning_artifact(plan, "Create a local calculator.")
    assert "planning_artifact_proposal_hash" in errors
    assert "planning_artifact_hash" in errors


def test_26_missing_required_arrays_get_structured_validation_errors():
    errors = compiler.validate_planning_proposal({"schema_version": "1.0", "interpreted_goal": "x"})
    assert "proposed_workstreams_must_be_array" in errors
    assert "source_grounding_must_be_array" in errors


def test_27_replan_feedback_is_structured_and_not_candidate_repair():
    goal = "Create a local calculator."
    doc = proposal(goal, core=["calculate"])
    doc["proposed_core_capabilities"] = []
    doc["proposed_workstreams"] = []
    doc["source_grounding"] = [
        row for row in doc["source_grounding"]
        if row["target"] not in {"proposed_core_capabilities", "proposed_workstreams"}
    ]
    result = compile_goal(goal, doc)
    feedback = compiler.requirement_replan_feedback(result)
    assert feedback["status"] == "NEEDS_REWORK"
    assert feedback["candidate_repair"] is False
    assert feedback["required_corrections"]


def test_28_live_surrogate_and_replay_share_canonical_semantics():
    goal = "Create a local microscope measurement tool."
    doc = proposal(goal, core=["measure_microscope_images"])
    values = [compile_goal(goal, copy.deepcopy(doc), mode=mode) for mode in ("live", "codex_surrogate", "deterministic_replay")]
    fields = ("raw_goal", "normalized_goal", "core_capabilities", "workstreams", "acceptance_anchors", "authority_decision")
    assert [{key: value[key] for key in fields} for value in values].count({key: values[0][key] for key in fields}) == 3


def test_29_bounded_replan_succeeds_on_second_proposal(tmp_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(pipeline, "provider_stage_checkpoint", lambda **kwargs: calls.append(kwargs["context"]["proposal_sequence"]) or {"artifact_ref": f"a{calls[-1]}", "artifact_hash": f"h{calls[-1]}"})
    results = iter([
        {"status": "NEEDS_REWORK", "goal_spec": {"goal_spec_hash": "g1"}, "requirement_replan": {"required_corrections": ["missing"], "candidate_repair": False}},
        {"status": "PASS", "goal_spec": {"goal_spec_hash": "g2"}},
    ])
    monkeypatch.setattr(pipeline.requirement_decision_lane, "run_requirement_decision", lambda *args, **kwargs: next(results))
    result, _ = pipeline.run_canonical_requirement_planning(provider_mode="live", user_goal="x", run_dir=tmp_path, phase_log_path=tmp_path / "log.jsonl", codex_plan_contract={})
    state = json.loads((tmp_path / "artifacts" / "requirement_replan_state.json").read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert calls == [1, 2]
    assert state["workflow_state"] == "RESOLVED"


def test_30_replan_wait_state_survives_process_boundary(tmp_path, monkeypatch):
    first_artifact = {"artifact_ref": "a1", "artifact_hash": "h1"}
    def checkpoint(**kwargs):
        if kwargs["context"]["proposal_sequence"] == 1:
            return first_artifact
        raise adapter.SurrogateResponseRequired(tmp_path / "request.json")
    monkeypatch.setattr(pipeline, "provider_stage_checkpoint", checkpoint)
    monkeypatch.setattr(pipeline.requirement_decision_lane, "run_requirement_decision", lambda *args, **kwargs: {
        "status": "NEEDS_REWORK", "goal_spec": {"goal_spec_hash": "g1"},
        "requirement_replan": {"required_corrections": ["grounding"], "candidate_repair": False},
    })
    with pytest.raises(adapter.SurrogateResponseRequired):
        pipeline.run_canonical_requirement_planning(provider_mode="codex_surrogate", user_goal="x", run_dir=tmp_path, phase_log_path=tmp_path / "log.jsonl", codex_plan_contract={})
    state = json.loads((tmp_path / "artifacts" / "requirement_replan_state.json").read_text(encoding="utf-8"))
    assert state["workflow_state"] == "WAITING_REQUIREMENT_REPLAN"
    assert state["next_attempt"] == 2


def test_31_replan_attempts_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "provider_stage_checkpoint", lambda **kwargs: {"artifact_ref": f"a{kwargs['context']['proposal_sequence']}", "artifact_hash": "h"})
    monkeypatch.setattr(pipeline.requirement_decision_lane, "run_requirement_decision", lambda *args, **kwargs: {
        "status": "NEEDS_REWORK", "goal_spec": {"goal_spec_hash": "g"},
        "requirement_replan": {"required_corrections": ["still_invalid"], "candidate_repair": False},
    })
    result, _ = pipeline.run_canonical_requirement_planning(provider_mode="live", user_goal="x", run_dir=tmp_path, phase_log_path=tmp_path / "log.jsonl", codex_plan_contract={})
    state = json.loads((tmp_path / "artifacts" / "requirement_replan_state.json").read_text(encoding="utf-8"))
    assert result["status"] == "NEEDS_REWORK"
    assert state["workflow_state"] == "REPLAN_EXHAUSTED"
    assert state["attempts_used"] == pipeline.MAX_REQUIREMENT_PLANNING_ATTEMPTS


def test_32_source_identity_contains_required_hashes():
    result = source_identity.capture(ROOT)
    assert len(result["head_sha"]) == 40
    assert result["git_diff_sha256"].startswith("sha256:")
    assert result["agent_kit_package_sha256"].startswith("sha256:")
    assert result["plugin_source_sha256"].startswith("sha256:")
    assert result["modified_canonical_module_hashes"]
    assert result["contract_hashes"]


def test_33_formal_replan_resume_and_accounting_share_one_run(tmp_path):
    goal = "Create a local calculator that adds two numbers."
    args = argparse.Namespace(
        plan="", goal=goal, out_dir=str(tmp_path / "project"), run_dir=str(tmp_path / "run"),
        resume_run_dir="", codex_capability_brief="", result=str(tmp_path / "result.json"),
        allow_network=False, allow_provider=False, use_api=False, provider_mode="codex_surrogate",
        project_id="replan-test", replay_dir="", model="gpt-4.1", small_model="gpt-4.1",
        large_model="gpt-4.1", repair_model="", disable_model_routing=False, timeout=120,
        allow_model_usage_planning=False, phase_log_path="", provider_semantic_repair_attempts=None,
        post_build_repair_attempts=None, json=True,
    )
    first = run_local_pipeline.execute(args)
    request1 = json.loads(pathlib.Path(first["pending_requests"][0]["request_path"]).read_text(encoding="utf-8"))
    invalid = proposal(goal, core=["add_numbers"])
    invalid["source_grounding"] = [row for row in invalid["source_grounding"] if row["target"] != "proposed_core_capabilities"]
    adapter.submit_response(tmp_path / "run", adapter.build_response(request1, json.dumps(invalid)))
    args.resume_run_dir = str(tmp_path / "run")
    waiting_replan = run_local_pipeline.execute(args)
    assert waiting_replan["status"] == "WAITING_REQUIREMENT_REPLAN"
    request2 = next(
        json.loads(pathlib.Path(item["request_path"]).read_text(encoding="utf-8"))
        for item in waiting_replan["pending_requests"] if not item["responded"]
    )
    adapter.submit_response(tmp_path / "run", adapter.build_response(request2, json.dumps(proposal(goal, core=["add_numbers"]))))
    resumed = run_local_pipeline.execute(args)
    state = json.loads((tmp_path / "run" / "artifacts" / "requirement_replan_state.json").read_text(encoding="utf-8"))
    accounting = adapter.status(tmp_path / "run")
    assert resumed["status"] == "WAITING_SURROGATE_RESPONSE"
    assert any(item["stage"] == "product_design" for item in resumed["pending_requests"])
    assert state["workflow_state"] == "RESOLVED"
    assert [item["attempt"] for item in state["history"]] == [1, 2]
    assert accounting["consumed_attempts"] == 2


def test_34_resolved_requirement_checkpoint_is_reused_without_provider_call(tmp_path, monkeypatch):
    artifact_path = tmp_path / "artifacts" / "provider_stage_artifacts" / "requirements_planning.attempt-0001.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps({"artifact_hash": "a", "artifact_ref": str(artifact_path)}), encoding="utf-8")
    result = {"status": "PASS", "goal_spec": {"status": "PASS"}}
    (tmp_path / "artifacts" / "requirement_decision_checkpoint.json").write_text(
        json.dumps({"result": result}), encoding="utf-8"
    )
    (tmp_path / "artifacts" / "requirement_replan_state.json").write_text(json.dumps({
        "workflow_state": "RESOLVED", "attempts_used": 1,
        "history": [{"planning_artifact_ref": str(artifact_path)}],
    }), encoding="utf-8")
    monkeypatch.setattr(pipeline, "provider_stage_checkpoint", lambda **kwargs: pytest.fail("resolved requirement stage must be reused"))
    cached, cached_artifact = pipeline.run_canonical_requirement_planning(
        provider_mode="codex_surrogate", user_goal="x", run_dir=tmp_path,
        phase_log_path=tmp_path / "log.jsonl", codex_plan_contract={},
    )
    assert cached == result
    assert cached_artifact["artifact_hash"] == "a"


def test_35_requirements_planning_uses_reviewed_run_model_policy(tmp_path, monkeypatch):
    goal = "Create a local calculator."
    captured = {}
    policy = pipeline.ProviderModelRoutingPolicy(
        small_model="reviewed-small",
        large_model="reviewed-large",
        repair_model="reviewed-repair",
    )

    def fake_provider_text(messages, model, timeout, **kwargs):
        captured.update({"model": model, "routing_policy": kwargs.get("routing_policy")})
        return json.dumps(proposal(goal, core=["calculate"]))

    monkeypatch.setattr(pipeline, "provider_text", fake_provider_text)
    monkeypatch.setattr(
        pipeline.requirement_decision_lane,
        "run_requirement_decision",
        lambda *args, **kwargs: {"status": "PASS", "goal_spec": {"goal_spec_hash": "g"}},
    )
    result, _ = pipeline.run_canonical_requirement_planning(
        provider_mode="live",
        user_goal=goal,
        run_dir=tmp_path,
        phase_log_path=tmp_path / "log.jsonl",
        codex_plan_contract={},
        routing_policy=policy,
    )
    assert result["status"] == "PASS"
    assert captured == {"model": "surrogate-stage", "routing_policy": policy}


# Round-B generation contract matrix (G01-G14).
def test_g01_valid_minimal_planning_proposal_is_accepted():
    assert compiler.validate_planning_proposal(proposal("Create a local calculator.")) == []


def test_g02_provider_schema_contains_legal_grounding_targets():
    enum = compiler.planning_proposal_json_schema()["properties"]["source_grounding"]["items"]["properties"]["target"]["enum"]
    assert set(enum) == compiler.GROUNDED_FIELDS


def test_g03_provider_schema_reflects_necessary_inference_item_contract():
    schema = compiler.planning_proposal_json_schema()
    assert schema["properties"]["necessary_inferences"] == {"$ref": "#/$defs/strings"}
    assert schema["$defs"]["strings"]["items"] == {"type": "string", "minLength": 1}


def test_g04_patch_context_preserves_unrelated_existing_planning(tmp_path, monkeypatch):
    existing = proposal("Create a local calculator.")
    existing_path = tmp_path / "existing.json"
    existing_path.write_text(json.dumps({"proposal": existing}), encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "requirement_replan_state.json").write_text(json.dumps({
        "workflow_state": "WAITING_REQUIREMENT_REPLAN", "next_attempt": 2,
        "history": [{"planning_artifact_ref": str(existing_path)}],
        "feedback": {"required_corrections": ["change only calculate"]},
    }), encoding="utf-8")
    captured = {}
    monkeypatch.setattr(pipeline, "provider_stage_checkpoint", lambda **kwargs: captured.update(kwargs["context"]) or {"artifact_ref": "next", "artifact_hash": "h", "proposal": existing})
    monkeypatch.setattr(pipeline.requirement_decision_lane, "run_requirement_decision", lambda *args, **kwargs: {"status": "PASS", "goal_spec": {"goal_spec_hash": "g"}})
    pipeline.run_canonical_requirement_planning(provider_mode="live", user_goal="Create a local calculator.", run_dir=tmp_path, phase_log_path=tmp_path / "log", codex_plan_contract={"brief_sha256": "sealed"})
    assert captured["context_sections"]["EXISTING_VALID_PLANNING"] == existing
    assert captured["context_sections"]["NEW_INFORMATION"] == {"required_corrections": ["change only calculate"]}


def test_g05_patch_instructions_allow_only_grounded_affected_planning(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(pipeline, "provider_text", lambda messages, *_a, **_k: seen.update(system=messages[0]["content"]) or json.dumps(proposal("Create a local calculator.")))
    pipeline.provider_stage_checkpoint(provider_mode="live", stage="requirements_planning", context={"goal": "Create a local calculator.", "proposal_sequence": 1}, run_dir=tmp_path, phase_log_path=tmp_path / "log")
    assert "modify only grounded affected elements" in seen["system"]


def test_g06_patch_unsupported_addition_is_rejected():
    goal = "Create a local calculator."
    doc = proposal(goal)
    doc["proposed_supporting_capabilities"] = ["cloud_upload"]
    doc["source_grounding"].append({"target": "proposed_supporting_capabilities", "value": "cloud_upload", "source_kind": "RAW_GOAL", "source_excerpt": goal, "rationale": "unsupported"})
    result = compile_goal(goal, doc)
    assert result["status"] == "NEEDS_REWORK"
    assert "unsupported_high_risk_addition:cloud_scope" in result["grounding_validation"]["unsupported_additions"]


def test_g07_replan_may_restructure_supported_planning():
    goal = "Create a local calculator that adds and subtracts."
    assert compile_goal(goal, proposal(goal, core=["add", "subtract"]))["status"] == "PASS"


def test_g08_replan_unsupported_requirement_is_rejected():
    test_g06_patch_unsupported_addition_is_rejected()


def test_g09_replan_prompt_preserves_supported_existing_intent(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(pipeline, "provider_text", lambda messages, *_a, **_k: seen.update(system=messages[0]["content"]) or json.dumps(proposal("Create a local calculator.")))
    pipeline.provider_stage_checkpoint(provider_mode="live", stage="requirements_planning", context={"goal": "Create a local calculator."}, run_dir=tmp_path, phase_log_path=tmp_path / "log")
    assert "REPLAN may restructure supported planning" in seen["system"]


def test_g10_missing_required_existing_planning_is_rejected():
    goal = "Create a local calculator that adds two numbers."
    existing = proposal(goal, core=["add_numbers", "show_result"])
    changed = proposal(goal, core=["add_numbers"])
    errors = compiler.validate_planning_preservation(changed, existing, {})
    assert "preservation_missing:proposed_core_capabilities:show_result" in errors


def test_g11_legal_grounding_target_is_accepted():
    assert not any(error.endswith("_target") for error in compiler.validate_planning_proposal(proposal("Create a local calculator.")))


def test_g12_illegal_grounding_target_is_rejected():
    doc = proposal("Create a local calculator.")
    doc["source_grounding"][0]["target"] = "invented_target"
    assert "source_grounding[0]_target" in compiler.validate_planning_proposal(doc)


def test_g13_valid_necessary_inference_item_is_accepted():
    doc = proposal("Create a local calculator.")
    doc["necessary_inferences"] = ["A bounded input parser is necessary."]
    assert "necessary_inferences_contains_invalid_item" not in compiler.validate_planning_proposal(doc)


def test_g14_invalid_necessary_inference_item_is_rejected():
    doc = proposal("Create a local calculator.")
    doc["necessary_inferences"] = [{"text": "invalid"}]
    assert "necessary_inferences_contains_invalid_item" in compiler.validate_planning_proposal(doc)


# Round-B schema repair matrix (R01-R10).
def _repair_contract(rejected=None, errors=None, sequence=2, brief="sealed"):
    return compiler.planning_proposal_repair_contract(rejected or {}, errors or [], generation_context={"proposal_sequence": sequence, "sealed_intent": {"brief_sha256": brief}})


def test_r01_invalid_target_repair_receives_exact_enum():
    assert set(_repair_contract(errors=["source_grounding[2]_target"])["legal_source_grounding_targets"]) == compiler.GROUNDED_FIELDS


def test_r02_invalid_inference_repair_receives_exact_item_schema():
    assert _repair_contract(errors=["necessary_inferences_contains_invalid_item"])["necessary_inferences_item_schema"] == {"type": "string", "minLength": 1}


def test_r03_repair_contract_requires_only_invalid_field_changes():
    assert any("change only fields" in item for item in _repair_contract()["invariants"])


def test_r04_repair_contract_preserves_valid_semantics():
    assert any("preserve every" in item for item in _repair_contract()["invariants"])


def test_r05_repair_contract_forbids_invented_additions():
    assert any("do not invent" in item for item in _repair_contract()["invariants"])


def test_r06_repair_cannot_bypass_local_validator(tmp_path, monkeypatch):
    invalid = proposal("Create a local calculator.")
    invalid["source_grounding"][0]["target"] = "still_invalid"
    monkeypatch.setattr(pipeline, "provider_text", lambda *_a, **_k: json.dumps(invalid))
    with pytest.raises(RuntimeError, match="invalid after the single schema repair"):
        pipeline.provider_stage_checkpoint(provider_mode="live", stage="requirements_planning", context={"goal": "Create a local calculator."}, run_dir=tmp_path, phase_log_path=tmp_path / "log")


def test_r07_still_invalid_target_is_rejected():
    test_g12_illegal_grounding_target_is_rejected()


def test_r08_schema_valid_unsupported_addition_is_semantically_rejected():
    test_g06_patch_unsupported_addition_is_rejected()


def test_r09_repair_retains_sealed_brief_identity():
    assert _repair_contract(brief="brief-19f7")["identity"]["sealed_brief_sha256"] == "brief-19f7"


def test_r10_repair_retains_generation_proposal_identity():
    assert _repair_contract(sequence=3)["identity"]["proposal_sequence"] == 3


# Round-B structured-output matrix (S01-S07).
def test_s01_response_format_uses_canonical_schema():
    fmt = compiler.planning_proposal_response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == compiler.planning_proposal_json_schema()
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert pipeline.provider_reasoning_effort(base_url, "qwen3.7-flash", "requirements_planning") == "none"
    payload = pipeline.check_connectivity._build_openai_compatible_payload(
        base_url,
        {"model": "qwen3.7-flash", "messages": [], "response_format": fmt},
        model="qwen3.7-flash",
        reasoning_effort="none",
    )
    assert payload["enable_thinking"] is False
    assert "max_tokens" not in payload


def test_s02_response_format_projects_grounding_enum():
    test_g02_provider_schema_contains_legal_grounding_targets()


def test_s03_response_format_projects_inference_item_schema():
    test_g03_provider_schema_reflects_necessary_inference_item_contract()


def test_s04_response_format_required_fields_match_canonical_schema():
    fmt = compiler.planning_proposal_response_format()["json_schema"]["schema"]
    assert set(fmt["required"]) == set(fmt["properties"])


def test_s05_response_format_exposes_no_secret_or_runtime_fields():
    text = json.dumps(compiler.planning_proposal_response_format()).lower()
    assert all(term not in text for term in ("api_key", "credential", "run_dir", "runtime_identity"))


def test_s06_response_format_is_deterministic():
    assert compiler.stable_hash(compiler.planning_proposal_response_format()) == compiler.stable_hash(compiler.planning_proposal_response_format())


def test_s07_local_validator_remains_final():
    invalid = proposal("Create a local calculator.")
    invalid["source_grounding"][0]["target"] = "not_in_provider_schema"
    assert compiler.validate_planning_proposal(invalid)
