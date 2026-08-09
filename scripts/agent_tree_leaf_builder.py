from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_tree_action_protocol import AgentActionRecorder
    from agent_tree_contracts import now, write_json
    import local_packager
    import real_test_execution
    import runtime_visual_evidence
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_action_protocol import AgentActionRecorder
    from scripts.agent_tree_contracts import now, write_json
    from scripts import local_packager, real_test_execution, runtime_visual_evidence


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _record(
    recorder: AgentActionRecorder,
    stage: dict[str, Any],
    local_context: dict[str, Any],
    action: str,
    reason: str,
) -> None:
    recorder.record(
        agent_id=str(stage["agent"]),
        agent_role="LeafBuilder" if str(stage["agent"]).endswith("_leaf") else "SpecialistAgent",
        stage=str(stage["id"]),
        action=action,
        target_files=list(stage.get("expected_files", [])),
        outputs=list(stage.get("outputs", [])),
        reason=reason,
        input_context_id=str(local_context.get("context_id", "")),
        expected_verification=list(stage.get("verify", [])),
        claimed_complete=False,
    )


def _foundation_source(shared_context: dict[str, Any]) -> str:
    goal_spec = shared_context.get("goal_spec", {})
    return (
        "from __future__ import annotations\n\n"
        f"GOAL_SPEC = {goal_spec!r}\n\n"
        "def project_summary() -> dict:\n"
        "    return {\n"
        "        'goal': GOAL_SPEC.get('goal', ''),\n"
        "        'domain': GOAL_SPEC.get('domain', ''),\n"
        "        'capabilities': list(GOAL_SPEC.get('capabilities', [])),\n"
        "        'interfaces': list(GOAL_SPEC.get('interfaces', [])),\n"
        "        'acceptance_behaviors': list(GOAL_SPEC.get('acceptance_behaviors', [])),\n"
        "    }\n\n"
        "if __name__ == '__main__':\n"
        "    print(project_summary())\n"
    )


def _business_leaf_source(stage: dict[str, Any], shared_context: dict[str, Any]) -> str:
    goal_spec = shared_context.get("goal_spec", {})
    payload = {
        "workstream": stage.get("id", ""),
        "scope": stage.get("scope", ""),
        "domain": goal_spec.get("domain", ""),
        "capabilities": goal_spec.get("capabilities", []),
        "test_intents": stage.get("test_intents", []),
    }
    return (
        "from __future__ import annotations\n\n"
        f"WORKSTREAM = {payload!r}\n\n"
        "def describe_scope() -> dict:\n"
        "    return {key: value[:] if isinstance(value, list) else value for key, value in WORKSTREAM.items()}\n"
    )


def _test_source(shared_context: dict[str, Any]) -> str:
    goal_spec = shared_context.get("goal_spec", {})
    return (
        "from app.main import project_summary\n\n"
        f"EXPECTED_DOMAIN = {str(goal_spec.get('domain', ''))!r}\n"
        f"EXPECTED_CAPABILITIES = {list(goal_spec.get('capabilities', []))!r}\n"
        f"EXPECTED_BEHAVIORS = {list(goal_spec.get('acceptance_behaviors', []))!r}\n\n"
        "def test_project_summary_tracks_canonical_goal_spec():\n"
        "    summary = project_summary()\n"
        "    assert summary['domain'] == EXPECTED_DOMAIN\n"
        "    assert summary['capabilities'] == EXPECTED_CAPABILITIES\n"
        "    assert summary['acceptance_behaviors'] == EXPECTED_BEHAVIORS\n"
    )


def build_controlled_stage(
    stage: dict[str, Any],
    *,
    shared_context: dict[str, Any],
    local_context: dict[str, Any],
    project_dir: str | pathlib.Path,
    out_dir: str | pathlib.Path,
    recorder: AgentActionRecorder,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    out = pathlib.Path(out_dir)
    stage_id = str(stage["id"])
    stage_type = str(stage.get("stage_type", ""))

    if stage_type == "requirement":
        _record(recorder, stage, local_context, "freeze_requirements", "Freeze the canonical GoalSpec and Project Plan before controlled work.")
        frozen = {
            "kind": "AgentTreeFrozenRequirement",
            "project_name": shared_context["project_name"],
            "user_goal": shared_context["user_goal"],
            "goal_spec": shared_context.get("goal_spec", {}),
            "project_plan": shared_context.get("project_plan", {}),
            "requirements": list(shared_context["acceptance_contract"]),
            "allowed_context_terms": list(shared_context["allowed_context_terms"]),
            "forbidden_context_terms": list(shared_context["forbidden_context_terms"]),
            "created_at": now(),
        }
        shared_context["frozen_requirements"] = frozen["requirements"]
        write_json(out / "frozen_requirement.json", frozen)
        return {"status": "ok", "outputs": ["frozen_requirement.json"]}

    if stage_type == "foundation":
        _record(recorder, stage, local_context, "create_foundation_files", "Create the goal-bound runnable project foundation.")
        goal_spec = shared_context.get("goal_spec", {})
        _write(
            project / "README.md",
            f"# {shared_context.get('project_name', 'Goal-driven local project')}\n\n"
            f"Goal: {shared_context.get('user_goal', '')}\n\n"
            f"Domain: {goal_spec.get('domain', '')}\n\n"
            "## Run\n\n```bash\npython app/main.py\n```\n",
        )
        _write(project / "pyproject.toml", "[project]\nname = \"goal-driven-controlled-project\"\nversion = \"0.1.0\"\n\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n")
        _write(project / "src" / "__init__.py", "")
        _write(project / "app" / "__init__.py", "")
        _write(project / "app" / "main.py", _foundation_source(shared_context))
        return {"status": "ok"}

    if stage_type == "business":
        _record(recorder, stage, local_context, "create_goal_scoped_leaf", "Materialize only this Project Plan leaf scope.")
        for relative in stage.get("expected_files", []):
            target = project / str(relative)
            if target.suffix.lower() == ".py":
                _write(target, _business_leaf_source(stage, shared_context))
            else:
                _write(target, json.dumps({"stage": stage_id, "scope": stage.get("scope", "")}, ensure_ascii=False, indent=2) + "\n")
        return {"status": "ok"}

    if stage_type == "tests":
        _record(recorder, stage, local_context, "create_and_run_goal_tests", "Materialize GoalSpec-derived test intent inputs in the controlled lane.")
        expected_files = list(stage.get("expected_files", [])) or ["tests/test_goal_behaviors.py"]
        for relative in expected_files:
            _write(project / str(relative), _test_source(shared_context))
        result = real_test_execution.run_tests(project, timeout=60)
        return {"status": "ok" if result.get("verdict") == "PASS" else "fail", "test_result": result}

    if stage_type == "visual":
        _record(recorder, stage, local_context, "create_visual_evidence", "Collect controlled synthetic previews without promoting them to formal evidence.")
        interface_names = [str(item) for item in shared_context.get("goal_spec", {}).get("interfaces", [])]
        preview_names = list(dict.fromkeys([*interface_names, "overview", "primary_action", "result_state"]))[:3]
        for name in preview_names:
            runtime_visual_evidence.write_runtime_preview_png(project / "screenshots" / f"{name}.png", title=name)
        result = runtime_visual_evidence.collect_visual_evidence(project)
        return {"status": "ok" if result.get("verdict") == "PASS" else "fail", "visual_result": result}

    if stage_type == "delivery":
        _record(recorder, stage, local_context, "package_delivery", "Exercise the existing packager and public gate in the controlled reference lane.")
        _write(project / "DELIVERY_NOTES.md", "# Delivery Notes\n\ncontrolled_agent_tree_lane: PASS\nnot_real_provider_proof: true\n")
        manifest = local_packager.package_project(
            project,
            output_dir=project,
            startup_command="python app/main.py",
            screenshot_path=next(iter(sorted((project / "screenshots").glob("*.png"))), None),
        )
        return {"status": "ok", "manifest": manifest}

    return {"status": "skipped", "reason": f"unknown stage {stage_id}"}
