from cgkn.application.interfaces import (
    ExecutableInterfaceContractSet,
    InterfaceContractCompiler,
    InterfaceKind,
)
from cgkn.application.requirements.csv import compile_csv_cleaner


def test_csv_contracts_are_deterministic_and_round_trip() -> None:
    obligations = compile_csv_cleaner().obligations
    first = InterfaceContractCompiler().compile_csv(obligations)
    second = InterfaceContractCompiler().compile_csv(obligations)
    restored = ExecutableInterfaceContractSet.from_dict(first.as_dict())
    assert first.interface_contract_set_hash == second.interface_contract_set_hash
    assert restored == first
    assert hash(restored.by_id("INTERFACE-CSV-CLI-001")) == hash(first.by_id("INTERFACE-CSV-CLI-001"))


def test_csv_cli_contract_encodes_exact_public_shape() -> None:
    contracts = InterfaceContractCompiler().compile_csv(compile_csv_cleaner().obligations)
    contract = contracts.by_id("INTERFACE-CSV-CLI-001")
    assert contract.interface_kind is InterfaceKind.CLI
    assert list(contract.required["entrypoint"]) == ["python", "-m", "csv_cleaner"]
    assert [item["name"] for item in contract.required["positionals"]] == ["input", "output"]
    assert set(contract.optional["options"]) == {"--dedupe-column", "--fill", "--preview", "--help"}
    assert set(contract.forbidden["options"]) == {"-o", "--output"}


def test_csv_contracts_retain_only_known_obligation_refs() -> None:
    compilation = compile_csv_cleaner()
    known = {item.obligation_id for item in compilation.obligations.obligations}
    contracts = InterfaceContractCompiler().compile_csv(compilation.obligations)
    assert {item.contract_id for item in contracts.contracts} == {
        "INTERFACE-CSV-MODULE-001", "INTERFACE-CSV-CLEAN-FUNCTION-001", "INTERFACE-CSV-CLI-001"
    }
    assert all(set(item.source_obligation_ids) <= known for item in contracts.contracts)
