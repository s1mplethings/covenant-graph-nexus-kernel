from experiments.semantic_artifact_design.common.failure import FailureAttributor


UNITS = {"cli-core": ("csv_cleaner/core.py",), "public-tests": ("tests/test_csv_cleaner.py",)}


def _attribute(text, phase="pytest"):
    return FailureAttributor().attribute(stdout=text, stderr="", returncode=1, manifests={"modules": []}, project_contract={}, test_contract={}, units=UNITS, phase=phase)


def test_failure_attribution_syntax_import_name_and_test_defect():
    assert _attribute('File "csv_cleaner/core.py", line 2\nSyntaxError: bad')["failure_class"] == "SYNTAX_ERROR"
    assert _attribute('File "csv_cleaner/core.py", line 2\nModuleNotFoundError: x')["failure_class"] == "IMPORT_ERROR"
    assert _attribute('File "csv_cleaner/core.py", line 2\nNameError: x')["failure_class"] == "NAME_ERROR"
    result = _attribute('File "tests/test_csv_cleaner.py", line 2\nNameError: missing')
    assert result["failure_class"] == "TEST_DEFECT"
    assert result["allowed_repair_units"] == ["public-tests"]


def test_failure_attribution_source_runtime_and_unknown():
    assert _attribute('File "csv_cleaner/core.py"\nAssertionError')["failure_class"] == "SOURCE_BEHAVIOR_DEFECT"
    assert _attribute("usage: csv_cleaner: error: bad", "runtime")["failure_class"] == "CLI_CONTRACT_DEFECT"
    assert _attribute("process failed")["failure_class"] == "UNKNOWN"
