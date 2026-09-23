from __future__ import annotations

import json
import pathlib

import pytest

from scripts.capability_execution import (
    apply_iteration_review,
    build_skill_registry,
    compile_capability_plan,
    create_skill_candidate,
    match_skills,
    select_reuse,
)
from scripts.work_nodes import WorkNode


def _node() -> WorkNode:
    return WorkNode("formula_recognition", "Recognize formula", inputs=("HandwritingArtifact",), outputs=("RecognizedFormula",), acceptance=("recognition contract passes",))


def _source(kind: str, ref: str, **extra):
    return {"type": kind, "ref": ref, "inputs": ["HandwritingArtifact"], "outputs": ["RecognizedFormula"], "acceptance_compatible": True, **extra}


def test_capability_planning_precedes_file_tree_and_maps_to_worknodes() -> None:
    plan = compile_capability_plan({"goal": "training", "capabilities": [{"id": "input", "goal": "Capture handwriting", "outputs": ["HandwritingArtifact"], "acceptance": ["capture works"]}, {"id": "recognize", "goal": "Recognize formula", "depends_on": ["input"], "inputs": ["HandwritingArtifact"], "outputs": ["RecognizedFormula"], "acceptance": ["recognized"]}]})
    assert [item["id"] for item in plan["capabilities"]] == ["input", "recognize"]
    assert plan["work_nodes"][1]["depends_on"] == ["worknode.input"]
    with pytest.raises(ValueError, match="capabilities_required_before_file_tree"):
        compile_capability_plan({"goal": "bad", "files": ["frontend/", "backend/"]})


def test_interface_mismatch_fails_before_execution() -> None:
    with pytest.raises(ValueError, match="interface_mismatch"):
        compile_capability_plan({"capabilities": [{"id": "a", "goal": "A", "outputs": ["AOut"]}, {"id": "b", "goal": "B", "depends_on": ["a"], "inputs": ["Wrong"], "outputs": ["BOut"]}]})


@pytest.mark.parametrize("expected,candidates,api_allowed", [
    ("internal", [_source("internal", "repo:ocr")], False),
    ("skill", [_source("skill", "skill:formula")], False),
    ("oss", [_source("oss", "pypi:pix2tex", version="1.1", license="MIT", integration_method="dependency")], False),
    ("github", [_source("github", "github:owner/module", version="abc123", license="Apache-2.0", integration_method="module_adapter")], False),
    ("api", [_source("api", "api:math", version="v1", integration_method="adapter")], True),
    ("build", [], False),
])
def test_reuse_source_selection(expected, candidates, api_allowed) -> None:
    assert select_reuse(_node(), candidates, api_allowed=api_allowed)["selected_source"]["type"] == expected


def test_reuse_rejections_are_explicit() -> None:
    candidates = [
        {**_source("skill", "skill:bad"), "inputs": ["StrokeStream"]},
        {**_source("oss", "pypi:bad", version="1", license="MIT"), "acceptance_compatible": False},
        _source("oss", "pypi:unknown", version="1", license="unknown"),
        _source("github", "github:whole", version="1", license="MIT", integration_method="whole_repo_copy"),
        _source("api", "api:forbidden", version="v1"),
    ]
    decision = select_reuse(_node(), candidates, api_allowed=False)
    assert decision["selected_source"]["type"] == "build"
    assert len(decision["rejected"]) == 5


def test_skill_registry_matches_interfaces_not_names(tmp_path: pathlib.Path) -> None:
    skill = tmp_path / "misleading-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: formula-helper\ndescription: tested formula recognition\n---\n", encoding="utf-8")
    (skill / "skill.json").write_text(json.dumps({"inputs": ["HandwritingArtifact"], "outputs": ["RecognizedFormula"], "acceptance": ["recognition contract passes"], "state": "approved"}), encoding="utf-8")
    registry = build_skill_registry(tmp_path)
    assert [item["skill_id"] for item in match_skills(_node(), registry)] == ["formula-helper"]
    mismatch = WorkNode("stroke", "stroke", inputs=("StrokeStream",), outputs=("RecognizedFormula",), acceptance=("recognition contract passes",))
    assert match_skills(mismatch, registry) == []


def test_agent_pass_creates_candidate_without_modifying_skills(tmp_path: pathlib.Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    before = list(skills.iterdir())
    target = create_skill_candidate(_node(), {"procedure": ["normalize", "recognize"], "acceptance": {"status": "PASS", "evidence_refs": ["test.json"]}}, tmp_path / "candidates")
    assert target and json.loads(target.read_text(encoding="utf-8"))["auto_promotion"] is False
    assert list(skills.iterdir()) == before


def test_two_iterations_apply_real_replan() -> None:
    backlog = [{"id": "slice-1", "state": "selected", "priority": 1, "executor": "agent"}, {"id": "slice-2", "state": "planned", "priority": 2, "executor": "agent"}]
    backlog, first = apply_iteration_review(backlog, accepted_ids=["slice-1"], failed_ids=[], change={"retrospective": "keep vertical slice small"})
    backlog, second = apply_iteration_review(backlog, accepted_ids=[], failed_ids=["slice-2"], change={"executor": "skill", "priority": 1, "retrospective": "reuse verified recognition"})
    assert first["state_changed"] and second["state_changed"]
    assert backlog[1]["state"] == "replanned"
    assert backlog[1]["executor"] == "skill"
