from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("architecture_diet_audit", ROOT / "scripts" / "architecture_diet_audit.py")
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


def test_inventory_is_deterministic_and_complete() -> None:
    first = audit_module.audit()
    second = audit_module.audit()
    baseline = audit_module.audit(audit_module.BASELINE)
    assert first == second
    assert first["metrics"]["production_module_count"] == len(first["module_inventory"])
    assert first["metrics"]["cyclic_scc_count"] == baseline["metrics"]["cyclic_scc_count"]
    required = {
        "purpose", "authority", "public_symbols", "incoming_dependencies",
        "outgoing_dependencies", "runtime_usage", "test_usage",
        "benchmark_only_usage", "candidate_status", "classification",
    }
    assert all(required <= set(record) for record in first["module_inventory"])


def test_safe_slimming_preserves_or_compatibly_extends_public_contract_surfaces() -> None:
    baseline = audit_module.audit(audit_module.BASELINE)
    current = audit_module.audit()
    assert current["registry_hash"] == baseline["registry_hash"]
    baseline_api = baseline["surface"]["public_api"]
    current_api = current["surface"]["public_api"]
    assert set(baseline_api) <= set(current_api)
    for module, contract in baseline_api.items():
        current_contract = current_api[module]
        assert set(contract["symbols"]) <= set(current_contract["symbols"])
        assert set(contract["project_imports"]) <= set(current_contract["project_imports"])
        assert set(contract["exports"]) <= set(current_contract["exports"])

    # The convergence branch intentionally evolves only the v2 checkpoint
    # schema.  Every other persisted knowledge contract must remain byte-for-
    # byte identical to the production baseline.
    baseline_formats = baseline["surface"]["knowledge_formats"]
    current_formats = current["surface"]["knowledge_formats"]
    assert set(baseline_formats) == set(current_formats)
    approved_schema_delta = "schemas/project_knowledge_checkpoint_v2.schema.json"
    assert {
        name: digest for name, digest in current_formats.items()
        if name != approved_schema_delta
    } == {
        name: digest for name, digest in baseline_formats.items()
        if name != approved_schema_delta
    }
    assert current_formats[approved_schema_delta] != baseline_formats[approved_schema_delta]
    learning_contracts = current["surface"]["public_api"]["cgkn.application.learning.contracts"]
    assert "GenerationRequest" in learning_contracts["project_imports"]
    assert "GenerationResult" in learning_contracts["project_imports"]


def test_inventory_classifies_runtime_contract_and_governance_modules() -> None:
    records = {row["path"]: row for row in audit_module.audit()["module_inventory"]}
    assert records["cgkn/application/conversation/service.py"]["classification"] == "PRODUCTION_RUNTIME"
    assert records["contracts/envelope.py"]["classification"] == "PRODUCTION_CONTRACT"
    assert records["src/cgkn_project_management/manager.py"]["classification"] == "GOVERNANCE"
    assert records["cgkn/runtime/dag_runner.py"]["authority"] == ["dag_runtime"]
