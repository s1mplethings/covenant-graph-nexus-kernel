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


def test_safe_slimming_preserves_public_contract_surfaces() -> None:
    baseline = audit_module.audit(audit_module.BASELINE)
    current = audit_module.audit()
    assert current["public_surface_hash"] == baseline["public_surface_hash"]
    assert current["registry_hash"] == baseline["registry_hash"]
    assert current["schema_hash"] == baseline["schema_hash"]
    learning_contracts = current["surface"]["public_api"]["cgkn.application.learning.contracts"]
    assert "GenerationRequest" in learning_contracts["project_imports"]
    assert "GenerationResult" in learning_contracts["project_imports"]


def test_inventory_classifies_runtime_contract_and_governance_modules() -> None:
    records = {row["path"]: row for row in audit_module.audit()["module_inventory"]}
    assert records["cgkn/application/conversation/service.py"]["classification"] == "PRODUCTION_RUNTIME"
    assert records["contracts/envelope.py"]["classification"] == "PRODUCTION_CONTRACT"
    assert records["src/cgkn_project_management/manager.py"]["classification"] == "GOVERNANCE"
    assert records["cgkn/runtime/dag_runner.py"]["authority"] == ["dag_runtime"]
