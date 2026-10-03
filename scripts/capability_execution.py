#!/usr/bin/env python3
"""Capability/interface planning and lightweight reusable executor selection.

This module produces support planning records only. It owns no scheduler,
Provider call, acceptance authority, package, or delivery exit.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from scripts.work_nodes import WorkNode, validate_work_nodes
from scripts import external_executor_discovery


REUSE_ORDER = {"internal": 0, "skill": 1, "oss": 2, "github": 3, "api": 4, "build": 5}


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in value or [] if str(item).strip()))


@dataclass(frozen=True)
class Capability:
    id: str
    goal: str
    depends_on: tuple[str, ...]
    input_interfaces: tuple[str, ...]
    output_interfaces: tuple[str, ...]
    acceptance: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Capability":
        return cls(
            id=str(value.get("id", "")).strip(),
            goal=str(value.get("goal", "")).strip(),
            depends_on=_tuple(value.get("depends_on", [])),
            input_interfaces=_tuple(value.get("inputs", [])),
            output_interfaces=_tuple(value.get("outputs", [])),
            acceptance=_tuple(value.get("acceptance", [])),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "goal": self.goal, "depends_on": list(self.depends_on), "inputs": list(self.input_interfaces), "outputs": list(self.output_interfaces), "acceptance": list(self.acceptance)}


def compile_capability_plan(
    requirement: Mapping[str, Any],
    *,
    executor_selections: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = requirement.get("capabilities", [])
    if not isinstance(raw, list) or not raw:
        raise ValueError("capability_plan.capabilities_required_before_file_tree")
    capabilities = [Capability.from_dict(item) for item in raw if isinstance(item, Mapping)]
    ids = {item.id for item in capabilities if item.id}
    errors: list[str] = []
    if len(ids) != len(capabilities):
        errors.append("capability_plan.unique_nonempty_ids")
    for item in capabilities:
        if not item.goal or not item.output_interfaces:
            errors.append(f"capability_plan.interface_required:{item.id}")
        for dependency in item.depends_on:
            if dependency not in ids:
                errors.append(f"capability_plan.unknown_dependency:{item.id}:{dependency}")
    if errors:
        raise ValueError(";".join(sorted(set(errors))))
    selections = executor_selections or {}
    nodes = [
        WorkNode(
            id=f"worknode.{item.id}",
            goal=item.goal,
            depends_on=tuple(f"worknode.{dep}" for dep in item.depends_on),
            inputs=item.input_interfaces,
            outputs=item.output_interfaces,
            interfaces=tuple(dict.fromkeys((*item.input_interfaces, *item.output_interfaces))),
            executor_type=(
                "external"
                if isinstance(selections.get(item.id), Mapping)
                and selections[item.id].get("executor", {}).get("type") == "external"
                else "agent"
            ),
            executor_details=(
                dict(selections[item.id].get("executor", {}))
                | {"selected_executor": dict(selections[item.id])}
                if isinstance(selections.get(item.id), Mapping)
                and selections[item.id].get("executor", {}).get("type") == "external"
                else {}
            ),
            acceptance=item.acceptance,
        )
        for item in capabilities
    ]
    node_errors = validate_work_nodes(nodes)
    if node_errors:
        raise ValueError(";".join(node_errors))
    validate_interface_graph(capabilities)
    return {"kind": "CGKNCapabilityPlan", "goal": str(requirement.get("goal", "")).strip(), "capabilities": [item.as_dict() for item in capabilities], "work_nodes": [item.as_dict() for item in nodes], "release_authority": False}


def discover_capability_executors(
    requirement: Mapping[str, Any],
    *,
    skill_root: pathlib.Path | None = None,
    allow_network: bool = True,
    discovery: Any = external_executor_discovery.discover_external_executor,
) -> dict[str, Any]:
    """Run the canonical Local -> Skill -> External -> Agent Build support seam."""
    base_plan = compile_capability_plan(requirement)
    registry = build_skill_registry(skill_root) if skill_root and skill_root.is_dir() else []
    results: list[dict[str, Any]] = []
    selections: dict[str, dict[str, Any]] = {}
    for raw_node, capability in zip(base_plan["work_nodes"], base_plan["capabilities"]):
        node = WorkNode.from_dict(raw_node)
        skills = [
            {
                "kind": "CGKNSelectedExecutor",
                "executor": {"type": "skill"},
                "skill_id": skill.get("skill_id"),
                "interface_compatible": True,
                "acceptance_compatible": True,
                "release_authority": False,
            }
            for skill in match_skills(node, registry, constraints=requirement.get("constraints", []))
        ]
        result = discovery(
            capability,
            language=str(requirement.get("language", "python")),
            platform=str(requirement.get("platform", "")) or None,
            constraints=requirement.get("constraints", []),
            required_interfaces=node.interfaces,
            skill_candidates=skills,
            allow_network=allow_network,
        )
        results.append(result)
        selected = result.get("selected_executor")
        if result.get("route") == "external" and isinstance(selected, Mapping):
            selections[capability["id"]] = dict(selected)
    plan = compile_capability_plan(requirement, executor_selections=selections)
    return {
        "kind": "CGKNCapabilityExecutorSelection",
        "schema_version": "1.0",
        "status": "PASS",
        "results": results,
        "capability_plan": plan,
        "provider_calls": 0,
        "release_authority": False,
    }


def discover_goal_spec_executors(
    goal_spec: Mapping[str, Any],
    *,
    skill_root: pathlib.Path | None = None,
    allow_network: bool = True,
    discovery: Any = external_executor_discovery.discover_external_executor,
) -> dict[str, Any]:
    """Adapt canonical GoalSpec string capabilities into the WorkNode seam."""
    raw_capabilities = goal_spec.get("capabilities", [])
    capabilities = [str(item).strip() for item in raw_capabilities if str(item).strip()]
    requirement = {
        "goal": str(goal_spec.get("goal", "")).strip(),
        "language": str(goal_spec.get("language", "python") or "python"),
        "platform": str(goal_spec.get("platform", "") or ""),
        "constraints": list(goal_spec.get("constraints", [])),
        "capabilities": [
            {
                "id": re.sub(r"[^a-z0-9_]+", "_", item.lower()).strip("_") or f"capability_{index}",
                "goal": item,
                "depends_on": [],
                "inputs": [],
                "outputs": [f"CapabilityResult.{index}"],
                "acceptance": list(goal_spec.get("acceptance_behaviors", [])),
            }
            for index, item in enumerate(capabilities)
        ],
    }
    if not requirement["capabilities"]:
        return {
            "kind": "CGKNCapabilityExecutorSelection",
            "schema_version": "1.0",
            "status": "NOT_EVALUATED",
            "reason": "goal_spec_has_no_capabilities",
            "results": [],
            "capability_plan": None,
            "provider_calls": 0,
            "release_authority": False,
        }
    return discover_capability_executors(
        requirement,
        skill_root=skill_root,
        allow_network=allow_network,
        discovery=discovery,
    )


def validate_interface_graph(capabilities: Iterable[Capability]) -> None:
    values = list(capabilities)
    by_id = {item.id: item for item in values}
    for consumer in values:
        available: set[str] = set()
        for dependency in consumer.depends_on:
            available.update(by_id[dependency].output_interfaces)
        missing = set(consumer.input_interfaces) - available
        if consumer.depends_on and missing:
            raise ValueError(f"capability_plan.interface_mismatch:{consumer.id}:{','.join(sorted(missing))}")


def _compatible(source: Mapping[str, Any], node: WorkNode) -> bool:
    return set(node.inputs).issubset(set(_tuple(source.get("inputs", [])))) and set(node.outputs).issubset(set(_tuple(source.get("outputs", [])))) and bool(source.get("acceptance_compatible", True))


def select_reuse(node: WorkNode, candidates: Iterable[Mapping[str, Any]], *, api_allowed: bool = False) -> dict[str, Any]:
    rejected: list[dict[str, str]] = []
    ordered = sorted((dict(item) for item in candidates), key=lambda item: REUSE_ORDER.get(str(item.get("type", "")), 99))
    for source in ordered:
        kind = str(source.get("type", "")).strip()
        ref = str(source.get("ref", "")).strip()
        reason = ""
        if kind not in REUSE_ORDER or kind == "build":
            continue
        if not ref:
            reason = "missing provenance ref"
        elif not _compatible(source, node):
            reason = "interface or acceptance mismatch"
        elif kind in {"oss", "github"} and str(source.get("license", "")).lower() in {"", "unknown", "incompatible"}:
            reason = "license incompatible or unknown"
        elif kind in {"oss", "github"} and not str(source.get("version", "")).strip():
            reason = "version missing"
        elif kind == "github" and str(source.get("integration_method", "")).strip() == "whole_repo_copy":
            reason = "whole repository copy rejected"
        elif kind == "api" and not api_allowed:
            reason = "external API not allowed"
        if reason:
            rejected.append({"type": kind, "ref": ref, "reason": reason})
            continue
        return {"capability_id": node.id, "selected_source": {"type": kind, "ref": ref}, "adapter_required": kind in {"oss", "github", "api"} or bool(source.get("adapter_required")), "reason": str(source.get("reason", "compatible reusable executor")), "provenance": {key: source.get(key) for key in ("version", "license", "integration_method") if source.get(key)}, "rejected": rejected}
    return {"capability_id": node.id, "selected_source": {"type": "build", "ref": "agent"}, "adapter_required": False, "reason": "no acceptable reusable executor", "rejected": rejected}


def build_skill_registry(skill_root: pathlib.Path) -> list[dict[str, Any]]:
    registry: list[dict[str, Any]] = []
    for skill_md in sorted(skill_root.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        name = re.search(r"(?m)^name:\s*(.+?)\s*$", text)
        description = re.search(r"(?m)^description:\s*(.+?)\s*$", text)
        metadata_path = skill_md.with_name("skill.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        registry.append({"skill_id": str(metadata.get("skill_id") or (name.group(1).strip() if name else skill_md.parent.name)), "description": description.group(1).strip() if description else "", "inputs": list(metadata.get("inputs", [])), "outputs": list(metadata.get("outputs", [])), "constraints": list(metadata.get("constraints", [])), "acceptance": list(metadata.get("acceptance", [])), "state": str(metadata.get("state", "approved")), "path": str(skill_md)})
    return registry


def match_skills(node: WorkNode, registry: Iterable[Mapping[str, Any]], *, constraints: Iterable[str] = ()) -> list[dict[str, Any]]:
    required_constraints = set(str(item) for item in constraints)
    return [dict(skill) for skill in registry if str(skill.get("state")) == "approved" and set(node.inputs).issubset(set(_tuple(skill.get("inputs", [])))) and set(node.outputs).issubset(set(_tuple(skill.get("outputs", [])))) and required_constraints.issubset(set(_tuple(skill.get("constraints", [])))) and set(node.acceptance).issubset(set(_tuple(skill.get("acceptance", []))))]


def create_skill_candidate(node: WorkNode, result: Mapping[str, Any], output_dir: pathlib.Path) -> pathlib.Path | None:
    acceptance = result.get("acceptance", {})
    if node.executor_type != "agent" or not isinstance(acceptance, Mapping) or acceptance.get("status") != "PASS":
        return None
    document = {"candidate_id": f"candidate.{node.id}", "problem_pattern": node.goal, "inputs": list(node.inputs), "outputs": list(node.outputs), "procedure": list(result.get("procedure", [])), "constraints": list(result.get("constraints", [])), "evidence_refs": list(acceptance.get("evidence_refs", [])), "source_worknode_ids": [node.id], "experience_state": "candidate", "auto_promotion": False}
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{node.id.replace('.', '_')}.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def apply_iteration_review(backlog: list[dict[str, Any]], *, accepted_ids: Iterable[str], failed_ids: Iterable[str], change: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = json.loads(json.dumps(backlog))
    accepted = set(accepted_ids)
    failed = set(failed_ids)
    for item in backlog:
        if item.get("id") in accepted:
            item["state"] = "accepted"
        elif item.get("id") in failed:
            item["state"] = "replanned"
            if "executor" in change:
                item["executor"] = change["executor"]
            if "priority" in change:
                item["priority"] = change["priority"]
    return backlog, {"kind": "CGKNIterationReview", "before": before, "after": backlog, "state_changed": before != backlog, "retrospective": str(change.get("retrospective", "")), "release_authority": False}
