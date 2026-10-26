from __future__ import annotations

import pytest

from experiments.semantic_artifact_design.common.interface import PythonInterfaceExtractor, compare_interfaces


SOURCE = '''
import csv
PUBLIC = 1
__all__ = ["clean_csv"]
def clean_csv(source, output, key=None, fill=""):
    return output
class Cleaner:
    def clean(self, source, output=None):
        return output
def _parser():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--key")
    parser.add_argument("--fill")
    return parser
if __name__ == "__main__":
    _parser().parse_args()
'''


def test_extractor_functions_classes_imports_cli_and_stable_hash():
    extractor = PythonInterfaceExtractor()
    first = extractor.extract_source(SOURCE, "csv_cleaner/core.py")
    second = extractor.extract_source(SOURCE, "csv_cleaner/core.py")
    assert first == second
    assert first["functions"][0]["name"] == "clean_csv"
    assert first["classes"][0]["methods"][0]["name"] == "clean"
    assert first["imports"] == ["csv"]
    assert first["cli_options"] == ["--fill", "--key"]
    assert first["main_guard"] is True


def test_extractor_rejects_syntax_error():
    with pytest.raises(ValueError, match="syntax error"):
        PythonInterfaceExtractor().extract_source("def broken(:\n", "broken.py")


@pytest.mark.parametrize("replacement,needle", [
    ("def renamed(source, output, key=None, fill=''):\n return output\n", "public function removed"),
    ("def clean_csv(source, key=None):\n return source\n", "public signature changed"),
    (SOURCE.replace('    parser.add_argument("--key")\n', ""), "CLI option removed"),
    (SOURCE.replace('if __name__ == "__main__":', "if False:"), "entrypoint removed"),
])
def test_guard_rejects_breaking_changes(replacement, needle):
    extractor = PythonInterfaceExtractor()
    old = {"modules": [extractor.extract_source(SOURCE, "csv_cleaner/core.py")]}
    new = {"modules": [extractor.extract_source(replacement, "csv_cleaner/core.py")]}
    result = compare_interfaces(old, new)
    assert result.compatible is False
    assert any(needle in item for item in result.breaking_changes)


def test_guard_accepts_private_helper_and_explicit_breaking_permission():
    extractor = PythonInterfaceExtractor()
    old = {"modules": [extractor.extract_source(SOURCE, "csv_cleaner/core.py")]}
    new_source = SOURCE + "\ndef _helper():\n    return 1\n"
    new = {"modules": [extractor.extract_source(new_source, "csv_cleaner/core.py")]}
    assert compare_interfaces(old, new).compatible is True
    removed = {"modules": []}
    assert compare_interfaces(old, removed, allow_breaking_change=True).compatible is True
