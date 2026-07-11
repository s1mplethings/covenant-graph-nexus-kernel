from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_branch_replanner import replan_branch
from scripts.agent_leaf_failure_classifier import classify_leaf_failure
from scripts.agent_leaf_provider_guard import provider_readiness
from scripts.agent_pruning_policy import decide_pruning
from scripts.agent_pruning_protocol import record_pruning_event
from scripts.agent_real_provider_leaf_builder import run_real_provider_leaf
from scripts.agent_scope_contract import load_scope_contract, save_scope_contract
from scripts.agent_tree_contracts import append_jsonl, read_json, write_json
from scripts.agent_tree_registry import add_agent, agent_by_id, mark_agent_pruned, save_registry
from scripts.agent_upward_pruning_router import route_pruning_event
from scripts.run_full_dynamic_real_project_eval import FRONTEND_TEST_TERMS, FRONTEND_SPECS


def _copy_contract(source_run: pathlib.Path, leaf_out: pathlib.Path, leaf: str, *, replacement: str | None = None) -> dict[str, Any]:
    contract = read_json(source_run / "scope_contracts" / f"{leaf}.json", {})
    if replacement:
        contract["agent_id"] = replacement
    save_scope_contract(contract, leaf_out)
    return contract


def _static_missing(project: pathlib.Path, leaf: str) -> list[str]:
    if leaf not in FRONTEND_TEST_TERMS:
        return []
    rel = FRONTEND_SPECS[leaf][2][0]
    text = (project / rel).read_text(encoding="utf-8", errors="replace") if (project / rel).exists() else ""
    missing = [
        "/".join(group)
        for group in FRONTEND_TEST_TERMS[leaf]
        if not any(term.lower() in text.lower() for term in group)
    ]
    lowered = text.lower()
    for marker in ("<!doctype", "<html", "<body", "</body>", "</html>"):
        if marker not in lowered:
            missing.append(f"html_structure:{marker}")
    return missing


def _execute(
    *,
    leaf: str,
    contract_leaf: str,
    source_run: pathlib.Path,
    out: pathlib.Path,
    project: pathlib.Path,
    goal: str,
    model: str,
    readiness: dict[str, Any],
    provider_output_override: str | None,
    run_leaf_tests: bool,
) -> dict[str, Any]:
    leaf_out = out / "leaves" / leaf
    contract = _copy_contract(source_run, leaf_out, contract_leaf, replacement=leaf if leaf != contract_leaf else None)
    result = run_real_provider_leaf(
        agent_id=leaf,
        out_dir=leaf_out,
        project_dir=project,
        user_goal=goal,
        model=model,
        readiness=readiness,
        provider_output_override=provider_output_override,
        max_repair_attempts=1,
        run_leaf_tests=run_leaf_tests,
    )
    expected = list(contract.get("allowed_files", []))
    missing = [rel for rel in expected if not (project / rel).is_file()]
    blocked = list(result.get("forbidden_write_attempts", []))
    static_missing = _static_missing(project, contract_leaf)
    passed = result.get("classification") == "real_provider_leaf_pass" and not missing and not blocked and not static_missing
    checkpoint = {
        "leaf": leaf,
        "replaces": contract_leaf if leaf != contract_leaf else None,
        "provider_mode": "real_provider",
        "expected_files": expected,
        "present_files": [rel for rel in expected if (project / rel).is_file()],
        "missing_files": missing,
        "blocked_files": blocked,
        "static_missing_terms": static_missing,
        "classification": result.get("classification"),
        "failure_type": result.get("failure_type", ""),
        "public_safe_error": result.get("public_safe_error", ""),
        "verdict": "PASS" if passed else ("BLOCKED" if result.get("classification") == "provider_unavailable" else "FAIL"),
        "can_merge": passed,
    }
    write_json(out / "checkpoints" / f"{leaf}.json", checkpoint)
    return checkpoint


def run_leaf_resume(
    *,
    resume_plan: str | pathlib.Path | dict[str, Any],
    out_dir: str | pathlib.Path,
    project_dir: str | pathlib.Path | None = None,
    goal: str = "Build a local AI knowledge studio for documents, search, tasks, reports, and local model settings.",
    model: str = "gpt-5.4-nano",
    readiness_override: dict[str, Any] | None = None,
    provider_output_overrides: dict[str, str] | None = None,
    run_deferred_tests: bool = False,
    retry_replacement_leaves: list[str] | None = None,
) -> dict[str, Any]:
    plan = resume_plan if isinstance(resume_plan, dict) else read_json(resume_plan, {})
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "checkpoints").mkdir(parents=True, exist_ok=True)
    (out / "leaves").mkdir(parents=True, exist_ok=True)
    source_run = pathlib.Path(plan["source_run_dir"])
    project = pathlib.Path(project_dir) if project_dir else out / "generated_project"
    if not project.exists():
        shutil.copytree(source_run / "generated_project", project)
    registry = read_json(
        out / "agent_tree_registry_after.json",
        read_json(source_run / "agent_tree_registry.json", read_json(source_run / "registry.json", {})),
    )
    replacement_retries = list(dict.fromkeys(retry_replacement_leaves or []))
    has_work = any(plan.get(key) for key in ("resume_leaf", "repair_leaf", "prune_candidates")) or bool(replacement_retries)
    if isinstance(readiness_override, dict):
        readiness = readiness_override
    elif not has_work and (out / "leaf_resume_result.json").exists():
        readiness = {"provider_ready": bool(read_json(out / "leaf_resume_result.json", {}).get("provider_ready"))}
    else:
        readiness = provider_readiness(out_dir=out / "provider_readiness", model=model)
    overrides = provider_output_overrides or {}

    existing_result = read_json(out / "leaf_resume_result.json", {})
    reused = list(existing_result.get("reused", []))
    reused_ids = {item.get("leaf_id") for item in reused}
    for leaf in plan.get("reuse_leaf", []):
        if leaf in reused_ids:
            continue
        source_checkpoint = source_run / "checkpoints" / f"{leaf}.json"
        checkpoint = read_json(source_checkpoint, {})
        shutil.copy2(source_checkpoint, out / "checkpoints" / source_checkpoint.name)
        reused.append({"leaf_id": leaf, "source_checkpoint": str(source_checkpoint), "verdict": checkpoint.get("verdict"), "provider_called": False})
    write_json(out / "reused_leaf_manifest.json", {"reused_leaves": reused, "provider_calls": 0})

    resumed: list[dict[str, Any]] = list(existing_result.get("resumed", []))
    repaired: list[dict[str, Any]] = list(existing_result.get("repaired", []))
    replacements: list[dict[str, Any]] = list(existing_result.get("replacements", []))
    for replacement_row in replacements:
        original_id = str(replacement_row.get("replaces", ""))
        replacement_id = str(replacement_row.get("leaf_id", ""))
        original = agent_by_id(registry, original_id)
        if not original or not replacement_id:
            continue
        if not agent_by_id(registry, replacement_id):
            add_agent(
                registry,
                {
                    "action_id": "RESUME-RESTORE",
                    "parent_agent": original["parent_id"],
                    "new_agent_id": replacement_id,
                    "role": original.get("role", "ReplacementLeafAgent"),
                    "depth": original.get("depth", 2),
                    "scope": list(original.get("scope", [])),
                    "replaces": original_id,
                },
            )
        if original.get("status") != "pruned":
            mark_agent_pruned(
                registry,
                original_id,
                pruning_event_id="PERSISTED-RESUME",
                replacement=replacement_id,
            )
    blocked = False
    test_leaves = {"smoke_test_leaf", "backend_tests_leaf", "ui_route_tests_leaf"}

    def replace_result(rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
        rows[:] = [item for item in rows if item.get("leaf_id") != row.get("leaf_id")]
        rows.append(row)

    def archive_evidence(leaf: str, label: str) -> None:
        source = out / "leaves" / leaf
        target = out / "leaves" / f"{leaf}_{label}"
        if source.exists() and not target.exists():
            shutil.copytree(source, target)

    def prune(
        leaf: str,
        checkpoint: dict[str, Any],
        *,
        failure_payload: dict[str, Any],
        action: str,
        replacement: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        classification = classify_leaf_failure({"leaf_id": leaf, "checkpoint": checkpoint, **failure_payload})
        append_jsonl(out / "failure_classifications.jsonl", classification)
        parent = str(agent_by_id(registry, leaf).get("parent_id"))
        policy = decide_pruning(classification, parent_agent=parent, consecutive_provider_failures=failure_payload.get("repair_attempts"))
        event = record_pruning_event(
            out_dir=out,
            leaf_id=leaf,
            parent_agent=parent,
            classification=classification,
            policy=policy,
            evidence_refs=[f"checkpoints/{leaf}.json", f"leaves/{leaf}/checkpoint_{leaf}.json"],
        )
        signal = route_pruning_event(out_dir=out, event=event, requested_parent_action=policy["next_action"])
        replan = replan_branch(
            out_dir=out,
            registry=registry,
            signal=signal,
            action=action,
            new_leaf_id=replacement,
            scope=list(load_scope_contract(source_run, leaf).get("allowed_files", [])),
            reason=policy["reason"],
        )
        return policy, replan

    for replacement in replacement_retries:
        replacement_row = next((item for item in replacements if item.get("leaf_id") == replacement), None)
        if not replacement_row:
            raise ValueError(f"replacement leaf is not present in persisted resume state: {replacement}")
        original = str(replacement_row.get("replaces", "")).strip()
        if not original:
            raise ValueError(f"replacement leaf has no replaces relationship: {replacement}")
        archive_evidence(replacement, "previous_attempt")
        replacement_result = _execute(
            leaf=replacement,
            contract_leaf=original,
            source_run=source_run,
            out=out,
            project=project,
            goal=goal,
            model=model,
            readiness=readiness,
            provider_output_override=overrides.get(replacement),
            run_leaf_tests=original not in test_leaves or run_deferred_tests,
        )
        replace_result(
            replacements,
            {
                **replacement_row,
                "result": replacement_result["verdict"],
                "classification": replacement_result["classification"],
                "failure_type": replacement_result.get("failure_type", ""),
                "scope_contract": list(load_scope_contract(out / "leaves" / replacement, replacement).get("allowed_files", [])),
            },
        )
        if replacement_result["classification"] == "provider_unavailable":
            blocked = True

    for leaf in plan.get("resume_leaf", []):
        result = _execute(
            leaf=leaf,
            contract_leaf=leaf,
            source_run=source_run,
            out=out,
            project=project,
            goal=goal,
            model=model,
            readiness=readiness,
            provider_output_override=overrides.get(leaf),
            run_leaf_tests=leaf not in test_leaves or run_deferred_tests,
        )
        resume_row = {"leaf_id": leaf, "previous_state": "provider_unavailable", "action": "resume_real_provider", "result": result["verdict"], "classification": result["classification"]}
        replace_result(resumed, resume_row)
        if result["classification"] == "provider_unavailable":
            blocked = True
            prune(
                leaf,
                result,
                failure_payload={"provider_status": {"provider_ready": False, "classification": "provider_unavailable", "failure_type": result.get("failure_type")}, "repair_attempts": 2},
                action="switch_leaf_provider_mode",
                replacement=f"{leaf}_v2",
            )
            continue
        if result["verdict"] != "PASS":
            archive_evidence(leaf, "resume_attempt_1")
            repair_result = _execute(
                leaf=leaf,
                contract_leaf=leaf,
                source_run=source_run,
                out=out,
                project=project,
                goal=goal,
                model=model,
                readiness=readiness,
                provider_output_override=overrides.get(f"{leaf}__repair"),
                run_leaf_tests=leaf not in test_leaves or run_deferred_tests,
            )
            resume_row.update(
                {
                    "action": "resume_then_repair",
                    "result": repair_result["verdict"],
                    "classification": repair_result["classification"],
                    "first_failure": {
                        "classification": result["classification"],
                        "static_missing_terms": result.get("static_missing_terms", []),
                        "missing_files": result.get("missing_files", []),
                    },
                }
            )
            if repair_result["verdict"] == "PASS":
                continue
            if repair_result["classification"] == "provider_unavailable":
                blocked = True
                prune(
                    leaf,
                    repair_result,
                    failure_payload={"provider_status": {"provider_ready": False, "classification": "provider_unavailable", "failure_type": repair_result.get("failure_type")}, "repair_attempts": 2},
                    action="switch_leaf_provider_mode",
                    replacement=f"{leaf}_v2",
                )
                continue
            replacement = f"{leaf}_v2"
            failure_payload = {
                "quality_insufficient": bool(repair_result.get("static_missing_terms")),
                "test_execution": read_json(out / "leaves" / leaf / "test_execution_result.json", {}),
                "scope_enforcement": {"blocked_files": repair_result.get("blocked_files", [])},
                "repair_attempts": 2,
            }
            _, replan = prune(
                leaf,
                repair_result,
                failure_payload=failure_payload,
                action="spawn_replacement_leaf",
                replacement=replacement,
            )
            archive_evidence(leaf, "repair_attempt_2")
            replacement_result = _execute(
                leaf=replacement,
                contract_leaf=leaf,
                source_run=source_run,
                out=out,
                project=project,
                goal=goal,
                model=model,
                readiness=readiness,
                provider_output_override=overrides.get(replacement),
                run_leaf_tests=leaf not in test_leaves or run_deferred_tests,
            )
            replace_result(
                replacements,
                {
                    "leaf_id": replacement,
                    "replaces": leaf,
                    "parent_id": replan["parent_agent"],
                    "result": replacement_result["verdict"],
                    "classification": replacement_result["classification"],
                    "failure_type": replacement_result.get("failure_type", ""),
                    "scope_contract": list(load_scope_contract(out / "leaves" / replacement, replacement).get("allowed_files", [])),
                },
            )
            if replacement_result["classification"] == "provider_unavailable":
                blocked = True

    for leaf in plan.get("repair_leaf", []):
        result = _execute(
            leaf=leaf,
            contract_leaf=leaf,
            source_run=source_run,
            out=out,
            project=project,
            goal=goal,
            model=model,
            readiness=readiness,
            provider_output_override=overrides.get(leaf),
            run_leaf_tests=leaf not in test_leaves or run_deferred_tests,
        )
        replace_result(repaired, {"leaf_id": leaf, "action": "repair_real_provider", "result": result["verdict"], "classification": result["classification"]})
        if result["verdict"] == "PASS":
            continue
        if result["classification"] == "provider_unavailable":
            blocked = True
            prune(
                leaf,
                result,
                failure_payload={"provider_status": {"provider_ready": False, "classification": "provider_unavailable", "failure_type": result.get("failure_type")}, "repair_attempts": 2},
                action="switch_leaf_provider_mode",
                replacement=f"{leaf}_v2",
            )
            continue
        replacement = f"{leaf}_v2"
        test_execution = read_json(out / "leaves" / leaf / "test_execution_result.json", {})
        failure_payload = {
            "test_execution": test_execution,
            "scope_enforcement": {"blocked_files": result.get("blocked_files", [])},
            "repair_attempts": 2,
        }
        _, replan = prune(
            leaf,
            result,
            failure_payload=failure_payload,
            action="spawn_replacement_leaf",
            replacement=replacement,
        )
        replacement_result = _execute(
            leaf=replacement,
            contract_leaf=leaf,
            source_run=source_run,
            out=out,
            project=project,
            goal=goal,
            model=model,
            readiness=readiness,
            provider_output_override=overrides.get(replacement),
            run_leaf_tests=leaf not in test_leaves or run_deferred_tests,
        )
        replace_result(
            replacements,
                {
                    "leaf_id": replacement,
                    "replaces": leaf,
                    "parent_id": replan["parent_agent"],
                    "result": replacement_result["verdict"],
                    "classification": replacement_result["classification"],
                    "failure_type": replacement_result.get("failure_type", ""),
                    "scope_contract": list(load_scope_contract(out / "leaves" / replacement, replacement).get("allowed_files", [])),
                },
            )
        if replacement_result["classification"] == "provider_unavailable":
            blocked = True

    for leaf in plan.get("prune_candidates", []):
        checkpoint = read_json(source_run / "checkpoints" / f"{leaf}.json", {})
        prune(
            leaf,
            checkpoint,
            failure_payload={"scope_enforcement": {"blocked_files": checkpoint.get("blocked_files", ["scope_violation"])}, "repair_attempts": 1},
            action="spawn_replacement_leaf",
            replacement=f"{leaf}_v2",
        )

    save_registry(registry, out, "agent_tree_registry_after.json")
    write_json(out / "resumed_leaf_results.json", {"results": resumed})
    write_json(out / "repaired_leaf_results.json", {"results": repaired})
    write_json(out / "replacement_leaf_results.json", {"results": replacements})
    replacement_passes = {item.get("replaces") for item in replacements if item.get("result") == "PASS"}
    effective_rows = [
        item
        for item in resumed + repaired
        if not (item.get("result") != "PASS" and item.get("leaf_id") in replacement_passes)
    ] + replacements
    result = {
        "verdict": "BLOCKED" if blocked else ("PASS" if all(item["result"] == "PASS" for item in effective_rows) else "NEEDS_REWORK"),
        "classification": "provider_unavailable_during_resume" if blocked else "leaf_resume_pass",
        "reused": reused,
        "resumed": resumed,
        "repaired": repaired,
        "replacements": replacements,
        "provider_ready": bool(readiness.get("provider_ready")),
        "project_dir": str(project),
        "registry": str(out / "agent_tree_registry_after.json"),
    }
    write_json(out / "leaf_resume_result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-dir")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--repair", action="append", default=[])
    parser.add_argument("--retry-replacement", action="append", default=[])
    parser.add_argument("--run-deferred-tests", action="store_true")
    parser.add_argument("--model", default="gpt-5.4-nano")
    args = parser.parse_args()
    plan = read_json(args.resume_plan, {})
    if args.only:
        selected = set(args.only)
        for key in ("resume_leaf", "repair_leaf", "prune_candidates"):
            plan[key] = [leaf for leaf in plan.get(key, []) if leaf in selected]
        plan["reuse_leaf"] = []
    if args.repair:
        plan["repair_leaf"] = list(dict.fromkeys([*plan.get("repair_leaf", []), *args.repair]))
        plan["reuse_leaf"] = [leaf for leaf in plan.get("reuse_leaf", []) if leaf not in set(args.repair)]
    result = run_leaf_resume(
        resume_plan=plan,
        out_dir=args.out,
        project_dir=args.project_dir,
        model=args.model,
        run_deferred_tests=args.run_deferred_tests,
        retry_replacement_leaves=args.retry_replacement,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
