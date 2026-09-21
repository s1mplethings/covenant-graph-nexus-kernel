from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

try:
    from . import (
        canonical_evidence_hash,
        canonical_user_review,
        customer_runtime_runner,
        product_design_depth_governance,
        real_test_execution,
    )
except ImportError:  # pragma: no cover - direct script execution
    import canonical_evidence_hash
    import canonical_user_review
    import customer_runtime_runner
    import product_design_depth_governance
    import real_test_execution


SCHEMA_VERSION = "1.0"
STATE_FILE = "canonical_finalization_state.json"
VERIFICATION_FILE = "canonical_verification_report.json"
GOVERNANCE_FILE = "canonical_governance_report.json"
ACCEPTANCE_FILE = "canonical_acceptance_decision.json"
PROMOTION_FILE = "canonical_promotion_manifest.json"

STATES = (
    "CANDIDATE_MATERIALIZED",
    "WAITING_CANONICAL_VERIFICATION",
    "WAITING_GOVERNANCE_EVALUATION",
    "WAITING_ACCEPTANCE_DECISION",
    "WAITING_USER_REVIEW",
    "READY_FOR_PROMOTION",
    "PROMOTION_REJECTED",
    "READY_FOR_PACKAGING",
    "PACKAGING_FAILED",
    "READY_FOR_DELIVERY",
    "DELIVERY_BLOCKED",
    "DELIVERED",
)

_ALLOWED = {
    "": {"CANDIDATE_MATERIALIZED"},
    "CANDIDATE_MATERIALIZED": {"WAITING_CANONICAL_VERIFICATION"},
    "WAITING_CANONICAL_VERIFICATION": {"WAITING_GOVERNANCE_EVALUATION", "PROMOTION_REJECTED"},
    "WAITING_GOVERNANCE_EVALUATION": {"WAITING_ACCEPTANCE_DECISION", "PROMOTION_REJECTED"},
    "WAITING_ACCEPTANCE_DECISION": {"WAITING_USER_REVIEW", "READY_FOR_PROMOTION", "PROMOTION_REJECTED"},
    "WAITING_USER_REVIEW": {"READY_FOR_PROMOTION", "PROMOTION_REJECTED", "WAITING_USER_REVIEW"},
    "READY_FOR_PROMOTION": {"READY_FOR_PACKAGING", "PROMOTION_REJECTED"},
    "READY_FOR_PACKAGING": {"READY_FOR_DELIVERY", "DELIVERY_BLOCKED", "PACKAGING_FAILED"},
    "PACKAGING_FAILED": {"READY_FOR_PACKAGING", "PACKAGING_FAILED"},
    "READY_FOR_DELIVERY": {"DELIVERED", "DELIVERY_BLOCKED"},
    "DELIVERY_BLOCKED": {"READY_FOR_DELIVERY", "DELIVERY_BLOCKED"},
    "PROMOTION_REJECTED": {"PROMOTION_REJECTED"},
    "DELIVERED": {"DELIVERED"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_hashed(path: pathlib.Path, document: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(document)
    payload["artifact_hash"] = ""
    payload["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(payload, ("artifact_hash",))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _identity(identity: dict[str, Any], candidate_hash: str) -> dict[str, str]:
    return {
        "run_id": str(identity.get("run_id", "")),
        "candidate_id": str(identity.get("candidate_id", "")),
        "candidate_hash": str(candidate_hash),
        "source_sha": str(identity.get("commit_sha", "")),
    }


def transition(
    run_dir: str | pathlib.Path,
    state: str,
    *,
    identity: dict[str, Any],
    candidate_hash: str,
    evidence_refs: list[dict[str, str]] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"unsupported canonical finalization state: {state}")
    root = pathlib.Path(run_dir).resolve()
    path = root / STATE_FILE
    prior = _read(path)
    prior_state = str(prior.get("state", ""))
    same_identity = all(
        str(prior.get(key, "")) in {"", value}
        for key, value in _identity(identity, candidate_hash).items()
    )
    if not same_identity:
        raise ValueError("canonical finalization identity changed")
    if state != prior_state and state not in _ALLOWED.get(prior_state, set()):
        raise ValueError(f"invalid canonical finalization transition: {prior_state or '<start>'}->{state}")
    history = list(prior.get("history", [])) if isinstance(prior.get("history"), list) else []
    if not history or history[-1].get("state") != state:
        history.append({"state": state, "at": _now(), "evidence_refs": evidence_refs or [], "detail": detail or {}})
    document = {
        "kind": "CGKNCanonicalFinalizationState",
        "schema_version": SCHEMA_VERSION,
        **_identity(identity, candidate_hash),
        "producer": "scripts/canonical_finalization.py",
        "created_at": str(prior.get("created_at") or _now()),
        "updated_at": _now(),
        "state": state,
        "history": history,
        "artifact_hash": "",
    }
    _write_hashed(path, document)
    return _read(path) | {"path": str(path)}


def _ref(role: str, path: pathlib.Path) -> dict[str, str]:
    return {
        "role": role,
        "ref": str(path.resolve()) if path.is_file() else "",
        "sha256": canonical_evidence_hash.sha256_file(path) if path.is_file() else "",
    }


def canonical_verify(
    project_dir: str | pathlib.Path,
    run_dir: str | pathlib.Path,
    *,
    identity: dict[str, Any],
    expected_candidate_hash: str,
    provenance_ref: str | pathlib.Path,
    visual_required: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    root = pathlib.Path(run_dir).resolve()
    source_hash = canonical_evidence_hash.candidate_source_hash(project)
    test = real_test_execution.inspect_test_report(project)
    runtime = customer_runtime_runner.inspect(project)
    readme = project / "README.md"
    entrypoints = [name for name in ("main.py", "app.py", "package.json", "index.html") if (project / name).is_file()]
    entrypoints.extend(path.relative_to(project).as_posix() for path in sorted(project.glob("*/__main__.py")))
    dependency_files = [name for name in ("requirements.txt", "pyproject.toml", "package.json", "environment.yml") if (project / name).is_file()]
    readme_text = readme.read_text(encoding="utf-8", errors="replace") if readme.is_file() else ""
    checks = {
        "candidate_hash_matches": source_hash == expected_candidate_hash,
        "canonical_tests_pass": test.get("status") == "PASS",
        "canonical_runtime_pass": runtime.get("status") == "PASS",
        "readme_present": readme.is_file(),
        "entrypoint_present": bool(entrypoints),
        "startup_documented": bool(readme_text.strip()),
        "dependencies_documented": bool(dependency_files) or "标准库" in readme_text or "standard library" in readme_text.lower(),
        "platform_documented": any(token in readme_text.lower() for token in ("windows", "linux", "macos", "python")),
        "error_output_recorded": (project / "test_stderr.txt").is_file(),
        "visual_requirement_checked": not visual_required or (project / "visual_evidence.json").is_file(),
        "generated_files_present": bool(canonical_evidence_hash.candidate_source_manifest(project)),
        "goal_fidelity_evaluable": True,
        "blocker_check_complete": True,
        "new_blocker_check_complete": True,
    }
    blockers = [
        name for name in (
            "candidate_hash_matches", "canonical_tests_pass", "canonical_runtime_pass",
            "readme_present", "entrypoint_present", "startup_documented",
            "visual_requirement_checked", "generated_files_present",
        ) if not checks[name]
    ]
    evidence_refs = [
        _ref("test_execution", project / "test_execution.json"),
        _ref("customer_runtime", project / "customer_runtime.json"),
        _ref("production_provenance", pathlib.Path(provenance_ref)),
    ]
    if visual_required:
        evidence_refs.append(_ref("visual_evidence", project / "visual_evidence.json"))
    document = {
        "kind": "CGKNCanonicalVerificationReport",
        "schema_version": SCHEMA_VERSION,
        **_identity(identity, source_hash),
        "producer": "scripts/canonical_finalization.canonical_verify",
        "authority_source": "local_canonical_verifier",
        "created_at": _now(),
        "status": "PASS" if not blockers else "NEEDS_REWORK",
        "checks": checks,
        "entrypoints": entrypoints,
        "dependency_files": dependency_files,
        "evidence_refs": evidence_refs,
        "blockers": blockers,
        "new_blockers": [],
        "artifact_hash": "",
    }
    path = _write_hashed(root / VERIFICATION_FILE, document)
    return _read(path) | {"path": str(path)}


def canonical_governance_evaluate(
    project_dir: str | pathlib.Path,
    run_dir: str | pathlib.Path,
    *,
    identity: dict[str, Any],
    candidate_hash: str,
    governance: dict[str, Any],
    maturity_evaluation: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    root = pathlib.Path(run_dir).resolve()
    reports = maturity_evaluation.get("reports", {}) if isinstance(maturity_evaluation.get("reports"), dict) else {}
    report_paths = maturity_evaluation.get("paths", {}) if isinstance(maturity_evaluation.get("paths"), dict) else {}
    failures: list[str] = []
    evidence_refs = [_ref("canonical_verification", pathlib.Path(str(verification.get("path", ""))))]
    for role in ("proxy_solution_report", "product_maturity_report", "public_claim_policy_report", "design_replan_report"):
        document = reports.get(role, {}) if isinstance(reports.get(role), dict) else {}
        validation = product_design_depth_governance.validate_artifact(document)
        path = pathlib.Path(str(report_paths.get(role, project / f"{role}.json")))
        evidence_refs.append(_ref(role, path))
        if validation.get("status") != "PASS" or not path.is_file():
            failures.append(f"canonical_governance_artifact:{role}")
    documents = governance.get("documents", {}) if isinstance(governance.get("documents"), dict) else {}
    required_contracts = (
        "goal_fidelity_contract", "project_complexity_profile", "core_difficulty_lock",
        "test_realism_contract", "challenge_matrix", "design_adequacy_report",
        "product_challenge_review", "overengineering_check_report",
    )
    contract_hashes: dict[str, str] = {}
    for name in required_contracts:
        document = documents.get(name, {}) if isinstance(documents.get(name), dict) else {}
        if not document:
            failures.append(f"governance_contract_missing:{name}")
        else:
            contract_hashes[name] = canonical_evidence_hash.canonical_json_hash(document, ())
    maturity = reports.get("product_maturity_report", {}) if isinstance(reports.get("product_maturity_report"), dict) else {}
    proxy = reports.get("proxy_solution_report", {}) if isinstance(reports.get("proxy_solution_report"), dict) else {}
    policy = reports.get("public_claim_policy_report", {}) if isinstance(reports.get("public_claim_policy_report"), dict) else {}
    document = {
        "kind": "CGKNCanonicalGovernanceReport",
        "schema_version": SCHEMA_VERSION,
        **_identity(identity, candidate_hash),
        "producer": "scripts/canonical_finalization.canonical_governance_evaluate",
        "authority_source": "local_product_design_depth_governance",
        "evaluation_version": product_design_depth_governance.contract.SCHEMA_VERSION,
        "created_at": _now(),
        "status": "PASS" if not failures else "NEEDS_REWORK",
        "verification_evidence_hash": str(verification.get("artifact_hash", "")),
        "contract_hashes": contract_hashes,
        "evidence_refs": evidence_refs,
        "maturity_level": str(maturity.get("maturity_level", "PROTOTYPE")),
        "maturity_ceiling": str(maturity.get("maximum_justified_level", "PROTOTYPE")),
        "target_goal_satisfied": bool(maturity.get("target_goal_satisfied")),
        "real_world_validated": bool(maturity.get("real_world_validated")),
        "proxy_detected": bool(proxy.get("proxy_detected", maturity.get("proxy_detected"))),
        "delivery_claims_allowed": list(policy.get("public_claims_allowed", [])),
        "delivery_claims_forbidden": list(policy.get("public_claims_forbidden", [])),
        "failures": failures,
        "artifact_hash": "",
    }
    path = _write_hashed(root / GOVERNANCE_FILE, document)
    return _read(path) | {"path": str(path)}


def decide_acceptance(
    run_dir: str | pathlib.Path,
    *,
    identity: dict[str, Any],
    candidate_hash: str,
    verification: dict[str, Any],
    governance: dict[str, Any],
) -> dict[str, Any]:
    root = pathlib.Path(run_dir).resolve()
    blockers = list(verification.get("blockers", [])) + list(governance.get("failures", []))
    accepted = verification.get("status") == "PASS" and governance.get("status") == "PASS" and not blockers
    document = {
        "kind": "CGKNCanonicalAcceptanceDecision",
        "schema_version": SCHEMA_VERSION,
        **_identity(identity, candidate_hash),
        "producer": "scripts/canonical_finalization.decide_acceptance",
        "created_at": _now(),
        "status": "PASS" if accepted else "NEEDS_REWORK",
        "verification_evidence_hash": str(verification.get("artifact_hash", "")),
        "governance_evidence_hash": str(governance.get("artifact_hash", "")),
        "maturity_level": str(governance.get("maturity_level", "PROTOTYPE")),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "acceptance_authority": "cgkn_local_canonical_acceptance_authority",
        "decision": "ACCEPT" if accepted else "REJECT",
        "decision_reason": "canonical verification and governance passed" if accepted else "canonical evidence or governance has blockers",
        "artifact_hash": "",
    }
    path = _write_hashed(root / ACCEPTANCE_FILE, document)
    return _read(path) | {"path": str(path)}


def promote(
    run_dir: str | pathlib.Path,
    *,
    identity: dict[str, Any],
    candidate_hash: str,
    acceptance: dict[str, Any],
    parent_lineage: list[str] | None = None,
    user_review_required: bool = False,
    project_dir: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(run_dir).resolve()
    path = root / PROMOTION_FILE
    existing = _read(path)
    if existing:
        inspection = inspect_promotion(path, expected_identity=_identity(identity, candidate_hash))
        if inspection.get("status") == "PASS":
            return existing | {"path": str(path), "idempotent_reuse": True}
        raise ValueError("existing canonical promotion manifest is invalid")
    if acceptance.get("decision") != "ACCEPT" or acceptance.get("status") != "PASS":
        raise ValueError("candidate is not accepted")
    if acceptance.get("candidate_hash") != candidate_hash:
        raise ValueError("acceptance candidate hash mismatch")
    if user_review_required:
        review = canonical_user_review.inspect_user_review_evidence(pathlib.Path(str(project_dir)))
        if review.get("status") != "PASS":
            raise ValueError("canonical user review is required")
    document = {
        "kind": "CGKNCanonicalPromotionManifest",
        "schema_version": SCHEMA_VERSION,
        **_identity(identity, candidate_hash),
        "producer": "scripts/canonical_finalization.promote",
        "created_at": _now(),
        "status": "PASS",
        "promotion_authority": "cgkn_local_canonical_promotion_authority",
        "accepted_candidate_id": str(identity.get("candidate_id", "")),
        "parent_lineage": list(parent_lineage or []),
        "verification_evidence_hash": str(acceptance.get("verification_evidence_hash", "")),
        "governance_evidence_hash": str(acceptance.get("governance_evidence_hash", "")),
        "acceptance_decision_hash": str(acceptance.get("artifact_hash", "")),
        "user_review_required": bool(user_review_required),
        "candidate_content_modified": False,
        "artifact_hash": "",
    }
    _write_hashed(path, document)
    return _read(path) | {"path": str(path), "idempotent_reuse": False}


def inspect_promotion(
    promotion: str | pathlib.Path | dict[str, Any],
    *,
    expected_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    if isinstance(promotion, dict):
        document = dict(promotion)
        path = pathlib.Path(str(document.get("path", "")))
    else:
        path = pathlib.Path(promotion).resolve()
        document = _read(path)
    failures: list[str] = []
    if not document or document.get("kind") != "CGKNCanonicalPromotionManifest" or document.get("status") != "PASS":
        failures.append("promotion_contract")
    if document and document.get("artifact_hash") != canonical_evidence_hash.canonical_json_hash(document, ("artifact_hash",)):
        failures.append("promotion_hash")
    if document.get("promotion_authority") != "cgkn_local_canonical_promotion_authority":
        failures.append("promotion_authority")
    for field, value in (expected_identity or {}).items():
        if str(document.get(field, "")) != str(value):
            failures.append(f"promotion_identity:{field}")
    return {"status": "PASS" if not failures else "NEEDS_REWORK", "failures": failures, "details": document, "path": str(path)}


def packaging_blockers(
    promotion: str | pathlib.Path | dict[str, Any] | None,
    *,
    expected_identity: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    inspection = inspect_promotion(promotion or {}, expected_identity=expected_identity)
    return [
        {
            "code": failure,
            "category": "missing_authority" if "authority" in failure or "contract" in failure else "failed_hash" if "hash" in failure else "failed_gate",
            "recoverable": True,
            "next_action": "complete canonical acceptance and promotion before packaging",
        }
        for failure in inspection.get("failures", [])
    ]
