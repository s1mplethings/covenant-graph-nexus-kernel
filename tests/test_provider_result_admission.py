from __future__ import annotations

import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import canonical_goal_spec_compiler as compiler
import run_local_pipeline_impl as pipeline


GOAL = "Create a local text counter that accepts UTF-8 input."


def proposal(goal: str = GOAL) -> dict:
    user = "the user who supplied the goal"
    outcome = "Count text from UTF-8 input."
    capability = "count_text"
    workflow = "provide text, run the counter, and review the count"
    forbidden = "Do not replace the executable counter with documentation."
    values = {
        "intended_users": [user],
        "desired_outcomes": [outcome],
        "proposed_core_capabilities": [capability],
        "proposed_supporting_capabilities": [],
        "proposed_user_workflows": [workflow],
        "explicit_constraints_found": compiler.extract_explicit_constraints(goal),
        "proposed_acceptance_anchors": [outcome],
        "proposed_forbidden_substitutions": [forbidden],
    }
    grounding = []
    inferred = {"intended_users", "proposed_user_workflows", "proposed_forbidden_substitutions"}
    for field, items in values.items():
        for value in items:
            grounding.append({
                "target": field,
                "value": value,
                "source_kind": "NECESSARY_INFERENCE" if field in inferred else "RAW_GOAL",
                "source_excerpt": goal,
                "rationale": "The bounded source directly requires or necessarily supports this item.",
            })
    grounding.append({
        "target": "proposed_workstreams",
        "value": "text_counter",
        "source_kind": "NECESSARY_INFERENCE",
        "source_excerpt": goal,
        "rationale": "One implementation workstream is necessary for the requested capability.",
    })
    return {
        "schema_version": "1.0",
        "interpreted_goal": goal,
        **values,
        "proposed_workstreams": [{"id": "text_counter", "scope": "Implement text counting", "covers_capabilities": [capability]}],
        "necessary_inferences": [],
        "assumptions": ["Unspecified reversible details use conservative defaults."],
        "open_questions": [],
        "source_grounding": grounding,
    }


def run_checkpoint(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, responses: list[object]):
    run_dir = tmp_path / "run"
    phase_log = run_dir / "provider_phase_log.jsonl"
    queue = list(responses)

    def provider_text(*_args, **_kwargs):
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(pipeline, "provider_text", provider_text)
    artifact = pipeline.provider_stage_checkpoint(
        provider_mode="live",
        stage="requirements_planning",
        context={"goal": GOAL, "proposal_sequence": 1},
        run_dir=run_dir,
        phase_log_path=phase_log,
    )
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]
    return artifact, events


def test_a01_one_attempt_success_is_admitted(tmp_path, monkeypatch):
    artifact, events = run_checkpoint(tmp_path, monkeypatch, [json.dumps(proposal())])
    assert artifact["transport_identity"]["validated"] is True
    assert [event for event in events if event.get("event") == "provider_result_admitted"]


def test_a02_fenced_valid_json_is_deterministically_admitted_without_provider_repair(tmp_path, monkeypatch):
    raw = "```json\n" + json.dumps(proposal()) + "\n```"
    artifact, events = run_checkpoint(tmp_path, monkeypatch, [raw])
    assert artifact["proposal"]["proposed_core_capabilities"] == ["count_text"]
    assert not [event for event in events if event.get("event") == "provider_result_validation_failed"]


def test_a03_commentary_wrapped_valid_object_is_admitted(tmp_path, monkeypatch):
    raw = "bounded result follows\n" + json.dumps(proposal()) + "\nend"
    artifact, events = run_checkpoint(tmp_path, monkeypatch, [raw])
    assert artifact["proposal"]["interpreted_goal"] == GOAL
    assert [event for event in events if event.get("used_in_formal_chain") is True]


def test_a06_http_text_with_invalid_schema_is_not_admitted(tmp_path, monkeypatch):
    invalid = json.dumps({"schema_version": "1.0", "interpreted_goal": GOAL})
    with pytest.raises(RuntimeError, match="invalid after the single schema repair"):
        run_checkpoint(tmp_path, monkeypatch, [invalid, invalid])
    events = [json.loads(line) for line in (tmp_path / "run/provider_phase_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len([event for event in events if event.get("event") == "provider_result_validation_failed"]) == 2
    assert not [event for event in events if event.get("event") == "provider_result_admitted"]


def test_a11_admitted_result_materializes_candidate_input_artifact(tmp_path, monkeypatch):
    artifact, _events = run_checkpoint(tmp_path, monkeypatch, [json.dumps(proposal())])
    artifact_path = tmp_path / "run/artifacts/provider_stage_artifacts/requirements_planning.json"
    assert artifact_path.is_file()
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["artifact_hash"] == artifact["artifact_hash"]


def test_a12_admission_preserves_original_goal_binding(tmp_path, monkeypatch):
    artifact, _events = run_checkpoint(tmp_path, monkeypatch, [json.dumps(proposal())])
    assert artifact["raw_goal_hash"] == compiler.raw_goal_hash(GOAL)


def test_a15_failed_schema_repair_produces_no_fake_artifact(tmp_path, monkeypatch):
    invalid = json.dumps({"summary": "not the planning contract"})
    with pytest.raises(RuntimeError):
        run_checkpoint(tmp_path, monkeypatch, [invalid, invalid])
    assert not (tmp_path / "run/artifacts/provider_stage_artifacts/requirements_planning.json").exists()


def test_real_run_shape_five_timeouts_then_valid_success_admits_once(tmp_path, monkeypatch):
    attempts = [TimeoutError("timeout") for _ in range(5)] + [json.dumps(proposal())]
    admitted = []
    for index, item in enumerate(attempts, start=1):
        if isinstance(item, TimeoutError):
            with pytest.raises(TimeoutError):
                run_checkpoint(tmp_path / f"attempt-{index}", monkeypatch, [item])
            continue
        artifact, events = run_checkpoint(tmp_path / f"attempt-{index}", monkeypatch, [item])
        admitted.extend(event for event in events if event.get("event") == "provider_result_admitted")
        assert artifact["proposal"]["interpreted_goal"] == GOAL
    assert len(admitted) == 1
