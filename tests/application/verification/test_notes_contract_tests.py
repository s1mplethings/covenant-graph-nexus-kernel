from cgkn.application.requirements import NOTES_DEPENDENCY_POLICY, compile_local_json_notes
from cgkn.application.verification import ContractTestCompiler, ContractTestRenderer, ContractTestValidator, OraclePlanCompiler


def test_notes_contract_tests_are_deterministic_complete_and_valid() -> None:
    compilation = compile_local_json_notes()
    oracle = OraclePlanCompiler().compile_notes(compilation.obligations, NOTES_DEPENDENCY_POLICY)
    plan = ContractTestCompiler().compile(compilation.obligations, oracle, NOTES_DEPENDENCY_POLICY)
    first = ContractTestRenderer().render(plan, NOTES_DEPENDENCY_POLICY)
    second = ContractTestRenderer().render(plan, NOTES_DEPENDENCY_POLICY)
    assert first.path == "tests/test_contract_notes.py"
    assert first.source_hash == second.source_hash
    assert len(plan.tests) == len(oracle.specs)
    assert ContractTestValidator().validate(plan, first.manifest, first.source, compilation.obligations, oracle, NOTES_DEPENDENCY_POLICY).status == "PASS"
    compile(first.source, first.path, "exec")
