from __future__ import annotations

import json
from pathlib import Path

from cgkn.application.test_authority import (
    AssertionAuthority,
    ContractAwareFailureRouter,
    ContractSemantic,
    PublicContractProjection,
    RepairMonotonicityGuard,
    TestAuthorityFirewall,
)
from cgkn.application.requirements.obligation import canonical_hash


FIXTURE = Path(__file__).parents[1] / "fixtures" / "test_authority_regression.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_previous_preview_header_conflict_is_rejected_before_commit() -> None:
    fixture = _fixture()
    projection = PublicContractProjection.for_case(str(fixture["case_id"]))
    receipt = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": str(fixture["conflicting_generated_test"])},
        projection,
    )
    assert receipt.status == "FAIL"
    assert AssertionAuthority.TEST_CONTRACT_CONFLICT.value in receipt.classifications
    assert "OBL-CSV-PREVIEW" in receipt.findings[0].requirement_ids


def test_unspecified_newline_is_not_promoted_to_public_authority() -> None:
    fixture = _fixture()
    projection = PublicContractProjection.for_case(str(fixture["case_id"]))
    receipt = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": str(fixture["newline_brittle_test"])},
        projection,
    )
    assert receipt.status == "FAIL"
    assert AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION.value in receipt.classifications


def _custom_projection(*, expected: dict[str, object], normalization: str = "NONE") -> PublicContractProjection:
    return PublicContractProjection(
        "custom",
        (ContractSemantic(
            ("REQ-PREVIEW-001",), "preview output", {"setup": {}}, "stdout",
            "preview output", expected, normalization_rule=normalization,
            verification_paths=("public_check",),
        ),),
        canonical_hash({"source": "custom public contract"}),
    )


def test_a_b_header_conflict_and_match_are_deterministic() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    conflict = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_header(header):\n assert header == ['wrong']\n"}, projection,
    )
    valid = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_header(header):\n assert header == ['id','name','city']\n"}, projection,
    )
    assert conflict.status == "FAIL"
    assert conflict.findings[0].authority is AssertionAuthority.TEST_CONTRACT_CONFLICT
    assert valid.status == "PASS"
    assert valid.findings[0].authority is AssertionAuthority.TEST_CONTRACT_VALID


def test_d_explicit_exact_newline_is_normative() -> None:
    projection = _custom_projection(expected={"stdout_exact": "row\n"}, normalization="EXACT_TEXT")
    source = "def test_preview(result):\n assert result.stdout == 'row\\n'\n"
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "PASS"
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_VALID


def test_e_f_g_contract_aware_routing() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    valid = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_header(header):\n assert header == ['id','name','city']\n"}, projection,
    )
    conflict = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_header(header):\n assert header == ['wrong']\n"}, projection,
    )
    unmapped = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_output(result):\n assert result.stdout.custom == 7\n"}, projection,
    )
    assert ContractAwareFailureRouter.route("NONCONFORMANT", valid, implementation_unit_id="core", tests_unit_id="tests") == "core"
    assert ContractAwareFailureRouter.route("CONFORMANT", conflict, implementation_unit_id="core", tests_unit_id="tests") == "tests"
    assert ContractAwareFailureRouter.route("CONFORMANT", unmapped, implementation_unit_id="core", tests_unit_id="tests") == "tests"


def test_h_monotonicity_keeps_conflicting_test_with_tests_owner() -> None:
    guard = RepairMonotonicityGuard()
    guard.record("OBL-CSV-PREVIEW", "sha256:implementation", "CONFORMANT")
    assert guard.route("OBL-CSV-PREVIEW", "sha256:implementation", AssertionAuthority.TEST_CONTRACT_CONFLICT) == "TESTS"
    try:
        guard.record("OBL-CSV-PREVIEW", "sha256:implementation", "NONCONFORMANT")
    except ValueError as exc:
        assert "cannot regress" in str(exc)
    else:
        raise AssertionError("conformance regression was accepted")


def test_l_m_projection_contains_no_old_test_or_hidden_authority() -> None:
    serialized = json.dumps(PublicContractProjection.for_case("cli_csv_cleaner").as_dict(), sort_keys=True)
    assert "conflicting_generated_test" not in serialized
    assert "hidden_acceptance" not in serialized
    assert "benchmarks/real_project_generation" not in serialized
    assert '"public_safe": true' in serialized


def test_n_o_manifest_claim_cannot_override_unknown_or_conflicting_ast() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    unknown = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_internal():\n assert 1 + 1 == 2\n"}, projection,
        declared_manifest=({"test_id": "test_internal", "file": "tests/test_cli.py", "line": 2, "requirement_ids": ["REQ-UNKNOWN"], "expected_semantics_source": "CONTRACT"},),
    )
    contradiction = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_header(header):\n assert header == ['wrong']\n"}, projection,
        declared_manifest=({"test_id": "test_header", "file": "tests/test_cli.py", "line": 2, "requirement_ids": ["OBL-CSV-HEADER-PRESERVATION"], "expected_semantics_source": "CONTRACT"},),
    )
    assert unknown.status == "FAIL"
    assert AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION.value in unknown.classifications
    assert contradiction.status == "FAIL"
    assert AssertionAuthority.TEST_CONTRACT_CONFLICT.value in contradiction.classifications


def test_p_q_internal_and_robustness_assertions_remain_allowed() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """import pytest
def test_internal():
    assert 1 + 1 == 2
    with pytest.raises(ValueError):
        int('bad')
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_internal.py": source}, projection)
    assert receipt.status == "PASS"
    assert set(receipt.classifications) == {AssertionAuthority.TEST_INTERNAL_ASSERTION.value}


def test_r_ambiguous_contract_stays_ambiguous() -> None:
    projection = _custom_projection(expected={"details": "UNSPECIFIED"}, normalization="UNSPECIFIED")
    receipt = TestAuthorityFirewall().validate(
        {"tests/test_cli.py": "def test_output(result):\n assert result.stdout == 'invented'\n"}, projection,
    )
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_UNPROVEN
    assert ContractAwareFailureRouter.route("UNKNOWN", receipt, implementation_unit_id="core", tests_unit_id="tests") == "CONTRACT_ATTRIBUTION_AMBIGUOUS"


def test_coverage_guard_rejects_requirement_without_any_verification_path() -> None:
    projection = PublicContractProjection(
        "custom",
        (ContractSemantic(("REQ-001",), "public behavior", {}, "public", "must work", {"status": "PASS"}),),
        canonical_hash({"source": "coverage"}),
    )
    receipt = TestAuthorityFirewall().validate(
        {"tests/test_internal.py": "def test_internal():\n assert True\n"},
        projection,
        required_requirement_ids=("REQ-001",),
    )
    assert receipt.status == "FAIL"
    assert AssertionAuthority.PUBLIC_REQUIREMENT_UNCOVERED.value in receipt.classifications


def test_external_output_existence_and_help_containment_are_mapped() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def test_output(output_path):
    assert output_path.exists()
def test_help(result):
    assert '--preview' in result.stdout
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "PASS"
    assert all(item.authority is AssertionAuthority.TEST_CONTRACT_VALID for item in receipt.findings)


def test_exact_file_text_is_non_normative_but_parsed_canonical_csv_is_valid() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    exact = TestAuthorityFirewall().validate(
        {"tests/test_output.py": "def test_output(output_path):\n assert output_path.read_text() == 'id,name,city\\n1,Ada,\\n'\n"},
        projection,
    )
    parsed = TestAuthorityFirewall().validate(
        {"tests/test_output.py": "def test_output(output_path, csv):\n assert list(csv.reader(output_path.open())) == [['id','name','city'],['1','Ada',''],['2','Lin','Paris']]\n"},
        projection,
    )
    assert exact.status == "FAIL"
    assert exact.findings[0].authority is AssertionAuthority.TEST_NON_NORMATIVE_ASSERTION
    assert parsed.status == "PASS"
    assert parsed.findings[0].authority is AssertionAuthority.TEST_CONTRACT_VALID


def test_live_worker_patterns_resolve_fixture_bindings_and_parsed_observables() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def test_clean_file_roundtrip_preserves_header_and_order(target):
    header = ['id', 'name', 'city']
    fieldnames = header
    assert fieldnames == header
    assert _read_csv(target) == [['id', 'name', 'city'], ['1', 'Ada', ''], ['2', 'Lin', 'Paris']]

def test_help_lists_public_options(result):
    for token in ('--preview', '--dedupe-column', '--fill'):
        assert token in result.stdout

def test_preview_prints_data_rows_and_writes_output(result, target):
    preview_rows = [['1', 'Ada', '']]
    assert result.returncode == 0
    assert target.exists()
    assert preview_rows == [['1', 'Ada', '']]

def test_whole_row_dedupe_preserves_header_and_order(result, target):
    assert result.returncode == 0
    assert _read_csv(target) == [['id', 'name', 'city'], ['1', 'Ada', ''], ['2', 'Lin', 'Paris']]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "PASS"
    assert set(receipt.classifications) == {AssertionAuthority.TEST_CONTRACT_VALID.value}


def test_module_header_and_parsed_csv_alias_slices_retain_public_semantics() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """HEADER = ['id', 'name', 'city']
def test_cli_whole_row_dedupe_preserves_header_and_order(target):
    written = _read_csv(target)
    assert written[0] == HEADER
    assert written[1:] == [['1', 'Ada', ''], ['2', 'Lin', 'Paris']]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "PASS"
    assert [item.observable for item in receipt.findings] == ["csv.header", "output.csv"]
    assert set(receipt.classifications) == {AssertionAuthority.TEST_CONTRACT_VALID.value}


def test_header_binding_inside_expected_csv_document_is_resolved() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def test_whole_row_dedupe(target):
    header = ['id', 'name', 'city']
    assert _read_csv(target) == [header, ['1', 'Ada', ''], ['2', 'Lin', 'Paris']]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "PASS"
    assert receipt.findings[0].observable == "output.csv"
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_VALID


def test_direct_csv_reader_helper_retains_canonical_output_semantics() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def read_output(path):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.reader(handle))

def test_dedupe_column_and_fill(output_path):
    assert read_output(output_path) == [
        ['id', 'name', 'city'],
        ['1', 'Ada', 'UNKNOWN'],
        ['2', 'Lin', 'UNKNOWN'],
    ]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "PASS"
    assert receipt.findings[0].observable == "output.csv"
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_VALID


def test_transforming_csv_reader_helper_is_not_treated_as_canonical_document() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def read_output(path):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.reader(handle))[1:]

def test_output(output_path):
    assert read_output(output_path) == [
        ['id', 'name', 'city'],
        ['1', 'Ada', ''],
        ['2', 'Lin', 'Paris'],
    ]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "FAIL"
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_UNMAPPED_ASSERTION


def test_preview_assertion_cannot_filter_observed_csv_rows() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def test_preview_prints_data_rows(result):
    preview_rows = [row for row in csv.reader(result.stdout.splitlines()) if row]
    assert preview_rows == [['1', 'Ada', '']]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "FAIL"
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_UNPROVEN
    assert "filters observed CSV rows" in receipt.findings[0].reason


def test_preview_assertion_cannot_hide_row_filtering_in_helper() -> None:
    projection = PublicContractProjection.for_case("cli_csv_cleaner")
    source = """def _parse_stdout_rows(text):
    return [row for row in csv.reader(text.splitlines()) if row]

def test_preview_prints_data_rows(result):
    preview_rows = _parse_stdout_rows(result.stdout)
    assert preview_rows == [['1', 'Ada', '']]
"""
    receipt = TestAuthorityFirewall().validate({"tests/test_cli.py": source}, projection)
    assert receipt.status == "FAIL"
    assert receipt.findings[0].authority is AssertionAuthority.TEST_CONTRACT_UNPROVEN
    assert "helper filters observed CSV rows" in receipt.findings[0].reason

