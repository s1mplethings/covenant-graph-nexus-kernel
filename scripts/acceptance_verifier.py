from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import canonical_evidence_hash
from scripts import formal_gate_registry
from scripts import goal_acceptance


KIND = "CGKNFinalVerdict"
SCHEMA_VERSION = "1.0"
FILE_NAME = "final_verdict.json"
PRODUCER = "scripts/acceptance_verifier.py"
PASS = "PASS"
TELEGRAM_DEPENDENT_GATES = {
    "user_review",
    "delivery_manifest",
    "delivery_receipt",
    "live_provider_e2e",
}
PROVIDER_DEPENDENT_GATES = {"provider_causal_trace", "live_provider_e2e"}
REQUIRED_GATES = (
    "test_execution",
    "customer_runtime",
    "visual_evidence",
    "media_evidence",
    "user_review",
    "delivery_manifest",
    "delivery_receipt",
    "leaf_profile",
    "workspace_truth",
    "full_all",
    "replan",
    "recovery",
    "provider_causal_trace",
    "collaboration_timing",
    "startup_profile",
    "deterministic_e2e",
    "live_provider_e2e",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _write(path: pathlib.Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _evidence_status(document: dict[str, Any]) -> str:
    return str(document.get("overall_status") or document.get("status") or "NOT_EVALUATED").upper()


def _aggregate_status(gates: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    internal_failures: list[str] = []
    blockers: list[str] = []
    for name, item in gates.items():
        status = str(item.get("status", "NOT_EVALUATED")).upper()
        if name in TELEGRAM_DEPENDENT_GATES and status.startswith("BLOCKED"):
            blockers.append(str(item.get("blocker_code") or "BLOCKED_TELEGRAM_TEST_CHAT"))
        elif name in PROVIDER_DEPENDENT_GATES and status == "BLOCKED_PROVIDER":
            blockers.append(str(item.get("blocker_code") or "BLOCKED_PROVIDER"))
        elif status != PASS:
            internal_failures.append(name)
    statuses = {str(item.get("status", "")).upper() for item in gates.values()}
    internal_statuses = {
        str(item.get("status", "")).upper()
        for name, item in gates.items()
        if name not in TELEGRAM_DEPENDENT_GATES | PROVIDER_DEPENDENT_GATES
    }
    if "FAIL" in statuses:
        overall = "FAIL"
    elif internal_failures or internal_statuses & {"NEEDS_REWORK", "NOT_EVALUATED", "PASS_WITH_LIMITS"}:
        overall = "NEEDS_REWORK"
    elif "BLOCKED_PROVIDER" in statuses:
        overall = "BLOCKED_PROVIDER"
    elif any(status.startswith("BLOCKED") for status in statuses):
        overall = "BLOCKED"
    else:
        overall = PASS
    return overall, sorted(set(internal_failures)), sorted(set(blockers))


def _inspect_goal_support(context: dict[str, Any] | None) -> dict[str, Any]:
    values = context or {}
    run_value = str(values.get("production_run_dir", "")).strip()
    project_value = str(values.get("candidate_dir", "")).strip()
    run = pathlib.Path(run_value).resolve() if run_value else None
    receipt = run / "artifacts" / goal_acceptance.FILE_NAME if run else None
    inspection = goal_acceptance.inspect_goal_acceptance(
        receipt,
        project_dir=project_value or None,
        run_dir=run,
        canonical_test_evidence_ref=(
            pathlib.Path(project_value).resolve() / "test_execution.json"
            if project_value
            else None
        ),
    )
    applicable = bool(inspection.get("applicable"))
    readable = bool(receipt and receipt.is_file() and not receipt.is_symlink())
    return {
        "status": str(inspection.get("status", "NEEDS_REWORK")).upper(),
        "applicable": applicable,
        "ref": str(receipt) if applicable and receipt else "",
        "file_hash": canonical_evidence_hash.sha256_file(receipt) if applicable and readable else "",
        "formal_delivery_authority": False,
        "inspection": inspection,
    }


def produce_canonical_final_verdict(
    acceptance_dir: str | pathlib.Path,
    *,
    run_id: str,
    candidate_id: str,
    candidate_hash: str,
    commit_sha: str,
    upstream_refs: dict[str, str | pathlib.Path],
    inspection_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(acceptance_dir).resolve()
    gates: dict[str, Any] = {}
    failures: list[str] = []
    for name in REQUIRED_GATES:
        ref_value = upstream_refs.get(name)
        path = pathlib.Path(ref_value).resolve() if ref_value else pathlib.Path()
        document = _read(path) if ref_value else {}
        formal_inspection: dict[str, Any] = {}
        if document.get("producer") == formal_gate_registry.FORMAL_GATE_STATUS_PRODUCER:
            formal_inspection = formal_gate_registry.inspect_gate_status(
                name,
                path,
                expected_identity={
                    "run_id": run_id,
                    "candidate_id": candidate_id,
                    "candidate_hash": candidate_hash,
                    "commit_sha": commit_sha,
                },
                context=inspection_context,
            )
            status = str(formal_inspection.get("status", "NOT_EVALUATED")).upper()
        else:
            formal_inspection = {
                "status": "NEEDS_REWORK",
                "failures": ["upstream_not_formal_gate_status"],
            }
            status = "NEEDS_REWORK"
        file_hash = canonical_evidence_hash.sha256_file(path) if ref_value and path.is_file() and not path.is_symlink() else ""
        gates[name] = {
            "status": status,
            "ref": str(path) if ref_value else "",
            "file_hash": file_hash,
            "blocker_code": str(document.get("blocker_code", "")),
            "formal_inspection": formal_inspection,
        }
        if not ref_value or not document:
            failures.append(f"missing_gate:{name}")
        elif status != PASS:
            failures.append(f"gate_not_pass:{name}:{status}")
        for field, expected in (
            ("run_id", run_id),
            ("candidate_id", candidate_id),
            ("candidate_hash", candidate_hash),
            ("commit_sha", commit_sha),
        ):
            if str(document.get(field, "")) != str(expected):
                failures.append(f"gate_identity_mismatch:{name}:{field}")
    overall, internal_failures, blockers = _aggregate_status(gates)
    goal_support = _inspect_goal_support(inspection_context)
    if goal_support["applicable"] and goal_support["status"] != PASS:
        failures.append(f"goal_acceptance_not_pass:{goal_support['status']}")
        if overall != "FAIL":
            overall = "NEEDS_REWORK"
    if failures and overall == PASS:
        overall = "NEEDS_REWORK"
    verdict: dict[str, Any] = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "commit_sha": commit_sha,
        "producer": PRODUCER,
        "created_at": _now(),
        "status": overall,
        "artifact_hash": "",
        "required_gates": list(REQUIRED_GATES),
        "upstream_gates": gates,
        "support_prerequisites": {"goal_acceptance": goal_support},
        "overall_status": overall,
        "failures": sorted(set(failures)),
        "internal_failures": internal_failures,
        "blockers": blockers,
    }
    verdict["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(verdict, ("artifact_hash",))
    _write(root / FILE_NAME, verdict)
    return verdict


def inspect_canonical_final_verdict(
    acceptance_dir: str | pathlib.Path,
    *,
    expected_run_id: str,
    expected_candidate_id: str,
    expected_candidate_hash: str,
    expected_commit_sha: str,
    expected_upstream_refs: dict[str, str | pathlib.Path],
    inspection_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(acceptance_dir).resolve()
    path = root / FILE_NAME
    failures: list[str] = []
    if not path.is_file() or path.is_symlink():
        return {"status": "NEEDS_REWORK", "failures": ["final_verdict_path_invalid"], "verdict_path": str(path)}
    document = _read(path)
    if document.get("kind") != KIND or document.get("schema_version") != SCHEMA_VERSION or document.get("producer") != PRODUCER:
        failures.append("final_verdict_contract")
    if document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("artifact_hash_mismatch")
    for field, expected in (
        ("run_id", expected_run_id),
        ("candidate_id", expected_candidate_id),
        ("candidate_hash", expected_candidate_hash),
        ("commit_sha", expected_commit_sha),
    ):
        if str(document.get(field, "")) != str(expected):
            failures.append(f"verdict_identity_mismatch:{field}")
    if document.get("required_gates") != list(REQUIRED_GATES):
        failures.append("required_gates_mismatch")
    gates = document.get("upstream_gates", {})
    if not isinstance(gates, dict) or set(gates) != set(REQUIRED_GATES):
        failures.append("upstream_gates_mismatch")
        gates = {}
    nonpass: list[str] = []
    for name in REQUIRED_GATES:
        expected_value = expected_upstream_refs.get(name)
        if not expected_value:
            failures.append(f"expected_upstream_ref_missing:{name}")
            nonpass.append(name)
            continue
        expected_path = pathlib.Path(expected_value).resolve()
        gate = gates.get(name, {}) if isinstance(gates.get(name), dict) else {}
        if gate.get("ref") != str(expected_path):
            failures.append(f"upstream_ref_mismatch:{name}")
        upstream = _read(expected_path)
        if not expected_path.is_file() or expected_path.is_symlink() or not upstream:
            failures.append(f"upstream_unreadable:{name}")
            nonpass.append(name)
            continue
        if gate.get("file_hash") != canonical_evidence_hash.sha256_file(expected_path):
            failures.append(f"upstream_hash_mismatch:{name}")
        if upstream.get("producer") == formal_gate_registry.FORMAL_GATE_STATUS_PRODUCER:
            actual_inspection = formal_gate_registry.inspect_gate_status(
                name,
                expected_path,
                expected_identity={
                    "run_id": expected_run_id,
                    "candidate_id": expected_candidate_id,
                    "candidate_hash": expected_candidate_hash,
                    "commit_sha": expected_commit_sha,
                },
                context=inspection_context,
            )
            status = str(actual_inspection.get("status", "NOT_EVALUATED")).upper()
        else:
            status = "NEEDS_REWORK"
            failures.append(f"upstream_not_formal_gate_status:{name}")
        if gate.get("status") != status:
            failures.append(f"upstream_status_mismatch:{name}")
        if status != PASS:
            nonpass.append(name)
        for field, expected in (
            ("run_id", expected_run_id),
            ("candidate_id", expected_candidate_id),
            ("candidate_hash", expected_candidate_hash),
            ("commit_sha", expected_commit_sha),
        ):
            if str(upstream.get(field, "")) != str(expected):
                failures.append(f"upstream_identity_mismatch:{name}:{field}")
    claimed = str(document.get("overall_status", ""))
    support = document.get("support_prerequisites", {})
    goal_support = support.get("goal_acceptance", {}) if isinstance(support, dict) else {}
    if not isinstance(goal_support, dict):
        goal_support = {}
    actual_goal_support = _inspect_goal_support(inspection_context)
    for field in ("status", "applicable", "ref", "file_hash", "formal_delivery_authority"):
        if goal_support.get(field) != actual_goal_support.get(field):
            failures.append(f"goal_acceptance_support_mismatch:{field}")
    if goal_support.get("inspection") != actual_goal_support.get("inspection"):
        failures.append("goal_acceptance_support_mismatch:inspection")
    nonpass_support: list[str] = []
    if actual_goal_support["applicable"] and actual_goal_support["status"] != PASS:
        nonpass_support.append("goal_acceptance")
    if claimed != document.get("status"):
        failures.append("overall_status_mismatch")
    if claimed == PASS and (failures or nonpass):
        failures.append("false_pass")
    if claimed != PASS and not failures and not nonpass:
        failures.append("false_nonpass")
    recomputed, internal_failures, blockers = _aggregate_status(
        {
            name: {
                "status": str((gates.get(name) or {}).get("status", "NOT_EVALUATED")),
                "blocker_code": str(_read(pathlib.Path(expected_upstream_refs[name]).resolve()).get("blocker_code", ""))
                if expected_upstream_refs.get(name)
                else "",
            }
            for name in REQUIRED_GATES
        }
    )
    if nonpass_support and recomputed != "FAIL":
        recomputed = "NEEDS_REWORK"
    if claimed != recomputed:
        failures.append("status_priority_mismatch")
    if document.get("internal_failures", []) != internal_failures:
        failures.append("internal_failures_mismatch")
    if document.get("blockers", []) != blockers:
        failures.append("blockers_mismatch")
    inspection_status = PASS if not failures and not nonpass and not nonpass_support and claimed == PASS else (
        claimed if not failures and (nonpass or nonpass_support) and claimed in {"NEEDS_REWORK", "BLOCKED", "BLOCKED_PROVIDER"} else "NEEDS_REWORK"
    )
    return {
        "status": inspection_status,
        "failures": sorted(set(failures)),
        "nonpass_gates": sorted(set(nonpass)),
        "nonpass_support": sorted(set(nonpass_support)),
        "verdict_path": str(path),
        "verdict": document,
    }


produce = produce_canonical_final_verdict
inspect = inspect_canonical_final_verdict
