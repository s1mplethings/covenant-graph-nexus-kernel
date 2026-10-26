#!/usr/bin/env python3
"""Deterministic projection of existing project evidence into Usage Beta truth."""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


GATE_ORDER = (
    "goal_fidelity",
    "runnable",
    "core_capability",
    "primary_user_path",
    "delivery",
)
PASS = "PASS"
FAIL_STATES = {"FAIL", "NEEDS_REWORK"}
UNEVALUATED_STATES = {"", "NOT_EVALUATED", "BLOCKED", "BLOCKED_ENVIRONMENT", "BLOCKED_PROVIDER", "BLOCKED_LOCAL_MODEL"}
EXECUTION_MODES = {"codex_surrogate", "live"}


def _status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status", "")
    return str(value or "").strip().upper()


def resolve_usage_beta_mode(*, requested_mode: str | None, usage_beta: bool) -> str:
    """Default only an omitted Usage Beta mode; never replace an explicit mode."""
    mode = str(requested_mode or "").strip().lower()
    if mode:
        if mode not in {"live", "codex_surrogate", "deterministic_replay"}:
            raise ValueError(f"unsupported provider mode: {mode}")
        return mode
    return "codex_surrogate" if usage_beta else "live"


def evaluate_usage_beta(
    *,
    gates: dict[str, Any],
    execution_mode: str,
    repository_global_verdict: str,
    global_limitations: list[str] | None = None,
    external_executor_required: bool = False,
    external_executor_project_status: str = "NOT_EVALUATED",
) -> dict[str, Any]:
    """Project the five hard gates without acquiring acceptance authority."""
    mode = str(execution_mode or "").strip().lower()
    if mode not in EXECUTION_MODES:
        raise ValueError("Usage Beta evidence requires live or codex_surrogate execution")
    normalized = {name: _status(gates.get(name)) for name in GATE_ORDER}
    external_status = _status(external_executor_project_status)
    findings: list[dict[str, str]] = []
    for name in GATE_ORDER:
        status = normalized[name]
        if status in FAIL_STATES:
            findings.append({"gate": name, "status": "NEEDS_REWORK", "code": f"{name.upper()}_FAILED"})
        elif status != PASS:
            findings.append({"gate": name, "status": "BLOCKED", "code": f"{name.upper()}_NOT_EVALUATED"})
        if name == "core_capability" and external_executor_required and external_status != PASS:
            finding_status = "NEEDS_REWORK" if external_status in FAIL_STATES else "BLOCKED"
            findings.append({
                "gate": "core_capability",
                "status": finding_status,
                "code": "PROJECT_EXTERNAL_EXECUTOR_INTEGRATION_FAILED" if finding_status == "NEEDS_REWORK" else "PROJECT_EXTERNAL_EXECUTOR_INTEGRATION_NOT_EVALUATED",
            })
    if any(item["status"] == "NEEDS_REWORK" for item in findings):
        status = "NEEDS_REWORK"
    elif findings:
        status = "BLOCKED"
    else:
        status = "PASS"
    primary = findings[0]["code"] if findings else ""
    return {
        "kind": "CGKNUsageBetaVerdict",
        "schema_version": "1.0",
        "status": status,
        "usage_beta_state": f"USAGE_BETA_{'READY' if status == 'PASS' else status}",
        **normalized,
        "execution_mode": mode,
        "repository_global_verdict": str(repository_global_verdict or "NOT_EVALUATED").strip().upper(),
        "global_limitations": list(dict.fromkeys(str(item) for item in (global_limitations or []) if str(item).strip())),
        "external_executor_required": bool(external_executor_required),
        "external_executor_project_status": external_status,
        "primary_blocker": primary,
        "secondary_findings": [item["code"] for item in findings[1:]],
        "release_ready": False,
        "commercial_ready": False,
        "formal_release_verdict": "NOT_EVALUATED",
        "formal_acceptance_authority": False,
        "packaging_authority": False,
        "delivery_authority": False,
    }


def write_usage_beta_verdict(run_dir: pathlib.Path, verdict: dict[str, Any]) -> pathlib.Path:
    output = run_dir / "artifacts" / "usage_beta_acceptance" / "usage_beta_verdict.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Project existing evidence into a non-release Usage Beta verdict.")
    parser.add_argument("--evidence", required=True, help="JSON object containing gates and status context")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    evidence = json.loads(pathlib.Path(args.evidence).read_text(encoding="utf-8"))
    verdict = evaluate_usage_beta(
        gates=evidence.get("gates", {}),
        execution_mode=evidence.get("execution_mode", ""),
        repository_global_verdict=evidence.get("repository_global_verdict", "NOT_EVALUATED"),
        global_limitations=evidence.get("global_limitations", []),
        external_executor_required=bool(evidence.get("external_executor_required", False)),
        external_executor_project_status=evidence.get("external_executor_project_status", "NOT_EVALUATED"),
    )
    output = write_usage_beta_verdict(pathlib.Path(args.run_dir), verdict)
    print(json.dumps({"status": verdict["status"], "primary_blocker": verdict["primary_blocker"], "output": str(output)}, ensure_ascii=False))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
