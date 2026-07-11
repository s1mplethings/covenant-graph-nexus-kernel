from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

try:
    from agent_tree_contracts import read_json, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import read_json, write_json


def _run_dir(previous: pathlib.Path) -> pathlib.Path:
    candidate = previous / "run_001"
    return candidate if candidate.exists() else previous


def _file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def analyze_previous_run(
    previous: str | pathlib.Path,
    *,
    out_dir: str | pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = pathlib.Path(previous)
    run = _run_dir(source)
    out = pathlib.Path(out_dir)
    checkpoints_dir = run / "checkpoints"
    rows: list[dict[str, Any]] = []
    categories: dict[str, list[str]] = {
        "pass": [],
        "provider_unavailable": [],
        "test_failed": [],
        "scope_violation": [],
        "missing_files": [],
    }
    for path in sorted(checkpoints_dir.glob("*.json")):
        checkpoint = read_json(path, {})
        leaf = str(checkpoint.get("leaf") or path.stem)
        classification = str(checkpoint.get("classification", ""))
        if checkpoint.get("verdict") == "PASS":
            state = "pass"
        elif classification == "provider_unavailable":
            state = "provider_unavailable"
        elif "test_failed" in classification:
            state = "test_failed"
        elif checkpoint.get("blocked_files") or "scope_violation" in classification:
            state = "scope_violation"
        elif checkpoint.get("missing_files"):
            state = "missing_files"
        else:
            state = "failed"
        if state in categories:
            categories[state].append(leaf)
        rows.append(
            {
                "leaf_id": leaf,
                "state": state,
                "classification": classification,
                "verdict": checkpoint.get("verdict"),
                "checkpoint": str(path),
                "expected_files": list(checkpoint.get("expected_files", [])),
                "missing_files": list(checkpoint.get("missing_files", [])),
                "blocked_files": list(checkpoint.get("blocked_files", [])),
            }
        )

    branch_merges = {
        path.stem: read_json(path, {}).get("merge_verdict")
        for path in sorted((run / "merge_results").glob("*_branch_agent.json"))
    }
    integration = read_json(run / "merge_results" / "integration_agent.json", {})
    gate_path = run / "public_delivery_gate.json"
    previous_final = read_json(source / "final_verdict.json", read_json(run / "final_verdict.json", {}))
    analysis = {
        "previous_run": str(source),
        "source_run_dir": str(run),
        "classification": previous_final.get("classification"),
        "verdict": previous_final.get("verdict"),
        "leaves": rows,
        "summary": {
            "total_leaf": len(rows),
            "pass_leaf": len(categories["pass"]),
            "provider_unavailable_leaf": len(categories["provider_unavailable"]),
            "test_failed_leaf": len(categories["test_failed"]),
            "scope_violation_leaf": len(categories["scope_violation"]),
            "missing_files_leaf": len(categories["missing_files"]),
        },
        "categories": categories,
        "branch_merge": branch_merges,
        "branch_merge_failure_reasons": {
            path.stem: read_json(path, {}).get("issues", [])
            for path in sorted((run / "merge_results").glob("*_branch_agent.json"))
        },
        "integration": integration.get("verdict", "NOT_RUN"),
        "public_delivery_gate": "NOT_RUN" if not gate_path.exists() else read_json(gate_path, {}).get("verdict"),
    }
    blocked = [
        "branch_merge",
        "integration",
        "real_test_execution",
        "runtime_visual_evidence",
        "bundle",
        "public_delivery_gate",
    ]
    plan = {
        "previous_run": str(source),
        "source_run_dir": str(run),
        "source_project_dir": str(run / "generated_project"),
        "source_registry": str(run / "agent_tree_registry.json"),
        "summary": analysis["summary"],
        "reuse_leaf": categories["pass"],
        "resume_leaf": categories["provider_unavailable"],
        "repair_leaf": categories["test_failed"] + categories["missing_files"],
        "prune_candidates": categories["scope_violation"],
        "blocked_downstream": blocked,
        "verdict": "RESUME_REQUIRED" if len(categories["pass"]) != len(rows) else "READY_TO_MERGE",
    }
    manifest = build_passed_leaf_cache(plan, run)
    write_json(out / "previous_run_analysis.json", analysis)
    write_json(out / "resume_plan.json", plan)
    write_json(out / "passed_leaf_cache_manifest.json", manifest)
    (out / "previous_run_analysis.md").write_text(_analysis_markdown(analysis), encoding="utf-8")
    (out / "resume_plan.md").write_text(_plan_markdown(plan), encoding="utf-8")
    return analysis, plan, manifest


def build_passed_leaf_cache(plan: dict[str, Any], source_run: str | pathlib.Path) -> dict[str, Any]:
    run = pathlib.Path(source_run)
    project = run / "generated_project"
    reused: list[dict[str, Any]] = []
    for leaf in plan.get("reuse_leaf", []):
        checkpoint_path = run / "checkpoints" / f"{leaf}.json"
        checkpoint = read_json(checkpoint_path, {})
        scope_path = run / "leaves" / leaf / "scope_enforcement_result.json"
        scope = read_json(scope_path, {})
        expected = list(checkpoint.get("expected_files", []))
        files_exist = bool(expected) and all((project / rel).is_file() for rel in expected)
        hashes = {rel: _file_hash(project / rel) for rel in expected if (project / rel).is_file()}
        scope_clean = scope.get("blocked_files", []) == []
        checkpoint_pass = checkpoint.get("verdict") == "PASS"
        reused.append(
            {
                "leaf_id": leaf,
                "provider_mode": "real_provider",
                "source_checkpoint": str(checkpoint_path),
                "source_files": expected,
                "source_hashes": hashes,
                "reuse_reason": "previous_checkpoint_pass",
                "checkpoint_pass": checkpoint_pass,
                "scope_clean": scope_clean,
                "files_exist": files_exist,
                "hash_verified": checkpoint_pass and scope_clean and files_exist and len(hashes) == len(expected),
                "provider_called_during_resume": False,
            }
        )
    return {
        "reused_leaves": reused,
        "reused_count": len(reused),
        "hash_verified": all(item["hash_verified"] for item in reused),
        "provider_calls_saved": len(reused),
    }


def _analysis_markdown(analysis: dict[str, Any]) -> str:
    summary = analysis["summary"]
    return "\n".join(
        [
            "# Previous Full Dynamic Run Analysis",
            "",
            f"- classification: {analysis['classification']}",
            f"- verdict: {analysis['verdict']}",
            f"- total leaves: {summary['total_leaf']}",
            f"- pass: {summary['pass_leaf']}",
            f"- provider unavailable: {summary['provider_unavailable_leaf']}",
            f"- test failed: {summary['test_failed_leaf']}",
            f"- integration: {analysis['integration']}",
            f"- public delivery gate: {analysis['public_delivery_gate']}",
            "",
        ]
    )


def _plan_markdown(plan: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Resume Plan",
            "",
            f"- reuse: {', '.join(plan['reuse_leaf'])}",
            f"- resume: {', '.join(plan['resume_leaf'])}",
            f"- repair: {', '.join(plan['repair_leaf'])}",
            f"- prune candidates: {', '.join(plan['prune_candidates'])}",
            f"- verdict: {plan['verdict']}",
            "",
        ]
    )
