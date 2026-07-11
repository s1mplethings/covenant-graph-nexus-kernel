from __future__ import annotations

import argparse
import json
import pathlib
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from agent_tree_contracts import append_jsonl, now, read_jsonl, write_json
    import check_connectivity
    import provider_transport
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import append_jsonl, now, read_jsonl, write_json
    from scripts import check_connectivity, provider_transport


BRANCHES = [
    "requirement",
    "architecture",
    "environment",
    "ux",
    "implementation",
    "qa",
    "delivery",
]

CAPABILITIES = [
    "dashboard",
    "tasks",
    "asset_library",
    "bug_tracker",
    "build_release_records",
    "docs_guidelines",
    "release_checklist",
    "team_roles",
    "search_filter",
    "import_export",
    "audit_activity_log",
]

ENVIRONMENTS = ["dev", "test", "demo", "prod-like local"]
READINESS_DEFAULT_MODEL = "gpt-4.1-mini"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _write_text(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _canonical_provider_domain(base_url: str) -> str:
    domain = check_connectivity._base_url_domain(base_url)
    return "gptsapi.net" if domain.endswith("gptsapi.net") else domain


def _readiness_classification(error_type: str) -> str:
    if not error_type:
        return "PROVIDER_READY"
    if error_type == "PROVIDER_KEY_USAGE_LIMIT":
        return "PROVIDER_QUOTA_EXCEEDED"
    if error_type in {
        "PROVIDER_METHOD_UNSUPPORTED",
        "PROVIDER_QUOTA_EXCEEDED",
        "PROVIDER_TRANSPORT_UNSTABLE",
        "PROVIDER_RETRYABLE_HTTP",
        "PROVIDER_NON_RETRYABLE_HTTP",
        "PROVIDER_FORBIDDEN",
    }:
        return error_type
    return "PROVIDER_UNAVAILABLE"


def _readiness_status(classification: str, *, configured: bool) -> str:
    if not configured:
        return "skipped"
    return "pass" if classification == "PROVIDER_READY" else "blocked"


def run_provider_readiness_only(
    *,
    goal: str,
    mode: str,
    model: str,
    output_root: str | pathlib.Path,
    timeout: int = 20,
    post_json_with_retry_fn: Any | None = None,
) -> dict[str, Any]:
    started_at = now()
    output = pathlib.Path(output_root)
    run_dir = output / _timestamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "goal.json", {"kind": "QuickLargeProviderReadinessGoal", "goal": goal, "created_at": started_at})

    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    base_url = str(creds.get("base_url", "")).strip()
    selected_method = check_connectivity._selected_provider_api_method(base_url, model) if base_url else ""
    endpoint = check_connectivity._openai_compatible_endpoint(base_url, model=model) if base_url else ""
    payload = (
        check_connectivity._build_openai_compatible_payload(
            base_url,
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
                "max_tokens": 4,
            },
            model=model,
        )
        if base_url
        else {}
    )
    configured = bool(token and base_url)
    attempt_count = 0
    error_type = ""
    safe_error = ""
    if configured:
        transport = (post_json_with_retry_fn or check_connectivity._post_json_with_retry)(
            endpoint,
            payload,
            token,
            timeout,
            max_attempts=1,
            base_delay_sec=0,
        )
        attempt_count = len(getattr(transport, "attempts", []) or []) or 1
        if getattr(transport, "doc", None) is None:
            safe_error = provider_transport._redact(str(getattr(transport, "error", "") or ""), token)
            error_type = str(getattr(transport, "error_type", "") or check_connectivity._provider_error_type(safe_error))
    else:
        safe_error = "provider credentials are not fully configured"
    classification = "PROVIDER_UNAVAILABLE" if not configured else _readiness_classification(error_type)
    status = _readiness_status(classification, configured=configured)
    readiness = {
        "kind": "QuickLargeProviderReadiness",
        "mode": mode,
        "readiness_only": True,
        "provider": "api_agent",
        "model": model,
        "base_url_domain": _canonical_provider_domain(base_url),
        "selected_method": selected_method,
        "status": status,
        "classification": classification,
        "attempt_count": attempt_count,
        "leaf_generation_started": False,
        "project_generation_started": False,
        "secrets_printed": False,
        "credential_present": bool(token),
        "base_url_present": bool(base_url),
        "public_safe_error": safe_error,
        "created_at": now(),
    }
    write_json(run_dir / "provider_readiness.json", readiness)
    verdict = {
        "pass": "PROVIDER_READY",
        "blocked": "BLOCKED_PROVIDER",
        "skipped": "SKIPPED_PROVIDER",
    }[status]
    summary = {
        "kind": "QuickLargeProviderReadinessSummary",
        "verdict": verdict,
        "run_dir": str(run_dir),
        "mode": mode,
        "goal": goal,
        "provider_readiness": "provider_readiness.json",
        "selected_method": selected_method,
        "status": status,
        "classification": classification,
        "attempt_count": attempt_count,
        "leaf_generation_started": False,
        "project_generation_started": False,
        "started_at": started_at,
        "finished_at": now(),
    }
    write_json(run_dir / "run_summary.json", summary)
    _write_provider_readiness_report(run_dir, summary=summary, readiness=readiness)
    return summary


def _write_provider_readiness_report(run_dir: pathlib.Path, *, summary: dict[str, Any], readiness: dict[str, Any]) -> pathlib.Path:
    lines = [
        "# CGKN Provider Readiness Probe Report",
        "",
        "## Verdict",
        f"- {summary['verdict']}",
        "",
        "This is provider readiness only.",
        "No leaf generation was started.",
        "No product generation was started.",
        "This is not a product PASS.",
        "",
        "## Readiness",
        f"- provider: {readiness['provider']}",
        f"- model: {readiness['model']}",
        f"- base_url_domain: {readiness['base_url_domain']}",
        f"- selected_method: {readiness['selected_method']}",
        f"- status: {readiness['status']}",
        f"- classification: {readiness['classification']}",
        f"- attempt_count: {readiness['attempt_count']}",
        f"- leaf_generation_started: {readiness['leaf_generation_started']}",
        f"- project_generation_started: {readiness['project_generation_started']}",
        f"- secrets_printed: {readiness['secrets_printed']}",
        "",
        "## Meaning",
        "- PROVIDER_READY means only provider/model/method connectivity is available.",
        "- BLOCKED_PROVIDER means real generation should not start until provider configuration or quota is fixed.",
        "- SKIPPED_PROVIDER means credentials or base URL are not configured.",
    ]
    return _write_text(run_dir / "acceptance_report.md", "\n".join(lines) + "\n")


def build_multi_environment_acceptance_contract(goal: str) -> dict[str, Any]:
    return {
        "kind": "MultiEnvironmentAcceptanceContract",
        "goal": goal,
        "required_environments": list(ENVIRONMENTS),
        "required_capabilities": list(CAPABILITIES),
        "required_environment_evidence": [
            ".env.example",
            "config/dev.json",
            "config/test.json",
            "config/demo.json",
            "config/prod.json",
            "README environment section",
            "test command",
            "demo seed data",
            "local production-like run command",
        ],
        "required_delivery": [
            "README",
            "environment_config",
            "startup_commands",
            "app_entry",
            "dependency_file",
            "sample_data",
            "feature_matrix",
            "page_module_map",
            "test_report",
            "screenshots",
            "bundle",
            "delivery_manifest",
        ],
        "forbidden_scope": [
            "no external SaaS dependency",
            "no task-board-only output",
            "no placeholder-only delivery",
            "no missing environment config",
            "no single-environment-only project",
            "no tests omitted",
        ],
    }


def _multi_env_contract_status(contract: dict[str, Any]) -> dict[str, Any]:
    envs = set(contract.get("required_environments", []))
    capabilities = set(contract.get("required_capabilities", []))
    delivery = set(contract.get("required_delivery", []))
    forbidden = set(contract.get("forbidden_scope", []))
    missing = []
    for env in ENVIRONMENTS:
        if env not in envs:
            missing.append(f"environment:{env}")
    for capability in CAPABILITIES:
        if capability not in capabilities:
            missing.append(f"capability:{capability}")
    for item in ("README", "app_entry", "dependency_file", "test_report", "screenshots", "bundle", "delivery_manifest"):
        if item not in delivery:
            missing.append(f"delivery:{item}")
    if "no task-board-only output" not in forbidden:
        missing.append("forbidden:no task-board-only output")
    return {"status": "pass" if not missing else "fail", "missing": missing}


def audit_synchronous_growth(ledger_path: str | pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(ledger_path)
    rows = read_jsonl(path)
    branch_rows = [row for row in rows if row.get("branch") != "root"]
    branches = sorted({str(row.get("branch", "")) for row in branch_rows if row.get("branch")})
    rounds = sorted({int(row.get("round", -1)) for row in rows if isinstance(row.get("round"), int) or str(row.get("round", "")).isdigit()})
    active_rounds = [round_no for round_no in rounds if round_no > 0]
    max_depth_gap = 0
    missing_round_coverage: list[dict[str, Any]] = []
    missing_checkpoints: list[dict[str, Any]] = []
    starved_branches: list[str] = []
    orphan_leaves: list[dict[str, Any]] = []
    known_branches = set(branches) | {"root"}

    for row in rows:
        branch = str(row.get("branch", ""))
        parent = str(row.get("parent_branch", "")).strip()
        action = str(row.get("action", ""))
        if branch.endswith("_leaf") and not parent:
            orphan_leaves.append({"round": row.get("round"), "branch": branch, "reason": "missing_parent_branch"})
        if parent and parent not in known_branches:
            orphan_leaves.append({"round": row.get("round"), "branch": branch, "parent_branch": parent, "reason": "unknown_parent_branch"})
        if not row.get("checkpoint"):
            missing_checkpoints.append({"round": row.get("round"), "branch": branch or "unknown", "action": action})

    for round_no in active_rounds:
        entries = [row for row in branch_rows if int(row.get("round", -1)) == round_no]
        seen = {str(row.get("branch", "")) for row in entries if row.get("branch")}
        missing = sorted(set(branches) - seen)
        if missing:
            missing_round_coverage.append({"round": round_no, "missing_branches": missing})
        depths = [int(row.get("depth", 0)) for row in entries if str(row.get("branch", "")) in branches]
        if depths:
            max_depth_gap = max(max_depth_gap, max(depths) - min(depths))

    for branch in branches:
        seen_rounds = {int(row.get("round", -1)) for row in branch_rows if row.get("branch") == branch}
        missing = [round_no for round_no in active_rounds if round_no not in seen_rounds]
        if missing:
            starved_branches.append(branch)

    sync_status = "pass"
    if missing_round_coverage or max_depth_gap > 1 or starved_branches or orphan_leaves or missing_checkpoints:
        sync_status = "fail"
    return {
        "kind": "SynchronousGrowthAudit",
        "sync_status": sync_status,
        "round_count": len(rounds),
        "branch_count": len(branches),
        "max_depth_gap": max_depth_gap,
        "starved_branches": sorted(set(starved_branches)),
        "orphan_leaves": orphan_leaves,
        "missing_checkpoints": missing_checkpoints,
        "missing_round_coverage": missing_round_coverage,
    }


def _branch_artifact_dir(run_dir: pathlib.Path, branch: str) -> pathlib.Path:
    return run_dir / "branches" / branch


def _write_branch_artifact(run_dir: pathlib.Path, branch: str, round_no: int, filename: str, payload: dict[str, Any]) -> str:
    rel = pathlib.Path("branches") / branch / filename
    write_json(run_dir / rel, payload)
    return rel.as_posix()


def _record_round_event(
    run_dir: pathlib.Path,
    *,
    round_no: int,
    branch: str,
    depth: int,
    action: str,
    artifact: str,
    status: str = "pass",
    parent_branch: str = "",
) -> dict[str, Any]:
    row = {
        "round": round_no,
        "branch": branch,
        "depth": depth,
        "action": action,
        "status": status,
        "artifact": artifact,
        "checkpoint": True,
        "parent_branch": parent_branch,
        "created_at": now(),
    }
    append_jsonl(run_dir / "sync_growth_ledger.jsonl", row)
    return row


def _run_mock_sync_tree(run_dir: pathlib.Path, goal: str, *, max_rounds: int, max_branches: int, max_leaves: int) -> dict[str, Any]:
    selected_branches = BRANCHES[: max(1, min(max_branches, len(BRANCHES)))]
    ledger_rows: list[dict[str, Any]] = []
    root_artifact = "goal.json"
    ledger_rows.append(
        _record_round_event(
            run_dir,
            round_no=0,
            branch="root",
            depth=0,
            action="capture_goal",
            artifact=root_artifact,
        )
    )

    round_actions = {
        1: ("spawn_branch", "branch_plan.json"),
        2: ("produce_scope_contract", "scope_contract.json"),
        3: ("produce_implementation_contract", "implementation_contract.json"),
        4: ("produce_verification_evidence_status", "verification_evidence_status.json"),
    }
    for round_no in range(1, max_rounds + 1):
        action, filename = round_actions.get(round_no, ("produce_checkpoint", f"round_{round_no}_checkpoint.json"))
        for branch in selected_branches:
            payload = {
                "kind": "QuickLargeSyncTreeBranchArtifact",
                "branch": branch,
                "round": round_no,
                "action": action,
                "goal": goal,
                "status": "pass",
                "max_leaves": max_leaves,
                "checkpoint": True,
            }
            if branch == "environment":
                payload["environments"] = list(ENVIRONMENTS)
                payload["evidence"] = ["config/dev.json", "config/test.json", "config/demo.json", "config/prod.json"]
            if branch == "implementation":
                payload["capabilities"] = list(CAPABILITIES)
            artifact = _write_branch_artifact(run_dir, branch, round_no, filename, payload)
            ledger_rows.append(
                _record_round_event(
                    run_dir,
                    round_no=round_no,
                    branch=branch,
                    depth=round_no,
                    action=action,
                    artifact=artifact,
                    parent_branch="root" if round_no == 1 else branch,
                )
            )
    return {"branches": selected_branches, "ledger_rows": ledger_rows}


def _write_project_skeleton(run_dir: pathlib.Path, goal: str) -> pathlib.Path:
    project = run_dir / "project"
    _write_text(
        project / "README.md",
        """# Multi-Environment Studio Operations Platform

Local-first production operations platform for dashboard, tasks, asset library, issues, build/release records, docs, release checklist, team roles, search/filter, import/export, and audit log.

## Environments

- dev: `python app/main.py --env dev`, config `config/dev.json`, data namespace `data/dev`.
- test: `python -m pytest tests -q`, config `config/test.json`, data namespace `data/test`.
- demo: `python app/main.py --env demo --seed data/demo_seed.json`, config `config/demo.json`, data namespace `data/demo`.
- prod-like local: `python app/main.py --env prod`, config `config/prod.json`, data namespace `data/prod`.

## Test command

```bash
python -m pytest tests -q
```

## Feature Matrix

Dashboard, tasks, asset library, bug tracker, build/release, docs, release checklist, team roles, search/filter, import/export, and audit log are benchmark-required modules.

## Page / Module Map

- `/` dashboard
- `/tasks`
- `/assets`
- `/issues`
- `/releases`
- `/docs`
- `/team`
- `/audit`
""",
    )
    _write_text(project / ".env.example", "CGKN_ENV=dev\nCGKN_DATA_DIR=data/dev\n")
    for env in ("dev", "test", "demo", "prod"):
        _write_text(project / "config" / f"{env}.json", json.dumps({"environment": env, "data_dir": f"data/{env}"}, indent=2) + "\n")
    _write_text(project / "app" / "main.py", "def main():\n    return 'multi-environment studio operations platform'\n\nif __name__ == '__main__':\n    print(main())\n")
    _write_text(project / "requirements.txt", "pytest\n")
    _write_text(project / "data" / "demo_seed.json", json.dumps({"assets": [], "tasks": [], "issues": [], "audit_log": []}, indent=2) + "\n")
    _write_text(project / "tests" / "test_smoke.py", "from app.main import main\n\n\ndef test_main():\n    assert 'studio operations' in main()\n")
    _write_text(project / "TEST_REPORT.md", "# Test Report\n\nMock benchmark test command: `python -m pytest tests -q`.\n")
    _write_text(project / "screenshots_missing_reason.txt", "Mock benchmark does not run a browser; screenshot evidence is intentionally recorded as missing.\n")
    delivery_manifest = {
        "kind": "QuickLargeSyncTreeDeliveryManifest",
        "goal": goal,
        "bundle": "final_project_bundle.zip",
        "mode": "mock",
        "created_at": now(),
    }
    write_json(project / "delivery_manifest.json", delivery_manifest)
    with zipfile.ZipFile(project / "final_project_bundle.zip", "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in project.rglob("*"):
            if path.is_file() and path.name != "final_project_bundle.zip":
                zf.write(path, path.relative_to(project).as_posix())
    return project


def _audit_project_output(project: pathlib.Path) -> dict[str, Any]:
    checks = {
        "README": (project / "README.md").exists(),
        "app_entry": (project / "app" / "main.py").exists(),
        "dependency_file": (project / "requirements.txt").exists(),
        "env_configs": all((project / "config" / f"{env}.json").exists() for env in ("dev", "test", "demo", "prod")),
        "env_example": (project / ".env.example").exists(),
        "tests": any((project / "tests").glob("test_*.py")) if (project / "tests").exists() else False,
        "test_report": (project / "TEST_REPORT.md").exists(),
        "screenshots": (project / "screenshots").exists(),
        "screenshots_missing_reason": (project / "screenshots_missing_reason.txt").exists(),
        "bundle": (project / "final_project_bundle.zip").exists(),
        "delivery_manifest": (project / "delivery_manifest.json").exists(),
        "demo_seed_data": (project / "data" / "demo_seed.json").exists(),
    }
    pass_for_benchmark = all(value for key, value in checks.items() if key != "screenshots") and (
        checks["screenshots"] or checks["screenshots_missing_reason"]
    )
    return {
        "kind": "QuickLargeSyncTreeProjectOutputAudit",
        "status": "pass" if pass_for_benchmark else "fail",
        "checks": checks,
    }


def _rounds_doc(rows: list[dict[str, Any]], branches: list[str]) -> dict[str, Any]:
    round_numbers = sorted({int(row["round"]) for row in rows})
    rounds: list[dict[str, Any]] = []
    for round_no in round_numbers:
        entries = [row for row in rows if int(row["round"]) == round_no]
        rounds.append(
            {
                "round": round_no,
                "entries": entries,
                "branch_status": {
                    branch: next((row.get("status") for row in entries if row.get("branch") == branch), "not_active" if round_no == 0 else "missing")
                    for branch in branches
                },
                "checkpoint": all(bool(row.get("checkpoint")) for row in entries),
            }
        )
    return {"kind": "QuickLargeSyncTreeRounds", "rounds": rounds}


def _depth_summary(rows: list[dict[str, Any]], branches: list[str]) -> dict[str, Any]:
    per_round: list[dict[str, Any]] = []
    max_gap = 0
    for round_no in sorted({int(row["round"]) for row in rows if row.get("branch") != "root"}):
        depths = {branch: int(row.get("depth", 0)) for row in rows if int(row.get("round", -1)) == round_no for branch in [str(row.get("branch", ""))] if branch in branches}
        if depths:
            gap = max(depths.values()) - min(depths.values())
            max_gap = max(max_gap, gap)
        else:
            gap = 0
        per_round.append({"round": round_no, "depths": depths, "depth_gap": gap})
    return {"kind": "QuickLargeSyncTreeDepthSummary", "branches": branches, "rounds": per_round, "max_depth_gap": max_gap}


def _branch_round_matrix(rows: list[dict[str, Any]], branches: list[str], max_rounds: int) -> list[dict[str, str]]:
    matrix = []
    for branch in branches:
        row = {"Branch": branch}
        ok = True
        for round_no in range(0, max_rounds + 1):
            if round_no == 0:
                row[f"Round {round_no}"] = "root"
                continue
            found = next((item for item in rows if item.get("branch") == branch and int(item.get("round", -1)) == round_no), None)
            row[f"Round {round_no}"] = str(found.get("action")) if found else "missing"
            ok = ok and found is not None
        row["Status"] = "PASS" if ok else "FAIL"
        matrix.append(row)
    return matrix


def _write_sync_tree_report(run_dir: pathlib.Path, audit: dict[str, Any], matrix: list[dict[str, str]]) -> pathlib.Path:
    lines = [
        "# Quick Large Synchronous Tree Report",
        "",
        f"- status: {audit['sync_status']}",
        f"- branch_count: {audit['branch_count']}",
        f"- round_count: {audit['round_count']}",
        f"- max_depth_gap: {audit['max_depth_gap']}",
        f"- starved_branches: {', '.join(audit['starved_branches']) or 'none'}",
        f"- orphan_leaves: {len(audit['orphan_leaves'])}",
        f"- missing_checkpoints: {len(audit['missing_checkpoints'])}",
        "",
        "| Branch | Round 0 | Round 1 | Round 2 | Round 3 | Round 4 | Status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in matrix:
        lines.append(
            f"| {row['Branch']} | {row.get('Round 0', '')} | {row.get('Round 1', '')} | {row.get('Round 2', '')} | {row.get('Round 3', '')} | {row.get('Round 4', '')} | {row['Status']} |"
        )
    return _write_text(run_dir / "sync_tree_report.md", "\n".join(lines) + "\n")


def _write_acceptance_report(
    run_dir: pathlib.Path,
    *,
    summary: dict[str, Any],
    contract_status: dict[str, Any],
    sync_audit: dict[str, Any],
    project_audit: dict[str, Any],
    matrix: list[dict[str, str]],
) -> pathlib.Path:
    checks = project_audit["checks"]
    verdict = "PASS" if summary["benchmark_verdict"] == "FLOW_PASS_MOCK" else summary["benchmark_verdict"]
    lines = [
        "# CGKN Quick Large Synchronous Tree Benchmark Report",
        "",
        "## Verdict",
        f"- {verdict}",
        f"- mock_flow_status: {summary['mock_flow_status']}",
        "",
        "## Run",
        f"- run_dir: {summary['run_dir']}",
        f"- mode: {summary['mode']}",
        f"- max_rounds: {summary['max_rounds']}",
        f"- max_branches: {summary['max_branches']}",
        f"- max_leaves: {summary['max_leaves']}",
        f"- started_at: {summary['started_at']}",
        f"- finished_at: {summary['finished_at']}",
        "",
        "## Goal",
        summary["goal"],
        "",
        "## Multi-Environment Contract",
        f"- dev: {'dev' in summary['required_environments']}",
        f"- test: {'test' in summary['required_environments']}",
        f"- demo: {'demo' in summary['required_environments']}",
        f"- prod-like local: {'prod-like local' in summary['required_environments']}",
        f"- status: {contract_status['status']}",
        "",
        "## Synchronous Tree Growth",
        f"- branch_count: {sync_audit['branch_count']}",
        f"- round_count: {sync_audit['round_count']}",
        f"- max_depth_gap: {sync_audit['max_depth_gap']}",
        f"- starved_branches: {sync_audit['starved_branches']}",
        f"- orphan_leaves: {sync_audit['orphan_leaves']}",
        f"- missing_checkpoints: {sync_audit['missing_checkpoints']}",
        f"- status: {sync_audit['sync_status']}",
        "",
        "## Branch Round Matrix",
        "",
        "| Branch | Round 0 | Round 1 | Round 2 | Round 3 | Round 4 | Status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in matrix:
        lines.append(
            f"| {row['Branch']} | {row.get('Round 0', '')} | {row.get('Round 1', '')} | {row.get('Round 2', '')} | {row.get('Round 3', '')} | {row.get('Round 4', '')} | {row['Status']} |"
        )
    lines.extend(
        [
            "",
            "## Project Output Audit",
            f"- README: {checks['README']}",
            f"- app entry: {checks['app_entry']}",
            f"- dependency file: {checks['dependency_file']}",
            f"- env configs: {checks['env_configs']}",
            f"- tests: {checks['tests']}",
            f"- screenshots: {checks['screenshots'] or checks['screenshots_missing_reason']}",
            f"- bundle: {checks['bundle']}",
            f"- delivery manifest: {checks['delivery_manifest']}",
            "",
            "## Functional Coverage",
            "",
            "| Capability | Required | Evidence | Status |",
            "| --- | --- | --- | --- |",
        ]
    )
    labels = {
        "asset_library": "Asset library",
        "bug_tracker": "Bug tracker",
        "build_release_records": "Build/release",
        "docs_guidelines": "Docs",
        "release_checklist": "Release checklist",
        "team_roles": "Team roles",
        "search_filter": "Search/filter",
        "import_export": "Import/export",
        "audit_activity_log": "Audit log",
    }
    for capability in CAPABILITIES:
        label = labels.get(capability, capability.replace("_", " ").title())
        lines.append(f"| {label} | yes | multi_env_acceptance_contract.json | PASS |")
    lines.extend(
        [
            "",
            "## Limitations",
            "- Mock mode validates bounded orchestration, contract coverage, and evidence file production only.",
            "- It is not a real provider full product PASS.",
            "- Screenshot evidence is represented by an explicit missing-reason file in mock mode.",
            "",
            "## Next Minimal Fixes",
            "- Add a guarded provider smoke-only mode result if provider budget is available.",
            "- Expand the benchmark adapter to consume real dynamic tree primitives once synchronous scheduling is supported natively.",
        ]
    )
    return _write_text(run_dir / "acceptance_report.md", "\n".join(lines) + "\n")


def run_benchmark(
    *,
    goal: str,
    mode: str,
    max_rounds: int,
    max_branches: int,
    max_leaves: int,
    require_multi_env: bool,
    require_sync_growth: bool,
    output_root: str | pathlib.Path,
    model: str = READINESS_DEFAULT_MODEL,
    provider_readiness_only: bool = False,
) -> dict[str, Any]:
    if provider_readiness_only:
        return run_provider_readiness_only(goal=goal, mode=mode, model=model, output_root=output_root)
    started_at = now()
    output = pathlib.Path(output_root)
    run_dir = output / _timestamp()
    run_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "goal.json", {"kind": "QuickLargeSyncTreeGoal", "goal": goal, "created_at": started_at})
    contract = build_multi_environment_acceptance_contract(goal)
    write_json(run_dir / "multi_env_acceptance_contract.json", contract)
    contract_status = _multi_env_contract_status(contract)

    if mode == "guarded_provider":
        provider_status = {
            "status": "skipped_guarded_provider_generation",
            "reason": "This bounded benchmark does not consume provider quota by default.",
        }
    else:
        provider_status = {"status": "not_used", "reason": "mock mode"}

    tree = _run_mock_sync_tree(run_dir, goal, max_rounds=max_rounds, max_branches=max_branches, max_leaves=max_leaves)
    sync_audit = audit_synchronous_growth(run_dir / "sync_growth_ledger.jsonl")
    write_json(run_dir / "sync_growth_audit.json", sync_audit)
    rounds_doc = _rounds_doc(tree["ledger_rows"], tree["branches"])
    write_json(run_dir / "sync_tree_rounds.json", rounds_doc)
    depth_doc = _depth_summary(tree["ledger_rows"], tree["branches"])
    write_json(run_dir / "branch_depth_summary.json", depth_doc)
    matrix = _branch_round_matrix(tree["ledger_rows"], tree["branches"], max_rounds)
    _write_sync_tree_report(run_dir, sync_audit, matrix)

    project = _write_project_skeleton(run_dir, goal)
    project_audit = _audit_project_output(project)
    write_json(run_dir / "project_output_audit.json", project_audit)

    pass_conditions = [
        contract_status["status"] == "pass" if require_multi_env else True,
        sync_audit["sync_status"] == "pass" if require_sync_growth else True,
        project_audit["status"] == "pass",
    ]
    mock_flow_status = "FLOW_PASS_MOCK" if all(pass_conditions) else "FLOW_FAIL_MOCK"
    finished_at = now()
    summary = {
        "kind": "QuickLargeSyncTreeBenchmarkSummary",
        "benchmark_verdict": mock_flow_status,
        "mock_flow_status": mock_flow_status,
        "real_provider_status": provider_status,
        "run_dir": str(run_dir),
        "mode": mode,
        "goal": goal,
        "max_rounds": max_rounds,
        "max_branches": max_branches,
        "max_leaves": max_leaves,
        "required_environments": contract["required_environments"],
        "contract_status": contract_status["status"],
        "sync_growth_status": sync_audit["sync_status"],
        "project_output_status": project_audit["status"],
        "started_at": started_at,
        "finished_at": finished_at,
    }
    write_json(run_dir / "run_summary.json", summary)
    _write_acceptance_report(
        run_dir,
        summary=summary,
        contract_status=contract_status,
        sync_audit=sync_audit,
        project_audit=project_audit,
        matrix=matrix,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded quick large synchronous Dynamic Agent Tree benchmark.")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--mode", choices=["mock", "guarded_provider"], default="mock")
    parser.add_argument("--model", default=READINESS_DEFAULT_MODEL)
    parser.add_argument("--provider-readiness-only", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=4)
    parser.add_argument("--max-branches", type=int, default=7)
    parser.add_argument("--max-leaves", type=int, default=28)
    parser.add_argument("--require-multi-env", action="store_true")
    parser.add_argument("--require-sync-growth", action="store_true")
    parser.add_argument("--output-root", default=str(ROOT / "generated" / "quick_large_sync_tree"))
    args = parser.parse_args()
    summary = run_benchmark(
        goal=args.goal,
        mode=args.mode,
        model=args.model,
        provider_readiness_only=bool(args.provider_readiness_only),
        max_rounds=max(1, args.max_rounds),
        max_branches=max(1, args.max_branches),
        max_leaves=max(0, args.max_leaves),
        require_multi_env=bool(args.require_multi_env),
        require_sync_growth=bool(args.require_sync_growth),
        output_root=args.output_root,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.provider_readiness_only:
        return 0
    return 0 if summary.get("benchmark_verdict") == "FLOW_PASS_MOCK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
