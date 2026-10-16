from __future__ import annotations

import argparse
import json
import pathlib

from cgkn.application.requirements import NormalizedRequirements, ObligationSet, RequirementSource, TraceabilityGraph, validate_traceability
from cgkn.application.requirements.obligation import FrozenMapping


def check(requirements_path: pathlib.Path, obligations_path: pathlib.Path, graph_path: pathlib.Path) -> dict:
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
    return {"kind": "CGKNObligationTraceabilityGate", "schema_version": "1.0"} | validate_traceability(requirements, obligations, graph).as_dict()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--obligations", required=True)
    parser.add_argument("--graph", required=True)
    args = parser.parse_args()
    value = check(pathlib.Path(args.requirements), pathlib.Path(args.obligations), pathlib.Path(args.graph))
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
