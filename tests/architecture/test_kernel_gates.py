from __future__ import annotations

import copy
import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kernel_architecture_gate as architecture
import kernel_completeness_gate as completeness
import test_architecture_gate as coverage


def layer_doc() -> dict:
    return {"layers": [{"id": "L1", "packages": ["cgkn.component"]}, {"id": "L2", "packages": ["cgkn.agent"]}]}


def authority_doc(canonical: str = "cgkn.component.spec:ComponentSpec") -> dict:
    return {"authorities": {"component": {"canonical": canonical}}, "compatibility_entrypoints": ["compat.py"]}


def test_missing_authority_is_rejected(monkeypatch, tmp_path: pathlib.Path) -> None:
    (tmp_path / "compat.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    monkeypatch.setattr(architecture, "source_files", lambda: set())
    monkeypatch.setattr(architecture, "load_json", lambda path: layer_doc() if "layers" in path else authority_doc("cgkn.missing:Nope") if "authorities" in path else {"compatibility_rule": "not the MVP planning or composition authority"})
    assert any(item.startswith("missing_canonical") for item in architecture.check()["errors"])


def test_duplicate_authority_is_rejected(monkeypatch, tmp_path: pathlib.Path) -> None:
    (tmp_path / "compat.py").write_text("", encoding="utf-8")
    doc = authority_doc(); doc["authorities"]["ports"] = {"canonical": "cgkn.component.spec:ComponentSpec"}
    monkeypatch.setattr(architecture, "ROOT", tmp_path); monkeypatch.setattr(architecture, "source_files", lambda: set())
    monkeypatch.setattr(architecture, "module_file", lambda _ref: pathlib.Path(__file__))
    monkeypatch.setattr(architecture, "load_json", lambda path: layer_doc() if "layers" in path else doc if "authorities" in path else {"compatibility_rule": "not the MVP planning or composition authority"})
    value = architecture.check()
    assert "duplicate_canonical_authority" in value["errors"]


def test_forbidden_low_to_high_import_is_rejected(monkeypatch, tmp_path: pathlib.Path) -> None:
    (tmp_path / "compat.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    monkeypatch.setattr(architecture, "source_files", lambda: {"cgkn/component/spec.py"})
    monkeypatch.setattr(architecture, "imported_modules", lambda _path: {"cgkn.agent"})
    monkeypatch.setattr(architecture, "load_json", lambda path: layer_doc() if "layers" in path else {"authorities": {}, "compatibility_entrypoints": ["compat.py"]} if "authorities" in path else {"compatibility_rule": "not the MVP planning or composition authority"})
    assert "forbidden_reverse_import:cgkn/component/spec.py:cgkn.agent" in architecture.check()["errors"]


def test_unmapped_source_and_missing_test_are_rejected(monkeypatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(coverage, "ROOT", tmp_path)
    monkeypatch.setattr(coverage, "source_files", lambda: {"cgkn/component/spec.py", "cgkn/component/ports.py"})
    monkeypatch.setattr(coverage, "collect_test_metadata", lambda: {})
    monkeypatch.setattr(coverage, "load_json", lambda path: {"sources": {"cgkn/component/spec.py": {"criticality": "P0", "test_cases": [{"nodeid": "tests/missing.py::test_x", "classes": ["happy_path", "negative", "boundary"]}], "required_classes": ["happy_path", "negative", "boundary"]}}} if "coverage" in path else {"kernel_foundation": "PARTIAL"})
    errors = coverage.check()["errors"]
    assert "unmapped_source:cgkn/component/ports.py" in errors
    assert any(item.startswith("orphan_test_mapping") for item in errors)


def test_complete_layer_with_blocker_is_rejected(monkeypatch) -> None:
    document = {"functional_readiness": "LEVEL_4", "kernel_foundation": "PARTIAL", "layers": {"L0": {"status": "COMPLETE", "evidence": ["x"], "blockers": ["open"]}}}
    monkeypatch.setattr(completeness, "load_json", lambda _path: document)
    monkeypatch.setattr(completeness, "coverage_check", lambda: {"status": "PASS"})
    assert "complete_with_blocker:L0" in completeness.check()["errors"]


def test_upper_complete_while_lower_partial_is_rejected(monkeypatch) -> None:
    document = {"functional_readiness": "LEVEL_4", "kernel_foundation": "PARTIAL", "layers": {"L0": {"status": "PARTIAL", "evidence": [], "blockers": ["x"]}, "L1": {"status": "COMPLETE", "evidence": ["x"], "blockers": []}}}
    monkeypatch.setattr(completeness, "load_json", lambda _path: document)
    monkeypatch.setattr(completeness, "coverage_check", lambda: {"status": "PASS"})
    assert "upper_complete_with_lower_incomplete:L1" in completeness.check()["errors"]


def test_current_kernel_governance_passes_all_gates() -> None:
    assert architecture.check()["status"] == "PASS"
    assert coverage.check()["status"] == "PASS"
    assert completeness.check()["status"] == "PASS"
