from cgkn.application.interfaces import (
    InterfaceContractCompiler,
    InterfaceContractStatus,
    extract_interfaces,
    guard_interface,
    guard_interfaces,
)
from cgkn.application.requirements.csv import compile_csv_cleaner


CORE = '''
def clean_csv(input_path, output_path, dedupe_column=None, fill=None):
    return None
'''


def _sources(arguments: str) -> dict[str, str]:
    return {
        "csv_cleaner/__init__.py": "from .core import clean_csv\n",
        "csv_cleaner/core.py": CORE,
        "csv_cleaner/__main__.py": f'''\nimport argparse\nparser = argparse.ArgumentParser()\n{arguments}\n''',
    }


def _contracts():
    return InterfaceContractCompiler().compile_csv(compile_csv_cleaner().obligations)


def _standard_options() -> str:
    return '''
parser.add_argument("--dedupe-column")
parser.add_argument("--fill")
parser.add_argument("--preview")
'''


def test_argparse_extractor_records_positionals_options_and_function() -> None:
    manifest = extract_interfaces(_sources('parser.add_argument("input")\nparser.add_argument("output")' + _standard_options()))
    assert [item["name"] for item in manifest.cli["positionals"]] == ["input", "output"]
    assert manifest.cli["options"]["--preview"]["takes_value"] is True
    assert manifest.functions["csv_cleaner.core.clean_csv"]["parameters"][1]["name"] == "output_path"


def test_correct_positional_cli_and_function_pass() -> None:
    manifest = extract_interfaces(_sources('parser.add_argument("input")\nparser.add_argument("output")' + _standard_options()))
    evidence = guard_interfaces(_contracts(), manifest)
    assert {item.status for item in evidence} == {InterfaceContractStatus.PASS}


def test_optional_output_is_precisely_rejected() -> None:
    manifest = extract_interfaces(_sources('parser.add_argument("input")\nparser.add_argument("-o", "--output")' + _standard_options()))
    evidence = guard_interface(_contracts().by_id("INTERFACE-CSV-CLI-001"), manifest)
    assert evidence.status is InterfaceContractStatus.FAIL
    assert evidence.failure_class == "POSITIONAL_TO_OPTIONAL"
    assert evidence.expected["kind"] == "POSITIONAL"
    assert list(evidence.observed["flags"]) == ["-o", "--output"]
    assert "second required positional" in evidence.required_action


def test_forbidden_alias_fails_even_when_output_positional_exists() -> None:
    manifest = extract_interfaces(_sources('parser.add_argument("input")\nparser.add_argument("output")\nparser.add_argument("-o", "--output-alias")' + _standard_options()))
    evidence = guard_interface(_contracts().by_id("INTERFACE-CSV-CLI-001"), manifest)
    assert evidence.status is InterfaceContractStatus.FAIL
    assert evidence.failure_class == "EXTRA_FORBIDDEN_OPTION"


def test_missing_positional_and_missing_function_are_classified() -> None:
    sources = _sources('parser.add_argument("input")' + _standard_options())
    sources["csv_cleaner/core.py"] = "value = 1\n"
    evidence = guard_interfaces(_contracts(), extract_interfaces(sources))
    by_contract = {item.contract_id: item for item in evidence}
    assert by_contract["INTERFACE-CSV-CLI-001"].failure_class == "MISSING_POSITIONAL"
    assert by_contract["INTERFACE-CSV-CLEAN-FUNCTION-001"].failure_class == "FUNCTION_MISSING"


def test_dynamic_argparse_is_unresolved_not_guessed() -> None:
    manifest = extract_interfaces(_sources('name = "output"\nparser.add_argument("input")\nparser.add_argument(name)' + _standard_options()))
    evidence = guard_interface(_contracts().by_id("INTERFACE-CSV-CLI-001"), manifest)
    assert evidence.status is InterfaceContractStatus.UNRESOLVED
    assert evidence.failure_class == "UNRESOLVED_INTERFACE"


def test_evidence_round_trip_is_stable() -> None:
    from cgkn.application.interfaces import InterfaceContractEvidence

    manifest = extract_interfaces(_sources('parser.add_argument("input")\nparser.add_argument("output")' + _standard_options()))
    evidence = guard_interface(_contracts().by_id("INTERFACE-CSV-CLI-001"), manifest)
    assert InterfaceContractEvidence.from_dict(evidence.as_dict()) == evidence
