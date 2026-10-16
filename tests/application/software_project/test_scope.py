import os

import pytest

from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopeViolation, ScopedFileTransaction
from cgkn.application.software_project.service import SoftwareProjectGenerationService


@pytest.mark.happy_path
@pytest.mark.local_functional
def test_scoped_transaction_applies_fully_validated_writes(tmp_path):
    tx = ScopedFileTransaction(tmp_path, WorkerScope(("pkg/a.py", "pkg/b.py"), target_paths=("pkg/a.py", "pkg/b.py")))
    rows = tx.apply([{"action": "write_file", "path": "pkg/a.py", "content": "A=1\n"}, {"action": "write_file", "path": "pkg/b.py", "content": "B=2\n"}])
    assert [row["path"] for row in rows] == ["pkg/a.py", "pkg/b.py"]


@pytest.mark.negative
@pytest.mark.security
@pytest.mark.boundary
def test_scoped_transaction_rejects_escape_protected_and_undeclared_paths_before_writes(tmp_path):
    tx = ScopedFileTransaction(tmp_path, WorkerScope(("ok.py",), target_paths=("ok.py",)))
    with pytest.raises(ScopeViolation):
        tx.apply([{"action": "write_file", "path": "ok.py", "content": "ok"}, {"action": "write_file", "path": "other.py", "content": "bad"}])
    assert not (tmp_path / "ok.py").exists()
    with pytest.raises(ValueError):
        WorkerScope(("../escape.py",))
    protected = ScopedFileTransaction(tmp_path, WorkerScope((".github/workflow.yml",), target_paths=(".github/workflow.yml",)))
    with pytest.raises(ScopeViolation):
        protected.apply([{"action": "write_file", "path": ".github/workflow.yml", "content": "bad"}])


@pytest.mark.fault_injection
@pytest.mark.recovery
@pytest.mark.local_functional
def test_scoped_transaction_rolls_back_partial_replace(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("old-a", encoding="utf-8")
    (tmp_path / "b.py").write_text("old-b", encoding="utf-8")
    tx = ScopedFileTransaction(tmp_path, WorkerScope(("a.py", "b.py"), target_paths=("a.py", "b.py")))
    real = os.replace
    calls = 0
    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2: raise OSError("injected")
        return real(source, target)
    monkeypatch.setattr(os, "replace", fail_second)
    with pytest.raises(OSError, match="injected"):
        tx.apply([{"action": "write_file", "path": "a.py", "content": "new-a"}, {"action": "write_file", "path": "b.py", "content": "new-b"}])
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "old-a"
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "old-b"


@pytest.mark.security
@pytest.mark.negative
def test_forbidden_scan_detects_candidate_evidence_secret_path_and_dependency(tmp_path):
    secret_like = "API_" + 'KEY = "synthetic-credential-value"'
    (tmp_path / "app.py").write_text(f'import third_party\n{secret_like}\nPATH = "C:\\\\Users\\\\demo\\\\file"\n', encoding="utf-8")
    (tmp_path / "generation_receipt.json").write_text("{}", encoding="utf-8")
    findings = SoftwareProjectGenerationService._forbidden_scan(tmp_path)
    assert any(item.startswith("undeclared-dependency:") for item in findings)
    assert any(item.startswith("secret-like-literal:") for item in findings)
    assert any(item.startswith("absolute-machine-path:") for item in findings)
    assert any(item.startswith("forged-evidence:") for item in findings)
