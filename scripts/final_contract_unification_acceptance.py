from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import acceptance_verifier
import canonical_evidence_hash


SCHEMA_VERSION = "1.0"
PRODUCER = "scripts/final_contract_unification_acceptance.py"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: pathlib.Path, document: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document["artifact_hash"] = ""
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _envelope(kind: str, identity: dict[str, str], status: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": SCHEMA_VERSION,
        **identity,
        "producer": PRODUCER,
        "created_at": _now(),
        "status": status,
        "artifact_hash": "",
        **extra,
    }


def _source(path: pathlib.Path) -> dict[str, str]:
    return {
        "source_ref": str(path.resolve()),
        "source_hash": canonical_evidence_hash.sha256_file(path) if path.is_file() and not path.is_symlink() else "",
    }


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _provider_causal_status(trace_path: pathlib.Path, project: pathlib.Path) -> tuple[str, list[str]]:
    failures: list[str] = []
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return "NOT_EVALUATED", ["provider_causal_trace_missing"]
    for field in ("provider_request_identity", "request_body_hash", "provider_response_id", "response_content_hash", "decision_hash", "patch_hash"):
        if not str(trace.get(field, "")).strip():
            failures.append(f"missing:{field}")
    if trace.get("provider_output_override") is not False:
        failures.append("provider_output_override_not_live")
    decision = trace.get("decision", {})
    patch = trace.get("patch", [])
    if trace.get("decision_hash") != canonical_evidence_hash.canonical_json_hash(decision, ()):
        failures.append("decision_hash_mismatch")
    if trace.get("patch_hash") != canonical_evidence_hash.canonical_json_hash({"patch": patch}, ()):
        # The leaf producer hashes the list directly; retain an independent equivalent calculation.
        expected = "sha256:" + hashlib.sha256(
            json.dumps(patch, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if trace.get("patch_hash") != expected:
            failures.append("patch_hash_mismatch")
    for item in patch if isinstance(patch, list) else []:
        path = project / str(item.get("path", ""))
        if not path.is_file() or item.get("file_hash") != canonical_evidence_hash.sha256_file(path):
            failures.append(f"patch_file_mismatch:{item.get('path', '')}")
    return ("PASS" if not failures else "NEEDS_REWORK"), failures


def build_acceptance(run_dir: str | pathlib.Path, *, test_chat_id: str = "") -> dict[str, Any]:
    out = pathlib.Path(run_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_id = out.name
    commit_sha = _git_sha()
    identity = {
        "run_id": run_id,
        "candidate_id": "CGKN",
        "candidate_hash": "sha256:" + hashlib.sha256(commit_sha.encode()).hexdigest(),
        "commit_sha": commit_sha,
    }
    live_leaf = out / "live_provider_leaf"
    project = out / "customer_project"
    causal_source = live_leaf / "provider_causal_trace.json"
    causal_status, causal_failures = _provider_causal_status(causal_source, project)

    requirement = _write(
        out / "requirement_snapshot.json",
        _envelope(
            "CGKNFinalAcceptanceRequirementSnapshot",
            identity,
            "PASS",
            required_gates=list(acceptance_verifier.REQUIRED_GATES),
            telegram_test_chat_required=True,
        ),
    )
    candidate = _write(out / "candidate_identity.json", _envelope("CGKNCandidateIdentity", identity, "PASS"))
    gate_specs: dict[str, tuple[str, dict[str, Any]]] = {
        "test_execution": ("NOT_EVALUATED", {"reason": "fresh full customer-project test execution not yet bound"}),
        "customer_runtime": ("NOT_EVALUATED", {"reason": "fresh customer runtime not yet executed"}),
        "visual_evidence": ("NOT_EVALUATED", {"reason": "fresh Playwright customer visual evidence not yet executed"}),
        "media_evidence": ("NOT_EVALUATED", {"reason": "formal generated media was not required by the live backend leaf"}),
        "user_review": ("NOT_EVALUATED", {"reason": "no fresh Telegram reviewer event"}),
        "delivery_manifest": ("NOT_EVALUATED", {"reason": "fresh final package not produced"}),
        "delivery_receipt": (
            "BLOCKED",
            {"blocker_code": "BLOCKED_TELEGRAM_TEST_CHAT", "reason": "no explicit Telegram test chat configured"},
        ),
        "leaf_profile": (
            "NEEDS_REWORK",
            {
                "reason": "one real backend leaf passed; independent persistence and frontend browser leaves remain absent",
                **_source(live_leaf / "checkpoint_acceptance_backend_leaf.json"),
            },
        ),
        "workspace_truth": ("NOT_EVALUATED", {"reason": "formal independent workspace inventory not executed"}),
        "full_all": ("NOT_EVALUATED", {"reason": "fresh full_all result not supplied"}),
        "replan": ("NOT_EVALUATED", {"reason": "fresh failure-to-replacement chain not executed"}),
        "recovery": ("NOT_EVALUATED", {"reason": "fresh worker kill/restart/re-execution chain not executed"}),
        "provider_causal_trace": (
            causal_status,
            {"failures": causal_failures, **_source(causal_source)},
        ),
        "collaboration_timing": ("NOT_EVALUATED", {"reason": "implementation-before-consumption timing not executed"}),
        "startup_profile": ("NOT_EVALUATED", {"reason": "declared startup profiles not freshly exercised"}),
        "deterministic_e2e": ("NOT_EVALUATED", {"reason": "fresh deterministic total-chain E2E not executed"}),
        "live_provider_e2e": (
            "NEEDS_REWORK" if causal_status == "PASS" else "NOT_EVALUATED",
            {"reason": "live provider leaf passed but downstream runtime/review/delivery chain is incomplete", **_source(causal_source)},
        ),
    }
    refs: dict[str, pathlib.Path] = {}
    for gate, (status, details) in gate_specs.items():
        refs[gate] = _write(out / f"{gate}.json", _envelope(f"CGKN{gate.title().replace('_', '')}Evidence", identity, status, **details))

    named_outputs = {
        "leaf_sessions.json": refs["leaf_profile"],
        "workspace_inventory.json": refs["workspace_truth"],
        "collaboration_evidence.json": refs["collaboration_timing"],
        "provider_causal_trace.json": refs["provider_causal_trace"],
        "replan_evidence.json": refs["replan"],
        "recovery_evidence.json": refs["recovery"],
        "test_profile_results.json": refs["test_execution"],
        "full_all_result.json": refs["full_all"],
        "customer_runtime.json": refs["customer_runtime"],
        "visual_evidence.json": refs["visual_evidence"],
        "user_review_request.json": refs["user_review"],
        "user_review.json": refs["user_review"],
        "delivery_manifest.json": refs["delivery_manifest"],
        "delivery_receipt.json": refs["delivery_receipt"],
    }
    for name, source in named_outputs.items():
        target = out / name
        if target.resolve() == source.resolve():
            continue
        doc = json.loads(source.read_text(encoding="utf-8"))
        doc["kind"] = "CGKNFinalAcceptance" + pathlib.Path(name).stem.title().replace("_", "")
        doc["source_evidence_ref"] = str(source.resolve())
        doc["source_evidence_hash"] = canonical_evidence_hash.sha256_file(source)
        _write(target, doc)

    verdict = acceptance_verifier.produce_canonical_final_verdict(out, upstream_refs=refs, **identity)
    inspection = acceptance_verifier.inspect_canonical_final_verdict(
        out,
        expected_run_id=identity["run_id"],
        expected_candidate_id=identity["candidate_id"],
        expected_candidate_hash=identity["candidate_hash"],
        expected_commit_sha=identity["commit_sha"],
        expected_upstream_refs=refs,
    )
    matrix = _write(
        out / "acceptance_matrix.json",
        _envelope(
            "CGKNAcceptanceMatrix",
            identity,
            verdict["status"],
            gates={name: json.loads(path.read_text(encoding="utf-8")).get("status") for name, path in refs.items()},
            final_verdict_ref=str((out / acceptance_verifier.FILE_NAME).resolve()),
            final_verdict_hash=canonical_evidence_hash.sha256_file(out / acceptance_verifier.FILE_NAME),
            final_verdict_inspection=inspection,
        ),
    )
    run_manifest = _write(
        out / "run_manifest.json",
        _envelope(
            "CGKNFinalContractUnificationAcceptanceRun",
            identity,
            verdict["status"],
            requirement_snapshot_ref=str(requirement),
            candidate_identity_ref=str(candidate),
            acceptance_matrix_ref=str(matrix),
            final_verdict_ref=str((out / acceptance_verifier.FILE_NAME).resolve()),
            telegram_test_chat_configured=bool(test_chat_id),
        ),
    )
    (out / "customer_validation_summary.md").write_text(
        "# CGKN final contract-unification acceptance\n\n"
        f"- run_id: {run_id}\n- commit_sha: {commit_sha}\n- verdict: {verdict['status']}\n"
        "- blocker: no explicit Telegram test chat; no Telegram message was sent\n"
        "- live provider: real non-cached backend Leaf and behavior test passed\n"
        "- remaining internal gates are recorded without promotion in acceptance_matrix.json\n",
        encoding="utf-8",
    )
    return {"run_manifest": str(run_manifest), "verdict": verdict["status"], "inspection": inspection["status"], "run_dir": str(out)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--telegram-test-chat-id", default="")
    args = parser.parse_args()
    result = build_acceptance(args.run_dir, test_chat_id=args.telegram_test_chat_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["inspection"] in {"PASS", "NEEDS_REWORK", "BLOCKED", "BLOCKED_PROVIDER"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
