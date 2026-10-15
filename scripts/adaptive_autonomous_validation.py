#!/usr/bin/env python3
"""Adaptive, contract-bound autonomous validation research runner.

This is a thin integration layer over Autonomous Validation Pass 3.  It keeps
the existing adapters, isolation, deterministic oracles, and reproduction
mechanism, then adds strict operation schemas, loss-audited observation
compression, and an evidence-gated optional second model call.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterator

from jsonschema import Draft202012Validator


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import autonomous_validation_pass3 as p3
import role_driven_validation as v1


KIND = "CGKNAdaptiveAutonomousValidationReport"
SCHEMA_VERSION = "1.0"
STATUS = "NOT_EVALUATED"
GROUPS = ("A", "B", "C", "D")
INITIAL_DETERMINISTIC_BUDGET = 6
INITIAL_SEMANTIC_BUDGET = 6
ESCALATION_ACTION_BUDGET = 2
MODEL_TOKEN_BUDGET_PER_PROJECT = 20_000
DEFAULT_MODEL = p3.DEFAULT_MODEL


@dataclass(frozen=True)
class AdaptiveProject:
    spec: p3.ProjectSpec
    action_schemas: dict[str, dict[str, Any]]


def obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string", "maxLength": 2048}
SMALL_INT = {"type": "integer", "minimum": -10_000, "maximum": 10_000}


KNOWLEDGE_SCHEMAS = {
    "import_document": obj({"title": STRING, "content": STRING}, ("title", "content")),
    "search_documents": obj(
        {"query": STRING, "source": {"enum": ["storage", "all_import_results"]}}, ("query", "source")
    ),
    "create_task": obj({"title": STRING}, ("title",)),
    "build_report": obj(
        {
            "documents": {"enum": ["storage", "all_import_results"]},
            "tasks": {"enum": ["storage", "all_task_results"]},
        },
        ("documents", "tasks"),
    ),
    "adapter_status": obj({"config": {"type": "object", "additionalProperties": {"type": "string"}}}, ("config",)),
    "restart_runtime": obj({}),
    "inspect_state": obj({}),
}

ORBIT_SCHEMAS = {
    "plan": obj({"units": {"type": "integer", "minimum": 1, "maximum": 100}, "width": {"type": "integer", "minimum": 1, "maximum": 20}}, ("units", "width")),
    "run": obj({"workers": {"type": "integer", "minimum": 1, "maximum": 20}}, ("workers",)),
    "status": obj({}),
    "repair": obj({"target": {"type": "string", "pattern": "^unit_[0-9]{3}$"}, "delta": SMALL_INT}, ("target", "delta")),
    "read_unit": obj({"target": {"type": "string", "pattern": "^unit_[0-9]{3}$"}}, ("target",)),
    "repeat_run": obj({"workers": {"type": "integer", "minimum": 1, "maximum": 20}}, ("workers",)),
}

TASK_SPEC = p3.ProjectSpec(
    project_id="task_ledger",
    name="Task Ledger",
    source_kind="snapshot",
    source_path="artifacts/function_stress_pass/20261010-pass2/operational/managed/project-pass2-operational/current",
    generated_by_cgkn=True,
    goal_files=("README.md",),
    channels=("cli", "file_state"),
    public_goal="Add bounded task titles to a local JSON ledger, list the persisted tasks, and retain them across process restarts.",
    operation_contract={
        "list_tasks": {},
        "add_task": {"title": "string"},
        "restart_runtime": {},
        "inspect_data_file": {},
    },
)

TASK_SCHEMAS = {
    "list_tasks": obj({}),
    "add_task": obj({"title": {"type": "string", "maxLength": 200}}, ("title",)),
    "restart_runtime": obj({}),
    "inspect_data_file": obj({}),
}

PROJECTS = (
    AdaptiveProject(p3.PROJECTS[0], KNOWLEDGE_SCHEMAS),
    AdaptiveProject(p3.PROJECTS[1], ORBIT_SCHEMAS),
    AdaptiveProject(TASK_SPEC, TASK_SCHEMAS),
)


class AdaptiveValidationError(RuntimeError):
    pass


def action_contract_for_prompt(project: AdaptiveProject) -> dict[str, Any]:
    return {op: schema for op, schema in project.action_schemas.items()}


def validate_proposal(project: AdaptiveProject, proposal: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Fail closed: invalid operations are recorded but never rewritten or queued."""
    if not isinstance(proposal, dict):
        return None, {"reason": "proposal_not_object", "proposal": p3.safe_json(proposal)}
    op = str(proposal.get("op") or "").strip()
    if op not in project.action_schemas:
        return None, {"reason": "unsupported_operation", "op": op, "proposal": p3.safe_json(proposal)}
    args = proposal.get("args", {})
    errors = sorted(Draft202012Validator(project.action_schemas[op]).iter_errors(args), key=lambda item: list(item.path))
    if errors:
        return None, {
            "reason": "schema_invalid",
            "op": op,
            "schema_errors": [item.message for item in errors],
            "proposal": p3.safe_json(proposal),
        }
    action = {
        "op": op,
        "args": p3.safe_json(args),
        "hypothesis": str(proposal.get("hypothesis") or "")[:800],
        "business_value": str(proposal.get("business_value") or "")[:800],
        "adapts_from": [str(item)[:120] for item in (proposal.get("adapts_from") or []) if str(item).strip()][:5],
    }
    return action, None


def validate_model_document(project: AdaptiveProject, document: dict[str, Any], limit: int) -> dict[str, Any]:
    raw = document.get("actions")
    if not isinstance(raw, list):
        raise AdaptiveValidationError("model response must contain an actions array")
    actions: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for index, proposal in enumerate(raw):
        if len(actions) >= limit:
            break
        action, invalid = validate_proposal(project, proposal)
        if invalid:
            unsupported.append({"proposal_index": index, **invalid, "executed": False, "auto_mapped": False})
        elif action:
            actions.append(action)
    return {
        "analysis_summary": str(document.get("analysis_summary") or "")[:1600],
        "important_unverified_assumptions": [str(item)[:600] for item in (document.get("important_unverified_assumptions") or [])][:8],
        "subjective_concerns": [str(item)[:600] for item in (document.get("subjective_concerns") or [])][:8],
        "actions": actions,
        "unsupported_proposals": unsupported,
    }


def deterministic_plan(project_id: str) -> list[dict[str, Any]]:
    if project_id != "task_ledger":
        spec = next(item.spec for item in PROJECTS if item.spec.project_id == project_id)
        return p3.c_plan(spec)
    rows = [
        ("list_tasks", {}, "Establish the current persisted ledger."),
        ("add_task", {"title": "daily review"}, "Exercise the normal add path."),
        ("list_tasks", {}, "Verify the task is visible through the public CLI."),
        ("add_task", {"title": ""}, "Verify an empty title is rejected without mutation."),
        ("add_task", {"title": "x" * 25}, "Verify the documented implementation boundary is rejected without mutation."),
        ("restart_runtime", {}, "Verify persisted tasks survive a fresh process boundary."),
    ]
    return [
        {"op": op, "args": args, "hypothesis": hypothesis, "business_value": hypothesis, "adapts_from": []}
        for op, args, hypothesis in rows
    ]


class TaskLedgerAdapter:
    def __init__(self, project: pathlib.Path, run_dir: pathlib.Path) -> None:
        self.project = project
        self.run_dir = run_dir
        self.env = p3.safe_env(project)

    def _state(self) -> Any:
        path = self.project / "data.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def execute(self, action: dict[str, Any], index: int) -> dict[str, Any]:
        op, args = action["op"], action["args"]
        before = p3.safe_json(self._state())
        started = time.perf_counter()
        if op == "list_tasks":
            result = v1.run_process([sys.executable, "main.py", "list"], cwd=self.project, env=self.env, timeout=30)
        elif op == "add_task":
            result = v1.run_process([sys.executable, "main.py", "add", str(args["title"])], cwd=self.project, env=self.env, timeout=30)
        elif op == "restart_runtime":
            result = v1.run_process([sys.executable, "main.py", "list"], cwd=self.project, env=self.env, timeout=30)
        elif op == "inspect_data_file":
            result = {"returncode": 0, "stdout": json.dumps(self._state(), ensure_ascii=False), "stderr": "", "duration_seconds": 0.0}
        else:  # pragma: no cover - schema gate owns this boundary
            raise AdaptiveValidationError(f"unsupported task-ledger operation: {op}")
        after = p3.safe_json(self._state())
        parsed = None
        try:
            parsed = json.loads(str(result.get("stdout") or ""))
        except json.JSONDecodeError:
            parsed = None
        row = {
            "observation_id": f"obs-{index:02d}",
            "op": op,
            "args": p3.safe_json(args),
            "result": p3.safe_json(parsed),
            "before": before,
            "after": after,
            "returncode": int(result["returncode"]),
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
            "duration_seconds": round(time.perf_counter() - started, 6),
        }
        row["independent_issues"] = task_ledger_oracle(row)
        return row


def task_ledger_oracle(row: dict[str, Any]) -> list[dict[str, Any]]:
    op, args = row["op"], row["args"]
    before, after = row["before"], row["after"]
    issues: list[dict[str, Any]] = []
    valid_title = op == "add_task" and bool(str(args.get("title", "")).strip()) and len(str(args["title"]).strip()) <= 24
    if valid_title:
        expected = str(args["title"]).strip()
        if row["returncode"] != 0 or len(after) != len(before) + 1 or after[-1].get("title") != expected:
            issues.append(p3.issue("task_add_not_persisted", "A valid task was not appended to the persisted ledger.", row))
    elif op == "add_task":
        if row["returncode"] == 0 or after != before:
            issues.append(p3.issue("invalid_task_mutated_ledger", "An invalid task title was accepted or changed persisted state.", row))
    elif op in {"list_tasks", "restart_runtime", "inspect_data_file"}:
        if row["returncode"] != 0 or row.get("result") != after:
            issues.append(p3.issue("ledger_output_state_mismatch", "The public output does not match the persisted task ledger.", row))
    return issues


def make_adapter(project: AdaptiveProject, path: pathlib.Path, run_dir: pathlib.Path) -> Any:
    if project.spec.project_id == "knowledge_studio":
        return p3.KnowledgeAdapter(path)
    if project.spec.project_id == "orbit360":
        return p3.OrbitAdapter(path, run_dir, p3.safe_env(path))
    return TaskLedgerAdapter(path, run_dir)


@contextlib.contextmanager
def isolated_project(project: AdaptiveProject, repo: pathlib.Path, commit: str, run_dir: pathlib.Path, label: str) -> Iterator[tuple[pathlib.Path, dict[str, Any], str]]:
    spec = project.spec
    if spec.source_kind == "git":
        identity = {
            "repository_root": str(repo),
            "project_relative_path": spec.source_path,
            "commit_sha": commit,
            "project_public_tree_sha256": "adaptive-bound",
            "target_path_clean": True,
        }
        with v1.isolated_worktree(identity, label) as (path, isolation):
            yield pathlib.Path(path), isolation, p3.tree_hash(pathlib.Path(path))
        return
    source = repo / spec.source_path
    target = run_dir / "project-copy"
    path = p3.prepare_snapshot(source, target)
    yield path, {
        "kind": "immutable_snapshot_copy",
        "source": str(source),
        "workspace": str(path),
        "source_modified": False,
        "production_data_modified": False,
    }, p3.tree_hash(source)


def execute_actions(adapter: Any, actions: list[dict[str, Any]], start: int = 1) -> list[dict[str, Any]]:
    rows = []
    for index, action in enumerate(actions, start=start):
        row = adapter.execute(action, index)
        row.update({key: action.get(key, [] if key == "adapts_from" else "") for key in ("hypothesis", "business_value", "adapts_from")})
        rows.append(row)
    return rows


def compact_value(value: Any, limit: int = 1200) -> Any:
    encoded = json.dumps(p3.safe_json(value), ensure_ascii=False, sort_keys=True)
    if len(encoded) <= limit:
        return p3.safe_json(value)
    if isinstance(value, list):
        return {"summary": "large_list", "count": len(value), "sha256": p3.canonical_hash(value), "head": p3.safe_json(value[:2]), "tail": p3.safe_json(value[-2:])}
    if isinstance(value, dict):
        return {"summary": "large_object", "keys": sorted(value)[:30], "sha256": p3.canonical_hash(value)}
    return {"summary": "large_value", "sha256": p3.sha_text(str(value)), "prefix": str(value)[:500]}


def compress_observation(row: dict[str, Any], raw_ref: str) -> dict[str, Any]:
    before = row.get("before", row.get("before_unit", row.get("before_files")))
    after = row.get("after", row.get("after_unit", row.get("after_files")))
    state_change = {
        "changed": p3.canonical_hash(before) != p3.canonical_hash(after),
        "before_sha256": p3.canonical_hash(before),
        "after_sha256": p3.canonical_hash(after),
        "before": compact_value(before, 600),
        "after": compact_value(after, 600),
    }
    errors = [str(row.get("stderr") or "")] if row.get("stderr") else []
    issues = p3.safe_json(row.get("independent_issues", []))
    return {
        "operation_id": row["observation_id"],
        "operation": row["op"],
        "execution_result": {"returncode": row["returncode"], "result": compact_value(row.get("result"))},
        "important_state_changes": state_change,
        "errors": errors,
        "artifact_refs": [raw_ref],
        "evidence_refs": [raw_ref] + [f"{raw_ref}#independent_issues/{index}" for index, _ in enumerate(issues)],
        "independent_issues": issues,
    }


def compression_audit(raw: list[dict[str, Any]], compressed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {item["operation_id"]: item for item in compressed}
    missing: list[str] = []
    for row in raw:
        item = by_id.get(row["observation_id"])
        if not item:
            missing.append(f"{row['observation_id']}: observation")
            continue
        if row.get("stderr") and str(row["stderr"]) not in item["errors"]:
            missing.append(f"{row['observation_id']}: error")
        raw_types = {issue["issue_type"] for issue in row.get("independent_issues", [])}
        compressed_types = {issue["issue_type"] for issue in item.get("independent_issues", [])}
        if not raw_types.issubset(compressed_types):
            missing.append(f"{row['observation_id']}: independent_issue")
        if int(row["returncode"]) != int(item["execution_result"]["returncode"]):
            missing.append(f"{row['observation_id']}: returncode")
    return {"status": "PASS" if not missing else "FAIL", "important_failure_evidence_lost": bool(missing), "missing": missing, "raw_observations": len(raw), "compressed_observations": len(compressed)}


def semantic_prompt(project: AdaptiveProject, context: dict[str, Any], group: str, round_index: int, requested: int, feedback: list[dict[str, Any]], unsupported: list[dict[str, Any]]) -> str:
    mode = "one-shot semantic exploration" if round_index == 1 else "conditional follow-up for the explicit evidence gap"
    return "\n".join(
        [
            "Design black-box acceptance operations for a real executable project.",
            f"MODE={mode}. Return JSON only: analysis_summary, important_unverified_assumptions, actions, subjective_concerns.",
            "Use only an operation name and argument object accepted by OPERATION_JSON_SCHEMAS. Never invent or rename an operation.",
            "Do not declare a defect or success. Do not use tests, hidden answers, prior reports, or evaluator oracles.",
            f"Return at most {requested} actions; each has op, args, hypothesis, business_value, adapts_from.",
            "For follow-up actions, adapts_from must cite relevant operation_id values from COMPRESSED_OBSERVATIONS.",
            f"PUBLIC_CONTEXT={json.dumps(context, ensure_ascii=False)}",
            f"OPERATION_JSON_SCHEMAS={json.dumps(action_contract_for_prompt(project), ensure_ascii=False)}",
            f"COMPRESSED_OBSERVATIONS={json.dumps(feedback, ensure_ascii=False)}",
            f"UNSUPPORTED_PRIOR_PROPOSALS={json.dumps(unsupported, ensure_ascii=False)}",
            f"GROUP={group}; ROUND={round_index}",
        ]
    )


def conservative_call_token_ceiling(prompt: str) -> int:
    """Bound a call before dispatch without depending on a provider tokenizer.

    Two UTF-8 bytes per input token is deliberately conservative for the
    English/JSON prompts in this study; the Provider output is capped at 1800.
    The observed receipt is still checked after the call.
    """
    return (len(prompt.encode("utf-8")) + 1) // 2 + 1800


def escalation_gate(observations: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if any(row.get("independent_issues") for row in observations):
        reasons.append("result_conflicts_with_goal")
    unexplained = [row["observation_id"] for row in observations if row["returncode"] != 0 and not row.get("independent_issues") and row["op"] not in {"add_task"}]
    if unexplained:
        reasons.append("unexplained_anomaly")
    if plan["unsupported_proposals"] and not plan["actions"]:
        reasons.append("important_uncovered_assumption")
    return {
        "allowed": bool(reasons),
        "reasons": reasons,
        "unexplained_observation_ids": unexplained,
        "normal_evidence_sufficient": not reasons,
    }


def run_project(group: str, project: AdaptiveProject, *, repo: pathlib.Path, commit: str, output: pathlib.Path, context: dict[str, Any], client: p3.ModelClient) -> dict[str, Any]:
    spec = project.spec
    run_dir = output / group / spec.project_id / "discovery"
    run_dir.mkdir(parents=True, exist_ok=True)
    deterministic = deterministic_plan(spec.project_id) if group in {"A", "C", "D"} else []
    plans: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    calls_before = len(client.calls)
    if group in {"B", "C", "D"}:
        response = client.call(semantic_prompt(project, context, group, 1, INITIAL_SEMANTIC_BUDGET, [], []), project_id=spec.project_id, group=group, round_index=1)
        plan = validate_model_document(project, response["document"], INITIAL_SEMANTIC_BUDGET)
        plan["round"] = 1
        plan["model_receipt"] = response["receipt"]
        plans.append(plan)
        semantic = plan["actions"]
        unsupported.extend(plan["unsupported_proposals"])
    initial_actions = deterministic + semantic
    with isolated_project(project, repo, commit, run_dir / "initial", f"adaptive-{group.lower()}-{spec.project_id}") as (path, isolation, source_hash):
        adapter = make_adapter(project, path, run_dir / "initial")
        initial_rows = execute_actions(adapter, initial_actions)
    v1.write_json(run_dir / "raw_execution_initial.json", {"actions": initial_actions, "observations": initial_rows})
    compressed = [compress_observation(row, str(run_dir / "raw_execution_initial.json")) for row in initial_rows]
    audit = compression_audit(initial_rows, compressed)
    gate = escalation_gate(initial_rows, plans[0] if plans else {"actions": [], "unsupported_proposals": []}) if group == "D" else {"allowed": False, "reasons": [], "normal_evidence_sufficient": True}
    escalation_actions: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []
    if group == "D" and gate["allowed"]:
        used_tokens = sum(call["total_tokens"] for call in client.calls[calls_before:] if call["project_id"] == spec.project_id)
        follow_up_prompt = semantic_prompt(project, context, group, 2, ESCALATION_ACTION_BUDGET, compressed, unsupported)
        projected_ceiling = used_tokens + conservative_call_token_ceiling(follow_up_prompt)
        gate["token_budget"] = MODEL_TOKEN_BUDGET_PER_PROJECT
        gate["tokens_used_before_follow_up"] = used_tokens
        gate["projected_token_ceiling"] = projected_ceiling
        if projected_ceiling <= MODEL_TOKEN_BUDGET_PER_PROJECT:
            response = client.call(follow_up_prompt, project_id=spec.project_id, group=group, round_index=2)
            observed_tokens = sum(call["total_tokens"] for call in client.calls[calls_before:] if call["project_id"] == spec.project_id)
            if observed_tokens > MODEL_TOKEN_BUDGET_PER_PROJECT:
                raise AdaptiveValidationError(f"model token budget exceeded for {spec.project_id}: {observed_tokens}")
            plan = validate_model_document(project, response["document"], ESCALATION_ACTION_BUDGET)
            plan["round"] = 2
            plan["model_receipt"] = response["receipt"]
            plans.append(plan)
            escalation_actions = plan["actions"]
            unsupported.extend(plan["unsupported_proposals"])
        else:
            gate["budget_blocked"] = "token_budget"
    final_actions = initial_actions + escalation_actions
    final_rows = initial_rows
    final_isolation = isolation
    if escalation_actions:
        replay_dir = run_dir / "escalated"
        with isolated_project(project, repo, commit, replay_dir, f"adaptive-{group.lower()}-escalated-{spec.project_id}") as (path, final_isolation, replay_hash):
            if replay_hash != source_hash:
                raise AdaptiveValidationError(f"source identity changed during escalation replay: {spec.project_id}")
            adapter = make_adapter(project, path, replay_dir)
            replay_rows = execute_actions(adapter, final_actions)
            final_rows = replay_rows
        v1.write_json(run_dir / "raw_execution_escalated.json", {"actions": final_actions, "observations": replay_rows})
        compressed = [compress_observation(row, str(run_dir / "raw_execution_escalated.json")) for row in replay_rows]
        audit = compression_audit(replay_rows, compressed)
    execution = {
        "project_id": spec.project_id,
        "group": group,
        "source_hash": source_hash,
        "public_context_sha256": p3.canonical_hash(context),
        "isolation": final_isolation,
        "actions": final_actions,
        "observations": final_rows,
        "initial_observations": initial_rows,
        "plans": plans,
        "unsupported_proposals": unsupported,
        "invalid_proposal_count": len(unsupported),
        "invalid_execution_count": 0,
        "auto_mapped_proposal_count": 0,
        "valid_proposals_after_correction": len(escalation_actions),
        "escalation_gate": gate,
        "escalated": bool(escalation_actions),
        "discovery_actions": len(final_actions),
        "execution_actions_including_escalation_replay": len(initial_rows) + len(replay_rows),
        "replay_overhead_actions": len(replay_rows) if replay_rows else 0,
        "compressed_observations": compressed,
        "compression_audit": audit,
        "formal_evidence_status": STATUS,
    }
    v1.write_json(run_dir / "execution.json", execution)
    return execution


def reproduce_finding(group: str, project: AdaptiveProject, finding: dict[str, Any], execution: dict[str, Any], *, repo: pathlib.Path, commit: str, output: pathlib.Path) -> None:
    actions = execution["actions"][: finding["action_index"] + 1]
    run_dir = output / group / project.spec.project_id / "reproduction" / finding["finding_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    with isolated_project(project, repo, commit, run_dir, f"adaptive-repro-{group.lower()}-{project.spec.project_id}-{finding['finding_id'][-6:].lower()}") as (path, isolation, source_hash):
        adapter = make_adapter(project, path, run_dir)
        rows = execute_actions(adapter, actions)
    reproduced = any(issue.get("issue_type") == finding["issue_type"] for row in rows for issue in row.get("independent_issues", []))
    finding.update({"independently_confirmed": reproduced, "false_positive": not reproduced, "reproduction_ref": str(run_dir / "execution.json"), "reproduction_source_hash": source_hash, "reproduction_actions": len(actions)})
    v1.write_json(run_dir / "execution.json", {"source_hash": source_hash, "isolation": isolation, "actions": actions, "observations": rows})


def metrics(group: str, executions: list[dict[str, Any]], findings: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [call for call in calls if call["group"] == group]
    valid = [item for item in findings if item["independently_confirmed"]]
    candidate_count = len(findings)
    cost_values = [call["estimated_cost_usd"] for call in selected if call["estimated_cost_usd"] is not None]
    escalated = [item for item in executions if item["escalated"]]
    added_by_escalation = {
        issue["issue_type"]
        for item in escalated
        for row in item["observations"][len(item["initial_observations"]):]
        for issue in row.get("independent_issues", [])
    }
    initial_issue_types = {
        issue["issue_type"] for item in escalated for row in item["initial_observations"] for issue in row.get("independent_issues", [])
    }
    novel_escalation = sorted(added_by_escalation - initial_issue_types)
    operation_seconds = round(sum(float(row.get("duration_seconds") or 0) for item in executions for row in item["initial_observations"] + ([] if not item["replay_overhead_actions"] else item["observations"])), 6)
    return {
        "group": group,
        "findings": findings,
        "candidate_findings": candidate_count,
        "valid_findings": len(valid),
        "unique_finding_keys": [],
        "issue_types": sorted({item["issue_type"] for item in valid}),
        "false_positive_rate": round((candidate_count - len(valid)) / candidate_count, 6) if candidate_count else 0.0,
        "reproduction_success_rate": round(len(valid) / candidate_count, 6) if candidate_count else None,
        "discovery_actions": sum(item["discovery_actions"] for item in executions),
        "actual_execution_actions": sum(item["execution_actions_including_escalation_replay"] for item in executions),
        "replay_overhead_actions": sum(item["replay_overhead_actions"] for item in executions),
        "model_calls": len(selected),
        "input_tokens": sum(item["input_tokens"] for item in selected),
        "output_tokens": sum(item["output_tokens"] for item in selected),
        "total_tokens": sum(item["total_tokens"] for item in selected),
        "estimated_cost_usd": round(sum(cost_values), 8) if len(cost_values) == len(selected) else None,
        "execution_wall_time_seconds": operation_seconds,
        "model_wall_time_seconds": round(sum(item["duration_seconds"] for item in selected), 6),
        "invalid_proposals": sum(item["invalid_proposal_count"] for item in executions),
        "invalid_executions": sum(item["invalid_execution_count"] for item in executions),
        "escalations": len(escalated),
        "unnecessary_escalations": sum(1 for item in escalated if not item["escalation_gate"]["reasons"]),
        "unnecessary_escalation_ratio": round(sum(1 for item in escalated if not item["escalation_gate"]["reasons"]) / len(escalated), 6) if escalated else 0.0,
        "nonproductive_escalations": len(escalated) if not novel_escalation else 0,
        "nonproductive_escalation_ratio": 1.0 if escalated and not novel_escalation else 0.0,
        "escalation_only_issue_types": novel_escalation,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# CGKN Adaptive Autonomous Validation — Auditable Comparison",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Model: `{report['model']['name']}`",
        f"- Formal evidence: `{STATUS}` (research support only)",
        f"- Contract audit: `{report['acceptance_audit']['operation_contract']['status']}`",
        f"- Compression audit: `{report['acceptance_audit']['compression']['status']}`",
        "",
        "## A/B/C/D results",
        "",
        "| Group | Strategy | Valid | Unique | False positive | Reproduction | Discovery / actual ops | Calls | Tokens | Cost USD | Time sec | Invalid executed | Escalations |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    names = {"A": "deterministic", "B": "one-shot semantic", "C": "combined", "D": "combined + conditional escalation"}
    for group in GROUPS:
        row = report["group_results"][group]
        reproduction = "N/A" if row["reproduction_success_rate"] is None else f"{row['reproduction_success_rate']:.0%}"
        cost = "N/A" if row["estimated_cost_usd"] is None else f"{row['estimated_cost_usd']:.8f}"
        lines.append(f"| {group} | {names[group]} | {row['valid_findings']} | {len(row['unique_finding_keys'])} | {row['false_positive_rate']:.0%} | {reproduction} | {row['discovery_actions']} / {row['actual_execution_actions']} | {row['model_calls']} | {row['total_tokens']} | {cost} | {row['execution_wall_time_seconds'] + row['model_wall_time_seconds']:.3f} | {row['invalid_executions']} | {row['escalations']} |")
    lines.extend(["", "## Reproduced findings", ""])
    for group in GROUPS:
        for item in report["group_results"][group]["findings"]:
            lines.append(f"- **{group} / {item['finding_key']}** — {item['summary']} Reproduction: `{item['reproduction_ref']}`")
    lines.extend(["", "## Decision", "", report["recommendation"], "", "The study does not change formal acceptance, packaging, delivery, or release status."])
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = pathlib.Path(args.repo).resolve()
    output = pathlib.Path(args.out).resolve()
    if (output / "validation_report.json").exists():
        raise AdaptiveValidationError("output already contains a completed report")
    output.mkdir(parents=True, exist_ok=True)
    commit = v1.git(repo, "rev-parse", "HEAD").stdout.strip()
    contexts = {item.spec.project_id: p3.public_context(repo, item.spec) for item in PROJECTS}
    source_identities = {item.spec.project_id: {"source_kind": item.spec.source_kind, "source_path": item.spec.source_path, "source_hash": p3.tree_hash(repo / item.spec.source_path), "generated_by_cgkn": item.spec.generated_by_cgkn, "prior_pass3_project": item.spec.project_id != "task_ledger"} for item in PROJECTS}
    plan = {
        "kind": "CGKNAdaptiveAutonomousValidationPlan",
        "schema_version": SCHEMA_VERSION,
        "created_at": p3.now(),
        "base_commit": commit,
        "groups": {"A": "deterministic boundary", "B": "one-shot semantic", "C": "combined", "D": "combined plus evidence-gated follow-up"},
        "budgets_per_project": {"A": {"actions": 6, "model_calls": 0}, "B": {"actions": 6, "model_calls": 1}, "C": {"actions": 12, "model_calls": 1}, "D": {"initial_actions": 12, "maximum_follow_up_actions": 2, "maximum_model_calls": 2, "maximum_tokens": MODEL_TOKEN_BUDGET_PER_PROJECT}},
        "budget_inequality_notice": "Coverage and action budgets intentionally differ by strategy. Findings are reported as observed results, not causal superiority from equal budgets.",
        "projects": [{**contexts[item.spec.project_id], "materials": [{"path": material["path"], "sha256": material["sha256"]} for material in contexts[item.spec.project_id]["materials"]], "operation_json_schemas": action_contract_for_prompt(item)} for item in PROJECTS],
        "hidden_answers_included": False,
        "formal_evidence_status": STATUS,
    }
    v1.write_json(output / "scenario_plan.json", plan)
    client = p3.ModelClient(model=args.model, timeout=args.model_timeout, input_price_per_million=args.input_price_per_million, output_price_per_million=args.output_price_per_million)
    executions: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
    for group in GROUPS:
        for item in PROJECTS:
            executions[group].append(run_project(group, item, repo=repo, commit=commit, output=output, context=contexts[item.spec.project_id], client=client))
    findings: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
    for group in GROUPS:
        for execution in executions[group]:
            project = next(item for item in PROJECTS if item.spec.project_id == execution["project_id"])
            for finding in p3.collect_findings(execution):
                reproduce_finding(group, project, finding, execution, repo=repo, commit=commit, output=output)
                findings[group].append(finding)
    results = {group: metrics(group, executions[group], findings[group], client.calls) for group in GROUPS}
    keys = {group: {item["finding_key"] for item in findings[group] if item["independently_confirmed"]} for group in GROUPS}
    for group in GROUPS:
        results[group]["unique_finding_keys"] = sorted(keys[group] - set().union(*(keys[other] for other in GROUPS if other != group)))
    combined_preserves = keys["A"].union(keys["B"]).issubset(keys["C"].union(keys["D"]))
    strategy_contributions = {
        "deterministic_only_vs_one_shot_semantic": sorted(keys["A"] - keys["B"]),
        "one_shot_semantic_only_vs_deterministic": sorted(keys["B"] - keys["A"]),
        "combined_observed_union": sorted(keys["C"].union(keys["D"])),
        "conditional_escalation_only": sorted(
            finding_key
            for finding_key in keys["D"] - keys["C"]
            if finding_key.split(":", 1)[-1] in results["D"]["escalation_only_issue_types"]
        ),
    }
    compression_failures = [f"{item['group']}:{item['project_id']}" for group in GROUPS for item in executions[group] if item["compression_audit"]["status"] != "PASS"]
    invalid_executions = sum(results[group]["invalid_executions"] for group in GROUPS)
    reproduced_all = all(item["independently_confirmed"] for group in GROUPS for item in findings[group])
    new_project_ran = all(any(item["project_id"] == "task_ledger" and item["observations"] for item in executions[group]) for group in GROUPS)
    escalation_added = bool(results["D"]["escalation_only_issue_types"])
    recommendation = (
        "Keep deterministic plus one-shot semantic validation as the default. Conditional escalation added independently reproduced findings and may remain opt-in behind the evidence gate."
        if escalation_added
        else "Keep deterministic plus one-shot semantic validation as the default and disable conditional escalation by default: this run found no additional independently reproduced defect from the follow-up calls."
    )
    report = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": output.name,
        "created_at": p3.now(),
        "formal_evidence_status": STATUS,
        "release_authority": False,
        "base_commit": commit,
        "source_identities": source_identities,
        "scenario_plan_ref": str(output / "scenario_plan.json"),
        "model": {"name": args.model, "model_neutral_openai_compatible_client": True, "local_model_compatible": True, "pricing": {"input_usd_per_million_tokens": args.input_price_per_million, "output_usd_per_million_tokens": args.output_price_per_million, "source": args.pricing_source, "estimate_only": True}},
        "budget_comparison": plan["budgets_per_project"],
        "budget_inequality_notice": plan["budget_inequality_notice"],
        "group_results": results,
        "strategy_contributions": strategy_contributions,
        "acceptance_audit": {
            "combined_preserves_unique_findings": {"status": "PASS" if combined_preserves else "FAIL", "a_union_b": sorted(keys["A"].union(keys["B"])), "c_union_d": sorted(keys["C"].union(keys["D"]))},
            "operation_contract": {"status": "PASS" if invalid_executions == 0 else "FAIL", "invalid_proposals": sum(results[group]["invalid_proposals"] for group in GROUPS), "invalid_executions": invalid_executions, "auto_mapped_proposals": sum(item["auto_mapped_proposal_count"] for group in GROUPS for item in executions[group])},
            "normal_case_no_unnecessary_escalation": {"status": "PASS" if next(item for item in executions["D"] if item["project_id"] == "task_ledger")["escalation_gate"]["normal_evidence_sufficient"] and not next(item for item in executions["D"] if item["project_id"] == "task_ledger")["escalated"] else "FAIL", "project": "task_ledger"},
            "independent_reproduction": {"status": "PASS" if reproduced_all else "FAIL", "all_findings_reproduced": reproduced_all},
            "compression": {"status": "PASS" if not compression_failures else "FAIL", "important_failure_evidence_lost": bool(compression_failures), "failures": compression_failures},
            "new_project": {"status": "PASS" if new_project_ran else "FAIL", "project": "task_ledger", "participated_in_prior_passes": False},
        },
        "conditional_escalation_default_enabled": escalation_added,
        "recommendation": recommendation,
        "model_call_receipts": client.calls,
        "known_limits": [
            "Three projects and one model do not establish broad generalization.",
            "The generated projects are historical snapshots and this support study cannot grant formal evidence.",
            "Action budgets differ by strategy, so added coverage is not interpreted as causal strategy superiority.",
            "No browser or HTTP primary path was exercised; visual interaction and rendering defects remain outside this adapter set.",
            "Cost is estimated from provider-reported tokens and supplied public rates, not an invoice.",
        ],
    }
    report["report_sha256"] = p3.canonical_hash(report)
    v1.write_json(output / "validation_report.json", report)
    (output / "validation_report.md").write_text(markdown(report), encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run adaptive CGKN autonomous validation integration study.")
    value.add_argument("--repo", default=".")
    value.add_argument("--out", required=True)
    value.add_argument("--model", default=DEFAULT_MODEL)
    value.add_argument("--model-timeout", type=int, default=90)
    value.add_argument("--input-price-per-million", type=float)
    value.add_argument("--output-price-per-million", type=float)
    value.add_argument("--pricing-source", default="not supplied")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        report = run(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "report": str(pathlib.Path(args.out).resolve() / "validation_report.json"), "valid_findings": {group: report["group_results"][group]["valid_findings"] for group in GROUPS}, "conditional_escalation_default_enabled": report["conditional_escalation_default_enabled"], "formal_evidence_status": STATUS}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
