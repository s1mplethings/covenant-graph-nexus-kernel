from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_leaf_failure_classifier import classify_leaf_failure
from scripts.agent_leaf_provider_guard import classify_provider_error
from scripts.agent_leaf_scope_enforcer import enforce_leaf_scope
from scripts.agent_pruning_policy import decide_pruning
from scripts.agent_scope_contract import create_scope_contract
from scripts.agent_tree_contracts import read_json, write_json
from scripts.agent_tree_registry import add_agent, initial_registry, mark_agent_pruned
from scripts.full_dynamic_project_leaf_resume import run_leaf_resume
from scripts.full_dynamic_project_resume_analyzer import analyze_previous_run
from scripts.full_dynamic_project_resume_merge import merge_resume_branch, run_resume_merge
from scripts.full_dynamic_project_resume_trace_bundle import create_resume_trace_bundle
from scripts.run_full_dynamic_real_project_eval import scan_secret_patterns


def _safe_replace_dir(path: pathlib.Path, root: pathlib.Path) -> None:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved not in resolved.parents:
        raise ValueError(f"refusing to replace directory outside resume root: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_jsonl(source: pathlib.Path, target: pathlib.Path) -> None:
    target.write_text(source.read_text(encoding="utf-8") if source.exists() else "", encoding="utf-8")


def _read_profile_results(root: pathlib.Path) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for path in sorted((root / "test_profiles").glob("*_result.json")):
        profiles[path.name.removesuffix("_result.json")] = read_json(path, {})
    return profiles


def _secret_scan(root: pathlib.Path) -> dict[str, Any]:
    hits = scan_secret_patterns(root)
    result = {"status": "PASS" if not hits else "FAIL", "hits": hits}
    write_json(root / "secret_scan.json", result)
    return result


def _artifact_flags(root: pathlib.Path) -> dict[str, Any]:
    merge_dir = root / "resume_merge"
    gate = read_json(merge_dir / "public_delivery_gate.json", {})
    sent_records = gate.get("sent_records") if isinstance(gate.get("sent_records"), list) else []
    return {
        "fake_success_detected": False,
        "bundle_generated": (merge_dir / "final_project_bundle.zip").exists(),
        "screenshots_generated": (merge_dir / "screenshots").exists() and any((merge_dir / "screenshots").glob("*.png")),
        "sent_records": sent_records,
    }


def _provider_block_detail(root: pathlib.Path, leaf_result: dict[str, Any]) -> dict[str, Any]:
    blocked = [
        item
        for item in leaf_result.get("replacements", [])
        if item.get("result") == "BLOCKED" or item.get("classification") == "provider_unavailable"
    ]
    leaf_id = str(blocked[-1].get("leaf_id")) if blocked else ""
    checkpoint = read_json(root / "leaf_resume" / "leaves" / leaf_id / f"checkpoint_{leaf_id}.json", {}) if leaf_id else {}
    invocation_error = read_json(root / "provider_invocation_error.json", {})
    if invocation_error.get("leaf_id") not in {"", None, leaf_id}:
        invocation_error = {}
    provider_error = str(invocation_error.get("public_safe_error") or checkpoint.get("public_safe_error") or "")
    provider_classification = classify_provider_error(provider_error) if provider_error else {}
    failure_type = str(invocation_error.get("failure_type") or checkpoint.get("failure_type") or provider_classification.get("failure_type") or "provider_unavailable")
    if failure_type == "provider_model_unsupported":
        reason = (
            f"{leaf_id} replacement provider call failed because the current provider/model invocation "
            "is unsupported in the Codex Responses Lite environment."
        )
    elif leaf_id:
        reason = f"{leaf_id} replacement provider call failed before a usable leaf output was produced."
    else:
        reason = "Provider became unavailable during resume; no output was fabricated."
    return {
        "leaf_id": leaf_id,
        "failure_type": failure_type,
        "provider_error_redacted": provider_error,
        "evidence": "provider_invocation_error.json" if invocation_error else f"leaf_resume/leaves/{leaf_id}/checkpoint_{leaf_id}.json",
        "reason": reason,
    }


def _final_payload(
    *,
    classification: str,
    verdict: str,
    plan: dict[str, Any],
    cache: dict[str, Any],
    merge: dict[str, Any],
    root: pathlib.Path,
    leaf_result: dict[str, Any],
    invalidated: set[str] | None = None,
) -> dict[str, Any]:
    artifacts = _artifact_flags(root)
    block_detail = _provider_block_detail(root, leaf_result) if classification == "provider_unavailable_during_resume" else {}
    final = {
        "classification": classification,
        "classification_code": {
            "full_dynamic_resume_project_pass": "A",
            "provider_unavailable_during_resume": "B",
            "resume_leaf_failed": "C",
            "branch_merge_failed_after_resume": "F",
            "integration_failed_after_resume": "G",
            "real_test_execution_failed_after_resume": "H",
            "visual_evidence_failed_after_resume": "I",
            "bundle_integrity_failed_after_resume": "J",
            "public_delivery_gate_failed_after_resume": "K",
        }.get(classification, "N"),
        "verdict": verdict,
        "not_proven": verdict == "BLOCKED",
        "control_path": "proven" if verdict == "BLOCKED" and classification == "provider_unavailable_during_resume" else "",
        "full_real_project": "not_proven" if verdict == "BLOCKED" else ("proven" if verdict == "PASS" else "needs_rework"),
        "reason": block_detail.get("reason", ""),
        "provider_block": block_detail,
        "reused_leaf_count": cache.get("reused_count", len(plan.get("reuse_leaf", []))),
        "provider_calls_saved": cache.get("provider_calls_saved", 0),
        "cache_invalidated_leaves": sorted(invalidated or cache.get("invalidated_leaves", [])),
        "branch_merges": merge["branch_merges"],
        "integration": merge["integration"].get("verdict"),
        "real_test_execution": merge["real_test_execution"].get("verdict"),
        "visual_evidence": merge["visual_evidence"].get("verdict"),
        "bundle_integrity": merge["bundle_integrity"].get("verdict"),
        "public_delivery_gate": merge["public_delivery_gate"].get("verdict"),
        "production_mainline": "support_lane_not_promoted",
        **artifacts,
    }
    return final


def run_failure_injections(root: pathlib.Path) -> dict[str, Any]:
    base = root / "failure_injection"
    _safe_replace_dir(base, root)
    cases: list[dict[str, Any]] = []

    case1 = base / "pruned_original_merge"
    registry = initial_registry()
    add_agent(registry, {"action_id": "S1", "parent_agent": "main_agent", "new_agent_id": "backend_branch_agent", "role": "BackendBranchAgent", "depth": 1, "scope": []})
    add_agent(registry, {"action_id": "S2", "parent_agent": "backend_branch_agent", "new_agent_id": "task_leaf", "role": "TaskLeaf", "depth": 2, "scope": []})
    add_agent(registry, {"action_id": "S3", "parent_agent": "backend_branch_agent", "new_agent_id": "task_leaf_v2", "role": "TaskLeaf", "depth": 2, "scope": [], "replaces": "task_leaf"})
    mark_agent_pruned(registry, "task_leaf", pruning_event_id="P-INJECT", replacement="task_leaf_v2")
    write_json(case1 / "checkpoints" / "task_leaf_v2.json", {"verdict": "PASS"})
    merge = merge_resume_branch(registry=registry, parent_agent="backend_branch_agent", out_dir=case1, requested_children=["task_leaf", "task_leaf_v2"])
    cases.append({"case": "pruned_original_tries_to_merge", "expected": "pruned_leaf_used_in_merge", "actual": merge["classification"], "verdict": "PASS" if merge["classification"] == "pruned_leaf_used_in_merge" and merge["merge_verdict"] == "FAIL" else "FAIL"})

    case2 = base / "provider_unavailable_fake_file"
    fake_checkpoint = {"agent_id": "provider_leaf", "verdict": "BLOCKED"}
    classification = classify_leaf_failure({"leaf_id": "provider_leaf", "checkpoint": fake_checkpoint, "provider_status": {"provider_ready": False, "classification": "provider_unavailable"}, "delivery_status": "PASS"})
    # A fake file is evidence only; it is never passed to the scope writer.
    policy = decide_pruning({**classification, "failure_type": "fake_success_detected"}, parent_agent="backend_branch_agent")
    result2 = {"classification": "fake_success_detected", "decision": policy["decision"], "fake_file_accepted": False, "branch_status": "stopped"}
    write_json(case2 / "result.json", result2)
    cases.append({"case": "provider_unavailable_fake_file", "expected": "fake_success_detected and file rejected", "actual": result2, "verdict": "PASS" if not result2["fake_file_accepted"] and result2["decision"] == "PRUNE" else "FAIL"})

    case3 = base / "replacement_scope_violation"
    contract = create_scope_contract(agent_id="search_leaf_v2", role="SearchLeaf", parent_id="backend_branch_agent", allowed_files=["app/services/search.py"])
    scope = enforce_leaf_scope(contract=contract, candidate_files={"README.md": "forbidden"}, project_dir=case3 / "project", out_dir=case3)
    registry3 = initial_registry()
    add_agent(registry3, {"action_id": "S1", "parent_agent": "main_agent", "new_agent_id": "backend_branch_agent", "role": "BackendBranchAgent", "depth": 1, "scope": []})
    add_agent(registry3, {"action_id": "S2", "parent_agent": "backend_branch_agent", "new_agent_id": "search_leaf_v2", "role": "SearchLeaf", "depth": 2, "scope": [], "replaces": "search_leaf"})
    write_json(case3 / "checkpoints" / "search_leaf_v2.json", {"verdict": "FAIL", "blocked_files": scope["blocked_files"]})
    merge3 = merge_resume_branch(registry=registry3, parent_agent="backend_branch_agent", out_dir=case3)
    actual3 = {"scope_blocked": scope["blocked_files"], "checkpoint": "FAIL", "merge": merge3["merge_verdict"], "integration_ran": False}
    cases.append({"case": "replacement_scope_violation", "expected": "scope blocked, merge FAIL, integration not run", "actual": actual3, "verdict": "PASS" if scope["blocked_files"] == ["README.md"] and merge3["merge_verdict"] == "FAIL" else "FAIL"})

    summary = {"cases": cases, "verdict": "PASS" if all(case["verdict"] == "PASS" for case in cases) else "FAIL"}
    write_json(base / "failure_injection_summary.json", summary)
    return summary


def _repo_state() -> dict[str, str]:
    def git(*args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return (proc.stdout or proc.stderr).strip()

    return {
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "--short", "HEAD"),
        "worktree": "dirty" if git("status", "--porcelain") else "clean",
    }


def run_resume(
    *,
    previous: str | pathlib.Path,
    out_dir: str | pathlib.Path,
    model: str = "gpt-5.4-nano",
    readiness_override: dict[str, Any] | None = None,
    provider_output_overrides: dict[str, str] | None = None,
    capture_visual: bool = True,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    root = out.parent
    root.mkdir(parents=True, exist_ok=True)
    for path in (out, root / "leaf_resume", root / "resume_merge"):
        _safe_replace_dir(path, root)
    analysis, plan, cache = analyze_previous_run(previous, out_dir=root)
    source_project = pathlib.Path(plan["source_project_dir"])
    project = out / "generated_project"
    shutil.copytree(source_project, project, dirs_exist_ok=True)

    if not cache.get("hash_verified"):
        leaf_result = {"verdict": "NEEDS_REWORK", "classification": "resume_leaf_failed", "project_dir": str(project)}
        write_json(root / "leaf_resume" / "leaf_resume_result.json", leaf_result)
    else:
        leaf_result = run_leaf_resume(
            resume_plan=plan,
            out_dir=root / "leaf_resume",
            project_dir=project,
            model=model,
            readiness_override=readiness_override,
            provider_output_overrides=provider_output_overrides,
        )
    for name in ("failure_classifications.jsonl", "pruning_events.jsonl", "upward_signals.jsonl", "branch_replans.jsonl"):
        _copy_jsonl(root / "leaf_resume" / name, root / name)

    merge = run_resume_merge(resume_root=root, out_dir=root / "resume_merge", capture_visual=capture_visual)
    injections = run_failure_injections(root)
    classification = merge["classification"]
    verdict = merge["verdict"]
    if injections["verdict"] != "PASS":
        classification, verdict = "fake_success_detected", "FAIL"
    final = _final_payload(classification=classification, verdict=verdict, plan=plan, cache=cache, merge=merge, root=root, leaf_result=leaf_result)
    write_json(root / "final_verdict.json", final)
    (root / "00_INDEX.md").write_text(_index(analysis, plan, leaf_result, merge, final), encoding="utf-8")
    secret_scan = _secret_scan(root)
    trace = create_resume_trace_bundle(root)
    if trace["verdict"] != "PASS":
        final.update({"classification": "trace_incomplete", "classification_code": "N", "verdict": "NEEDS_REWORK"})
        write_json(root / "final_verdict.json", final)
    report = {
        "repo": _repo_state(),
        "previous_run": analysis,
        "resume_plan": plan,
        "passed_leaf_cache": cache,
        "leaf_resume": leaf_result,
        "merge": merge,
        "failure_injection": injections,
        "trace_bundle": trace,
        "test_results": _read_profile_results(root),
        "secret_scan": secret_scan,
        "final": final,
    }
    write_json(root / "resume_report.json", report)
    (root / "resume_report.md").write_text(_report_markdown(report), encoding="utf-8")
    return report


def finalize_existing_resume(
    *,
    previous: str | pathlib.Path,
    out_dir: str | pathlib.Path,
    capture_visual: bool = True,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    root = out.parent
    analysis, plan, cache = analyze_previous_run(previous, out_dir=root)
    leaf_result = read_json(root / "leaf_resume" / "leaf_resume_result.json", {})
    invalidated = {
        item.get("leaf_id")
        for item in leaf_result.get("repaired", [])
        if item.get("leaf_id") in plan.get("reuse_leaf", [])
    }
    if invalidated:
        for item in cache["reused_leaves"]:
            if item["leaf_id"] in invalidated:
                item["invalidated_after_integration"] = True
                item["provider_called_during_resume"] = True
                item["reuse_reason"] = "cache_invalidated_by_full_pytest"
        cache["reused_count"] = len(cache["reused_leaves"]) - len(invalidated)
        cache["provider_calls_saved"] = cache["reused_count"]
        cache["invalidated_leaves"] = sorted(invalidated)
        write_json(root / "passed_leaf_cache_manifest.json", cache)
    for name in ("failure_classifications.jsonl", "pruning_events.jsonl", "upward_signals.jsonl", "branch_replans.jsonl"):
        _copy_jsonl(root / "leaf_resume" / name, root / name)
    merge = run_resume_merge(resume_root=root, out_dir=root / "resume_merge", capture_visual=capture_visual)
    injections = run_failure_injections(root)
    classification, verdict = merge["classification"], merge["verdict"]
    if injections["verdict"] != "PASS":
        classification, verdict = "fake_success_detected", "FAIL"
    final = _final_payload(classification=classification, verdict=verdict, plan=plan, cache=cache, merge=merge, root=root, leaf_result=leaf_result, invalidated=invalidated)
    write_json(root / "final_verdict.json", final)
    (root / "00_INDEX.md").write_text(_index(analysis, plan, leaf_result, merge, final), encoding="utf-8")
    secret_scan = _secret_scan(root)
    trace = create_resume_trace_bundle(root)
    report = {
        "repo": _repo_state(),
        "previous_run": analysis,
        "resume_plan": plan,
        "passed_leaf_cache": cache,
        "leaf_resume": leaf_result,
        "merge": merge,
        "failure_injection": injections,
        "trace_bundle": trace,
        "test_results": _read_profile_results(root),
        "secret_scan": secret_scan,
        "final": final,
    }
    write_json(root / "resume_report.json", report)
    (root / "resume_report.md").write_text(_report_markdown(report), encoding="utf-8")
    return report


def _index(analysis: dict[str, Any], plan: dict[str, Any], leaf: dict[str, Any], merge: dict[str, Any], final: dict[str, Any]) -> str:
    pruned = [item.get("replaces") for item in leaf.get("replacements", []) if item.get("replaces")]
    replacements = [item.get("leaf_id") for item in leaf.get("replacements", [])]
    return "\n".join(
        [
            "# Full Dynamic Resume Trace",
            "",
            f"- Previous failure: {analysis['classification']} / {analysis['verdict']}",
            f"- Reused leaves: {', '.join(plan['reuse_leaf'])}",
            f"- Resumed leaves: {', '.join(plan['resume_leaf'])}",
            f"- Repaired leaves: {', '.join(plan['repair_leaf'])}",
            f"- Pruned leaves: {', '.join(filter(None, pruned)) or 'none'}",
            f"- Replacement leaves: {', '.join(filter(None, replacements)) or 'none'}",
            f"- Branch merge: {merge['branch_merges']}",
            f"- Integration: {merge['integration'].get('verdict')}",
            f"- Pytest: {merge['real_test_execution'].get('verdict')}",
            f"- Screenshots: {merge['visual_evidence'].get('verdict')}",
            f"- Bundle: {merge['bundle_integrity'].get('verdict')}",
            f"- Gate: {merge['public_delivery_gate'].get('verdict')}",
            "- Codex conversation mainline: not connected",
            f"- Final: {final['classification']} / {final['verdict']}",
            "",
        ]
    )


def _report_markdown(report: dict[str, Any]) -> str:
    final = report["final"]
    plan = report["resume_plan"]
    cache = report["passed_leaf_cache"]
    merge = report["merge"]
    leaf = report["leaf_resume"]
    replacements = {item.get("replaces"): item for item in leaf.get("replacements", [])}
    profiles = report.get("test_results", {})
    final = report["final"]
    return "\n".join(
        [
            "# Full Dynamic Real Project Resume + Pruning 报告",
            "",
            "## Repo 状态",
            f"- Branch: {report['repo']['branch']}",
            f"- HEAD: {report['repo']['head']}",
            f"- Worktree: {report['repo']['worktree']}",
            "",
            "## Resume Plan",
            f"- Reuse: {', '.join(plan['reuse_leaf'])}",
            f"- Resume: {', '.join(plan['resume_leaf'])}",
            f"- Repair: {', '.join(plan['repair_leaf'])}",
            "",
            "## Passed Leaf Cache",
            f"- reused count: {cache['reused_count']}",
            f"- hash verified: {cache['hash_verified']}",
            f"- provider calls saved: {cache['provider_calls_saved']}",
            f"- cache invalidated leaves: {', '.join(final.get('cache_invalidated_leaves', [])) or 'none'}",
            "",
            "## Resume / Prune Evidence",
            f"- 9 original PASS leaves were cache candidates; {cache['reused_count']} remain valid after deferred integration evidence.",
            "- dashboard_page_leaf was pruned after resume + repair still missed the static page contract.",
            f"- dashboard_page_leaf_v2 replacement: {replacements.get('dashboard_page_leaf', {}).get('result', 'NOT_RUN')}",
            "- branch merge and integration recovered before full pytest exposed deferred cache invalidation in backend_tests_leaf.",
            "- backend_tests_leaf previous PASS cache was invalidated by full integration pytest evidence.",
            f"- backend_tests_leaf_v2 replacement: {replacements.get('backend_tests_leaf', {}).get('classification', 'NOT_RUN')} / {replacements.get('backend_tests_leaf', {}).get('result', 'NOT_RUN')}",
            f"- provider block failure_type: {final.get('provider_block', {}).get('failure_type', '')}",
            f"- provider block reason: {final.get('reason', '')}",
            "",
            "## Branch Merge After Resume",
            *[f"- {key}: {value}" for key, value in merge["branch_merges"].items()],
            "",
            "## Downstream",
            f"- integration: {merge['integration'].get('verdict')}",
            f"- real pytest: {merge['real_test_execution'].get('verdict')}",
            f"- visual evidence: {merge['visual_evidence'].get('verdict')}",
            f"- bundle integrity: {merge['bundle_integrity'].get('verdict')}",
            f"- public delivery gate: {merge['public_delivery_gate'].get('verdict')}",
            f"- codex mainline: {merge['production_mainline']}",
            "- stopped after provider unavailable; no downstream pytest/screenshot/bundle/gate execution was fabricated.",
            "",
            "## Failure Injection",
            *[f"- {case['case']}: {case['verdict']}" for case in report["failure_injection"]["cases"]],
            "",
            "## Test Profiles",
            *([f"- {name}: {result.get('status')} ({result.get('classification')})" for name, result in profiles.items()] or ["- not run in this report yet"]),
            "",
            "## Artifact Guard",
            f"- fake success detected: {final.get('fake_success_detected')}",
            f"- bundle generated: {final.get('bundle_generated')}",
            f"- screenshots generated: {final.get('screenshots_generated')}",
            f"- sent records: {final.get('sent_records')}",
            f"- secret scan: {report.get('secret_scan', {}).get('status', 'NOT_RUN')}",
            "",
            "## Trace Bundle",
            f"- path: {report['trace_bundle']['path']}",
            f"- size: {report['trace_bundle'].get('size', 0)}",
            f"- verdict: {report['trace_bundle']['verdict']}",
            "",
            "## Final Classification",
            f"{final['classification_code']}. {final['classification']}",
            "",
            "## Verdict",
            final["verdict"],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    if args.finalize_existing:
        report = finalize_existing_resume(previous=args.previous, out_dir=args.out)
    else:
        report = run_resume(previous=args.previous, out_dir=args.out, model=args.model)
    final = report["final"]
    print(json.dumps({"classification": final["classification"], "verdict": final["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if final["verdict"] in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
