from __future__ import annotations

from dataclasses import replace

from cgkn.application.requirements import CSV_DEPENDENCY_POLICY, compile_csv_cleaner
from cgkn.application.verification import ContractTestCompiler, ContractTestRenderer, ContractTestValidator, OraclePlanCompiler


def inputs():
    compilation = compile_csv_cleaner(); oracle = OraclePlanCompiler().compile_csv(compilation.obligations, CSV_DEPENDENCY_POLICY)
    plan = ContractTestCompiler().compile(compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    artifact = ContractTestRenderer().render(plan, CSV_DEPENDENCY_POLICY)
    return compilation, oracle, plan, artifact


def test_validator_accepts_complete_trace_and_dependency_policy() -> None:
    compilation, oracle, plan, artifact = inputs()
    result = ContractTestValidator().validate(plan, artifact.manifest, artifact.source, compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    assert result.status == "PASS" and result.errors == ()


def test_validator_rejects_manifest_source_and_extra_assertion_tamper() -> None:
    compilation, oracle, plan, artifact = inputs()
    tampered = artifact.source + "\ndef test_unprovenanced(): assert False\n"
    result = ContractTestValidator().validate(plan, artifact.manifest, tampered, compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    assert "unprovenanced_or_extra_assertion" in result.errors
    bad_manifest = replace(artifact.manifest, source_hash="sha256:bad")
    result = ContractTestValidator().validate(plan, bad_manifest, artifact.source, compilation.obligations, oracle, CSV_DEPENDENCY_POLICY)
    assert "manifest_or_source_tamper" in result.errors
