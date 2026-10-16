from __future__ import annotations

import json

from cgkn.application.requirements import ObligationSet, RequirementCompiler, RequirementSource, RequirementSourceType, build_traceability
from cgkn.application.requirements.obligation import Obligation, ObligationKind
from scripts import obligation_traceability_gate


def test_gate_reports_harness_contract_gap_for_orphan_hidden_test(tmp_path) -> None:
    compiler = RequirementCompiler()
    requirements = compiler.normalize((RequirementSource("REQ-001", "do it", RequirementSourceType.USER_EXPLICIT),), ("REQ-001",))
    obligation = Obligation("OBL-BEHAVIOR-001", ObligationKind.BEHAVIOR, "do it", ("REQ-001",), expected={"done": True}, verification_method=("public_test",))
    obligations = ObligationSet((obligation,))
    graph = build_traceability(requirements, obligations)
    graph_doc = graph.as_dict()
    graph_doc["acceptance_to_obligation"] = {"ACCEPT-HIDDEN": ["OBL-MISSING-001"]}
    paths = [tmp_path / name for name in ("requirements.json", "obligations.json", "graph.json")]
    for path, value in zip(paths, (requirements.as_dict(), obligations.as_dict(), graph_doc)):
        path.write_text(json.dumps(value), encoding="utf-8")
    result = obligation_traceability_gate.check(*paths)
    assert result["status"] == "HARNESS_CONTRACT_GAP"
    assert result["hidden_acceptance_coverage"] == 0.0
