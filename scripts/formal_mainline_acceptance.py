from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import acceptance_verifier
from scripts import canonical_evidence_hash
from scripts import formal_gate_registry
from scripts import production_candidate_provenance

PRODUCER = "scripts/formal_mainline_acceptance.py"
SCHEMA_VERSION = "1.0"
CODEX_GATES = {"user_review", "delivery_manifest", "delivery_receipt"}
PRODUCTION_MAINLINE = {
    "entry": "scripts.codex_conversation.start_generation_from_income",
    "default_generation": "scripts.codex_conversation.run_provider_generation_job",
    "execution_chain": [
        "scripts.codex_conversation.run_provider_execute_with_retries",
        "provider output validation",
        "scripts.post_build_finalize.run",
        "scripts.real_test_execution.run_tests",
        "scripts.customer_runtime_runner.run",
        "scripts.browser_visual_evidence.finalize_evidence",
        "scripts.canonical_user_review",
        "scripts.local_packager.package_project",
        "scripts.codex_conversation.evaluate_public_delivery_gate",
        "scripts.codex_conversation.send_delivery_from_manifest",
        "scripts.canonical_delivery_receipt.produce_canonical_delivery_receipt",
        "scripts.acceptance_verifier.produce_canonical_final_verdict",
    ],
    "support_lane": [
        "scripts.codex_conversation.run_agent_generation_job",
        "scripts.dynamic_pipeline_runner.run_dynamic_pipeline",
        "scripts.agent_conversation_loop.run_agent_loop",
    ],
    "diagnostic_only": ["scripts.final_internal_acceptance"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def write_json(path: pathlib.Path, document: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document["artifact_hash"] = ""
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def envelope(kind: str, identity: dict[str, str], status: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": SCHEMA_VERSION,
        **identity,
        "producer": PRODUCER,
        "created_at": now(),
        "status": status,
        "artifact_hash": "",
        **extra,
    }


def _candidate_identity(candidate_dir: pathlib.Path | None, commit_sha: str) -> tuple[dict[str, str], list[str]]:
    failures: list[str] = []
    if candidate_dir is None or not candidate_dir.is_dir():
        return {
            "run_id": "NOT_EVALUATED",
            "candidate_id": "NOT_EVALUATED",
            "candidate_hash": "NOT_EVALUATED",
            "commit_sha": commit_sha,
        }, ["production_candidate_missing"]
    candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate_dir)
    identity_docs = [
        read_json(candidate_dir / name)
        for name in (
            "test_execution.json",
            "customer_runtime.json",
            "visual_evidence.json",
            "user_review_request.json",
            "user_review.json",
            "delivery_manifest.json",
            "delivery_receipt.json",
        )
        if (candidate_dir / name).is_file()
    ]
    run_ids = {str(doc.get("run_id", "")).strip() for doc in identity_docs if str(doc.get("run_id", "")).strip()}
    candidate_ids = {
        str(doc.get("candidate_id", "")).strip()
        for doc in identity_docs
        if str(doc.get("candidate_id", "")).strip()
    }
    if len(run_ids) != 1:
        failures.append("production_run_identity_missing_or_mixed")
    if len(candidate_ids) != 1:
        failures.append("production_candidate_identity_missing_or_mixed")
    for doc in identity_docs:
        if doc.get("candidate_hash") != candidate_hash:
            failures.append("candidate_identity_mismatch")
        if doc.get("commit_sha") != commit_sha:
            failures.append("commit_mismatch")
    return {
        "run_id": next(iter(run_ids), "NOT_EVALUATED"),
        "candidate_id": next(iter(candidate_ids), candidate_dir.name),
        "candidate_hash": candidate_hash,
        "commit_sha": commit_sha,
    }, sorted(set(failures))


def _source_for_gate(
    gate: str,
    *,
    candidate_dir: pathlib.Path | None,
    production_run_dir: pathlib.Path | None,
    full_all_result: pathlib.Path | None,
) -> pathlib.Path | None:
    spec = formal_gate_registry.GATE_SPECS[gate]
    if gate == "full_all":
        return full_all_result
    artifact = str(spec.get("artifact", "")).strip()
    if gate == "provider_causal_trace" and production_run_dir is not None:
        run_source = production_run_dir / artifact
        return run_source if run_source.is_file() else None
    if artifact and candidate_dir is not None:
        candidate_source = candidate_dir / artifact
        if candidate_source.is_file():
            return candidate_source
    if artifact and production_run_dir is not None:
        run_source = production_run_dir / artifact
        if run_source.is_file():
            return run_source
    return None


def _production_provenance(
    candidate_dir: pathlib.Path | None,
    production_run_dir: pathlib.Path | None,
    commit_sha: str,
) -> dict[str, Any]:
    if candidate_dir is None or not candidate_dir.is_dir():
        return {
            "status": "NOT_EVALUATED",
            "failures": ["production_candidate_missing"],
        }
    if production_run_dir is None or not production_run_dir.is_dir():
        return {
            "status": "NOT_EVALUATED",
            "failures": ["production_run_missing"],
        }
    provenance_ref = production_run_dir / production_candidate_provenance.FILE_NAME
    if not provenance_ref.is_file() or provenance_ref.is_symlink():
        return {
            "status": "NOT_EVALUATED",
            "failures": ["canonical_production_candidate_provenance_missing"],
            "provenance_ref": str(provenance_ref),
        }
    return production_candidate_provenance.inspect(
        provenance_ref,
        expected_candidate_dir=candidate_dir,
        expected_production_run_dir=production_run_dir,
        expected_commit_sha=commit_sha,
    )


def _gate_status(
    gate: str,
    *,
    identity: dict[str, str],
    source: pathlib.Path | None,
    codex_test_conversation_configured: bool,
    context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    spec = formal_gate_registry.GATE_SPECS[gate]
    if source is not None:
        inspection = formal_gate_registry.inspect_source(
            gate, source, expected_identity=identity, context=context
        )
        return str(inspection["status"]), inspection
    if gate in CODEX_GATES and not codex_test_conversation_configured:
        return "BLOCKED", {
            "status": "BLOCKED",
            "failures": [],
            "blocker_code": "BLOCKED_USER_REVIEW",
            "reason": "No explicit Codex conversation test chat is configured; no send was attempted.",
        }
    reason = (
        "formal_inspector_unavailable"
        if not spec.get("inspector")
        else "production_artifact_missing"
    )
    return "NOT_EVALUATED", {"status": "NOT_EVALUATED", "failures": [reason], "reason": reason}


def build_acceptance(
    out_dir: str | pathlib.Path,
    *,
    candidate_dir: str | pathlib.Path | None = None,
    production_run_dir: str | pathlib.Path | None = None,
    full_all_result: str | pathlib.Path | None = None,
    codex_test_conversation_id: str = "",
    receipt_expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = pathlib.Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit_sha = git_sha()
    candidate = pathlib.Path(candidate_dir).resolve() if candidate_dir else None
    production_run = pathlib.Path(production_run_dir).resolve() if production_run_dir else None
    full_all = pathlib.Path(full_all_result).resolve() if full_all_result else None
    identity, identity_failures = _candidate_identity(candidate, commit_sha)
    provenance = _production_provenance(candidate, production_run, commit_sha)
    if provenance["status"] == "PASS":
        provenance_identity = provenance.get("identity", {})
        for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha"):
            if identity.get(field) != provenance_identity.get(field):
                identity_failures.append(f"production_provenance_identity_mismatch:{field}")
        identity = {
            field: str(provenance_identity.get(field, ""))
            for field in ("run_id", "candidate_id", "candidate_hash", "commit_sha")
        }
    if provenance["status"] != "PASS":
        identity_failures.append("production_candidate_provenance_not_verified")
        identity_failures = sorted(set(identity_failures))
    repository_identity = {
        "repository_root": str(ROOT),
        "commit_sha": commit_sha,
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
    }
    write_json(
        out / "repository_identity.json",
        envelope(
            "CGKNRepositoryIdentity",
            identity,
            "PASS",
            scope="repository",
            repository_identity=repository_identity,
        ),
    )
    write_json(
        out / "candidate_identity.json",
        envelope(
            "CGKNCandidateIdentity",
            identity,
            "PASS" if not identity_failures else "NOT_EVALUATED",
            scope="candidate",
            candidate_root=str(candidate) if candidate else "",
            identity_failures=identity_failures,
            hash_method="scripts.canonical_evidence_hash.candidate_source_hash",
        ),
    )
    provenance_inspection_ref = write_json(
        out / "production_provenance_inspection.json",
        envelope(
            "CGKNProductionCandidateProvenanceInspection",
            identity,
            str(provenance["status"]),
            **{
                key: value
                for key, value in provenance.items()
                if key not in {"status", "identity"}
            },
        ),
    )
    requirement = write_json(
        out / "requirement_snapshot.json",
        envelope(
            "CGKNFormalAcceptanceRequirementSnapshot",
            identity,
            "NOT_EVALUATED",
            reason="No frozen production requirement snapshot was supplied.",
            required_gates=list(acceptance_verifier.REQUIRED_GATES),
        ),
    )
    registry = write_json(
        out / "gate_registry.json",
        envelope(
            "CGKNFormalGateRegistry",
            identity,
            "PASS",
            gates=formal_gate_registry.GATE_SPECS,
            forbidden_producers=sorted(formal_gate_registry.FORBIDDEN_PRODUCERS),
            production_mainline=PRODUCTION_MAINLINE,
        ),
    )
    refs: dict[str, pathlib.Path] = {}
    gate_results: dict[str, dict[str, Any]] = {}
    context = {
        "production_provenance_ref": str(provenance.get("provenance_ref", "")),
        "candidate_dir": str(candidate) if candidate else "",
        "production_run_dir": str(production_run) if production_run else "",
        **(
            {"delivery_receipt_expectations": receipt_expectations}
            if receipt_expectations
            else {}
        ),
    }
    for gate in acceptance_verifier.REQUIRED_GATES:
        source = _source_for_gate(
            gate,
            candidate_dir=candidate,
            production_run_dir=production_run,
            full_all_result=full_all,
        )
        status, inspection = _gate_status(
            gate,
            identity=identity,
            source=source,
            codex_test_conversation_configured=bool(codex_test_conversation_id),
            context=context,
        )
        spec = formal_gate_registry.GATE_SPECS[gate]
        blocker_code = str(inspection.get("blocker_code", ""))
        document = envelope(
            "CGKNFormalGateStatus",
            identity,
            status,
            gate=gate,
            scope=spec["scope"],
            source_ref=str(source.resolve()) if source else "",
            source_hash=canonical_evidence_hash.sha256_file(source)
            if source and source.is_file() and not source.is_symlink()
            else "",
            source_producer=str(inspection.get("source_producer", "")),
            inspector=str(inspection.get("inspector", spec.get("inspector", ""))),
            inspector_result=inspection.get("inspector_result", inspection),
            production_provenance_ref=str(
                provenance.get("provenance_ref", "")
            )
            if gate
            in formal_gate_registry.PROVENANCE_BOUND_GATES
            | {"provider_causal_trace"}
            else "",
            production_provenance_hash=str(
                provenance.get("provenance_hash", "")
            )
            if gate
            in formal_gate_registry.PROVENANCE_BOUND_GATES
            | {"provider_causal_trace"}
            else "",
            production_provenance_inspection=inspection.get(
                "provenance_inspection", {}
            ),
            failures=inspection.get("failures", []),
            reason=str(inspection.get("reason", "")),
            blocker_code=blocker_code,
        )
        refs[gate] = write_json(out / f"{gate}_gate_status.json", document)
        gate_results[gate] = {
            "status": status,
            "source_ref": document["source_ref"],
            "producer": document["source_producer"],
            "inspector": document["inspector"],
            "failures": document["failures"],
            "blocker_code": blocker_code,
        }
    verdict = acceptance_verifier.produce_canonical_final_verdict(
        out, upstream_refs=refs, inspection_context=context, **identity
    )
    for gate, result in gate_results.items():
        verified = verdict.get("upstream_gates", {}).get(gate, {})
        result["status"] = str(verified.get("status", result["status"]))
        result["formal_inspection"] = verified.get("formal_inspection", {})
    verdict_inspection = acceptance_verifier.inspect_canonical_final_verdict(
        out,
        expected_run_id=identity["run_id"],
        expected_candidate_id=identity["candidate_id"],
        expected_candidate_hash=identity["candidate_hash"],
        expected_commit_sha=identity["commit_sha"],
        expected_upstream_refs=refs,
        inspection_context=context,
    )
    matrix = write_json(
        out / "acceptance_matrix.json",
        envelope(
            "CGKNFormalAcceptanceMatrix",
            identity,
            verdict["status"],
            gates=gate_results,
            internal_failures=verdict.get("internal_failures", []),
            blockers=verdict.get("blockers", []),
            final_verdict_ref=str((out / acceptance_verifier.FILE_NAME).resolve()),
            final_verdict_hash=canonical_evidence_hash.sha256_file(out / acceptance_verifier.FILE_NAME),
            final_verdict_inspection=verdict_inspection,
        ),
    )
    run_manifest = write_json(
        out / "run_manifest.json",
        envelope(
            "CGKNFormalMainlineAcceptanceRun",
            identity,
            verdict["status"],
            repository_identity_ref=str((out / "repository_identity.json").resolve()),
            candidate_identity_ref=str((out / "candidate_identity.json").resolve()),
            production_provenance_ref=str(
                provenance.get("provenance_ref", "")
            ),
            production_provenance_inspection_ref=str(
                provenance_inspection_ref
            ),
            requirement_snapshot_ref=str(requirement),
            gate_registry_ref=str(registry),
            acceptance_matrix_ref=str(matrix),
            final_verdict_ref=str((out / acceptance_verifier.FILE_NAME).resolve()),
            codex_messages_sent=0,
            codex_test_conversation_configured=bool(codex_test_conversation_id),
        ),
    )
    pass_gates = sorted(name for name, result in gate_results.items() if result["status"] == "PASS")
    nonpass_gates = sorted(name for name, result in gate_results.items() if result["status"] != "PASS")
    (out / "customer_validation_summary.md").write_text(
        "# CGKN formal mainline acceptance\n\n"
        f"- verdict: {verdict['status']}\n"
        f"- production run identity: {identity['run_id']}\n"
        f"- customer candidate hash: {identity['candidate_hash'] or 'NOT_EVALUATED'}\n"
        f"- inspected PASS gates: {', '.join(pass_gates) or 'none'}\n"
        f"- non-PASS gates: {', '.join(nonpass_gates)}\n"
        "- Codex conversation messages sent: 0\n"
        "- Fixture/diagnostic producers cannot authorize formal Gate PASS.\n",
        encoding="utf-8",
    )
    return {
        "status": verdict["status"],
        "inspection": verdict_inspection["status"],
        "run_dir": str(out),
        "candidate_identity": identity,
        "gates": gate_results,
        "run_manifest": str(run_manifest),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--candidate-dir", default="")
    parser.add_argument("--production-run-dir", default="")
    parser.add_argument("--full-all-result", default="")
    parser.add_argument("--codex-test-conversation-id", default="")
    args = parser.parse_args()
    result = build_acceptance(
        args.out_dir,
        candidate_dir=args.candidate_dir or None,
        production_run_dir=args.production_run_dir or None,
        full_all_result=args.full_all_result or None,
        codex_test_conversation_id=args.codex_test_conversation_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["inspection"] in {
        "PASS",
        "NEEDS_REWORK",
        "NOT_EVALUATED",
        "BLOCKED",
        "BLOCKED_PROVIDER",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
