from __future__ import annotations

import argparse
import json
import pathlib

from cgkn.application.requirements import NormalizedRequirements, ObligationSet, RequirementSource, TraceabilityGraph, validate_traceability
from cgkn.application.requirements.obligation import FrozenMapping
from cgkn.application.verification import OracleEvidence, OraclePlan, OracleRegistry, OracleStatus


def validate_oracle_traceability(
    obligations: ObligationSet,
    plan: OraclePlan,
    evidence: tuple[OracleEvidence, ...] = (),
    *,
    final_project_status: str | None = None,
) -> dict:
    obligation_ids = {item.obligation_id for item in obligations.obligations}
    errors: list[str] = []
    if plan.obligation_set_hash != obligations.as_dict()["obligation_set_hash"]:
        errors.append("ORACLE_PLAN_OBLIGATION_HASH_MISMATCH")
    if set(plan.source_obligation_ids) != obligation_ids:
        errors.append("ORACLE_PLAN_OBLIGATION_SET_MISMATCH")
    covered = {identifier for spec in plan.specs for identifier in spec.obligation_ids}
    for item in obligations.obligations:
        if item.severity == "MUST" and item.obligation_id not in covered:
            errors.append(f"P0_OBLIGATION_MISSING_ORACLE:{item.obligation_id}")
    registry = OracleRegistry(plan)
    by_oracle: dict[str, list[OracleEvidence]] = {}
    for item in evidence:
        try:
            registry.validate_evidence(item)
        except (KeyError, ValueError) as exc:
            errors.append(f"ORACLE_EVIDENCE_DANGLING:{item.evidence_id}:{exc}")
            continue
        by_oracle.setdefault(item.oracle_id, []).append(item)
    if final_project_status == "PASS":
        for oracle_id in plan.required_oracle_ids:
            results = by_oracle.get(oracle_id, [])
            if not results:
                errors.append(f"FINAL_PASS_MISSING_ORACLE_EVIDENCE:{oracle_id}")
            elif not any(item.status is OracleStatus.PASS for item in results):
                errors.append(f"FINAL_PASS_ORACLE_NOT_PASS:{oracle_id}")
    coverage = 1.0 if not obligation_ids else len(covered & obligation_ids) / len(obligation_ids)
    return {
        "status": "PASS" if not errors else "HARNESS_CONTRACT_GAP",
        "errors": sorted(errors),
        "oracle_coverage": coverage,
        "required_oracles": len(plan.required_oracle_ids),
        "evidence_count": len(evidence),
    }


def check(
    requirements_path: pathlib.Path,
    obligations_path: pathlib.Path,
    graph_path: pathlib.Path,
    oracle_plan_path: pathlib.Path | None = None,
    oracle_evidence_path: pathlib.Path | None = None,
    final_project_status: str | None = None,
) -> dict:
    requirement_doc = json.loads(requirements_path.read_text(encoding="utf-8"))
    requirements = NormalizedRequirements(
        tuple(RequirementSource.from_dict(item) for item in requirement_doc.get("sources", ())),
        tuple(requirement_doc.get("public_acceptance_refs", ())),
        str(requirement_doc.get("schema_version", "1.0")),
    )
    obligations = ObligationSet.from_dict(json.loads(obligations_path.read_text(encoding="utf-8")))
    value = json.loads(graph_path.read_text(encoding="utf-8"))
    graph = TraceabilityGraph(*(
        FrozenMapping(value.get(name, {})) for name in (
            "requirement_to_obligations", "obligation_to_work_units", "obligation_to_tests",
            "test_to_obligation", "acceptance_to_obligation", "evidence_to_obligation",
        )
    ), schema_version=str(value.get("schema_version", "1.0")))
    result = {"kind": "CGKNObligationTraceabilityGate", "schema_version": "1.0"} | validate_traceability(requirements, obligations, graph).as_dict()
    if oracle_plan_path is not None:
        plan = OraclePlan.from_dict(json.loads(oracle_plan_path.read_text(encoding="utf-8")))
        evidence_doc = json.loads(oracle_evidence_path.read_text(encoding="utf-8")) if oracle_evidence_path else []
        evidence_rows = evidence_doc.get("evidence", ()) if isinstance(evidence_doc, dict) else evidence_doc
        oracle = validate_oracle_traceability(
            obligations,
            plan,
            tuple(OracleEvidence.from_dict(item) for item in evidence_rows),
            final_project_status=final_project_status,
        )
        result["oracle_traceability"] = oracle
        if oracle["status"] != "PASS":
            result["status"] = "HARNESS_CONTRACT_GAP"
            result["errors"] = sorted(list(result.get("errors", ())) + oracle["errors"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--obligations", required=True)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--oracle-plan")
    parser.add_argument("--oracle-evidence")
    parser.add_argument("--final-project-status")
    args = parser.parse_args()
    value = check(
        pathlib.Path(args.requirements), pathlib.Path(args.obligations), pathlib.Path(args.graph),
        pathlib.Path(args.oracle_plan) if args.oracle_plan else None,
        pathlib.Path(args.oracle_evidence) if args.oracle_evidence else None,
        args.final_project_status,
    )
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
